"""Graph edge API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend import schemas
from backend.api._shared import api_error, edge_dto, require_graph
from backend.deps import get_session
from council.graphs import create_edge, delete_edge, delete_socket_edges

router = APIRouter(tags=["edges"])


@router.post("/graphs/{graph_id}/edges", response_model=schemas.GraphEdgeDto)
def create_edge_route(graph_id: int, payload: schemas.CreateEdgeRequest, session: Session = Depends(get_session)):
    """Create a graph socket edge."""

    require_graph(session, graph_id)
    try:
        edge = create_edge(
            session,
            graph_id,
            from_node_id=payload.from_node_id,
            from_socket=payload.from_socket,
            to_node_id=payload.to_node_id,
            to_socket=payload.to_socket,
        )
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc)) from exc
    return edge_dto(edge)


@router.delete("/edges/{edge_id}", response_model=schemas.OkResponse)
def delete_edge_route(edge_id: int, session: Session = Depends(get_session)):
    """Delete one graph edge."""

    graph_id = delete_edge(session, edge_id)
    if graph_id is None:
        raise api_error(404, "not_found", f"Edge {edge_id} does not exist")
    return schemas.OkResponse()


@router.delete("/graphs/{graph_id}/socket-edges", response_model=schemas.OkResponse)
def delete_socket_edges_route(graph_id: int, payload: schemas.DeleteSocketEdgesRequest, session: Session = Depends(get_session)):
    """Delete all edges attached to one socket."""

    require_graph(session, graph_id)
    delete_socket_edges(session, graph_id, node_id=payload.node_id, socket=payload.socket, side=payload.side)
    return schemas.OkResponse()
