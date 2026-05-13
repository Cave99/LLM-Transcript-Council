"""Graph API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend import schemas
from backend.api._shared import api_error, graph_detail, graph_plan_dto, graph_summary, require_graph, require_project
from backend.deps import get_session
from council.db import engine
from council.graph_spec import validate_spec_payload
from council.graph_runtime import create_graph_native_run
from council.graphs import create_graph, delete_graph, fork_graph, rename_graph, update_graph_layout, update_graph_spec
from council.jobs import start_graph_run_thread

router = APIRouter(prefix="/graphs", tags=["graphs"])


@router.post("", response_model=schemas.GraphSummary)
def create_graph_route(payload: schemas.GraphCreate, session: Session = Depends(get_session)):
    """Create a graph draft."""

    require_project(session, payload.project_id)
    graph = create_graph(session, payload.project_id, payload.name, payload.spec)
    return graph_summary(graph)


@router.get("/{graph_id}", response_model=schemas.GraphDetail)
def get_graph(graph_id: int, session: Session = Depends(get_session)):
    """Return a complete graph editor payload."""

    return graph_detail(session, require_graph(session, graph_id))


@router.patch("/{graph_id}", response_model=schemas.GraphDetail)
def update_graph(graph_id: int, payload: schemas.GraphUpdate, session: Session = Depends(get_session)):
    """Update graph name, spec, and/or layout."""

    graph = require_graph(session, graph_id)
    if payload.name is not None:
        graph = rename_graph(session, graph_id, payload.name)
    if payload.spec is not None:
        try:
            graph = update_graph_spec(session, graph_id, payload.spec, payload.layout)
        except ValueError as exc:
            raise api_error(422, "validation_error", str(exc)) from exc
    elif payload.layout is not None:
        graph = update_graph_layout(session, graph_id, payload.layout)
    if not graph:
        raise api_error(404, "not_found", f"Graph {graph_id} does not exist")
    return graph_detail(session, graph)


@router.get("/{graph_id}/spec")
def get_graph_spec(graph_id: int, session: Session = Depends(get_session)):
    """Export canonical graph spec JSON."""

    graph = require_graph(session, graph_id)
    import json

    return json.loads(graph.spec_json or "{}")


@router.put("/{graph_id}/spec", response_model=schemas.GraphDetail)
def put_graph_spec(graph_id: int, payload: dict, session: Session = Depends(get_session)):
    """Replace canonical graph spec JSON."""

    require_graph(session, graph_id)
    try:
        graph = update_graph_spec(session, graph_id, payload)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc)) from exc
    return graph_detail(session, graph)


@router.post("/validate-spec", response_model=schemas.ValidationResultDto)
def validate_graph_spec(payload: dict):
    """Validate unsaved graph spec JSON."""

    result = validate_spec_payload(payload)
    return schemas.ValidationResultDto(**result.model_dump())


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
