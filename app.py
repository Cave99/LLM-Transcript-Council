"""Local FastHTML GUI for LLM-Transcript-Council."""

from __future__ import annotations

import asyncio
import json
import os
import random
import threading
from pathlib import Path

from dotenv import load_dotenv
from fasthtml.common import *
from sqlmodel import Session, select

from council.db import engine, init_db
from council.elo import consistent_swapped_vote
from council.files import list_markdown_files
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
)
from council.runner import (
    GeneratorSpec,
    JudgeSpec,
    create_project,
    create_run,
    delete_project,
    delete_task,
    rename_project,
    recover_run,
    reset_run,
    stop_run,
    create_task,
    execute_run,
    run_progress,
)
from council.openrouter import OpenRouterClient


JUDGE_PATTERN_ANALYSIS_PROMPT = """You analyze LLM-as-judge reasoning traces from a completed evaluation run.

Write one brief paragraph describing the strongest patterns in judge preferences. Focus on trends such as whether judges favor longer or shorter responses, stricter JSON/schema adherence, more transcript evidence, more specific recommendations, tone, risk awareness, or other repeated choice drivers.

Use only the provided traces. Be concrete but concise. Do not list every trace. Do not mention internal sampling mechanics."""

load_dotenv()
init_db()

app, rt = fast_app(
    hdrs=(
        Link(rel="stylesheet", href="/static/app.css"),
        Script(src="/static/app.js"),
    )
)

RUN_THREADS: dict[int, threading.Thread] = {}


def session() -> Session:
    """Return a short-lived database session for request handlers."""

    return Session(engine)


def shell(title: str, *content):
    """Wrap a page body in the shared app chrome."""

    return Html(
        Head(
            Title(f"{title} - LLM-Transcript-Council"),
            Link(rel="stylesheet", href="/static/app.css"),
            Script(src="/static/app.js"),
        ),
        Body(
            Div(
                A("LLM-Transcript-Council", href="/", cls="brand"),
                Nav(
                    A("Projects", href="/"),
                    A("New Task", href="/tasks/new"),
                    A("New Run", href="/runs/new"),
                    A("Runs", href="/runs"),
                ),
                cls="topbar",
            ),
            Main(*content, cls="layout"),
        ),
    )


def help_label(label: str, help_text: str | None = None):
    """Render a form label with an optional inline help tooltip."""

    return Span(
        Span(label),
        Span("?", title=help_text, cls="help-dot") if help_text else "",
        cls="label-text",
    )


def input_row(label: str, name: str, value: str = "", *, placeholder: str = "", type: str = "text", help_text: str | None = None, **attrs):
    """Render a standard labeled input row used throughout the app."""

    return Label(help_label(label, help_text), Input(name=name, value=value, placeholder=placeholder, type=type, **attrs), cls="field")


def textarea_row(label: str, name: str, value: str = "", *, rows: int = 4):
    """Render a labeled textarea row."""

    return Label(Span(label), Textarea(value, name=name, rows=rows), cls="field")


def selected_option(value, label, selected=False):
    """Render a select option with stringified values."""

    return Option(label, value=str(value), selected=selected)


def path_label(path: str | Path) -> str:
    """Show paths relative to the current repo when possible."""

    resolved = Path(path)
    cwd = Path.cwd().resolve()
    try:
        return str(resolved.resolve().relative_to(cwd))
    except ValueError:
        return resolved.name


def preview_text(text: str, limit: int = 220) -> str:
    """Collapse long text into a short preview for summary cards."""

    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    cutoff = compact.rfind(" ", 0, limit)
    if cutoff <= 0:
        cutoff = limit
    return f"{compact[:cutoff].rstrip()}..."


def prompt_picker(label: str, name: str, files: list[Path], selected: str | Path | None = None, help_text: str | None = None):
    """Render a file input paired with a dropdown of prompt files."""

    selected_path = str(Path(selected).resolve()) if selected else None
    fallback = selected_path or (str(files[0].resolve()) if files else "")
    return Label(
        help_label(label, help_text),
        Div(
            Input(name=name, value=fallback, placeholder="/path/to/prompt.md"),
            Select(
                Option("Choose...", value=""),
                *[selected_option(path.resolve(), path_label(path)) for path in files],
                aria_label=f"Choose {label.lower()} file",
                onchange=f"const input=this.previousElementSibling; if (this.value && input) input.value=this.value; this.value='';",
            ),
            cls="path-combo",
        ),
        cls="field",
    )


def model_input(name: str, value: str):
    """Render a model ID text field with a helpful placeholder."""

    return Input(name=name, value=value, placeholder="openai/gpt-4o-mini")


def config_card(kind: str, index: int, *, prompt_files: list[Path], defaults: dict[str, str], required: bool = False):
    """Render one generator or judge configuration card."""

    prefix = f"{kind}_{index}"
    title = f"{kind.title()} {index}"
    return Div(
        H3(title),
        Label(Span("Label"), Input(name=f"{prefix}_label", value=defaults.get("label", ""), placeholder="baseline" if kind == "generator" else "judge-1"), cls="field"),
        Label(Span("Model"), model_input(f"{prefix}_model_id", defaults.get("model_id", "")), cls="field"),
        Label(Span("Temperature"), Input(name=f"{prefix}_temperature", value=defaults.get("temperature", "0.0"), type="number", step="0.1", min="0", max="2"), cls="field"),
        prompt_picker("Prompt", f"{prefix}_prompt_path", prompt_files, defaults.get("prompt_path") or (prompt_files[0] if prompt_files else None)),
        Input(type="hidden", name=f"{prefix}_required", value="true" if required else "false"),
        cls="config-card",
    )


def status_pill(status: str):
    """Render a small status badge for runs and work items."""

    return Span(status, cls=f"pill pill-{status}")


def empty_state(title: str, body: str, href: str | None = None, action: str | None = None):
    """Render a plain empty-state panel with an optional call to action."""

    children = [H3(title), P(body, cls="muted")]
    if href and action:
        children.append(A(action, href=href, cls="button subtle"))
    return Div(*children, cls="empty-state")


