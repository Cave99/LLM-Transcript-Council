"""Graph API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend import schemas
from backend.api._shared import api_error, graph_detail, graph_plan_dto, graph_summary, require_graph, require_project
from backend.deps import get_session
from council.db import engine
from council.graph_runtime import create_graph_native_run
from council.graphs import create_graph, delete_graph, fork_graph, rename_graph
from council.jobs import start_graph_run_thread

router = APIRouter(prefix="/graphs", tags=["graphs"])


@router.post("", response_model=schemas.GraphSummary)
def create_graph_route(payload: schemas.GraphCreate, session: Session = Depends(get_session)):
    """Create a graph draft."""

    require_project(session, payload.project_id)
    graph = create_graph(session, payload.project_id, payload.name)
    return graph_summary(graph)


@router.get("/{graph_id}", response_model=schemas.GraphDetail)
def get_graph(graph_id: int, session: Session = Depends(get_session)):
    """Return a complete graph editor payload."""

    return graph_detail(session, require_graph(session, graph_id))


@router.patch("/{graph_id}", response_model=schemas.GraphSummary)
def update_graph(graph_id: int, payload: schemas.GraphUpdate, session: Session = Depends(get_session)):
    """Rename a graph."""

    graph = rename_graph(session, graph_id, payload.name)
    if not graph:
        raise api_error(404, "not_found", f"Graph {graph_id} does not exist")
    return graph_summary(graph)


@router.post("/{graph_id}/fork", response_model=schemas.GraphSummary)
def fork_graph_route(graph_id: int, session: Session = Depends(get_session)):
    """Fork a graph into a new editable draft."""

    require_graph(session, graph_id)
    graph = fork_graph(session, graph_id)
    return graph_summary(graph)


@router.delete("/{graph_id}", response_model=schemas.OkResponse)
def delete_graph_route(graph_id: int, session: Session = Depends(get_session)):
    """Delete a graph and its graph-native child rows."""

    require_graph(session, graph_id)
    delete_graph(session, graph_id)
    return schemas.OkResponse()


@router.get("/{graph_id}/plan", response_model=schemas.GraphPlanDto)
def get_graph_plan(graph_id: int, session: Session = Depends(get_session)):
    """Return graph launch estimates and warnings."""

    require_graph(session, graph_id)
    return graph_plan_dto(session, graph_id)


@router.post("/{graph_id}/launch", response_model=schemas.GraphRunSummary)
def launch_graph(graph_id: int, payload: schemas.LaunchGraphRunRequest, session: Session = Depends(get_session)):
    """Create and start a graph-native run."""

    graph = require_graph(session, graph_id)
    sample_size = 1 if payload.run_mode == "test" else None
    run = create_graph_native_run(session, graph.id, max_concurrency=payload.max_concurrency, sample_size=sample_size)
    graph.last_run_id = run.id
    session.add(graph)
    session.commit()
    session.refresh(run)
    start_graph_run_thread(run.id, lambda: Session(engine))
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
