"""Spec-backed graph execution, human evaluation, and leaderboards."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import select

from council.elo import Winner, consistent_swapped_vote, update_elo
from council.graph_spec import CandidateSpec, EvaluatorSpec, GraphSpec, StageSpec, dump_spec, parse_spec, validate_spec_payload
from council.judge import render_template
from council.json_tools import maybe_repair_json, parse_json_object
from council.models import ExperimentGraph, GraphInvocation, GraphJudgement, GraphPair, GraphRun, GraphStatus, Status, utc_now
from council.openrouter import OpenRouterClient


@dataclass(frozen=True)
class DatasetItem:
    """One dataset row normalized for prompt rendering."""

    key: str
    values: dict[str, str]


@dataclass(frozen=True)
class OutputBranch:
    """One stage output flowing into later matrix stages."""

    item: DatasetItem
    stage_id: str
    candidate_id: str
    candidate_title: str
    lineage_key: str
    output: str
    invocation_id: int


def create_graph_native_run(session, graph_id: int, *, max_concurrency: int = 5, sample_size: int | None = None) -> GraphRun:
    """Create a resumable spec-backed run with launch-time snapshots."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        raise ValueError(f"Graph {graph_id} does not exist")
    spec = parse_spec(graph.spec_json)
    validation = validate_spec_payload(spec.model_dump(mode="json"), check_prompt_paths=True)
    if not validation.valid:
        raise ValueError("; ".join(error.message for error in validation.errors))
    items = dataset_items(spec)
    effective_sample_size = sample_size or _optional_int(spec.dataset.config.get("sample_size"))
    if effective_sample_size:
        items = items[:effective_sample_size]
    run = GraphRun(
        graph_id=graph_id,
        name=f"{graph.name} test run" if sample_size == 1 else graph.name,
        max_concurrency=max_concurrency,
        sample_size=sample_size,
        spec_snapshot_json=dump_spec(spec),
        prompts_snapshot_json=json.dumps(_prompt_snapshots(spec), sort_keys=True),
        dataset_hash=_dataset_hash(items),
    )
    session.add(run)
    graph.status = GraphStatus.running
    session.add(graph)
    session.commit()
    session.refresh(run)
    return run


def stop_graph_native_run(session, graph_run_id: int) -> GraphRun:
    """Pause a graph run so no new model calls are scheduled."""

    run = _require_run(session, graph_run_id)
    run.status = Status.paused
    session.add(run)
    _sync_graph_status(session, run)
    session.commit()
    session.refresh(run)
    return run


def continue_graph_native_run(session, graph_run_id: int) -> GraphRun:
    """Resume a paused or failed run."""

    run = _require_run(session, graph_run_id)
    _requeue_unfinished_invocations(session, graph_run_id)
    run.status = Status.pending
    run.error = None
    run.completed_at = None
    session.add(run)
    _sync_graph_status(session, run)
    session.commit()
    session.refresh(run)
    return run


def retry_graph_native_failures(session, graph_run_id: int) -> GraphRun:
    """Requeue failed model invocations while preserving evidence that succeeded."""

    run = _require_run(session, graph_run_id)
    _requeue_unfinished_invocations(session, graph_run_id)
    run.status = Status.pending
    run.error = None
    run.completed_at = None
    session.add(run)
    _sync_graph_status(session, run)
    session.commit()
    session.refresh(run)
    return run