def delete_form(action: str, confirm_message: str):
    """Render a destructive form that asks for confirmation in the UI."""

    return Form(
        Button("Delete", type="submit", cls="button subtle danger"),
        action=action,
        method="post",
        cls="delete-form",
        data_confirm_message=confirm_message,
    )


def list_card(title: str, href: str, meta: str, delete_action: str, confirm_message: str):
    """Render a clickable summary card with a paired delete action."""

    return Div(
        A(H3(title), P(meta), href=href, cls="card-link"),
        delete_form(delete_action, confirm_message),
        cls="list-card list-card-with-actions",
    )


@rt("/")
def get():
    """Render the project index page."""

    with session() as db:
        projects = db.exec(select(Project).order_by(Project.created_at.desc())).all()
        runs = db.exec(select(Run).order_by(Run.created_at.desc()).limit(5)).all()
    return shell(
        "Projects",
        Section(
            Div(
                H1("LLM-Transcript-Council"),
                P("Compare subjective LLM outputs with blind pairwise judges and ELO rankings."),
                cls="hero-copy",
            ),
            Form(
                input_row("Project name", "name", placeholder="Call coaching evals", help_text="A project groups related tasks, runs, and results. Use one for a product area, customer workflow, or experiment family."),
                Button("Create project", type="submit"),
                action="/projects",
                method="post",
                cls="panel compact-form",
            ),
            cls="hero-band",
        ),
        Section(
            H2("Projects"),
            Div(
                *[
                    list_card(
                        project.name,
                        f"/projects/{project.id}",
                        f"Created {project.created_at:%Y-%m-%d %H:%M}",
                        f"/projects/{project.id}/delete",
                        f"Delete project '{project.name}'? This will also delete its tasks and runs.",
                    )
                    for project in projects
                ]
                or [empty_state("No projects yet", "Create a project to group related tasks and runs.")],
                cls="grid",
            ),
            cls="section",
        ),
        Section(
            H2("Recent Runs"),
            run_table(runs),
            cls="section",
        ),
    )


@rt("/projects")
def get():
    """Redirect the legacy projects index to the home page."""

    return RedirectResponse("/", status_code=303)


@rt("/projects")
def post(name: str):
    """Create a project from the home-page form."""

    if not name.strip():
        return RedirectResponse("/", status_code=303)
    with session() as db:
        project = create_project(db, name)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@rt("/projects/{project_id}/delete")
def post(project_id: int):
    """Delete a project and redirect back to the home page."""

    with session() as db:
        project = db.get(Project, project_id)
        if not project:
            return RedirectResponse("/", status_code=303)
        delete_project(db, project_id)
        db.commit()
    return RedirectResponse("/", status_code=303)


@rt("/projects/{project_id}/rename")
def post(project_id: int, name: str):
    """Rename a project from the inline edit form."""

    with session() as db:
        project = rename_project(db, project_id, name)
        if not project:
            return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@rt("/projects/{project_id}")
def get(project_id: int):
    """Render one project and its task list."""

    with session() as db:
        project = db.get(Project, project_id)
        tasks = db.exec(select(Task).where(Task.project_id == project_id)).all()
    return shell(
        project.name,
        Div(
            Div(
                Div(
                    H1(project.name),
                    Button("✎", type="button", cls="icon-button", aria_label="Rename project", data_rename_toggle="true"),
                    cls="title-row",
                ),
                Form(
                    input_row("Rename project", "name", value=project.name, help_text="Update the project name shown across the app.", data_rename_input="true"),
                    Button("Save", type="submit"),
                    Button("Cancel", type="button", cls="button subtle", data_rename_cancel="true"),
                    action=f"/projects/{project_id}/rename",
                    method="post",
                    cls="compact-form project-rename-form",
                    data_project_rename_form="true",
                    hidden=True,
                ),
                cls="hero-copy",
            ),
            A("Create task", href=f"/tasks/new?project_id={project_id}", cls="button"),
            cls="page-head",
        ),
        Section(
            H2("Tasks"),
            Div(
                *[
                    list_card(
                        task.name,
                        f"/tasks/{task.id}",
                        Path(task.description_path).name,
                        f"/tasks/{task.id}/delete",
                        f"Delete task '{task.name}'? This will also delete its runs and results.",
                    )
                    for task in tasks
                ]
                or [empty_state("No tasks yet", "Create a task before configuring evaluation runs.", f"/tasks/new?project_id={project_id}", "Create task")],
                cls="grid",
            ),
            cls="section",
        ),
    )


@rt("/tasks/new")
def get(project_id: int | None = None):
    """Render the task creation page."""

    with session() as db:
        projects = db.exec(select(Project)).all()
    if not projects:
        return shell(
            "New Task",
            Div(H1("New Task"), P("Create a project first, then attach task descriptions, judge prompts, and transcripts.", cls="muted"), cls="page-head"),
            empty_state("No projects available", "Tasks live inside projects so previous runs stay grouped over time.", "/", "Create project"),
        )
    task_files = list_markdown_files("prompts/tasks")
    judge_files = list_markdown_files("prompts/judges")
    transcript_root = Path("transcripts").resolve()
    return shell(
        "New Task",
        H1("New Task"),
        Form(
            Label(
                help_label("Project", "The project keeps this task grouped with related evaluation work."),
                Select(
                    *[selected_option(p.id, p.name, p.id == project_id) for p in projects],
                    name="project_id",
                ),
                cls="field",
            ),
            input_row("Task name", "name", placeholder="Cross-sell coaching feedback", help_text="A task defines the evaluation question that every run under it will test."),
            prompt_picker("Task description", "description_path", task_files, Path("prompts/tasks/example_task.md").resolve(), help_text="Markdown instructions describing what good output should do. This content is snapshotted into the task."),
            Label(
                help_label("Transcript folder", "Folder of markdown transcripts. Runs generate outputs for these transcripts, or for the sample size you choose."),
                Input(name="transcript_root", value=str(transcript_root), placeholder="/path/to/transcripts"),
                cls="field",
            ),
            prompt_picker("Default judge prompt", "default_judge_prompt_path", judge_files, Path("prompts/judges/default_pairwise.md").resolve(), help_text="Default pairwise comparison prompt used when creating runs for this task."),
            input_row("Default pairing sample %", "default_pairing_sample_pct", value="100", type="number", min="1", max="100", step="1", help_text="Percent of generator pairings to judge for each run. Use 20-30 for faster random sampling instead of full pairwise."),
            Label(Input(type="checkbox", name="default_swap_enabled", value="true", checked=True), Span("Swap A/B positions to check judge position bias by default"), cls="check"),
            Button("Create task", type="submit"),
            action="/tasks",
            method="post",
            cls="panel form-stack",
        ),
    )


