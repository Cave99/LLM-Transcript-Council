"""Shared API mapping helpers."""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlmodel import Session, select

from backend import schemas
from council.graph_runtime import graph_native_progress, graph_run_leaderboards
from council.graphs import config, graph_edges, graph_nodes, plan_graph, prompt_inputs
from council.models import ExperimentGraph, GraphEdge, GraphInvocation, GraphNode, GraphRun, GraphRunAnalysis, Project, Status


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    """Create one consistent API error payload."""

    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def require_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise api_error(404, "not_found", f"Project {project_id} does not exist")
    return project


def require_graph(session: Session, graph_id: int) -> ExperimentGraph:
    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        raise api_error(404, "not_found", f"Graph {graph_id} does not exist")
    return graph


def require_graph_run(session: Session, graph_run_id: int) -> GraphRun:
    run = session.get(GraphRun, graph_run_id)
    if not run:
        raise api_error(404, "not_found", f"Graph run {graph_run_id} does not exist")
    return run


def graph_summary(graph: ExperimentGraph) -> schemas.GraphSummary:
    return schemas.GraphSummary(
        id=graph.id,
        project_id=graph.project_id,
        name=graph.name,
        status=graph.status.value,
        last_run_id=graph.last_run_id,
        created_at=graph.created_at,
        updated_at=graph.updated_at,
    )


