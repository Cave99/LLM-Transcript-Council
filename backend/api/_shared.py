"""Shared API mapping helpers for spec-backed graphs."""

from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from backend import schemas
from council.graph_runtime import graph_native_progress, graph_run_leaderboards
from council.graphs import ensure_graph_spec, graph_layout, graph_spec, plan_graph, semantic_nodes_edges
from council.models import ExperimentGraph, GraphInvocation, GraphJudgement, GraphPair, GraphRun, GraphRunAnalysis, Project, Status


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
    return ensure_graph_spec(session, graph)


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
        spec_hash=graph.spec_hash,
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
        recent_runs = session.exec(select(GraphRun).where(GraphRun.graph_id.in_(graph_ids)).order_by(GraphRun.created_at.desc()).limit(5)).all()
    return schemas.ProjectSummary(id=project.id, name=project.name, created_at=project.created_at, graph_count=len(graph_ids), recent_graph_runs=[graph_run_summary(run) for run in recent_runs])


def graph_plan_dto(session: Session, graph_id: int) -> schemas.GraphPlanDto:
    plan = plan_graph(session, graph_id)
    return schemas.GraphPlanDto(
        transcript_count=plan.transcript_count,
        stage_count=plan.stage_count,
        candidate_count=plan.candidate_count,
        evaluator_count=plan.evaluator_count,
        generation_calls=plan.generation_calls,
        pair_count=plan.pair_count,
        judge_calls=plan.judge_calls,
        human_review_count=plan.human_review_count,
        warnings=list(plan.warnings),
    )


def graph_detail(session: Session, graph: ExperimentGraph) -> schemas.GraphDetail:
    latest_run = graph_run_summary(session.get(GraphRun, graph.last_run_id)) if graph.last_run_id and session.get(GraphRun, graph.last_run_id) else None
    graph_runs = session.exec(select(GraphRun).where(GraphRun.graph_id == graph.id).order_by(GraphRun.created_at.desc()).limit(25)).all()
    nodes, edges = semantic_nodes_edges(graph)
    return schemas.GraphDetail(
        graph=graph_summary(graph),
        spec=graph_spec(graph).model_dump(mode="json", exclude_none=True),
        layout=graph_layout(graph),
        nodes=[schemas.SemanticNodeDto(id=node.id, kind=node.kind, title=node.title, x=node.x, y=node.y) for node in nodes],
        edges=[schemas.SemanticEdgeDto(id=edge["id"], source=edge["source"], target=edge["target"]) for edge in edges],
        plan=graph_plan_dto(session, graph.id),
        latest_run=latest_run,
        graph_runs=[graph_run_summary(run) for run in graph_runs],
    )


def progress_dto(progress: dict[str, int]) -> schemas.GraphProgress:
    return schemas.GraphProgress(**progress)


def graph_run_diagnostics(run: GraphRun, progress: dict[str, int]) -> list[schemas.GraphDiagnostic]:
    diagnostics = []
    if run.error:
        diagnostics.append(schemas.GraphDiagnostic(level="error", message=run.error))
    if progress["failed"]:
        diagnostics.append(schemas.GraphDiagnostic(level="warning", message=f"{progress['failed']} model call(s) failed."))
    if run.status == Status.running:
        diagnostics.append(schemas.GraphDiagnostic(level="info", message="Worker is running."))
    if not diagnostics:
        diagnostics.append(schemas.GraphDiagnostic(level="info", message="No diagnostics."))
    return diagnostics


def leaderboard_groups(session: Session, run: GraphRun, view_mode: str) -> list[schemas.GraphLeaderboardGroup]:
    groups = graph_run_leaderboards(session, run.id, view_mode=view_mode)
    return [
        schemas.GraphLeaderboardGroup(
            title=group["title"],
            view_mode=group.get("view_mode", view_mode),
            rows=[
                schemas.GraphLeaderboardRow(
                    entity_key=row["entity_key"],
                    label=row["label"],
                    rating=row["rating"],
                    wins=row["wins"],
                    losses=row["losses"],
                    ties=row["ties"],
                    avg_tokens=row["avg_tokens"],
                    favorites=[schemas.LeaderboardFavorite(id=fav["id"], title=fav["title"]) for fav in row.get("favorites", [])],
                )
                for row in group["rows"]
            ],
        )
        for group in groups
    ]


