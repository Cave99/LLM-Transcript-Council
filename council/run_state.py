"""Shared run status, progress, and logging helpers."""

from __future__ import annotations

from sqlmodel import Session, select

from council.models import Generation, Judgement, Match, Run, RunLog, Status, Transcript


def add_run_log(session: Session, run_id: int, message: str, *, level: str = "info") -> None:
    """Record run events in one place so workers and routes share audit logs."""

    session.add(RunLog(run_id=run_id, level=level, message=message))
    print(f"[run {run_id}] {level.upper()}: {message}", flush=True)


def is_run_paused(session: Session, run_id: int) -> bool:
    """Check cancellation state before scheduling more background work."""

    run = session.get(Run, run_id)
    return bool(run and run.status == Status.paused)


def run_progress(session: Session, run_id: int) -> dict[str, int]:
    """Count run work items by status for UI progress and route guards."""

    def counts(model) -> dict[str, int]:
        rows = session.exec(select(model).where(model.run_id == run_id)).all()
        return {
            "total": len(rows),
            "pending": sum(1 for row in rows if row.status == Status.pending),
            "running": sum(1 for row in rows if row.status == Status.running),
            "complete": sum(1 for row in rows if row.status == Status.complete),
            "failed": sum(1 for row in rows if row.status == Status.failed),
        }

    generations = counts(Generation)
    matches = counts(Match)
    judgements = session.exec(
        select(Judgement).join(Match).where(Match.run_id == run_id)
    ).all()
    transcripts = session.exec(select(Transcript).where(Transcript.run_id == run_id)).all()
    return {
        "transcripts": len(transcripts),
        "generations": generations["total"],
        "generations_total": generations["total"],
        "generations_complete": generations["complete"],
        "generations_pending": generations["pending"],
        "generations_running": generations["running"],
        "generations_failed": generations["failed"],
        "matches": matches["total"],
        "matches_total": matches["total"],
        "matches_complete": matches["complete"],
        "matches_pending": matches["pending"],
        "matches_running": matches["running"],
        "matches_failed": matches["failed"],
        "judgements": len(judgements),
    }