def graph_run_summary(run: GraphRun) -> schemas.GraphRunSummary:
    return schemas.GraphRunSummary(
        id=run.id,
        graph_id=run.graph_id,
        name=run.name,
        status=run.status.value,
        max_concurrency=run.max_concurrency,
        sample_size=run.sample_size,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def project_summary(session: Session, project: Project) -> schemas.ProjectSummary:
    graph_ids = list(session.exec(select(ExperimentGraph.id).where(ExperimentGraph.project_id == project.id)).all())
    recent_runs = []
    if graph_ids:
        recent_runs = session.exec(
            select(GraphRun)
            .where(GraphRun.graph_id.in_(graph_ids))
            .order_by(GraphRun.created_at.desc())
            .limit(5)
        ).all()
    return schemas.ProjectSummary(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        graph_count=len(graph_ids),
        recent_graph_runs=[graph_run_summary(run) for run in recent_runs],
    )


def graph_plan_dto(session: Session, graph_id: int) -> schemas.GraphPlanDto:
    plan = plan_graph(session, graph_id)
    return schemas.GraphPlanDto(
        transcript_count=plan.transcript_count,
        prompt_stage_count=plan.prompt_stage_count,
        generator_model_count=plan.generator_model_count,
        judge_model_count=plan.judge_model_count,
        pair_count=plan.pair_count,
        sampled_matches_per_transcript=plan.sampled_matches_per_transcript,
        generation_calls=plan.generation_calls,
        match_count=plan.match_count,
        judge_calls=plan.judge_calls,
        swap_multiplier=plan.swap_multiplier,
        warnings=list(plan.warnings),
    )


def node_dto(node: GraphNode) -> schemas.GraphNodeDto:
    cfg = config(node)
    return schemas.GraphNodeDto(
        id=node.id,
        graph_id=node.graph_id,
        kind=node.kind,
        title=node.title,
        body=node.body,
        config=cfg,
        x=node.x,
        y=node.y,
        width=node.width,
        height=node.height,
        input_sockets=input_sockets(node, cfg),
        output_sockets=output_sockets(node, cfg),
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def edge_dto(edge: GraphEdge) -> schemas.GraphEdgeDto:
    return schemas.GraphEdgeDto(
        id=edge.id,
        graph_id=edge.graph_id,
        from_node_id=edge.from_node_id,
        from_socket=edge.from_socket,
        to_node_id=edge.to_node_id,
        to_socket=edge.to_socket,
        created_at=edge.created_at,
    )


def graph_detail(session: Session, graph: ExperimentGraph) -> schemas.GraphDetail:
    latest_run = None
    if graph.last_run_id:
        latest = session.get(GraphRun, graph.last_run_id)
        latest_run = graph_run_summary(latest) if latest else None
    graph_runs = session.exec(
        select(GraphRun)
        .where(GraphRun.graph_id == graph.id)
        .order_by(GraphRun.created_at.desc())
        .limit(25)
    ).all()
    return schemas.GraphDetail(
        graph=graph_summary(graph),
        nodes=[node_dto(node) for node in graph_nodes(session, graph.id)],
        edges=[edge_dto(edge) for edge in graph_edges(session, graph.id)],
        plan=graph_plan_dto(session, graph.id),
        latest_run=latest_run,
        graph_runs=[graph_run_summary(run) for run in graph_runs],
    )


def input_sockets(node: GraphNode, cfg: dict | None = None) -> list[str]:
    cfg = cfg if cfg is not None else config(node)
    if node.kind == "prompt":
        return prompt_inputs(node.body)
    if node.kind == "judge":
        sockets = prompt_inputs(node.body)
        defaults = ["models", "output", "output_a", "output_b"]
        return unique([*sockets, *defaults])
    if node.kind == "model":
        return ["model", "prompt", "judge_prompt"]
    return []


def output_sockets(node: GraphNode, cfg: dict | None = None) -> list[str]:
    cfg = cfg if cfg is not None else config(node)
    if node.kind == "dataset":
        if cfg.get("source_type", "markdown") == "csv":
            return unique(["transcript", cfg.get("id_column") or "call_id", "row_json"])
        return ["transcript", "call_id"]
    if node.kind == "constant":
        return [str(cfg.get("socket") or node.title or "constant")]
    if node.kind == "prompt":
        return ["output", "full_prompt", "template"]
    if node.kind == "model":
        return ["model", "raw", "json"]
    if node.kind == "judge":
        return ["judgement", "judge_prompt"]
    return []


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def progress_dto(progress: dict[str, int]) -> schemas.GraphProgress:
    return schemas.GraphProgress(**progress)


def node_progress(session: Session, nodes: list[GraphNode], invocations: list[GraphInvocation]) -> dict[int, schemas.GraphProgress]:
    by_node = {}
    for node in nodes:
        rows = [row for row in invocations if row.node_id == node.id]
        by_node[node.id] = progress_dto(
            {
                "total": len(rows),
                "pending": sum(1 for row in rows if row.status == Status.pending),
                "running": sum(1 for row in rows if row.status == Status.running),
                "complete": sum(1 for row in rows if row.status == Status.complete),
                "failed": sum(1 for row in rows if row.status == Status.failed),
            }
        )
    return by_node


def graph_run_diagnostics(run: GraphRun, progress: dict[str, int]) -> list[schemas.GraphDiagnostic]:
    diagnostics = []
    if run.error:
        diagnostics.append(schemas.GraphDiagnostic(level="error", message=run.error))
    if progress["failed"]:
        diagnostics.append(schemas.GraphDiagnostic(level="warning", message=f"{progress['failed']} invocation(s) failed."))
    if run.status == Status.running:
        diagnostics.append(schemas.GraphDiagnostic(level="info", message="Worker is running."))
    if not diagnostics:
        diagnostics.append(schemas.GraphDiagnostic(level="info", message="No diagnostics."))
    return diagnostics


def leaderboard_groups(session: Session, run: GraphRun, nodes: list[GraphNode], view_mode: str) -> list[schemas.GraphLeaderboardGroup]:
    normalized = view_mode if view_mode in {"aggregate", "overall", "chain"} else "aggregate"
    groups = graph_run_leaderboards(session, run.id, nodes, view_mode=normalized)
    if normalized == "overall" and groups:
        groups = [groups[0]]
    elif normalized != "overall":
        scoped = [group for group in groups if group["title"] != "Overall"]
        groups = scoped or groups
    return [
        schemas.GraphLeaderboardGroup(
            title=group["title"],
            judge_prompt_node_id=group.get("judge_prompt_node_id"),
            view_mode=group.get("view_mode", normalized),
            rows=[
                schemas.GraphLeaderboardRow(
                    entity_key=row["entity_key"],
                    label=row["label"],
                    node_id=row["node"].id if row.get("node") else None,
                    rating=row["rating"],
                    wins=row["wins"],
                    losses=row["losses"],
                    ties=row["ties"],
                    avg_tokens=row["avg_tokens"],
                    favorites=[schemas.LeaderboardFavorite(id=fav.id, title=fav.title) for fav in row.get("favorites", [])],
                )
                for row in group["rows"]
            ],
        )
        for group in groups
    ]


def invocation_dto(invocation: GraphInvocation, node_lookup: dict[int, GraphNode]) -> schemas.GraphInvocationDto:
    node = node_lookup.get(invocation.node_id)
    model = node_lookup.get(invocation.model_node_id)
    return schemas.GraphInvocationDto(
        id=invocation.id,
        graph_run_id=invocation.graph_run_id,
        node_id=invocation.node_id,
        model_node_id=invocation.model_node_id,
        node_title=node.title if node else "Unknown node",
        model_title=model.title if model else None,
        item_key=invocation.item_key,
        stage_index=invocation.stage_index,
        status=invocation.status.value,
        rendered_prompt=invocation.rendered_prompt,
        output_raw=invocation.output_raw,
        output_json=invocation.output_json,
        error=invocation.error,
        prompt_tokens=invocation.prompt_tokens,
        completion_tokens=invocation.completion_tokens,
        duration_seconds=invocation.duration_seconds,
        output_tokens_per_second=invocation.output_tokens_per_second,
        cost=invocation.cost,
        created_at=invocation.created_at,
        started_at=invocation.started_at,
        completed_at=invocation.completed_at,
    )


def analysis_dto(analysis: GraphRunAnalysis) -> schemas.GraphRunAnalysisDto:
    return schemas.GraphRunAnalysisDto(
        id=analysis.id,
        graph_run_id=analysis.graph_run_id,
        top_model_node_id=analysis.top_model_node_id,
        judge_prompt_node_id=analysis.judge_prompt_node_id,
        leaderboard_view=analysis.leaderboard_view,
        top_entity_key=analysis.top_entity_key,
        top_entity_label=analysis.top_entity_label,
        model_id=analysis.model_id,
        win_sample_size=analysis.win_sample_size,
        loss_sample_size=analysis.loss_sample_size,
        summary=analysis.summary,
        created_at=analysis.created_at,
    )


def graph_run_detail(session: Session, run: GraphRun, view_mode: str = "aggregate") -> schemas.GraphRunDetail:
    graph = require_graph(session, run.graph_id)
    nodes = graph_nodes(session, graph.id)
    node_lookup = {node.id: node for node in nodes}
    invocations = session.exec(
        select(GraphInvocation)
        .where(GraphInvocation.graph_run_id == run.id)
        .order_by(GraphInvocation.stage_index, GraphInvocation.created_at, GraphInvocation.id)
    ).all()
    analyses = session.exec(
        select(GraphRunAnalysis)
        .where(GraphRunAnalysis.graph_run_id == run.id)
        .order_by(GraphRunAnalysis.created_at.desc())
    ).all()
    progress = graph_native_progress(session, run.id)
    return schemas.GraphRunDetail(
        run=graph_run_summary(run),
        graph=graph_summary(graph),
        nodes=[node_dto(node) for node in nodes],
        edges=[edge_dto(edge) for edge in graph_edges(session, graph.id)],
        progress=progress_dto(progress),
        node_progress=node_progress(session, nodes, invocations),
        diagnostics=graph_run_diagnostics(run, progress),
        leaderboards=leaderboard_groups(session, run, nodes, view_mode),
        invocations=[invocation_dto(invocation, node_lookup) for invocation in invocations],
        analyses=[analysis_dto(analysis) for analysis in analyses],
    )


def parse_config_json(config_json: str) -> dict:
    try:
        return json.loads(config_json or "{}")
    except json.JSONDecodeError:
        return {}
