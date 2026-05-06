"""Run creation and high-level execution orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, delete, select

from council.files import list_markdown_files, read_text_snapshot
from council.generation import run_generations
from council.judging import run_matches
from council.leaderboard import apply_match_elo as _apply_match_elo
from council.leaderboard import recalculate_elo
from council.models import (
    EloRating,
    Generation,
    GeneratorConfig,
    JudgeConfig,
    Judgement,
    Match,
    MatchResult,
    Project,
    Run,
    RunAnalysis,
    RunLog,
    Status,
    Task,
    Transcript,
    utc_now,
)
from council.openrouter import OpenRouterClient
from council.run_rows import ensure_elo_rows, ensure_generation_rows, ensure_match_rows
from council.run_state import add_run_log, is_run_paused, run_progress


@dataclass(frozen=True)
class GeneratorSpec:
    """Lightweight generator configuration used while creating a run."""

    label: str
    model_id: str
    temperature: float
    prompt_path: str


@dataclass(frozen=True)
class JudgeSpec:
    """Lightweight judge configuration used while creating a run."""

    label: str
    model_id: str
    temperature: float
    prompt_path: str


def create_project(session: Session, name: str) -> Project:
    """Create a project with a trimmed display name."""

    project = Project(name=name.strip())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def rename_project(session: Session, project_id: int, name: str) -> Project | None:
    """Rename a project if it exists and the new name is non-empty."""

    project = session.get(Project, project_id)
    if not project:
        return None
    cleaned_name = name.strip()
    if not cleaned_name:
        return project
    project.name = cleaned_name
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def delete_run(session: Session, run_id: int) -> None:
    """Delete a run and every row that depends on it."""

    session.exec(delete(Judgement).where(Judgement.match_id.in_(select(Match.id).where(Match.run_id == run_id))))
    session.exec(delete(MatchResult).where(MatchResult.match_id.in_(select(Match.id).where(Match.run_id == run_id))))
    session.exec(delete(Match).where(Match.run_id == run_id))
    session.exec(delete(RunLog).where(RunLog.run_id == run_id))
    session.exec(delete(RunAnalysis).where(RunAnalysis.run_id == run_id))
    session.exec(delete(EloRating).where(EloRating.run_id == run_id))
    session.exec(delete(Generation).where(Generation.run_id == run_id))
    session.exec(delete(JudgeConfig).where(JudgeConfig.run_id == run_id))
    session.exec(delete(GeneratorConfig).where(GeneratorConfig.run_id == run_id))
    session.exec(delete(Transcript).where(Transcript.run_id == run_id))
    session.exec(delete(Run).where(Run.id == run_id))


def delete_task(session: Session, task_id: int) -> None:
    """Delete a task and all of its runs before removing the task row."""

    run_ids = list(session.exec(select(Run.id).where(Run.task_id == task_id)).all())
    for run_id in run_ids:
        delete_run(session, run_id)
    session.exec(delete(Task).where(Task.id == task_id))


def delete_project(session: Session, project_id: int) -> None:
    """Delete a project after recursively deleting its tasks."""

    task_ids = list(session.exec(select(Task.id).where(Task.project_id == project_id)).all())
    for task_id in task_ids:
        delete_task(session, task_id)
    session.exec(delete(Project).where(Project.id == project_id))


def create_task(
    session: Session,
    *,
    project_id: int,
    name: str,
    description_path: str,
    transcript_root: str,
    default_judge_prompt_path: str,
    default_pairing_sample_pct: float = 100.0,
    default_swap_enabled: bool = True,
) -> Task:
    """Create a task and snapshot its markdown inputs for later auditing."""

    description = read_text_snapshot(description_path)
    task = Task(
        project_id=project_id,
        name=name.strip(),
        description_path=description.path,
        description_snapshot=description.content,
        description_hash=description.content_hash,
        transcript_root=str(Path(transcript_root).expanduser().resolve()),
        default_judge_prompt_path=str(Path(default_judge_prompt_path).expanduser().resolve()),
        default_pairing_sample_pct=max(1.0, min(100.0, default_pairing_sample_pct)),
        default_swap_enabled=default_swap_enabled,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def create_run(
    session: Session,
    *,
    task_id: int,
    name: str,
    generator_specs: list[GeneratorSpec],
    judge_specs: list[JudgeSpec],
    transcript_paths: list[str] | None = None,
    sample_size: int | None = None,
    pairing_sample_pct: float = 100.0,
    max_concurrency: int = 5,
    swap_enabled: bool = True,
) -> Run:
    """Create a run, snapshot all inputs, and prebuild work rows."""

    task = session.get(Task, task_id)
    if not task:
        raise ValueError(f"Task {task_id} does not exist")
    if len(generator_specs) < 2:
        raise ValueError("At least two generator configs are required")
    if not judge_specs:
        raise ValueError("At least one judge config is required")

    run = Run(
        task_id=task_id,
        name=name.strip(),
        max_concurrency=max_concurrency,
        sample_size=sample_size,
        pairing_sample_pct=max(1.0, min(100.0, pairing_sample_pct)),
        swap_enabled=swap_enabled,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    for spec in generator_specs:
        prompt = read_text_snapshot(spec.prompt_path)
        session.add(
            GeneratorConfig(
                run_id=run.id,
                label=spec.label.strip(),
                model_id=spec.model_id.strip(),
                temperature=spec.temperature,
                prompt_path=prompt.path,
                prompt_snapshot=prompt.content,
                prompt_hash=prompt.content_hash,
            )
        )

    for spec in judge_specs:
        prompt = read_text_snapshot(spec.prompt_path)
        session.add(
            JudgeConfig(
                run_id=run.id,
                label=spec.label.strip(),
                model_id=spec.model_id.strip(),
                temperature=spec.temperature,
                prompt_path=prompt.path,
                prompt_snapshot=prompt.content,
                prompt_hash=prompt.content_hash,
            )
        )

    paths = [Path(p) for p in transcript_paths] if transcript_paths else list_markdown_files(task.transcript_root)
    if sample_size:
        paths = paths[:sample_size]
    if not paths:
        raise ValueError("No transcript markdown files selected")

    for path in paths:
        snapshot = read_text_snapshot(path)
        session.add(
            Transcript(
                run_id=run.id,
                path=snapshot.path,
                content_snapshot=snapshot.content,
                content_hash=snapshot.content_hash,
            )
        )

    session.commit()
    ensure_generation_rows(session, run.id)
    ensure_match_rows(session, run.id)
    ensure_elo_rows(session, run.id)
    return run


def reset_run(session: Session, run_id: int) -> Run:
    """Reset a run so it can be rerun from scratch with fresh outputs."""

    run = session.get(Run, run_id)
    if not run:
        raise ValueError(f"Run {run_id} does not exist")

    session.exec(delete(Judgement).where(Judgement.match_id.in_(select(Match.id).where(Match.run_id == run_id))))
    session.exec(delete(MatchResult).where(MatchResult.match_id.in_(select(Match.id).where(Match.run_id == run_id))))
    session.exec(delete(RunLog).where(RunLog.run_id == run_id))

    generations = session.exec(select(Generation).where(Generation.run_id == run_id)).all()
    for generation in generations:
        generation.status = Status.pending
        generation.output_raw = None
        generation.output_repaired = None
        generation.error = None
        generation.prompt_tokens = None
        generation.completion_tokens = None
        generation.cost = None
        generation.started_at = None
        generation.completed_at = None
        session.add(generation)

    matches = session.exec(select(Match).where(Match.run_id == run_id)).all()
    for match in matches:
        match.status = Status.pending
        session.add(match)

    ratings = session.exec(select(EloRating).where(EloRating.run_id == run_id)).all()
    for rating in ratings:
        rating.rating = run.elo_start
        rating.wins = 0
        rating.losses = 0
        rating.ties = 0
        session.add(rating)

    run.status = Status.pending
    run.error = None
    run.started_at = None
    run.completed_at = None
    session.add(run)
    add_run_log(session, run_id, "Run reset. Previous outputs, judgements, match results, and ELO state were cleared.")
    session.commit()
    session.refresh(run)
    return run


def recover_run(session: Session, run_id: int) -> Run:
    """Requeue only incomplete work that never captured an output."""

    run = session.get(Run, run_id)
    if not run:
        raise ValueError(f"Run {run_id} does not exist")

    reset_generations = 0
    generations = session.exec(select(Generation).where(Generation.run_id == run_id)).all()
    for generation in generations:
        if generation.status != Status.complete and not generation.output_raw and not generation.output_repaired:
            generation.status = Status.pending
            generation.error = None
            generation.started_at = None
            session.add(generation)
            reset_generations += 1

    reset_matches = 0
    matches = session.exec(select(Match).where(Match.run_id == run_id)).all()
    for match in matches:
        result = session.exec(select(MatchResult).where(MatchResult.match_id == match.id)).first()
        if not result and match.status != Status.complete:
            match.status = Status.pending
            session.add(match)
            reset_matches += 1

    run.status = Status.pending
    run.error = None
    run.completed_at = None
    session.add(run)
    add_run_log(session, run_id, f"Recover run requested. Requeued {reset_generations} generations and {reset_matches} matches without outputs.")
    session.commit()
    session.refresh(run)
    return run


def stop_run(session: Session, run_id: int) -> Run:
    """Mark a run as paused so background workers stop scheduling new work."""

    run = session.get(Run, run_id)
    if not run:
        raise ValueError(f"Run {run_id} does not exist")
    run.status = Status.paused
    session.add(run)
    add_run_log(session, run_id, "Stop requested. In-flight LLM calls may finish; no new work will be scheduled.")
    session.commit()
    session.refresh(run)
    return run


async def execute_run(run_id: int, session_factory, client: OpenRouterClient | None = None) -> None:
    """Execute the full generation, judging, and leaderboard pipeline."""

    client = client or OpenRouterClient()
    if not client.api_key:
        with session_factory() as session:
            run = session.get(Run, run_id)
            if run:
                run.status = Status.failed
                run.error = "OPENROUTER_API_KEY is not set"
                session.add(run)
                session.commit()
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    with session_factory() as session:
        run = session.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} does not exist")
        run.status = Status.running
        run.started_at = run.started_at or utc_now()
        session.add(run)
        add_run_log(session, run_id, f"Run started with max_concurrency={run.max_concurrency}.")
        session.commit()
        max_concurrency = run.max_concurrency

    semaphore = asyncio.Semaphore(max_concurrency)
    await run_generations(run_id, session_factory, client, semaphore)
    with session_factory() as session:
        if is_run_paused(session, run_id):
            add_run_log(session, run_id, "Run paused before judging. Completed generation outputs were kept.")
            session.commit()
            return
    await run_matches(run_id, session_factory, client, semaphore)

    with session_factory() as session:
        if is_run_paused(session, run_id):
            add_run_log(session, run_id, "Run paused before leaderboard recalculation.")
            session.commit()
            return
        recalculate_elo(session, run_id)
        run = session.get(Run, run_id)
        if run:
            run.status = Status.complete
            run.completed_at = utc_now()
            session.add(run)
            add_run_log(session, run_id, "Run complete. Leaderboard recalculated.")
            session.commit()
