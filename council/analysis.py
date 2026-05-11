"""Judge-pattern analysis over completed or paused runs."""

from __future__ import annotations

import os
import random

from sqlmodel import Session, select

from council.graph_runtime import graph_run_leaderboard, graph_run_leaderboards
from council.graphs import config, graph_nodes
from council.json_tools import parse_json_object
from council.models import GeneratorConfig, GraphInvocation, GraphNode, GraphRun, GraphRunAnalysis, JudgeConfig, Judgement, Match, Run, RunAnalysis, Status
from council.openrouter import OpenRouterClient
from council.run_state import run_progress


JUDGE_PATTERN_ANALYSIS_PROMPT = """You analyze LLM-as-judge reasoning traces from a completed evaluation run.

Write one brief paragraph describing the strongest patterns in judge preferences. Focus on trends such as whether judges favor longer or shorter responses, stricter JSON/schema adherence, more transcript evidence, more specific recommendations, tone, risk awareness, or other repeated choice drivers.

Use only the provided traces. Be concrete but concise. Do not list every trace. Do not mention internal sampling mechanics."""


GRAPH_JUDGE_SUMMARY_PROMPT = """You summarize why judges favored the top model in a graph evaluation run.

Write a very short summary. Use 2-4 compact bullet points or sentences total.
Focus on repeated reasons the winning traces preferred the top model over other models.
End with a short 1-2 sentence note about why it lost when it lost.
Reply in Markdown. Prefer short bullet points with bold labels when useful.

Use only the provided judge reasoning traces. Do not mention sampling mechanics."""


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


async def generate_graph_run_judge_summary(
    graph_run_id: int,
    session_factory,
    client: OpenRouterClient | None = None,
    *,
    judge_prompt_node_id: int | None = None,
    leaderboard_view: str = "aggregate",
    top_entity_key: str = "",
) -> None:
    """Generate a short judge-preference summary for the top graph-run model."""

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
        nodes = graph_nodes(session, graph_run.graph_id)
        leaderboard_view = leaderboard_view if leaderboard_view in {"aggregate", "chain", "overall"} else "aggregate"
        groups = graph_run_leaderboards(session, graph_run_id, nodes, view_mode=leaderboard_view)
        group = next((g for g in groups if g.get("judge_prompt_node_id") == judge_prompt_node_id), None) or groups[0]
        leaderboard = group["rows"]
        if not leaderboard:
            graph_run.error = "No completed judge votes are available for judge summary."
            session.add(graph_run)
            session.commit()
            return
        top_row = next((row for row in leaderboard if not top_entity_key or row.get("entity_key") == top_entity_key), leaderboard[0])
        top_node = top_row["node"]
        top_entity_key = top_row.get("entity_key") or str(top_node.id)
        top_node_id = top_node.id if top_node else int(str(top_entity_key).split(">")[-1])
        top_node_title = top_row.get("label") or top_node.title
        traces = sample_graph_judge_reasoning_traces(
            session,
            graph_run_id,
            top_entity_key,
            judge_prompt_node_id=judge_prompt_node_id,
            leaderboard_view=leaderboard_view,
        )
        if not traces["wins"] and not traces["losses"]:
            graph_run.error = "No judge reasoning traces are available for judge summary."
            session.add(graph_run)
            session.commit()
            return
        model_id = os.getenv("JUDGE_SUMMARY_MODEL", os.getenv("JUDGE_PATTERN_ANALYZER_MODEL", "qwen/qwen3.6-flash"))
        reasoning_effort = os.getenv("JUDGE_SUMMARY_REASONING", "medium")
        prompt_body = render_graph_judge_summary_prompt(top_node_title, traces)

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
                    top_model_node_id=top_node_id,
                    judge_prompt_node_id=judge_prompt_node_id,
                    leaderboard_view=leaderboard_view,
                    top_entity_key=top_entity_key,
                    top_entity_label=top_node_title,
                    model_id=model_id,
                    win_sample_size=len(traces["wins"]),
                    loss_sample_size=len(traces["losses"]),
                    summary=response.text.strip(),
                    prompt_snapshot=GRAPH_JUDGE_SUMMARY_PROMPT,
                )
            )
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            graph_run = session.get(GraphRun, graph_run_id)
            if graph_run:
                graph_run.error = f"Judge summary failed: {exc}"
                session.add(graph_run)
                session.commit()


