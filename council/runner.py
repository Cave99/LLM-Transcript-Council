"""Run creation and execution orchestration."""

from __future__ import annotations

import asyncio
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from council.elo import consistent_swapped_vote, majority_vote, update_elo
from council.files import list_markdown_files, read_text_snapshot
from council.judge import (
    parse_judgement_response,
    render_generation_prompt,
    render_judge_prompt,
)
from council.json_tools import maybe_repair_json
from council.models import (
    EloRating,
    Generation,
    GeneratorConfig,
    JudgeConfig,
    Judgement,
    Match,
    MatchResult,
    Project,
    Run,
    Status,
    Task,
    Transcript,
    utc_now,
)
from council.openrouter import OpenRouterClient


@dataclass(frozen=True)
class GeneratorSpec:
    label: str
    model_id: str
    temperature: float
    prompt_path: str


@dataclass(frozen=True)
class JudgeSpec:
    label: str
    model_id: str
    temperature: float
    prompt_path: str


def create_project(session: Session, name: str) -> Project:
    project = Project(name=name.strip())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def create_task(
    session: Session,
    *,
    project_id: int,
    name: str,
    description_path: str,
    transcript_root: str,
    default_judge_prompt_path: str,
) -> Task:
    description = read_text_snapshot(description_path)
    task = Task(
        project_id=project_id,
        name=name.strip(),
        description_path=description.path,
        description_snapshot=description.content,
        description_hash=description.content_hash,
        transcript_root=str(Path(transcript_root).expanduser().resolve()),
        default_judge_prompt_path=str(Path(default_judge_prompt_path).expanduser().resolve()),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def create_run(
    session: Session,
    *,
    task_id: int,
    name: str,
    generator_specs: list[GeneratorSpec],
    judge_specs: list[JudgeSpec],
    transcript_paths: list[str] | None = None,
    sample_size: int | None = None,
    max_concurrency: int = 5,
    swap_enabled: bool = True,
) -> Run:
    task = session.get(Task, task_id)
    if not task:
        raise ValueError(f"Task {task_id} does not exist")
    if len(generator_specs) < 2:
        raise ValueError("At least two generator configs are required")
    if not judge_specs:
        raise ValueError("At least one judge config is required")

    run = Run(
        task_id=task_id,
        name=name.strip(),
        max_concurrency=max_concurrency,
        sample_size=sample_size,
        swap_enabled=swap_enabled,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    for spec in generator_specs:
        prompt = read_text_snapshot(spec.prompt_path)
        session.add(
            GeneratorConfig(
                run_id=run.id,
                label=spec.label.strip(),
                model_id=spec.model_id.strip(),
                temperature=spec.temperature,
                prompt_path=prompt.path,
                prompt_snapshot=prompt.content,
                prompt_hash=prompt.content_hash,
            )
        )

    for spec in judge_specs:
        prompt = read_text_snapshot(spec.prompt_path)
        session.add(
            JudgeConfig(
                run_id=run.id,
                label=spec.label.strip(),
                model_id=spec.model_id.strip(),
                temperature=spec.temperature,
                prompt_path=prompt.path,
                prompt_snapshot=prompt.content,
                prompt_hash=prompt.content_hash,
            )
        )

    paths = [Path(p) for p in transcript_paths] if transcript_paths else list_markdown_files(task.transcript_root)
    if sample_size:
        paths = paths[:sample_size]
    if not paths:
        raise ValueError("No transcript markdown files selected")

    for path in paths:
        snapshot = read_text_snapshot(path)
        session.add(
            Transcript(
                run_id=run.id,
                path=snapshot.path,
                content_snapshot=snapshot.content,
                content_hash=snapshot.content_hash,
            )
        )

    session.commit()
    _ensure_generation_rows(session, run.id)
    _ensure_match_rows(session, run.id)
    _ensure_elo_rows(session, run.id)
    return run


def run_progress(session: Session, run_id: int) -> dict[str, int]:
    def count(model, status: Status | None = None) -> int:
        statement = select(model).where(model.run_id == run_id)
        if status:
            statement = statement.where(model.status == status)
        return len(session.exec(statement).all())

    generations = count(Generation)
    matches = count(Match)
    complete_generations = count(Generation, Status.complete)
    complete_matches = count(Match, Status.complete)
    judgements = session.exec(
        select(Judgement).join(Match).where(Match.run_id == run_id)
    ).all()
    return {
        "generations": generations,
        "generations_complete": complete_generations,
        "matches": matches,
        "matches_complete": complete_matches,
        "judgements": len(judgements),
    }


async def execute_run(run_id: int, session_factory, client: OpenRouterClient | None = None) -> None:
    """Execute or resume a run."""

    client = client or OpenRouterClient()
    if not client.api_key:
        with session_factory() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = Status.failed
                run.error = "OPENROUTER_API_KEY is not set"
                session.add(run)
                session.commit()
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    with session_factory() as session:
        run = session.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} does not exist")
        run.status = Status.running
        run.started_at = run.started_at or utc_now()
        session.add(run)
        session.commit()
        max_concurrency = run.max_concurrency

    semaphore = asyncio.Semaphore(max_concurrency)
    await _run_generations(run_id, session_factory, client, semaphore)
    await _run_matches(run_id, session_factory, client, semaphore)

    with session_factory() as session:
        _recalculate_elo(session, run_id)
        run = session.get(Run, run_id)
        if run:
            run.status = Status.complete
            run.completed_at = utc_now()
            session.add(run)
            session.commit()


def _ensure_generation_rows(session: Session, run_id: int) -> None:
    transcripts = session.exec(select(Transcript).where(Transcript.run_id == run_id)).all()
    configs = session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
    existing = {
        (row.transcript_id, row.generator_config_id)
        for row in session.exec(select(Generation).where(Generation.run_id == run_id)).all()
    }
    for transcript, config in itertools.product(transcripts, configs):
        if (transcript.id, config.id) not in existing:
            session.add(
                Generation(
                    run_id=run_id,
                    transcript_id=transcript.id,
                    generator_config_id=config.id,
                )
            )
    session.commit()


def _ensure_match_rows(session: Session, run_id: int) -> None:
    transcripts = session.exec(select(Transcript).where(Transcript.run_id == run_id)).all()
    configs = session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
    existing = {
        (row.transcript_id, row.config_a_id, row.config_b_id)
        for row in session.exec(select(Match).where(Match.run_id == run_id)).all()
    }
    generations = session.exec(select(Generation).where(Generation.run_id == run_id)).all()
    generation_lookup = {
        (generation.transcript_id, generation.generator_config_id): generation
        for generation in generations
    }
    for transcript in transcripts:
        for config_a, config_b in itertools.combinations(configs, 2):
            if (transcript.id, config_a.id, config_b.id) in existing:
                continue
            gen_a = generation_lookup[(transcript.id, config_a.id)]
            gen_b = generation_lookup[(transcript.id, config_b.id)]
            session.add(
                Match(
                    run_id=run_id,
                    transcript_id=transcript.id,
                    generation_a_id=gen_a.id,
                    generation_b_id=gen_b.id,
                    config_a_id=config_a.id,
                    config_b_id=config_b.id,
                )
            )
    session.commit()


def _ensure_elo_rows(session: Session, run_id: int) -> None:
    run = session.get(Run, run_id)
    configs = session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
    existing = {
        row.generator_config_id
        for row in session.exec(select(EloRating).where(EloRating.run_id == run_id)).all()
    }
    for config in configs:
        if config.id not in existing:
            session.add(
                EloRating(
                    run_id=run_id,
                    generator_config_id=config.id,
                    rating=run.elo_start if run else 1500.0,
                )
            )
    session.commit()


async def _run_generations(run_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    with session_factory() as session:
        rows = session.exec(
            select(Generation).where(
                Generation.run_id == run_id,
                Generation.status != Status.complete,
            )
        ).all()
    await asyncio.gather(*[_generate_one(row.id, session_factory, client, semaphore) for row in rows])


async def _generate_one(generation_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        with session_factory() as session:
            generation = session.get(Generation, generation_id)
            if not generation or generation.status == Status.complete:
                return
            run = session.get(Run, generation.run_id)
            task = session.get(Task, run.task_id)
            transcript = session.get(Transcript, generation.transcript_id)
            config = session.get(GeneratorConfig, generation.generator_config_id)
            generation.status = Status.running
            session.add(generation)
            session.commit()

        prompt = render_generation_prompt(
            config.prompt_snapshot,
            transcript=transcript.content_snapshot,
            task_description=task.description_snapshot,
        )
        try:
            response = await client.chat(
                model=config.model_id,
                temperature=config.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            with session_factory() as session:
                generation = session.get(Generation, generation_id)
                generation.status = Status.complete
                generation.output_raw = response.text
                generation.output_repaired = maybe_repair_json(response.text)
                generation.prompt_tokens = response.prompt_tokens
                generation.completion_tokens = response.completion_tokens
                generation.cost = response.cost
                generation.completed_at = utc_now()
                session.add(generation)
                session.commit()
        except Exception as exc:
            with session_factory() as session:
                generation = session.get(Generation, generation_id)
                generation.status = Status.failed
                generation.error = str(exc)
                session.add(generation)
                session.commit()


async def _run_matches(run_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    with session_factory() as session:
        rows = session.exec(
            select(Match).where(Match.run_id == run_id, Match.status != Status.complete)
        ).all()
    for match in rows:
        await _judge_match(match.id, session_factory, client, semaphore)


async def _judge_match(match_id: int, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
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
        match.status = Status.running
        session.add(match)
        session.commit()

    if gen_a.status != Status.complete or gen_b.status != Status.complete:
        with session_factory() as session:
            match = session.get(Match, match_id)
            match.status = Status.failed
            session.add(match)
            session.commit()
        return

    votes: list[str] = []
    tasks = [
        _judge_with_swap(
            match_id,
            judge.id,
            task.description_snapshot,
            transcript.content_snapshot,
            gen_a.output_repaired or gen_a.output_raw or "",
            gen_b.output_repaired or gen_b.output_raw or "",
            session_factory,
            client,
            semaphore,
        )
        for judge in judges
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
        session.commit()


async def _judge_with_swap(
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
    first = await _judge_once(
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
    swapped = await _judge_once(
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


async def _judge_once(
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

    prompt = render_judge_prompt(
        judge.prompt_snapshot,
        task_description=task_description,
        transcript=transcript,
        output_a=output_a,
        output_b=output_b,
    )
    try:
        async with semaphore:
            response = await client.chat(
                model=judge.model_id,
                temperature=judge.temperature,
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
                )
            )
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
                )
            )
            session.commit()
        return "TIE"


def _recalculate_elo(session: Session, run_id: int) -> None:
    run = session.get(Run, run_id)
    ratings = {
        row.generator_config_id: row
        for row in session.exec(select(EloRating).where(EloRating.run_id == run_id)).all()
    }
    for row in ratings.values():
        row.rating = run.elo_start if run else 1500.0
        row.wins = row.losses = row.ties = 0
        session.add(row)

    matches = session.exec(select(Match).where(Match.run_id == run_id, Match.status == Status.complete)).all()
    for match in matches:
        result = session.exec(select(MatchResult).where(MatchResult.match_id == match.id)).first()
        if not result:
            continue
        rating_a = ratings[match.config_a_id]
        rating_b = ratings[match.config_b_id]
        rating_a.rating, rating_b.rating = update_elo(
            rating_a.rating,
            rating_b.rating,
            result.final_winner,  # type: ignore[arg-type]
            k_factor=run.k_factor if run else 32.0,
        )
        if result.final_winner == "A":
            rating_a.wins += 1
            rating_b.losses += 1
        elif result.final_winner == "B":
            rating_b.wins += 1
            rating_a.losses += 1
        else:
            rating_a.ties += 1
            rating_b.ties += 1
        session.add(rating_a)
        session.add(rating_b)
    session.commit()
