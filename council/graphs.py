"""Spec-backed graph CRUD and planning helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from council.graph_spec import GraphSpec, dump_spec, generated_layout, minimal_spec, parse_spec, spec_hash, validate_spec_payload
from council.models import ExperimentGraph, GraphInvocation, GraphJudgement, GraphPair, GraphRun, GraphRunAnalysis, GraphStatus, Project, utc_now


@dataclass(frozen=True)
class GraphPlan:
    """Computed work plan shown before a graph is launched."""

    transcript_count: int
    stage_count: int
    candidate_count: int
    evaluator_count: int
    generation_calls: int
    pair_count: int
    judge_calls: int
    human_review_count: int
    warnings: tuple[str, ...]


def create_graph(session: Session, project_id: int, name: str, spec_payload: dict[str, Any] | None = None) -> ExperimentGraph:
    """Create a draft graph with a canonical spec."""

    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} does not exist")
    spec = parse_spec(spec_payload)
    graph = ExperimentGraph(
        project_id=project_id,
        name=name.strip() or "Untitled graph",
        spec_json=dump_spec(spec),
        layout_json=json.dumps(_default_layout(spec), sort_keys=True),
        spec_hash=spec_hash(spec),
    )
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph


def ensure_graph_spec(session: Session, graph: ExperimentGraph) -> ExperimentGraph:
    """Ensure a graph always has a canonical spec payload."""

    if not graph:
        raise ValueError("Graph does not exist")
    if graph.spec_json and graph.spec_json != "{}":
        return graph
    spec = minimal_spec()
    graph.spec_json = dump_spec(spec)
    graph.layout_json = json.dumps(_default_layout(spec), sort_keys=True)
    graph.spec_hash = spec_hash(spec)
    graph.updated_at = utc_now()
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph


def rename_graph(session: Session, graph_id: int, name: str) -> ExperimentGraph | None:
    """Rename a graph draft or completed graph."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        return None
    cleaned = name.strip()
    if cleaned:
        graph.name = cleaned
        graph.updated_at = utc_now()
        session.add(graph)
        session.commit()
        session.refresh(graph)
    return graph


def update_graph_spec(session: Session, graph_id: int, spec_payload: dict[str, Any], layout_payload: dict[str, Any] | None = None) -> ExperimentGraph:
    """Persist an editable graph draft and optional canvas layout."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        raise ValueError(f"Graph {graph_id} does not exist")
    validation = validate_spec_payload(spec_payload, require_executable=False)
    if not validation.valid:
        raise ValueError("; ".join(error.message for error in validation.errors))
    spec = parse_spec(spec_payload)
    graph.spec_json = dump_spec(spec)
    if layout_payload is not None:
        graph.layout_json = json.dumps(layout_payload, sort_keys=True)
    graph.spec_hash = spec_hash(spec)
    graph.status = GraphStatus.draft if graph.status == GraphStatus.complete else graph.status
    graph.updated_at = utc_now()
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph


def update_graph_layout(session: Session, graph_id: int, layout_payload: dict[str, Any]) -> ExperimentGraph:
    """Persist canvas layout without changing the semantic spec hash."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        raise ValueError(f"Graph {graph_id} does not exist")
    graph.layout_json = json.dumps(layout_payload, sort_keys=True)
    graph.updated_at = utc_now()
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph


def delete_graph(session: Session, graph_id: int) -> None:
    """Delete a spec-backed graph and all graph-native child rows."""

    graph_run_ids = list(session.exec(select(GraphRun.id).where(GraphRun.graph_id == graph_id)).all())
    for graph_run_id in graph_run_ids:
        for analysis in session.exec(select(GraphRunAnalysis).where(GraphRunAnalysis.graph_run_id == graph_run_id)).all():
            session.delete(analysis)
        pair_ids = list(session.exec(select(GraphPair.id).where(GraphPair.graph_run_id == graph_run_id)).all())
        for pair_id in pair_ids:
            for judgement in session.exec(select(GraphJudgement).where(GraphJudgement.pair_id == pair_id)).all():
                session.delete(judgement)
            pair = session.get(GraphPair, pair_id)
            if pair:
                session.delete(pair)
        for invocation in session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id)).all():
            session.delete(invocation)
        run = session.get(GraphRun, graph_run_id)
        if run:
            session.delete(run)
    graph = session.get(ExperimentGraph, graph_id)
    if graph:
        session.delete(graph)
    session.commit()