@rt("/tasks")
def post(
    project_id: int,
    name: str,
    description_path: str,
    transcript_root: str,
    default_judge_prompt_path: str,
    default_pairing_sample_pct: str = "100",
    default_swap_enabled: str | None = None,
):
    """Create a task from the task form."""

    if not name.strip():
        return RedirectResponse(f"/tasks/new?project_id={project_id}", status_code=303)
    with session() as db:
        task = create_task(
            db,
            project_id=project_id,
            name=name,
            description_path=description_path,
            transcript_root=transcript_root,
            default_judge_prompt_path=default_judge_prompt_path,
            default_pairing_sample_pct=float(default_pairing_sample_pct or 100),
            default_swap_enabled=default_swap_enabled == "true",
        )
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@rt("/tasks/{task_id}/delete")
def post(task_id: int):
    """Delete a task and return to its parent project."""

    with session() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/", status_code=303)
        project_id = task.project_id
        delete_task(db, task_id)
        db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@rt("/tasks/{task_id}")
def get(task_id: int):
    """Render a task detail page with its runs and transcript summary."""

    with session() as db:
        task = db.get(Task, task_id)
        runs = db.exec(select(Run).where(Run.task_id == task_id).order_by(Run.created_at.desc())).all()
    files = list_markdown_files(task.transcript_root)
    return shell(
        task.name,
        Div(
            Div(H1(task.name), P(preview_text(task.description_snapshot), cls="muted"), cls="hero-copy"),
            A("New run", href=f"/runs/new?task_id={task.id}", cls="button"),
            cls="page-head",
        ),
        Section(
            H2("Transcript Set"),
            P(f"{len(files)} markdown transcript files in {task.transcript_root}", cls="muted"),
            P(f"Default pairing sample: {task.default_pairing_sample_pct:.0f}% of generator pairings", cls="muted"),
            P(f"A/B swap validation: {'enabled' if task.default_swap_enabled else 'disabled'} by default", cls="muted"),
            cls="section panel",
        ),
        Section(H2("Runs"), run_table(runs), cls="section"),
    )


@rt("/runs/new")
def get(task_id: int | None = None):
    """Render the run creation page."""

    with session() as db:
        tasks = db.exec(select(Task)).all()
    if not tasks:
        return shell(
            "New Run",
            Div(H1("New Run"), P("Create a task first, then compare generator configurations against its transcripts.", cls="muted"), cls="page-head"),
            empty_state("No tasks available", "Runs need a task description, transcript folder, and default judge prompt before they can start.", "/tasks/new", "Create task"),
        )
    task = next((t for t in tasks if t.id == task_id), tasks[0] if tasks else None)
    default_judge = task.default_judge_prompt_path if task else str(Path("prompts/judges/default_pairwise.md").resolve())
    default_pairing_sample_pct = task.default_pairing_sample_pct if task else 100
    default_swap_enabled = task.default_swap_enabled if task else True
    generator_prompt_files = list_markdown_files("prompts/generators")
    judge_prompt_files = list_markdown_files("prompts/judges")
    default_generator_prompt = str(Path("prompts/generators/example_prompt.md").resolve())
    return shell(
        "New Run",
        H1("New Run"),
        Form(
            Label(
                help_label("Task", "The task supplies transcript set, task description, and default judge prompt for this run."),
                Select(*[selected_option(t.id, t.name, t.id == task_id) for t in tasks], name="task_id"),
                cls="field",
            ),
            input_row("Run name", "name", placeholder="gpt prompt v2 comparison", help_text="A run is one experiment with fixed generator configs, judge configs, sampling settings, and snapshots."),
            input_row("Transcript sample size", "sample_size", placeholder="leave blank for all", type="number", min="1", help_text="Limits how many transcript files are included. Leave blank to evaluate every transcript."),
            input_row("Pairing sample %", "pairing_sample_pct", value=f"{default_pairing_sample_pct:.0f}", type="number", min="1", max="100", step="1", help_text="Percent of generator pairings to judge per transcript. 100% is full pairwise evaluation; use 20-30 for faster random sampling."),
            input_row("Max concurrent LLM calls", "max_concurrency", value=os.getenv("MAX_CONCURRENT_LLM_CALLS", "5"), type="number", min="1", help_text="Caps simultaneous OpenRouter calls across generation and judging."),
            H2("Generator configs"),
            Div(
                config_card("generator", 1, prompt_files=generator_prompt_files, defaults={"label": "baseline", "model_id": "openai/gpt-4o-mini", "temperature": "0.2", "prompt_path": default_generator_prompt}, required=True),
                config_card("generator", 2, prompt_files=generator_prompt_files, defaults={"label": "variant", "model_id": "anthropic/claude-3.5-haiku", "temperature": "0.2", "prompt_path": default_generator_prompt}, required=True),
                config_card("generator", 3, prompt_files=generator_prompt_files, defaults={"temperature": "0.2", "prompt_path": default_generator_prompt}),
                config_card("generator", 4, prompt_files=generator_prompt_files, defaults={"temperature": "0.2", "prompt_path": default_generator_prompt}),
                config_card("generator", 5, prompt_files=generator_prompt_files, defaults={"temperature": "0.2", "prompt_path": default_generator_prompt}),
                cls="config-grid",
            ),
            H2("Judge configs"),
            Div(
                config_card("judge", 1, prompt_files=judge_prompt_files, defaults={"label": "judge-1", "model_id": "openai/gpt-4o-mini", "temperature": "0.0", "prompt_path": default_judge}, required=True),
                config_card("judge", 2, prompt_files=judge_prompt_files, defaults={"label": "judge-2", "model_id": "anthropic/claude-3.5-haiku", "temperature": "0.0", "prompt_path": default_judge}),
                config_card("judge", 3, prompt_files=judge_prompt_files, defaults={"label": "judge-3", "model_id": "google/gemini-flash-1.5", "temperature": "0.0", "prompt_path": default_judge}),
                config_card("judge", 4, prompt_files=judge_prompt_files, defaults={"temperature": "0.0", "prompt_path": default_judge}),
                config_card("judge", 5, prompt_files=judge_prompt_files, defaults={"temperature": "0.0", "prompt_path": default_judge}),
                cls="config-grid",
            ),
            Label(Input(type="checkbox", name="swap_enabled", value="true", checked=default_swap_enabled), Span("Validate each judge vote with swapped A/B positions"), cls="check"),
            Button("Create and start run", type="submit"),
            action="/runs",
            method="post",
            cls="panel form-stack",
        ),
    )


