"""Judging phase execution for pairwise matches."""

from __future__ import annotations

import asyncio
import json

from sqlmodel import select

from council.elo import consistent_swapped_vote, majority_vote
from council.judge import parse_judgement_response, render_judge_prompt
from council.leaderboard import apply_match_elo
from council.models import Generation, JudgeConfig, Judgement, Match, MatchResult, Run, Status, Task, Transcript, utc_now
from council.openrouter import OpenRouterClient
from council.run_state import add_run_log, is_run_paused


async def run_matches(run_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    """Queue and execute match judging one pair at a time."""

    with session_factory() as session:
        match_ids = [
            row.id
            for row in session.exec(
                select(Match).where(Match.run_id == run_id, Match.status != Status.complete)
            ).all()
            if row.id is not None
        ]
        add_run_log(session, run_id, f"Judging phase queued {len(match_ids)} incomplete matches.")
        session.commit()
    for match_id in match_ids:
        with session_factory() as session:
            if is_run_paused(session, run_id):
                add_run_log(session, run_id, "Judging phase stopped before scheduling the next match.")
                session.commit()
                return
        await judge_match(match_id, session_factory, client, semaphore)


async def judge_match(match_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    """Run all judges for one match and store the final match result."""

    with session_factory() as session:
        match = session.get(Match, match_id)
        if not match or match.status == Status.complete:
            return
        run = session.get(Run, match.run_id)
        task = session.get(Task, run.task_id)
        transcript = session.get(Transcript, match.transcript_id)
        gen_a = session.get(Generation, match.generation_a_id)
        gen_b = session.get(Generation, match.generation_b_id)
        judges = session.exec(select(JudgeConfig).where(JudgeConfig.run_id == run.id)).all()
        judge_ids = [judge.id for judge in judges]
        task_description = task.description_snapshot
        transcript_content = transcript.content_snapshot
        output_a = gen_a.output_repaired or gen_a.output_raw or ""
        output_b = gen_b.output_repaired or gen_b.output_raw or ""
        gen_a_status = gen_a.status
        gen_b_status = gen_b.status
        match.status = Status.running
        session.add(match)
        add_run_log(session, run.id, f"Match started: #{match.id} with {len(judge_ids)} judges.")
        session.commit()

    if gen_a_status != Status.complete or gen_b_status != Status.complete:
        with session_factory() as session:
            match = session.get(Match, match_id)
            match.status = Status.failed
            session.add(match)
            add_run_log(session, match.run_id, f"Match skipped: #{match_id} is waiting on incomplete generations.", level="warning")
            session.commit()
        return

    tasks = [
        judge_with_swap(
            match_id,
            judge_id,
            task_description,
            transcript_content,
            output_a,
            output_b,
            session_factory,
            client,
            semaphore,
        )
        for judge_id in judge_ids
    ]
    votes = list(await asyncio.gather(*tasks))
    final = majority_vote([vote for vote in votes if vote in {"A", "B", "TIE"}])
    agreement = votes.count(final) / len(votes) if votes else 0.0

    with session_factory() as session:
        result = MatchResult(
            match_id=match_id,
            final_winner=final,
            agreement=agreement,
            votes_json=json.dumps(votes),
        )
        session.add(result)
        match = session.get(Match, match_id)
        match.status = Status.complete
        session.add(match)
        apply_match_elo(session, match, final)
        add_run_log(session, match.run_id, f"Match complete: #{match_id}, winner={final}, agreement={agreement:.0%}.")
        session.commit()


async def judge_with_swap(
    match_id: int,
    judge_id: int,
    task_description: str,
    transcript: str,
    output_a: str,
    output_b: str,
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> str:
    """Run a judge twice, then reconcile the swapped vote back to one result."""

    first = await judge_once(
        match_id,
        judge_id,
        "normal",
        task_description,
        transcript,
        output_a,
        output_b,
        session_factory,
        client,
        semaphore,
    )
    swapped = await judge_once(
        match_id,
        judge_id,
        "swapped",
        task_description,
        transcript,
        output_b,
        output_a,
        session_factory,
        client,
        semaphore,
    )
    return consistent_swapped_vote(first, swapped)


async def judge_once(
    match_id: int,
    judge_id: int,
    direction: str,
    task_description: str,
    transcript: str,
    output_a: str,
    output_b: str,
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> str:
    """Run one judge prompt and persist the raw vote and reasoning."""

    with session_factory() as session:
        existing = session.exec(
            select(Judgement).where(
                Judgement.match_id == match_id,
                Judgement.judge_config_id == judge_id,
                Judgement.direction == direction,
            )
        ).first()
        if existing and not existing.error:
            return existing.winner
        judge = session.get(JudgeConfig, judge_id)
        prompt_snapshot = judge.prompt_snapshot
        model_id = judge.model_id
        temperature = judge.temperature

    prompt = render_judge_prompt(
        prompt_snapshot,
        task_description=task_description,
        transcript=transcript,
        output_a=output_a,
        output_b=output_b,
    )
    started_at = utc_now()
    try:
        async with semaphore:
            response = await client.chat(
                model=model_id,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        parsed = parse_judgement_response(response.text)
        with session_factory() as session:
            session.add(
                Judgement(
                    match_id=match_id,
                    judge_config_id=judge_id,
                    direction=direction,
                    winner=parsed.winner,
                    reasoning=parsed.reasoning,
                    raw_response=response.text,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost=response.cost,
                    started_at=started_at,
                    completed_at=utc_now(),
                )
            )
            match = session.get(Match, match_id)
            add_run_log(session, match.run_id, f"Judge vote recorded: judge #{judge_id}, match #{match_id}, {direction}, winner={parsed.winner}.")
            session.commit()
        return parsed.winner
    except Exception as exc:
        with session_factory() as session:
            session.add(
                Judgement(
                    match_id=match_id,
                    judge_config_id=judge_id,
                    direction=direction,
                    winner="TIE",
                    reasoning="Judge call failed; counted as tie.",
                    raw_response="",
                    error=str(exc),
                    started_at=started_at,
                    completed_at=utc_now(),
                )
            )
            match = session.get(Match, match_id)
            add_run_log(session, match.run_id, f"Judge call failed: judge #{judge_id}, match #{match_id}, {direction}: {exc}", level="error")
            session.commit()
        return "TIE"