def fork_graph(session: Session, graph_id: int, name: str | None = None) -> ExperimentGraph:
    """Create an editable draft copy of an existing graph spec."""

    source = ensure_graph_spec(session, session.get(ExperimentGraph, graph_id))
    fork = ExperimentGraph(
        project_id=source.project_id,
        name=(name or f"{source.name} draft").strip(),
        status=GraphStatus.draft,
        spec_json=source.spec_json,
        layout_json=source.layout_json,
        spec_hash=source.spec_hash,
    )
    session.add(fork)
    session.commit()
    session.refresh(fork)
    return fork


def graph_spec(graph: ExperimentGraph) -> GraphSpec:
    """Return a parsed graph spec."""

    return parse_spec(graph.spec_json)


def graph_layout(graph: ExperimentGraph) -> dict[str, Any]:
    """Return graph layout JSON."""

    try:
        return json.loads(graph.layout_json or "{}")
    except json.JSONDecodeError:
        return {}


def semantic_nodes_edges(graph: ExperimentGraph):
    """Return semantic React Flow nodes and edges generated from the spec."""

    return generated_layout(graph_spec(graph), graph_layout(graph))


def plan_graph(session: Session, graph_id: int, *, sample_size: int | None = None) -> GraphPlan:
    """Calculate spec-backed call counts and launch warnings."""

    graph = ensure_graph_spec(session, session.get(ExperimentGraph, graph_id))
    spec = graph_spec(graph)
    transcript_count = _dataset_count(spec)
    if sample_size:
        transcript_count = min(transcript_count, sample_size)
    stage_branch_counts: list[int] = []
    current_branches = 1
    generation_calls = 0
    candidate_count = 0
    warnings: list[str] = []
    for stage in spec.stages:
        candidates = len(stage.candidates)
        candidate_count += candidates
        calls = transcript_count * current_branches * candidates
        generation_calls += calls
        current_branches = max(1, current_branches * max(1, candidates))
        stage_branch_counts.append(current_branches)
        if calls > 1000:
            warnings.append(f"Stage {stage.id} will create {calls:,} generation calls with matrix fanout.")
    pair_count = 0
    judge_calls = 0
    human_review_count = 0
    stage_index = {stage.id: index for index, stage in enumerate(spec.stages)}
    for evaluator in spec.evaluators:
        target_index = stage_index.get(evaluator.target_stage)
        branches = stage_branch_counts[target_index] if target_index is not None and target_index < len(stage_branch_counts) else 0
        pairs_per_item = branches * (branches - 1) // 2
        sampled = _sampled_pair_count(pairs_per_item, evaluator.pairing.sample_pct)
        multiplier = 2 if evaluator.pairing.swap else 1
        evaluator_pairs = transcript_count * sampled * multiplier
        pair_count += evaluator_pairs
        if evaluator.type == "human_pairwise":
            human_review_count += evaluator_pairs
        else:
            judge_calls += evaluator_pairs
    return GraphPlan(
        transcript_count=transcript_count,
        stage_count=len(spec.stages),
        candidate_count=candidate_count,
        evaluator_count=len(spec.evaluators),
        generation_calls=generation_calls,
        pair_count=pair_count,
        judge_calls=judge_calls,
        human_review_count=human_review_count,
        warnings=tuple(warnings),
    )


def _default_layout(spec: GraphSpec) -> dict[str, dict[str, int]]:
    nodes, _edges = generated_layout(spec, {})
    return {node.id: {"x": node.x, "y": node.y} for node in nodes}


def _dataset_count(spec: GraphSpec) -> int:
    cfg = spec.dataset.config
    path = str(cfg.get("path") or "")
    sample_size = _optional_int(cfg.get("sample_size"))
    if spec.dataset.provider == "csv":
        import csv

        try:
            with Path(path).open(newline="", encoding="utf-8") as handle:
                count = sum(1 for _row in csv.DictReader(handle))
        except OSError:
            return 0
    else:
        root = Path(path)
        if not root.exists():
            return 0
        count = len(sorted([p for p in root.iterdir() if p.suffix.lower() in {".md", ".txt"}]))
    return min(count, sample_size) if sample_size else count


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _sampled_pair_count(pair_count: int, sample_pct: float) -> int:
    if pair_count == 0:
        return 0
    if sample_pct >= 100:
        return pair_count
    return max(1, int(pair_count * max(1.0, min(100.0, sample_pct)) / 100))