async def execute_graph_native_run(graph_run_id: int, session_factory, client: OpenRouterClient | None = None) -> None:
    """Execute a spec snapshot over dataset items and evaluators."""

    client = client or OpenRouterClient()
    if not client.api_key:
        with session_factory() as session:
            run = session.get(GraphRun, graph_run_id)
            if run:
                run.status = Status.failed
                run.error = "OPENROUTER_API_KEY is not set"
                session.add(run)
                _sync_graph_status(session, run)
                session.commit()
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    with session_factory() as session:
        run = _require_run(session, graph_run_id)
        run.status = Status.running
        run.started_at = run.started_at or utc_now()
        session.add(run)
        session.commit()
        spec = parse_spec(run.spec_snapshot_json)
        max_concurrency = run.max_concurrency
        items = dataset_items(spec)
        effective_sample_size = run.sample_size or _optional_int(spec.dataset.config.get("sample_size"))
        if effective_sample_size:
            items = items[:effective_sample_size]

    semaphore = asyncio.Semaphore(max_concurrency)
    constants = {key: str(value) for key, value in spec.constants.items()}
    branches: list[OutputBranch] = []
    stage_outputs: dict[str, list[OutputBranch]] = {}

    for stage_index, stage in enumerate(spec.stages):
        with session_factory() as session:
            run = session.get(GraphRun, graph_run_id)
            if run and run.status == Status.paused:
                _sync_graph_status(session, run)
                session.commit()
                return
        input_branches: list[OutputBranch | None] = branches if branches else [None]
        tasks = []
        for item in items:
            scoped_inputs = [branch for branch in input_branches if branch is None or branch.item.key == item.key]
            for input_branch in scoped_inputs:
                for candidate in stage.candidates:
                    tasks.append(_run_generation_invocation(graph_run_id, stage_index, stage, candidate, item, input_branch, constants, session_factory, client, semaphore))
        results = await asyncio.gather(*tasks)
        branches = [branch for branch in results if branch is not None and branch.output]
        stage_outputs[stage.id] = branches

    for evaluator in spec.evaluators:
        target_outputs = stage_outputs.get(evaluator.target_stage, [])
        if evaluator.type == "human_pairwise":
            with session_factory() as session:
                _ensure_pairs(session, graph_run_id, evaluator, target_outputs)
            continue
        pairs = []
        with session_factory() as session:
            pairs = _ensure_pairs(session, graph_run_id, evaluator, target_outputs)
        stage_output_mode = next((item.upstream_output for item in spec.stages if item.id == evaluator.target_stage), "raw")
        tasks = [_run_llm_judge_pair(graph_run_id, evaluator, pair.id, constants, stage_output_mode, session_factory, client, semaphore) for pair in pairs]
        if tasks:
            await asyncio.gather(*tasks)

    with session_factory() as session:
        finish_graph_native_run(session, graph_run_id)


def finish_graph_native_run(session, graph_run_id: int) -> GraphRun | None:
    """Finalize model execution once no model invocation is pending or running."""

    run = session.get(GraphRun, graph_run_id)
    if not run or run.status == Status.paused:
        return run
    progress = graph_native_progress(session, graph_run_id)
    run.status = Status.failed if progress["failed"] else Status.complete
    run.completed_at = utc_now()
    if progress["failed"]:
        run.error = f"{progress['failed']} model call(s) failed."
    session.add(run)
    _sync_graph_status(session, run)
    session.commit()
    session.refresh(run)
    return run


def graph_native_progress(session, graph_run_id: int) -> dict[str, int]:
    """Count model-call invocations for progress displays."""

    rows = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id)).all()
    return {
        "total": len(rows),
        "pending": sum(1 for row in rows if row.status == Status.pending),
        "running": sum(1 for row in rows if row.status == Status.running),
        "complete": sum(1 for row in rows if row.status == Status.complete),
        "failed": sum(1 for row in rows if row.status == Status.failed),
    }


def submit_human_judgement(session, graph_run_id: int, pair_id: int, *, winner: str, reasoning: str = "", human_reviewer: str = "") -> GraphJudgement:
    """Complete or update one human pairwise judgement."""

    pair = session.get(GraphPair, pair_id)
    if not pair or pair.graph_run_id != graph_run_id:
        raise ValueError(f"Pair {pair_id} does not exist for run {graph_run_id}")
    winner = winner.upper()
    if winner not in {"A", "B", "TIE"}:
        raise ValueError("winner must be A, B, or TIE")
    judgement = session.exec(select(GraphJudgement).where(GraphJudgement.pair_id == pair_id, GraphJudgement.evaluator_type == "human_pairwise")).first()
    if not judgement:
        judgement = GraphJudgement(pair_id=pair_id, evaluator_type="human_pairwise")
    judgement.winner = winner
    judgement.reasoning = reasoning.strip()
    judgement.human_reviewer = human_reviewer.strip() or None
    judgement.updated_at = utc_now()
    pair.status = Status.complete
    session.add(pair)
    session.add(judgement)
    session.commit()
    session.refresh(judgement)
    return judgement


