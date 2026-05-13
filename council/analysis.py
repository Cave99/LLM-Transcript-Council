"""Judge-summary analysis over spec-backed graph runs."""

from __future__ import annotations

import os
import random

from sqlmodel import Session, select

from council.graph_runtime import graph_run_leaderboards
from council.models import GraphJudgement, GraphPair, GraphRun, GraphRunAnalysis, Status
from council.openrouter import OpenRouterClient

GRAPH_JUDGE_SUMMARY_PROMPT = """You summarize why judges favored the top candidate in a graph evaluation run.

Write a very short summary. Use 2-4 compact bullet points or sentences total.
Focus on repeated reasons the winning traces preferred the top candidate over other candidates.
End with a short 1-2 sentence note about why it lost when it lost.
Reply in Markdown. Use only the provided judge reasoning traces."""


async def generate_graph_run_judge_summary(
    graph_run_id: int,
    session_factory,
    client: OpenRouterClient | None = None,
    *,
    judge_prompt_node_id: int | None = None,
    leaderboard_view: str = "aggregate",
    top_entity_key: str = "",
) -> None:
    """Generate a short judge-preference summary for the top graph candidate."""

    client = client or OpenRouterClient()
    with session_factory() as session:
        graph_run = session.get(GraphRun, graph_run_id)
        if not graph_run:
            return
        if graph_run.status not in {Status.complete, Status.paused}:
            graph_run.error = "Judge summary is available after completion, or after stopping a run."
            session.add(graph_run)
            session.commit()
            return
        group = graph_run_leaderboards(session, graph_run_id, view_mode=leaderboard_view)[0]
        leaderboard = group["rows"]
        if not leaderboard:
            graph_run.error = "No completed judge votes are available for judge summary."
            session.add(graph_run)
            session.commit()
            return
        top_row = next((row for row in leaderboard if not top_entity_key or row.get("entity_key") == top_entity_key), leaderboard[0])
        top_entity_key = top_row["entity_key"]
        top_label = top_row["label"]
        traces = sample_graph_judge_reasoning_traces(session, graph_run_id, top_entity_key)
        if not traces["wins"] and not traces["losses"]:
            graph_run.error = "No judge reasoning traces are available for judge summary."
            session.add(graph_run)
            session.commit()
            return
        model_id = os.getenv("JUDGE_SUMMARY_MODEL", os.getenv("JUDGE_PATTERN_ANALYZER_MODEL", "qwen/qwen3.6-flash"))
        reasoning_effort = os.getenv("JUDGE_SUMMARY_REASONING", "medium")
        prompt_body = render_graph_judge_summary_prompt(top_label, traces)

    try:
        response = await client.chat(
            model=model_id,
            temperature=0.2,
            reasoning_effort=reasoning_effort,
            messages=[
                {"role": "system", "content": GRAPH_JUDGE_SUMMARY_PROMPT},
                {"role": "user", "content": prompt_body},
            ],
        )
        with session_factory() as session:
            graph_run = session.get(GraphRun, graph_run_id)
            if graph_run:
                graph_run.error = None
                session.add(graph_run)
            session.add(
                GraphRunAnalysis(
                    graph_run_id=graph_run_id,
                    evaluator_id="",
                    leaderboard_view=leaderboard_view,
                    top_entity_key=top_entity_key,
                    top_entity_label=top_label,
                    model_id=model_id,
                    win_sample_size=len(traces["wins"]),
                    loss_sample_size=len(traces["losses"]),
                    summary=response.text.strip(),
                    prompt_snapshot=GRAPH_JUDGE_SUMMARY_PROMPT,
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        with session_factory() as session:
            graph_run = session.get(GraphRun, graph_run_id)
            if graph_run:
                graph_run.error = f"Judge summary failed: {exc}"
                session.add(graph_run)
                session.commit()


def sample_graph_judge_reasoning_traces(session: Session, graph_run_id: int, top_entity_key: str, **_kwargs) -> dict[str, list[dict[str, str]]]:
    """Sample judgement reasons for wins and losses by one candidate key."""

    pairs = {pair.id: pair for pair in session.exec(select(GraphPair).where(GraphPair.graph_run_id == graph_run_id)).all()}
    judgements = session.exec(select(GraphJudgement)).all()
    wins: list[dict[str, str]] = []
    losses: list[dict[str, str]] = []
    for judgement in judgements:
        pair = pairs.get(judgement.pair_id)
        if not pair or not judgement.winner or not judgement.reasoning:
            continue
        a_key = pair.a_lineage_key.split("->")[-1]
        b_key = pair.b_lineage_key.split("->")[-1]
        if top_entity_key not in {a_key, b_key}:
            continue
        top_side = "A" if a_key == top_entity_key else "B"
        trace = {
            "judge": pair.evaluator_id,
            "item": pair.item_key,
            "opponent": b_key if top_side == "A" else a_key,
            "winner": judgement.winner,
            "reasoning": judgement.reasoning,
        }
        if judgement.winner == top_side:
            wins.append(trace)
        elif judgement.winner in {"A", "B"}:
            losses.append(trace)
    rng = random.Random(f"graph-run:{graph_run_id}:top:{top_entity_key}")
    return {"wins": _sample_traces(wins, 20, rng), "losses": _sample_traces(losses, 10, rng)}


def render_graph_judge_summary_prompt(top_model_label: str, traces: dict[str, list[dict[str, str]]]) -> str:
    """Format top-candidate win/loss traces for the summary prompt."""

    return (
        f"Top candidate: {top_model_label}\n\n"
        f"Winning traces:\n{_format_graph_traces(traces['wins'])}\n\n"
        f"Losing traces:\n{_format_graph_traces(traces['losses'])}\n\n"
        "Write the short judge preference summary now."
    )


def _sample_traces(traces: list[dict[str, str]], limit: int, rng: random.Random) -> list[dict[str, str]]:
    if len(traces) <= limit:
        shuffled = list(traces)
        rng.shuffle(shuffled)
        return shuffled
    return rng.sample(traces, limit)


def _format_graph_traces(traces: list[dict[str, str]]) -> str:
    if not traces:
        return "None."
    return "\n\n".join(
        f"Trace {index}\nJudge: {trace['judge']}\nItem: {trace['item']}\nOpponent: {trace['opponent']}\nWinner: {trace['winner']}\nReasoning: {trace['reasoning']}"
        for index, trace in enumerate(traces, start=1)
    )