@rt("/runs")
def post(
    task_id: int,
    name: str,
    sample_size: str = "",
    pairing_sample_pct: str = "100",
    max_concurrency: int = 5,
    swap_enabled: str | None = None,
    generator_1_label: str = "",
    generator_1_model_id: str = "",
    generator_1_temperature: str = "0.2",
    generator_1_prompt_path: str = "",
    generator_2_label: str = "",
    generator_2_model_id: str = "",
    generator_2_temperature: str = "0.2",
    generator_2_prompt_path: str = "",
    generator_3_label: str = "",
    generator_3_model_id: str = "",
    generator_3_temperature: str = "0.2",
    generator_3_prompt_path: str = "",
    generator_4_label: str = "",
    generator_4_model_id: str = "",
    generator_4_temperature: str = "0.2",
    generator_4_prompt_path: str = "",
    generator_5_label: str = "",
    generator_5_model_id: str = "",
    generator_5_temperature: str = "0.2",
    generator_5_prompt_path: str = "",
    judge_1_label: str = "",
    judge_1_model_id: str = "",
    judge_1_temperature: str = "0.0",
    judge_1_prompt_path: str = "",
    judge_2_label: str = "",
    judge_2_model_id: str = "",
    judge_2_temperature: str = "0.0",
    judge_2_prompt_path: str = "",
    judge_3_label: str = "",
    judge_3_model_id: str = "",
    judge_3_temperature: str = "0.0",
    judge_3_prompt_path: str = "",
    judge_4_label: str = "",
    judge_4_model_id: str = "",
    judge_4_temperature: str = "0.0",
    judge_4_prompt_path: str = "",
    judge_5_label: str = "",
    judge_5_model_id: str = "",
    judge_5_temperature: str = "0.0",
    judge_5_prompt_path: str = "",
):
    """Create a run and immediately start execution in the background."""

    generators = build_generator_specs(
        [
            (generator_1_label, generator_1_model_id, generator_1_temperature, generator_1_prompt_path),
            (generator_2_label, generator_2_model_id, generator_2_temperature, generator_2_prompt_path),
            (generator_3_label, generator_3_model_id, generator_3_temperature, generator_3_prompt_path),
            (generator_4_label, generator_4_model_id, generator_4_temperature, generator_4_prompt_path),
            (generator_5_label, generator_5_model_id, generator_5_temperature, generator_5_prompt_path),
        ]
    )
    judges = build_judge_specs(
        [
            (judge_1_label, judge_1_model_id, judge_1_temperature, judge_1_prompt_path),
            (judge_2_label, judge_2_model_id, judge_2_temperature, judge_2_prompt_path),
            (judge_3_label, judge_3_model_id, judge_3_temperature, judge_3_prompt_path),
            (judge_4_label, judge_4_model_id, judge_4_temperature, judge_4_prompt_path),
            (judge_5_label, judge_5_model_id, judge_5_temperature, judge_5_prompt_path),
        ]
    )
    with session() as db:
        run = create_run(
            db,
            task_id=task_id,
            name=name,
            generator_specs=generators,
            judge_specs=judges,
            sample_size=int(sample_size) if sample_size else None,
            pairing_sample_pct=float(pairing_sample_pct or 100),
            max_concurrency=max_concurrency,
            swap_enabled=swap_enabled == "true",
        )
        run_id = run.id
    start_run_thread(run_id)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@rt("/runs")
def get():
    """Render the global runs index."""

    with session() as db:
        runs = db.exec(select(Run).order_by(Run.created_at.desc())).all()
    return shell("Runs", Div(H1("Runs"), A("New run", href="/runs/new", cls="button"), cls="page-head"), run_table(runs))