def graph_run_leaderboards(session, graph_run_id: int, _nodes=None, *, view_mode: str = "aggregate", target_stage_id: str = "", evaluator_type: str = "") -> list[dict[str, Any]]:
    """Compute one terminal-candidate ELO leaderboard from completed judgements."""

    pairs = {pair.id: pair for pair in session.exec(select(GraphPair).where(GraphPair.graph_run_id == graph_run_id)).all()}
    judgements = session.exec(select(GraphJudgement)).all()
    spec = _run_spec(session, graph_run_id)
    candidate_labels = {candidate.id: candidate.title or candidate.id for stage in spec.stages for candidate in stage.candidates}
    ratings: dict[str, float] = {}
    records: dict[str, dict[str, int]] = {}
    favorites: dict[str, set[str]] = {}
    for judgement in judgements:
        pair = pairs.get(judgement.pair_id)
        if not pair or pair.graph_run_id != graph_run_id or not judgement.winner:
            continue
        if target_stage_id and pair.target_stage_id != target_stage_id:
            continue
        if evaluator_type and judgement.evaluator_type != evaluator_type:
            continue
        entity_a = _terminal_candidate(pair.a_lineage_key)
        entity_b = _terminal_candidate(pair.b_lineage_key)
        if not entity_a or not entity_b or entity_a == entity_b:
            continue
        winner: Winner = judgement.winner if judgement.winner in {"A", "B", "TIE"} else "TIE"  # type: ignore[assignment]
        if pair.direction == "swapped":
            winner = "B" if winner == "A" else "A" if winner == "B" else "TIE"
        ratings.setdefault(entity_a, 1500.0)
        ratings.setdefault(entity_b, 1500.0)
        records.setdefault(entity_a, {"wins": 0, "losses": 0, "ties": 0})
        records.setdefault(entity_b, {"wins": 0, "losses": 0, "ties": 0})
        ratings[entity_a], ratings[entity_b] = update_elo(ratings[entity_a], ratings[entity_b], winner)
        if winner == "A":
            records[entity_a]["wins"] += 1
            records[entity_b]["losses"] += 1
            favorites.setdefault(entity_a, set()).add(pair.evaluator_id)
        elif winner == "B":
            records[entity_b]["wins"] += 1
            records[entity_a]["losses"] += 1
            favorites.setdefault(entity_b, set()).add(pair.evaluator_id)
        else:
            records[entity_a]["ties"] += 1
            records[entity_b]["ties"] += 1
    rows = [
        {
            "entity_key": key,
            "label": candidate_labels.get(key, key),
            "node_id": None,
            "rating": rating,
            "wins": records.get(key, {}).get("wins", 0),
            "losses": records.get(key, {}).get("losses", 0),
            "ties": records.get(key, {}).get("ties", 0),
            "avg_tokens": "n/a",
            "favorites": [{"id": index, "title": title} for index, title in enumerate(sorted(favorites.get(key, set())), start=1)],
        }
        for key, rating in sorted(ratings.items(), key=lambda item: item[1], reverse=True)
    ]
    return [{"title": "ELO Leaderboard", "judge_prompt_node_id": None, "view_mode": view_mode, "rows": rows}]


def graph_run_leaderboard(session, graph_run_id: int, nodes=None) -> list[dict[str, Any]]:
    """Compatibility wrapper for analysis code."""

    groups = graph_run_leaderboards(session, graph_run_id, nodes)
    return groups[0]["rows"] if groups else []


def dataset_items(spec: GraphSpec) -> list[DatasetItem]:
    """Load markdown-folder or CSV dataset items."""

    cfg = spec.dataset.config
    if spec.dataset.provider == "csv":
        path = Path(str(cfg.get("path") or ""))
        if not path.exists():
            return []
        id_column = str(cfg.get("id_column") or "call_id")
        text_column = str(cfg.get("text_column") or "transcript")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        items = []
        for index, row in enumerate(rows):
            values = {key: str(value or "") for key, value in row.items()}
            if text_column in values:
                values["transcript"] = values[text_column]
            items.append(DatasetItem(key=values.get(id_column) or f"row_{index + 1}", values=values))
        return items
    root = Path(str(cfg.get("path") or "transcripts"))
    if not root.exists():
        return []
    items = []
    for path in sorted([p for p in root.iterdir() if p.suffix.lower() in {".md", ".txt"}]):
        items.append(DatasetItem(key=path.stem, values={"call_id": path.stem, "transcript": path.read_text(encoding="utf-8")}))
    return items


