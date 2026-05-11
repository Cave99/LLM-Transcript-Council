"""Project API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend import schemas
from backend.api._shared import graph_summary, project_summary, require_project
from backend.deps import get_session
from council.graphs import delete_graph
from council.models import ExperimentGraph, Project
from council.runner import create_project, rename_project

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[schemas.ProjectSummary])
def list_projects(session: Session = Depends(get_session)):
    """List projects with graph counts and recent graph runs."""

    projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    return [project_summary(session, project) for project in projects]


@router.post("", response_model=schemas.ProjectSummary)
def create_project_route(payload: schemas.ProjectCreate, session: Session = Depends(get_session)):
    """Create a project."""

    project = create_project(session, payload.name)
    return project_summary(session, project)


@router.get("/{project_id}", response_model=schemas.ProjectDetail)
def get_project(project_id: int, session: Session = Depends(get_session)):
    """Return one project and its graphs."""

    project = require_project(session, project_id)
    summary = project_summary(session, project)
    graphs = session.exec(
        select(ExperimentGraph)
        .where(ExperimentGraph.project_id == project_id)
        .order_by(ExperimentGraph.updated_at.desc())
    ).all()
    return schemas.ProjectDetail(**summary.model_dump(), graphs=[graph_summary(graph) for graph in graphs])


@router.patch("/{project_id}", response_model=schemas.ProjectSummary)
def update_project(project_id: int, payload: schemas.ProjectUpdate, session: Session = Depends(get_session)):
    """Rename a project."""

    project = rename_project(session, project_id, payload.name)
    if not project:
        project = require_project(session, project_id)
    return project_summary(session, project)


@router.delete("/{project_id}", response_model=schemas.OkResponse)
def delete_project_route(project_id: int, session: Session = Depends(get_session)):
    """Delete a project and graph-native child rows."""

    project = require_project(session, project_id)
    graph_ids = list(session.exec(select(ExperimentGraph.id).where(ExperimentGraph.project_id == project.id)).all())
    for graph_id in graph_ids:
        delete_graph(session, graph_id)
    session.delete(project)
    session.commit()
    return schemas.OkResponse()

