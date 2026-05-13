"""Graph analysis API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from backend import schemas
from backend.api._shared import require_graph_run
from backend.deps import get_session
from council.db import engine
from council.jobs import start_graph_analysis_thread

router = APIRouter(prefix="/graph-runs", tags=["analysis"])


@router.post("/{graph_run_id}/judge-summary", response_model=schemas.OkResponse)
def start_judge_summary(graph_run_id: int, payload: schemas.StartJudgeSummaryRequest, session: Session = Depends(get_session)):
    """Start a graph-run judge summary worker."""

    require_graph_run(session, graph_run_id)
    start_graph_analysis_thread(
        graph_run_id,
        lambda: Session(engine),
        leaderboard_view=payload.leaderboard_view,
        top_entity_key=payload.top_entity_key,
    )
    return schemas.OkResponse()