def sample_graph_judge_reasoning_traces(
    session: Session,
    graph_run_id: int,
    top_model_node_id: int | str,
    *,
    judge_prompt_node_id: int | None = None,
    leaderboard_view: str = "aggregate",
) -> dict[str, list[dict[str, str]]]:
    """Sample judge reasons for wins and losses by the top graph model."""

    graph_run = session.get(GraphRun, graph_run_id)
    if not graph_run:
        return {"wins": [], "losses": []}
    nodes = graph_nodes(session, graph_run.graph_id)
    node_lookup = {node.id: node for node in nodes}
    judge_prompt_ids = {node.id for node in nodes if node.kind == "judge"}
    invocations = session.exec(
        select(GraphInvocation)
        .where(GraphInvocation.graph_run_id == graph_run_id)
        .where(GraphInvocation.status == Status.complete)
    ).all()
    wins: list[dict[str, str]] = []
    losses: list[dict[str, str]] = []
    for invocation in invocations:
        judge_prompt = node_lookup.get(invocation.node_id)
        if not judge_prompt or judge_prompt.id not in judge_prompt_ids or not invocation.output_json:
            continue
        if judge_prompt_node_id and invocation.node_id != judge_prompt_node_id:
            continue
        parsed_pair = _parse_graph_pair(invocation.item_key)
        top_entity_key = str(top_model_node_id)
        if not parsed_pair:
            continue
        entity_a, entity_b = parsed_pair
        a_matches = _graph_entity_matches(entity_a, top_entity_key, leaderboard_view)
        b_matches = _graph_entity_matches(entity_b, top_entity_key, leaderboard_view)
        if not a_matches and not b_matches:
            continue
        try:
            result = parse_json_object(invocation.output_json)
        except Exception:
            continue
        winner_key = config(judge_prompt).get("winner_key") or "winner"
        reasoning_key = config(judge_prompt).get("reasoning_key") or "reasoning"
        winner = str(result.get(winner_key, "TIE")).upper()
        reasoning = str(result.get(reasoning_key, "")).strip()
        if winner not in {"A", "B"} or not reasoning:
            continue
        top_side = "A" if a_matches else "B"
        opponent_key = entity_b if top_side == "A" else entity_a
        trace = {
            "judge": node_lookup.get(invocation.model_node_id).title if node_lookup.get(invocation.model_node_id) else "Judge",
            "item": invocation.item_key.split(":", 1)[0],
            "opponent": _graph_entity_label(opponent_key, node_lookup),
            "winner": winner,
            "reasoning": reasoning,
        }
        if winner == top_side:
            wins.append(trace)
        else:
            losses.append(trace)
    rng = random.Random(f"graph-run:{graph_run_id}:top:{top_model_node_id}")
    return {
        "wins": _sample_traces(wins, 20, rng),
        "losses": _sample_traces(losses, 10, rng),
    }


def render_graph_judge_summary_prompt(top_model_label: str, traces: dict[str, list[dict[str, str]]]) -> str:
    """Format top-model win/loss traces for the graph judge-summary prompt."""

    return (
        f"Top model: {top_model_label}\n\n"
        f"Winning traces:\n{_format_graph_traces(traces['wins'])}\n\n"
        f"Losing traces:\n{_format_graph_traces(traces['losses'])}\n\n"
        "Write the short judge preference summary now."
    )


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


def _parse_graph_pair(item_key: str) -> tuple[str, str] | None:
    try:
        _item, pair = item_key.rsplit(":", 1)
        entity_a, entity_b = pair.split("-vs-", 1)
        return entity_a, entity_b
    except ValueError:
        return None


def _graph_entity_label(entity_key: str, node_lookup: dict[int, GraphNode]) -> str:
    labels = []
    for part in entity_key.split(">"):
        try:
            node = node_lookup.get(int(part))
        except ValueError:
            node = None
        labels.append(node.title if node else part)
    return " -> ".join(labels)


def _graph_entity_matches(entity_key: str, target_key: str, leaderboard_view: str) -> bool:
    """Match raw judge chain keys against the current leaderboard display entity."""

    if entity_key == target_key:
        return True
    parts = entity_key.split(">")
    if leaderboard_view != "chain":
        return bool(parts) and parts[-1] == target_key
    target_parts = target_key.split(">")
    return parts[: len(target_parts)] == target_parts


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


def render_judge_pattern_prompt(traces: list[dict[str, str]]) -> str:
    """Format sampled judge traces into the analyzer prompt body."""

    payload = "\n\n".join(
        f"Trace {index}\nJudge: {trace['judge']}\nMatch: {trace['match_id']}\nDirection: {trace['direction']}\nWinner: {trace['winner']}\nReasoning: {trace['reasoning']}"
        for index, trace in enumerate(traces, start=1)
    )
    return f"Sampled judge reasoning traces:\n\n{payload}\n\nWrite the one-paragraph trend analysis now."
