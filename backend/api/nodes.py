"""Graph node API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend import schemas
from backend.api._shared import api_error, node_dto, require_graph
from backend.deps import get_session
from council.graphs import add_constant_node, add_dataset_node, add_judge_node, add_model_node, add_prompt_node, delete_node, update_node, update_node_position

router = APIRouter(tags=["nodes"])


@router.post("/graphs/{graph_id}/nodes", response_model=schemas.GraphNodeDto)
def create_node(graph_id: int, payload: schemas.CreateNodeRequest, session: Session = Depends(get_session)):
    """Create a graph node of the requested kind."""

    require_graph(session, graph_id)
    title = payload.title or ""
    if payload.kind == "dataset":
        node = add_dataset_node(session, graph_id, x=payload.x, y=payload.y)
    elif payload.kind == "prompt":
        node = add_prompt_node(session, graph_id, title=title or "Next prompt", x=payload.x, y=payload.y)
    elif payload.kind == "constant":
        node = add_constant_node(session, graph_id, title=title or "Constant", body="", x=payload.x, y=payload.y)
    elif payload.kind == "model":
        node = add_model_node(session, graph_id, title=title or "Model", model_id="", role="generator", x=payload.x, y=payload.y)
    elif payload.kind == "judge":
        node = add_judge_node(session, graph_id, title=title or "Pairwise judge prompt", x=payload.x, y=payload.y)
    else:
        raise api_error(422, "validation_error", f"Unsupported node kind: {payload.kind}")
    return node_dto(node)


@router.patch("/nodes/{node_id}", response_model=schemas.GraphNodeDto)
def update_node_route(node_id: int, payload: schemas.UpdateNodeRequest, session: Session = Depends(get_session)):
    """Update node content and JSON config."""

    try:
        node = update_node(session, node_id, title=payload.title, body=payload.body, config_values=payload.config)
    except ValueError as exc:
        raise api_error(404, "not_found", str(exc)) from exc
    return node_dto(node)


@router.patch("/nodes/{node_id}/position", response_model=schemas.GraphNodeDto)
def update_position(node_id: int, payload: schemas.UpdateNodePositionRequest, session: Session = Depends(get_session)):
    """Persist node canvas geometry."""

    try:
        node = update_node_position(session, node_id, x=payload.x, y=payload.y, width=payload.width, height=payload.height)
    except ValueError as exc:
        raise api_error(404, "not_found", str(exc)) from exc
    return node_dto(node)


@router.delete("/nodes/{node_id}", response_model=schemas.OkResponse)
def delete_node_route(node_id: int, session: Session = Depends(get_session)):
    """Delete a graph node."""

    graph_id = delete_node(session, node_id)
    if graph_id is None:
        raise api_error(404, "not_found", f"Node {node_id} does not exist")
    return schemas.OkResponse()