@rt("/runs/{run_id}")
def get(run_id: int):
    """Render one run with progress, leaderboard, logs, and matches."""

    with session() as db:
        run = db.get(Run, run_id)
        task = db.get(Task, run.task_id)
        progress = run_progress(db, run_id)
        leaderboard = db.exec(
            select(EloRating, GeneratorConfig)
            .where(EloRating.run_id == run_id)
            .where(EloRating.generator_config_id == GeneratorConfig.id)
            .order_by(EloRating.rating.desc())
        ).all()
        matches = db.exec(select(Match).where(Match.run_id == run_id).limit(20)).all()
        logs = db.exec(select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.created_at.desc()).limit(40)).all()
        generator_configs = db.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
        judge_configs = db.exec(select(JudgeConfig).where(JudgeConfig.run_id == run_id)).all()
        judge_favorites = judge_favorite_map(db, run_id, judge_configs)
        analyses = db.exec(select(RunAnalysis).where(RunAnalysis.run_id == run_id).order_by(RunAnalysis.created_at.desc())).all()
        throughput = generation_throughput(db, run_id)
        judge_throughput = judgement_throughput(db, run_id)
        analysis_allowed, analysis_help = judge_pattern_analysis_availability(run, progress["judgements"])
    return shell(
        run.name,
        Div(
            Div(H1(run.name), P(task.name, cls="muted"), cls="hero-copy"),
            Div(
                status_pill(run.status.value),
                run_action_button(run, "Recover Run", f"/runs/{run.id}/recover") if run.status != Status.running else "",
                run_action_button(run, "Run / Re-run", f"/runs/{run.id}/rerun") if run.status != Status.running else "",
                run_action_button(run, "Stop Run", f"/runs/{run.id}/stop", subtle=True) if run.status == Status.running else "",
                A("Refresh", href=f"/runs/{run.id}", cls="button subtle"),
                cls="actions",
            ),
            cls="page-head",
        ),
        Section(
            H2("Progress"),
            P(run.error, cls="error") if run.error else "",
            P(f"Pairing sample: {run.pairing_sample_pct:.0f}% of generator pairings per transcript", cls="muted"),
            progress_meter("Generations", progress["generations_complete"], progress["generations"]),
            progress_breakdown(
                pending=progress["generations_pending"],
                running=progress["generations_running"],
                failed=progress["generations_failed"],
            ),
            progress_meter("Matches", progress["matches_complete"], progress["matches"]),
            progress_breakdown(
                pending=progress["matches_pending"],
                running=progress["matches_running"],
                failed=progress["matches_failed"],
            ),
            P(f'{progress["judgements"]} judge calls recorded', cls="muted"),
            cls="section panel",
        ),
        Details(
            Summary("Run Console"),
            run_console(logs),
            data_details_key="run-console",
            cls="section panel",
        ),
        Section(
            H2("Generation Throughput"),
            throughput_table(throughput),
            P("TPS uses completed generation calls with recorded token counts and start/end times.", cls="muted"),
            cls="section panel",
        ),
        Section(
            H2("Judge Throughput"),
            throughput_table(judge_throughput),
            P("Judge TPS uses completed judge calls with recorded token counts and start/end times.", cls="muted"),
            cls="section panel",
        ),
        Section(
            H2("Leaderboard"),
            analysis_action_button(run, f"/runs/{run.id}/judge-pattern-analysis")
            if analysis_allowed
            else P(analysis_help, cls="muted"),
            Table(
                Thead(Tr(Th("Config"), Th("Model"), Th("Judge Favs"), Th("Temp"), Th("ELO"), Th("W"), Th("L"), Th("T"))),
                Tbody(
                    *[
                        Tr(
                            Td(config.label),
                            Td(config.model_id),
                            Td(judge_favorite_badges(config.id, judge_favorites)),
                            Td(str(config.temperature)),
                            Td(f"{rating.rating:.1f}"),
                            Td(str(rating.wins)),
                            Td(str(rating.losses)),
                            Td(str(rating.ties)),
                        )
                        for rating, config in leaderboard
                    ]
                ),
            ),
            P(f"Judged by {', '.join(judge.model_id for judge in judge_configs)}", cls="judged-by"),
            analysis_history(analyses),
            cls="section panel",
        ),
        Section(
            H2("Prompt Snapshots"),
            Div(
                prompt_snapshot_group("Generator Prompts", generator_configs),
                prompt_snapshot_group("Judge Prompts", judge_configs),
                cls="prompt-inspector",
            ),
            cls="section panel",
        ),
        Section(
            H2("Recent Matches"),
            Table(
                Thead(Tr(Th("Transcript"), Th("Matchup"), Th("Winner"), Th("Agreement"), Th("Votes"), Th("Status"), Th(""))),
                Tbody(
                    *[match_row(match.id) for match in matches]
                    or [Tr(Td("No matches yet.", colspan="7", cls="muted"))]
                ),
                cls="match-table",
            ),
            cls="section panel",
        ),
    )


@rt("/runs/{run_id}/rerun")
def post(run_id: int):
    """Reset and rerun a completed or failed run."""

    if run_id in RUN_THREADS and RUN_THREADS[run_id].is_alive():
        return RedirectResponse(f"/runs/{run_id}", status_code=303)
    with session() as db:
        reset_run(db, run_id)
    start_run_thread(run_id)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@rt("/runs/{run_id}/recover")
def post(run_id: int):
    """Recover a paused or failed run without deleting completed outputs."""

    if run_id in RUN_THREADS and RUN_THREADS[run_id].is_alive():
        return RedirectResponse(f"/runs/{run_id}", status_code=303)
    with session() as db:
        recover_run(db, run_id)
    start_run_thread(run_id)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@rt("/runs/{run_id}/stop")
def post(run_id: int):
    """Pause a running run."""

    with session() as db:
        stop_run(db, run_id)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@rt("/runs/{run_id}/judge-pattern-analysis")