async def _run_generation_invocation(
    graph_run_id: int,
    stage_index: int,
    stage: StageSpec,
    candidate: CandidateSpec,
    item: DatasetItem,
    input_branch: OutputBranch | None,
    constants: dict[str, str],
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> OutputBranch | None:
    previous_output = input_branch.output if input_branch else ""
    lineage_key = f"{input_branch.lineage_key}->{candidate.id}" if input_branch else candidate.id
    template = _prompt_text(candidate.prompt_path, candidate.prompt_inline)
    rendered = render_template(template, {**item.values, **constants, "previous_output": previous_output})
    unresolved = _unresolved_inputs(rendered)
    with session_factory() as session:
        existing = session.exec(
            select(GraphInvocation).where(
                GraphInvocation.graph_run_id == graph_run_id,
                GraphInvocation.kind == "generation",
                GraphInvocation.stage_id == stage.id,
                GraphInvocation.candidate_id == candidate.id,
                GraphInvocation.item_key == item.key,
                GraphInvocation.lineage_key == lineage_key,
            )
        ).first()
        if existing and existing.status == Status.complete:
            return OutputBranch(
                item=item,
                stage_id=stage.id,
                candidate_id=candidate.id,
                candidate_title=candidate.title or candidate.id,
                lineage_key=lineage_key,
                output=existing.output_json if stage.upstream_output == "json" and existing.output_json else existing.output_raw or "",
                invocation_id=existing.id,
            )
        invocation = existing or GraphInvocation(graph_run_id=graph_run_id, kind="generation", stage_id=stage.id, candidate_id=candidate.id, item_key=item.key, lineage_key=lineage_key, stage_index=stage_index, model_id=candidate.model)
        invocation.status = Status.running
        invocation.rendered_prompt = rendered
        invocation.error = None
        invocation.error_category = None
        if unresolved:
            invocation.status = Status.failed
            invocation.error = f"Unresolved prompt inputs: {', '.join(unresolved)}"
            invocation.error_category = "unresolved_template"
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
            return None
        invocation.started_at = utc_now()
        session.add(invocation)
        session.commit()
        invocation_id = invocation.id
    try:
        async with semaphore:
            started = time.perf_counter()
            response = await client.chat(model=candidate.model, temperature=candidate.params.temperature, reasoning_effort=candidate.params.reasoning_effort, retries=candidate.params.retry_count, messages=[{"role": "user", "content": rendered}])
            duration = max(time.perf_counter() - started, 0.001)
        repaired = maybe_repair_json(response.text)
        output_text = response.text
        output_json = repaired
        if stage.upstream_output == "json":
            try:
                parsed = parse_json_object(repaired)
            except Exception as exc:  # noqa: BLE001
                with session_factory() as session:
                    invocation = session.get(GraphInvocation, invocation_id)
                    invocation.status = Status.failed
                    invocation.output_raw = response.text
                    invocation.output_json = repaired
                    invocation.error = f"Invalid JSON output for {stage.id}: {exc}"
                    invocation.error_category = "invalid_json_output"
                    invocation.completed_at = utc_now()
                    session.add(invocation)
                    session.commit()
                print(f"[graph run {graph_run_id}] invalid JSON output: {response.text}", flush=True)
                return None
            output_json = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
            output_text = output_json
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.complete
            invocation.output_raw = response.text
            invocation.output_json = output_json
            invocation.prompt_tokens = response.prompt_tokens
            invocation.completion_tokens = response.completion_tokens
            invocation.duration_seconds = duration
            invocation.output_tokens_per_second = (response.completion_tokens or 0) / duration if response.completion_tokens else None
            invocation.cost = response.cost
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
            return OutputBranch(item=item, stage_id=stage.id, candidate_id=candidate.id, candidate_title=candidate.title or candidate.id, lineage_key=lineage_key, output=output_text, invocation_id=invocation_id)
    except Exception as exc:  # noqa: BLE001
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.failed
            invocation.error = str(exc)
            invocation.error_category = _error_category(exc)
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
        print(f"[graph run {graph_run_id}] generation failed: {traceback.format_exc()}", flush=True)
        return None


def _ensure_pairs(session, graph_run_id: int, evaluator: EvaluatorSpec, outputs: list[OutputBranch]) -> list[GraphPair]:
    by_item: dict[str, list[OutputBranch]] = {}
    for output in outputs:
        by_item.setdefault(output.item.key, []).append(output)
    created_or_existing: list[GraphPair] = []
    for item_outputs in by_item.values():
        pairs = [(a, b) for index, a in enumerate(item_outputs) for b in item_outputs[index + 1 :]]
        pairs = _sample_pairs(pairs, evaluator.pairing.sample_pct)
        for a, b in pairs:
            directions = ["normal", "swapped"] if evaluator.pairing.swap else ["normal"]
            for direction in directions:
                first, second = (b, a) if direction == "swapped" else (a, b)
                pair_key = f"{first.lineage_key}-vs-{second.lineage_key}"
                existing = session.exec(
                    select(GraphPair).where(
                        GraphPair.graph_run_id == graph_run_id,
                        GraphPair.evaluator_id == evaluator.id,
                        GraphPair.target_stage_id == evaluator.target_stage,
                        GraphPair.item_key == first.item.key,
                        GraphPair.pair_key == pair_key,
                        GraphPair.direction == direction,
                    )
                ).first()
                pair = existing or GraphPair(
                    graph_run_id=graph_run_id,
                    evaluator_id=evaluator.id,
                    target_stage_id=evaluator.target_stage,
                    item_key=first.item.key,
                    pair_key=pair_key,
                    a_invocation_id=first.invocation_id,
                    b_invocation_id=second.invocation_id,
                    a_lineage_key=first.lineage_key,
                    b_lineage_key=second.lineage_key,
                    direction=direction,
                    status=Status.pending,
                )
                session.add(pair)
                session.flush()
                created_or_existing.append(pair)
    session.commit()
    return session.exec(select(GraphPair).where(GraphPair.graph_run_id == graph_run_id, GraphPair.evaluator_id == evaluator.id)).all()


async def _run_llm_judge_pair(graph_run_id: int, evaluator: EvaluatorSpec, pair_id: int, constants: dict[str, str], output_mode: str, session_factory, client: OpenRouterClient, semaphore: asyncio.Semaphore) -> None:
    with session_factory() as session:
        pair = session.get(GraphPair, pair_id)
        if not pair or pair.status == Status.complete:
            return
        a_invocation = session.get(GraphInvocation, pair.a_invocation_id)
        b_invocation = session.get(GraphInvocation, pair.b_invocation_id)
        if not a_invocation or not b_invocation:
            pair.status = Status.failed
            session.add(pair)
            session.commit()
            return
        if output_mode == "json" and (not a_invocation.output_json or not b_invocation.output_json):
            pair.status = Status.failed
            session.add(pair)
            session.commit()
            return
        values = {
            **constants,
            "output_a": a_invocation.output_json if output_mode == "json" else a_invocation.output_raw or "",
            "output_b": b_invocation.output_json if output_mode == "json" else b_invocation.output_raw or "",
            "model_a": pair.a_lineage_key,
            "model_b": pair.b_lineage_key,
            "lineage_a": pair.a_lineage_key,
            "lineage_b": pair.b_lineage_key,
        }
        template = _prompt_text(evaluator.prompt_path, evaluator.prompt_inline)
        rendered = render_template(template, values)
        existing_judgement = session.exec(select(GraphJudgement).where(GraphJudgement.pair_id == pair_id, GraphJudgement.evaluator_type == "llm_pairwise")).first()
        if existing_judgement and existing_judgement.winner:
            pair.status = Status.complete
            session.add(pair)
            session.commit()
            return
        invocation = GraphInvocation(graph_run_id=graph_run_id, kind="llm_judge", stage_id=evaluator.target_stage, evaluator_id=evaluator.id, item_key=pair.item_key, lineage_key=pair.pair_key, stage_index=10_000, model_id=evaluator.model, rendered_prompt=rendered, status=Status.running, started_at=utc_now())
        session.add(invocation)
        session.commit()
        invocation_id = invocation.id
    try:
        async with semaphore:
            started = time.perf_counter()
            response = await client.chat(model=evaluator.model, temperature=evaluator.params.temperature, reasoning_effort=evaluator.params.reasoning_effort, retries=evaluator.params.retry_count, messages=[{"role": "user", "content": rendered}])
            duration = max(time.perf_counter() - started, 0.001)
        parsed = parse_json_object(response.text)
        winner = str(parsed.get(evaluator.output.winner_key, "TIE")).upper()
        if winner not in {"A", "B", "TIE"}:
            winner = "TIE"
        reasoning = str(parsed.get(evaluator.output.reasoning_key, "")).strip()
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.complete
            invocation.output_raw = response.text
            invocation.output_json = maybe_repair_json(response.text)
            invocation.prompt_tokens = response.prompt_tokens
            invocation.completion_tokens = response.completion_tokens
            invocation.duration_seconds = duration
            invocation.output_tokens_per_second = (response.completion_tokens or 0) / duration if response.completion_tokens else None
            invocation.cost = response.cost
            invocation.completed_at = utc_now()
            session.add(invocation)
            judgement = GraphJudgement(pair_id=pair_id, evaluator_type="llm_pairwise", judge_invocation_id=invocation_id, winner=winner, reasoning=reasoning)
            pair = session.get(GraphPair, pair_id)
            pair.status = Status.complete
            session.add(pair)
            session.add(judgement)
            session.commit()
    except Exception as exc:  # noqa: BLE001
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.failed
            invocation.error = str(exc)
            invocation.error_category = _error_category(exc)
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
        print(f"[graph run {graph_run_id}] judge failed: {traceback.format_exc()}", flush=True)


def _run_spec(session, graph_run_id: int) -> GraphSpec:
    run = _require_run(session, graph_run_id)
    return parse_spec(run.spec_snapshot_json)


def _require_run(session, graph_run_id: int) -> GraphRun:
    run = session.get(GraphRun, graph_run_id)
    if not run:
        raise ValueError(f"Graph run {graph_run_id} does not exist")
    return run


def _requeue_unfinished_invocations(session, graph_run_id: int) -> None:
    """Reset unfinished invocations so a resumed run can make forward progress."""

    rows = session.exec(
        select(GraphInvocation).where(
            GraphInvocation.graph_run_id == graph_run_id,
            GraphInvocation.status.in_([Status.failed, Status.running]),
        )
    ).all()
    for invocation in rows:
        invocation.status = Status.pending
        invocation.error = None
        invocation.error_category = None
        invocation.output_raw = None
        invocation.output_json = None
        invocation.started_at = None
        invocation.completed_at = None
        invocation.prompt_tokens = None
        invocation.completion_tokens = None
        invocation.duration_seconds = None
        invocation.output_tokens_per_second = None
        invocation.cost = None
        session.add(invocation)


def _sync_graph_status(session, run: GraphRun) -> None:
    graph = session.get(ExperimentGraph, run.graph_id)
    if graph and run.status.value in {status.value for status in GraphStatus}:
        graph.status = GraphStatus(run.status.value)
        graph.last_run_id = run.id
        graph.updated_at = utc_now()
        session.add(graph)


def _prompt_text(path: str | None, inline: str | None) -> str:
    if inline:
        return inline
    if path:
        return Path(path).read_text(encoding="utf-8")
    return ""


def _prompt_snapshots(spec: GraphSpec) -> dict[str, dict[str, str]]:
    paths = [candidate.prompt_path for stage in spec.stages for candidate in stage.candidates if candidate.prompt_path]
    paths += [evaluator.prompt_path for evaluator in spec.evaluators if evaluator.type == "llm_pairwise" and evaluator.prompt_path]
    snapshots = {}
    for path in sorted(set(paths)):
        content = Path(path).read_text(encoding="utf-8")
        snapshots[path] = {"content": content, "hash": hashlib.sha256(content.encode("utf-8")).hexdigest()}
    return snapshots


def _dataset_hash(items: list[DatasetItem]) -> str:
    payload = json.dumps([{"item_key": item.key, "values": item.values} for item in items], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sample_pairs(pairs: list[tuple[OutputBranch, OutputBranch]], sample_pct: float) -> list[tuple[OutputBranch, OutputBranch]]:
    if sample_pct >= 100:
        return pairs
    if not pairs:
        return []
    count = max(1, int(len(pairs) * max(1.0, min(100.0, sample_pct)) / 100))
    return pairs[:count]


def _terminal_candidate(lineage_key: str) -> str:
    return lineage_key.split("->")[-1] if lineage_key else ""


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _unresolved_inputs(rendered: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}", rendered)))


def _error_category(exc: Exception) -> str:
    message = str(exc).lower()
    if "api_key" in message or "api key" in message:
        return "missing_api_key"
    if "404" in message or "not found" in message:
        return "model_not_found"
    if "timeout" in message:
        return "timeout"
    if "rate" in message or "429" in message:
        return "rate_limit"
    return "model_call_failed"
