"""Graph run API routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from backend import schemas
from backend.api._shared import graph_run_detail, graph_run_summary, human_eval_pairs, require_graph_run
from backend.deps import get_session
from council.db import engine
from council.graph_runtime import continue_graph_native_run, graph_native_progress, retry_graph_native_failures, stop_graph_native_run, submit_human_judgement
from council.jobs import start_graph_run_thread
from council.models import GraphRun, Status

router = APIRouter(prefix="/graph-runs", tags=["graph-runs"])


@router.get("/{graph_run_id}", response_model=schemas.GraphRunDetail)
def get_graph_run(graph_run_id: int, leaderboard_view: schemas.LeaderboardView = "aggregate", session: Session = Depends(get_session)):
    """Return one graph run report."""

    return graph_run_detail(session, require_graph_run(session, graph_run_id), leaderboard_view)


@router.post("/{graph_run_id}/stop", response_model=schemas.GraphRunSummary)
def stop_graph_run(graph_run_id: int, session: Session = Depends(get_session)):
    """Pause a graph run."""

    run = stop_graph_native_run(session, graph_run_id)
    return graph_run_summary(run)


@router.post("/{graph_run_id}/continue", response_model=schemas.GraphRunSummary)
def continue_graph_run(graph_run_id: int, session: Session = Depends(get_session)):
    """Resume a graph run."""

    run = continue_graph_native_run(session, graph_run_id)
    start_graph_run_thread(run.id, lambda: Session(engine))
    return graph_run_summary(run)


@router.post("/{graph_run_id}/retry-failures", response_model=schemas.GraphRunSummary)
def retry_graph_run_failures(graph_run_id: int, session: Session = Depends(get_session)):
    """Requeue failed graph invocations and resume the run."""

    run = retry_graph_native_failures(session, graph_run_id)
    start_graph_run_thread(run.id, lambda: Session(engine))
    return graph_run_summary(run)


@router.get("/{graph_run_id}/human-evals", response_model=list[schemas.GraphPairDto])
def get_human_evals(graph_run_id: int, session: Session = Depends(get_session)):
    """Return human pairwise review rows for a graph run."""

    require_graph_run(session, graph_run_id)
    return human_eval_pairs(session, graph_run_id)


@router.post("/{graph_run_id}/human-evals/{pair_id}", response_model=schemas.GraphPairDto)
def submit_human_eval(graph_run_id: int, pair_id: int, payload: schemas.HumanJudgementSubmit, session: Session = Depends(get_session)):
    """Submit one human A/B/TIE judgement."""

    submit_human_judgement(session, graph_run_id, pair_id, winner=payload.winner, reasoning=payload.reasoning, human_reviewer=payload.human_reviewer)
    return next(pair for pair in human_eval_pairs(session, graph_run_id) if pair.id == pair_id)


@router.get("/{graph_run_id}/events")
async def graph_run_events(graph_run_id: int):
    """Stream graph run progress as server-sent events."""

    async def event_stream():
        last_payload = ""
        while True:
            with Session(engine) as session:
                run = session.get(GraphRun, graph_run_id)
                if not run:
                    yield 'event: failed\ndata: {"type":"failed","message":"Graph run not found"}\n\n'
                    break
                progress = graph_native_progress(session, graph_run_id)
                event_type = "progress"
                payload = {"type": event_type, "progress": progress}
                if run.status in {Status.complete, Status.failed}:
                    event_type = run.status.value
                    payload = {"type": event_type, "run": graph_run_summary(run).model_dump(mode="json")}
                encoded = json.dumps(payload, sort_keys=True)
                if encoded != last_payload:
                    last_payload = encoded
                    yield f"event: {event_type}\ndata: {encoded}\n\n"
                if run.status in {Status.complete, Status.failed, Status.paused}:
                    break
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
