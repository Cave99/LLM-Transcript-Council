"""Judge-pattern analysis over completed or paused runs."""

from __future__ import annotations

import os
import random

from sqlmodel import Session, select

from council.models import GeneratorConfig, JudgeConfig, Judgement, Match, Run, RunAnalysis, Status
from council.openrouter import OpenRouterClient
from council.run_state import run_progress


JUDGE_PATTERN_ANALYSIS_PROMPT = """You analyze LLM-as-judge reasoning traces from a completed evaluation run.

Write one brief paragraph describing the strongest patterns in judge preferences. Focus on trends such as whether judges favor longer or shorter responses, stricter JSON/schema adherence, more transcript evidence, more specific recommendations, tone, risk awareness, or other repeated choice drivers.

Use only the provided traces. Be concrete but concise. Do not list every trace. Do not mention internal sampling mechanics."""


def judge_pattern_analysis_availability(run: Run, judge_votes: int) -> tuple[bool, str]:
    """Decide whether judge-pattern analysis should be offered."""

    if run.status == Status.complete:
        return True, ""
    if run.status == Status.paused and judge_votes >= 10:
        return True, ""
    if run.status == Status.paused:
        return False, f"Judge pattern analysis needs at least 10 judge votes for a stopped run. Current votes: {judge_votes}."
    return False, "Judge pattern analysis is available after completion, or after stopping once at least 10 judge votes exist."


async def generate_judge_pattern_analysis(run_id: int, session_factory, client: OpenRouterClient | None = None) -> None:
    """Generate and persist judge-pattern analysis outside request handlers."""

    client = client or OpenRouterClient()
    with session_factory() as session:
        run = session.get(Run, run_id)
        if not run:
            return
        progress = run_progress(session, run_id)
        analysis_allowed, _analysis_help = judge_pattern_analysis_availability(run, progress["judgements"])
        if not analysis_allowed:
            return
        traces = sample_judge_reasoning_traces(session, run_id)
        if not traces:
            run.error = "No judge reasoning traces are available for pattern analysis."
            session.add(run)
            session.commit()
            return
        model_id = os.getenv("JUDGE_PATTERN_ANALYZER_MODEL", "deepseek/deepseek-v4-flash")

    try:
        response = await client.chat(
            model=model_id,
            temperature=0.2,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": JUDGE_PATTERN_ANALYSIS_PROMPT},
                {"role": "user", "content": render_judge_pattern_prompt(traces)},
            ],
        )
        with session_factory() as session:
            run = session.get(Run, run_id)
            if run:
                run.error = None
                session.add(run)
            session.add(
                RunAnalysis(
                    run_id=run_id,
                    model_id=model_id,
                    sample_size=len(traces),
                    summary=response.text.strip(),
                    prompt_snapshot=JUDGE_PATTERN_ANALYSIS_PROMPT,
                )
            )
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            run = session.get(Run, run_id)
            if run:
                run.error = f"Judge pattern analysis failed: {exc}"
                session.add(run)
                session.commit()


def sample_judge_reasoning_traces(session: Session, run_id: int) -> list[dict[str, str]]:
    """Sample a balanced subset of judge reasoning traces for analysis."""

    rows = session.exec(
        select(Judgement, JudgeConfig, Match, GeneratorConfig)
        .where(Match.run_id == run_id)
        .where(Judgement.match_id == Match.id)
        .where(Judgement.judge_config_id == JudgeConfig.id)
        .where(Judgement.error == None)  # noqa: E711
        .where(GeneratorConfig.id == Match.config_a_id)
    ).all()
    traces = [
        {
            "judge": judge.model_id,
            "direction": judgement.direction,
            "winner": judgement.winner,
            "reasoning": judgement.reasoning,
            "match_id": str(match.id),
        }
        for judgement, judge, match, _config_a in rows
        if judgement.reasoning.strip()
    ]
    sample_size = max(1, round(len(traces) * 0.10)) if traces else 0
    rng = random.Random(run_id)
    by_judge: dict[str, list[dict[str, str]]] = {}
    for trace in traces:
        by_judge.setdefault(trace["judge"], []).append(trace)
    sampled: list[dict[str, str]] = []
    judge_names = list(by_judge)
    rng.shuffle(judge_names)
    while len(sampled) < sample_size and any(by_judge.values()):
        for judge_name in judge_names:
            if by_judge[judge_name] and len(sampled) < sample_size:
                sampled.append(by_judge[judge_name].pop(rng.randrange(len(by_judge[judge_name]))))
    return sampled


def render_judge_pattern_prompt(traces: list[dict[str, str]]) -> str:
    """Format sampled judge traces into the analyzer prompt body."""

    payload = "\n\n".join(
        f"Trace {index}\nJudge: {trace['judge']}\nMatch: {trace['match_id']}\nDirection: {trace['direction']}\nWinner: {trace['winner']}\nReasoning: {trace['reasoning']}"
        for index, trace in enumerate(traces, start=1)
    )
    return f"Sampled judge reasoning traces:\n\n{payload}\n\nWrite the one-paragraph trend analysis now."