def post(run_id: int):
    """Generate a judge-pattern analysis summary for a run."""

    with session() as db:
        run = db.get(Run, run_id)
        if not run:
            return RedirectResponse(f"/runs/{run_id}", status_code=303)
        progress = run_progress(db, run_id)
        analysis_allowed, _analysis_help = judge_pattern_analysis_availability(run, progress["judgements"])
        if not analysis_allowed:
            return RedirectResponse(f"/runs/{run_id}", status_code=303)
        traces = sample_judge_reasoning_traces(db, run_id)
        if not traces:
            run.error = "No judge reasoning traces are available for pattern analysis."
            db.add(run)
            db.commit()
            return RedirectResponse(f"/runs/{run_id}", status_code=303)
        model_id = os.getenv("JUDGE_PATTERN_ANALYZER_MODEL", "deepseek/deepseek-v4-flash")

    prompt = render_judge_pattern_prompt(traces)
    try:
        response = asyncio.run(
            OpenRouterClient().chat(
                model=model_id,
                temperature=0.2,
                reasoning_effort="low",
                messages=[
                    {"role": "system", "content": JUDGE_PATTERN_ANALYSIS_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        )
        summary = response.text.strip()
        with session() as db:
            run = db.get(Run, run_id)
            if run:
                run.error = None
                db.add(run)
            db.add(
                RunAnalysis(
                    run_id=run_id,
                    model_id=model_id,
                    sample_size=len(traces),
                    summary=summary,
                    prompt_snapshot=JUDGE_PATTERN_ANALYSIS_PROMPT,
                )
            )
            db.commit()
    except Exception as exc:
        with session() as db:
            run = db.get(Run, run_id)
            if run:
                run.error = f"Judge pattern analysis failed: {exc}"
                db.add(run)
                db.commit()
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@rt("/matches/{match_id}")
def get(match_id: int):
    """Render a single match detail page."""

    with session() as db:
        match = db.get(Match, match_id)
        transcript = db.get(Transcript, match.transcript_id)
        gen_a = db.get(Generation, match.generation_a_id)
        gen_b = db.get(Generation, match.generation_b_id)
        cfg_a = db.get(GeneratorConfig, match.config_a_id)
        cfg_b = db.get(GeneratorConfig, match.config_b_id)
        result = db.exec(select(MatchResult).where(MatchResult.match_id == match_id)).first()
        judgements = db.exec(select(Judgement).where(Judgement.match_id == match_id)).all()
    return shell(
        f"Match {match_id}",
        H1(f"Match {match_id}"),
        Section(
            H2("Result"),
            P(result.final_winner if result else "Pending", cls="big-result"),
            P(f"Agreement: {result.agreement:.0%}" if result else "", cls="muted"),
            cls="section panel",
        ),
        Section(H2("Transcript"), Pre(transcript.content_snapshot), cls="section panel"),
        Div(
            Section(H2(f"Output A: {cfg_a.label}"), Pre(gen_a.output_repaired or gen_a.output_raw or ""), cls="panel"),
            Section(H2(f"Output B: {cfg_b.label}"), Pre(gen_b.output_repaired or gen_b.output_raw or ""), cls="panel"),
            cls="two-col",
        ),
        Section(
            H2("Judge Reasoning"),
            Div(
                *[
                    Div(
                        H3(f"{j.direction}: {j.winner}"),
                        P(j.reasoning),
                        cls="list-card",
                    )
                    for j in judgements
                ],
                cls="stack",
            ),
            cls="section",
        ),
    )


def run_table(runs):
    """Render a compact table of runs."""

    return Table(
        Thead(Tr(Th("Run"), Th("Status"), Th("Created"), Th(""))),
        Tbody(
            *[
                Tr(
                    Td(run.name),
                    Td(status_pill(run.status.value)),
                    Td(f"{run.created_at:%Y-%m-%d %H:%M}"),
                    Td(A("Open", href=f"/runs/{run.id}")),
                )
                for run in runs
            ]
            or [Tr(Td("No runs yet.", colspan="4", cls="muted"))]
        ),
        cls="run-table",
    )


def progress_meter(label: str, complete: int, total: int):
    """Render a simple completion bar with a count label."""

    pct = int((complete / total) * 100) if total else 0
    return Div(
        Div(Span(label), Span(f"{complete}/{total}"), cls="meter-label"),
        Div(Div(style=f"width:{pct}%"), cls="meter"),
        cls="meter-wrap",
    )


def progress_breakdown(*, pending: int, running: int, failed: int):
    """Render a compact breakdown of pending, running, and failed work."""

    return Div(
        Span(f"{running} running "),
        Span(f"{pending} pending "),
        Span(f"{failed} failed"),
        cls="progress-breakdown",
    )


def run_action_button(run: Run, label: str, action: str, *, subtle: bool = False):
    """Render a one-click action form for run controls."""

    return Form(
        Button(label, type="submit", cls="button subtle" if subtle else None),
        action=action,
        method="post",
        cls="inline-form",
    )


def analysis_action_button(run: Run, action: str):
    """Render the judge-pattern analysis form."""

    return Form(
        Button("Judge Pattern Analysis", type="submit"),
        Span("", cls="analysis-progress", aria_live="polite"),
        action=action,
        method="post",
        cls="inline-form analysis-form",
        data_analysis_form="true",
    )


def judge_pattern_analysis_availability(run: Run, judge_votes: int) -> tuple[bool, str]:
    """Decide whether judge-pattern analysis should be offered."""

    if run.status == Status.complete:
        return True, ""
    if run.status == Status.paused and judge_votes >= 10:
        return True, ""
    if run.status == Status.paused:
        return False, f"Judge pattern analysis needs at least 10 judge votes for a stopped run. Current votes: {judge_votes}."
    return False, "Judge pattern analysis is available after completion, or after stopping once at least 10 judge votes exist."


def run_console(logs):
    """Render the run event log."""

    return Div(
        *[
            Div(
                Span(f"{log.created_at:%H:%M:%S} ", cls="log-time"),
                Span(log.message),
                cls=f"run-log run-log-{log.level}",
            )
            for log in logs
        ]
        or [P("No run events yet.", cls="muted")],
        cls="run-console",
    )


def generation_throughput(db: Session, run_id: int) -> list[dict[str, str]]:
    """Aggregate generation timing and token throughput by config."""

    rows = db.exec(
        select(Generation, GeneratorConfig)
        .where(Generation.run_id == run_id)
        .where(Generation.generator_config_id == GeneratorConfig.id)
        .where(Generation.status == Status.complete)
    ).all()
    by_config: dict[int, dict] = {}
    for generation, config in rows:
        if not generation.started_at or not generation.completed_at:
            continue
        seconds = max((generation.completed_at - generation.started_at).total_seconds(), 0.001)
        output_tokens = generation.completion_tokens or 0
        total_tokens = (generation.prompt_tokens or 0) + output_tokens
        bucket = by_config.setdefault(
            config.id,
            {
                "label": config.label,
                "model": config.model_id,
                "calls": 0,
                "seconds": 0.0,
                "output_tokens": 0,
                "total_tokens": 0,
                "recent_completed_at": None,
                "recent_tps": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["seconds"] += seconds
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        if not bucket["recent_completed_at"] or generation.completed_at > bucket["recent_completed_at"]:
            bucket["recent_completed_at"] = generation.completed_at
            bucket["recent_tps"] = output_tokens / seconds if output_tokens else 0.0

    metrics = []
    for bucket in by_config.values():
        avg_tps = bucket["output_tokens"] / bucket["seconds"] if bucket["seconds"] else 0.0
        avg_latency = bucket["seconds"] / bucket["calls"] if bucket["calls"] else 0.0
        metrics.append(
            {
                "label": bucket["label"],
                "model": bucket["model"],
                "calls": str(bucket["calls"]),
                "avg_tps": f"{avg_tps:.1f}",
                "recent_tps": f"{bucket['recent_tps']:.1f}",
                "avg_latency": f"{avg_latency:.1f}s",
                "output_tokens": f"{bucket['output_tokens']:,}",
                "total_tokens": f"{bucket['total_tokens']:,}",
            }
        )
    return sorted(metrics, key=lambda row: float(row["avg_tps"]), reverse=True)


def throughput_table(rows: list[dict[str, str]]):
    """Render throughput metrics in a table."""

    return Table(
        Thead(Tr(Th("Config"), Th("Model"), Th("Calls"), Th("Avg TPS"), Th("Latest TPS"), Th("Avg Latency"), Th("Output Tok"), Th("Total Tok"))),
        Tbody(
            *[
                Tr(
                    Td(row["label"]),
                    Td(row["model"]),
                    Td(row["calls"]),
                    Td(row["avg_tps"]),
                    Td(row["recent_tps"]),
                    Td(row["avg_latency"]),
                    Td(row["output_tokens"]),
                    Td(row["total_tokens"]),
                )
                for row in rows
            ]
            or [Tr(Td("No timed generation completions yet.", colspan="8", cls="muted"))]
        ),
        cls="throughput-table",
    )


def judgement_throughput(db: Session, run_id: int) -> list[dict[str, str]]:
    """Aggregate judge timing and token throughput by config."""

    rows = db.exec(
        select(Judgement, JudgeConfig, Match)
        .where(Match.run_id == run_id)
        .where(Judgement.match_id == Match.id)
        .where(Judgement.judge_config_id == JudgeConfig.id)
        .where(Judgement.error == None)  # noqa: E711
    ).all()
    by_config: dict[int, dict] = {}
    for judgement, judge, _match in rows:
        if not judgement.started_at or not judgement.completed_at:
            continue
        seconds = max((judgement.completed_at - judgement.started_at).total_seconds(), 0.001)
        output_tokens = judgement.completion_tokens or 0
        total_tokens = (judgement.prompt_tokens or 0) + output_tokens
        bucket = by_config.setdefault(
            judge.id,
            {
                "label": judge.label,
                "model": judge.model_id,
                "calls": 0,
                "seconds": 0.0,
                "output_tokens": 0,
                "total_tokens": 0,
                "recent_completed_at": None,
                "recent_tps": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["seconds"] += seconds
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        if not bucket["recent_completed_at"] or judgement.completed_at > bucket["recent_completed_at"]:
            bucket["recent_completed_at"] = judgement.completed_at
            bucket["recent_tps"] = output_tokens / seconds if output_tokens else 0.0

    metrics = []
    for bucket in by_config.values():
        avg_tps = bucket["output_tokens"] / bucket["seconds"] if bucket["seconds"] else 0.0
        avg_latency = bucket["seconds"] / bucket["calls"] if bucket["calls"] else 0.0
        metrics.append(
            {
                "label": bucket["label"],
                "model": bucket["model"],
                "calls": str(bucket["calls"]),
                "avg_tps": f"{avg_tps:.1f}",
                "recent_tps": f"{bucket['recent_tps']:.1f}",
                "avg_latency": f"{avg_latency:.1f}s",
                "output_tokens": f"{bucket['output_tokens']:,}",
                "total_tokens": f"{bucket['total_tokens']:,}",
            }
        )
    return sorted(metrics, key=lambda row: float(row["avg_tps"]), reverse=True)


def judge_favorite_map(db: Session, run_id: int, judges: list[JudgeConfig]) -> dict[int, list[tuple[JudgeConfig, int]]]:
    """Map each generator config to the judges that favor it most."""

    matches = db.exec(select(Match).where(Match.run_id == run_id, Match.status == Status.complete)).all()
    tallies: dict[int, dict[int, int]] = {judge.id: {} for judge in judges if judge.id is not None}
    judge_lookup = {judge.id: judge for judge in judges if judge.id is not None}

    for match in matches:
        for judge_id in judge_lookup:
            normal = db.exec(
                select(Judgement).where(
                    Judgement.match_id == match.id,
                    Judgement.judge_config_id == judge_id,
                    Judgement.direction == "normal",
                )
            ).first()
            swapped = db.exec(
                select(Judgement).where(
                    Judgement.match_id == match.id,
                    Judgement.judge_config_id == judge_id,
                    Judgement.direction == "swapped",
                )
            ).first()
            if not normal or not swapped:
                continue
            winner = consistent_swapped_vote(normal.winner, swapped.winner)
            if winner == "A":
                config_id = match.config_a_id
            elif winner == "B":
                config_id = match.config_b_id
            else:
                continue
            tallies[judge_id][config_id] = tallies[judge_id].get(config_id, 0) + 1

    favorites: dict[int, list[tuple[JudgeConfig, int]]] = {}
    for judge_id, config_counts in tallies.items():
        if not config_counts:
            continue
        favorite_id, wins = max(config_counts.items(), key=lambda item: item[1])
        favorites.setdefault(favorite_id, []).append((judge_lookup[judge_id], wins))
    return favorites


def judge_favorite_badges(config_id: int | None, favorites: dict[int, list[tuple[JudgeConfig, int]]]):
    """Render badges that show which judges favored a config."""

    if config_id is None:
        return Span("None yet", cls="muted")
    badges = favorites.get(config_id, [])
    if not badges:
        return Span("None yet", cls="muted")
    return Span(
        *[
            Span("🥇", title=f"{judge.model_id} favored this config in {wins} matches", cls="judge-fav")
            for judge, wins in badges
        ],
        cls="judge-favs",
    )


def analysis_history(analyses: list[RunAnalysis]):
    """Render past judge-pattern analysis summaries."""

    return Div(
        *[
            Div(
                Div(
                    Span(f"{analysis.created_at:%Y-%m-%d %H:%M}"),
                    Span(f"{analysis.model_id} · {analysis.sample_size} traces"),
                    cls="analysis-meta",
                ),
                P(analysis.summary),
                cls="analysis-card",
            )
            for analysis in analyses
        ],
        cls="analysis-history",
    ) if analyses else P("No judge pattern analysis yet.", cls="muted")


def sample_judge_reasoning_traces(db: Session, run_id: int) -> list[dict[str, str]]:
    """Sample a small set of judge reasoning traces for analysis."""

    rows = db.exec(
        select(Judgement, JudgeConfig, Match, GeneratorConfig)
        .where(Match.run_id == run_id)
        .where(Judgement.match_id == Match.id)
        .where(Judgement.judge_config_id == JudgeConfig.id)
        .where(Judgement.error == None)  # noqa: E711
        .where(GeneratorConfig.id == Match.config_a_id)
    ).all()
    traces = [
        {
            "judge": judge.model_id,
            "direction": judgement.direction,
            "winner": judgement.winner,
            "reasoning": judgement.reasoning,
            "match_id": str(match.id),
        }
        for judgement, judge, match, _config_a in rows
        if judgement.reasoning.strip()
    ]
    sample_size = max(1, round(len(traces) * 0.10)) if traces else 0
    rng = random.Random(run_id)
    by_judge: dict[str, list[dict[str, str]]] = {}
    for trace in traces:
        by_judge.setdefault(trace["judge"], []).append(trace)
    sampled: list[dict[str, str]] = []
    judge_names = list(by_judge)
    rng.shuffle(judge_names)
    while len(sampled) < sample_size and any(by_judge.values()):
        for judge_name in judge_names:
            if by_judge[judge_name] and len(sampled) < sample_size:
                sampled.append(by_judge[judge_name].pop(rng.randrange(len(by_judge[judge_name]))))
    return sampled


def render_judge_pattern_prompt(traces: list[dict[str, str]]) -> str:
    """Format sampled judge traces into the analyzer prompt body."""

    payload = "\n\n".join(
        f"Trace {index}\nJudge: {trace['judge']}\nMatch: {trace['match_id']}\nDirection: {trace['direction']}\nWinner: {trace['winner']}\nReasoning: {trace['reasoning']}"
        for index, trace in enumerate(traces, start=1)
    )
    return f"Sampled judge reasoning traces:\n\n{payload}\n\nWrite the one-paragraph trend analysis now."


def prompt_snapshot_group(title: str, configs):
    """Render a collapsible prompt snapshot section."""

    group_key = title.lower().replace(" ", "-")
    return Details(
        Summary(title),
        Div(
            *[
                Details(
                    Summary(f"{config.label} - {config.model_id}"),
                    Div(
                        Div(
                            Span(f"Temp {config.temperature}"),
                            Span(path_label(config.prompt_path)),
                            cls="prompt-meta",
                        ),
                        Pre(config.prompt_snapshot),
                        cls="prompt-body",
                    ),
                    cls="prompt-card",
                    data_details_key=f"prompt-{group_key}-{config.id}",
                )
                for config in configs
            ],
            cls="prompt-stack",
        ),
        cls="prompt-group",
        data_details_key=f"prompt-{group_key}",
    )


def match_row(match_id: int):
    """Render one row in the recent matches table."""

    with session() as db:
        match = db.get(Match, match_id)
        transcript = db.get(Transcript, match.transcript_id)
        cfg_a = db.get(GeneratorConfig, match.config_a_id)
        cfg_b = db.get(GeneratorConfig, match.config_b_id)
        result = db.exec(select(MatchResult).where(MatchResult.match_id == match_id)).first()
    winner = match_winner_label(result.final_winner, cfg_a, cfg_b) if result else "Pending"
    return Tr(
        Td(Path(transcript.path).name),
        Td(Span(cfg_a.label, cls="match-model"), Span(" vs ", cls="muted"), Span(cfg_b.label, cls="match-model")),
        Td(Span(winner, cls=f"result-chip result-{(result.final_winner if result else match.status.value).lower()}")),
        Td(f"{result.agreement:.0%}" if result else "-"),
        Td(vote_summary(result.votes_json) if result else "-"),
        Td(status_pill(match.status.value)),
        Td(A("Inspect", href=f"/matches/{match_id}", cls="table-link")),
    )


def match_winner_label(winner: str, cfg_a: GeneratorConfig, cfg_b: GeneratorConfig) -> str:
    """Map match winners back to the generator label that won."""

    if winner == "A":
        return cfg_a.label
    if winner == "B":
        return cfg_b.label
    return "Tie"


def vote_summary(votes_json: str) -> str:
    """Summarize raw vote JSON for table display."""

    try:
        votes = json.loads(votes_json)
    except Exception:
        return "-"
    return " / ".join(f"{label}:{votes.count(label)}" for label in ("A", "B", "TIE") if votes.count(label))


def build_generator_specs(rows: list[tuple[str, str, str, str]]) -> list[GeneratorSpec]:
    """Convert form rows into generator specs and skip blank entries."""

    specs = []
    for label, model_id, temperature, prompt_path in rows:
        if not label.strip() and not model_id.strip():
            continue
        if not label.strip() or not model_id.strip() or not prompt_path.strip():
            continue
        specs.append(GeneratorSpec(label.strip(), model_id.strip(), float(temperature or 0.0), prompt_path.strip()))
    return specs


def build_judge_specs(rows: list[tuple[str, str, str, str]]) -> list[JudgeSpec]:
    """Convert form rows into judge specs and skip blank entries."""

    specs = []
    for label, model_id, temperature, prompt_path in rows:
        if not label.strip() and not model_id.strip():
            continue
        if not label.strip() or not model_id.strip() or not prompt_path.strip():
            continue
        specs.append(JudgeSpec(label.strip(), model_id.strip(), float(temperature or 0.0), prompt_path.strip()))
    return specs


def start_run_thread(run_id: int):
    """Start a background thread for one run if it is not already active."""

    if run_id in RUN_THREADS and RUN_THREADS[run_id].is_alive():
        return

    def target():
        """Run the background job and persist failures to the run row."""

        try:
            asyncio.run(execute_run(run_id, session))
        except Exception as exc:
            with session() as db:
                run = db.get(Run, run_id)
                if run:
                    run.status = Status.failed
                    run.error = str(exc)
                    db.add(run)
                    db.commit()

    thread = threading.Thread(target=target, daemon=True)
    RUN_THREADS[run_id] = thread
    thread.start()


if __name__ == "__main__":
    serve(host="127.0.0.1", port=5001)