def invocation_dto(invocation: GraphInvocation) -> schemas.GraphInvocationDto:
    return schemas.GraphInvocationDto(
        id=invocation.id,
        graph_run_id=invocation.graph_run_id,
        kind=invocation.kind,
        stage_id=invocation.stage_id,
        candidate_id=invocation.candidate_id,
        evaluator_id=invocation.evaluator_id,
        lineage_key=invocation.lineage_key,
        model_id=invocation.model_id,
        item_key=invocation.item_key,
        stage_index=invocation.stage_index,
        status=invocation.status.value,
        rendered_prompt=invocation.rendered_prompt,
        output_raw=invocation.output_raw,
        output_json=invocation.output_json,
        error=invocation.error,
        error_category=invocation.error_category,
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
        evaluator_id=analysis.evaluator_id,
        leaderboard_view=analysis.leaderboard_view,
        top_entity_key=analysis.top_entity_key,
        top_entity_label=analysis.top_entity_label,
        model_id=analysis.model_id,
        win_sample_size=analysis.win_sample_size,
        loss_sample_size=analysis.loss_sample_size,
        summary=analysis.summary,
        created_at=analysis.created_at,
    )


def pair_dto(pair: GraphPair, judgement: GraphJudgement | None, invocations: dict[int, GraphInvocation]) -> schemas.GraphPairDto:
    a = invocations.get(pair.a_invocation_id)
    b = invocations.get(pair.b_invocation_id)
    return schemas.GraphPairDto(
        id=pair.id,
        graph_run_id=pair.graph_run_id,
        evaluator_id=pair.evaluator_id,
        target_stage_id=pair.target_stage_id,
        item_key=pair.item_key,
        pair_key=pair.pair_key,
        a_lineage_key=pair.a_lineage_key,
        b_lineage_key=pair.b_lineage_key,
        direction=pair.direction,
        status=pair.status.value,
        output_a=a.output_raw if a else None,
        output_b=b.output_raw if b else None,
        winner=judgement.winner if judgement else None,
        reasoning=judgement.reasoning if judgement else "",
        human_reviewer=judgement.human_reviewer if judgement else None,
    )


def human_eval_pairs(session: Session, run_id: int) -> list[schemas.GraphPairDto]:
    pairs = session.exec(select(GraphPair).where(GraphPair.graph_run_id == run_id)).all()
    judgements = {judgement.pair_id: judgement for judgement in session.exec(select(GraphJudgement).where(GraphJudgement.evaluator_type == "human_pairwise")).all()}
    invocation_ids = {pair.a_invocation_id for pair in pairs} | {pair.b_invocation_id for pair in pairs}
    invocations = {row.id: row for row in session.exec(select(GraphInvocation).where(GraphInvocation.id.in_(invocation_ids))).all()} if invocation_ids else {}
    return [pair_dto(pair, judgements.get(pair.id), invocations) for pair in pairs]


def graph_run_detail(session: Session, run: GraphRun, view_mode: str = "aggregate") -> schemas.GraphRunDetail:
    graph = require_graph(session, run.graph_id)
    invocations = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == run.id).order_by(GraphInvocation.stage_index, GraphInvocation.created_at, GraphInvocation.id)).all()
    analyses = session.exec(select(GraphRunAnalysis).where(GraphRunAnalysis.graph_run_id == run.id).order_by(GraphRunAnalysis.created_at.desc())).all()
    progress = graph_native_progress(session, run.id)
    nodes, edges = semantic_nodes_edges(graph)
    return schemas.GraphRunDetail(
        run=graph_run_summary(run),
        graph=graph_summary(graph),
        nodes=[schemas.SemanticNodeDto(id=node.id, kind=node.kind, title=node.title, x=node.x, y=node.y) for node in nodes],
        edges=[schemas.SemanticEdgeDto(id=edge["id"], source=edge["source"], target=edge["target"]) for edge in edges],
        progress=progress_dto(progress),
        diagnostics=graph_run_diagnostics(run, progress),
        leaderboards=leaderboard_groups(session, run, view_mode),
        invocations=[invocation_dto(invocation) for invocation in invocations],
        human_evals=human_eval_pairs(session, run.id),
        analyses=[analysis_dto(analysis) for analysis in analyses],
    )
