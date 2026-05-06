"""Local FastHTML GUI for LLM-Transcript-Council."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from fasthtml.common import *
from sqlmodel import Session, select

from council.db import engine, init_db
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
    Status,
    Task,
    Transcript,
)
from council.runner import (
    GeneratorSpec,
    JudgeSpec,
    create_project,
    create_run,
    create_task,
    execute_run,
    run_progress,
)

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
    return Session(engine)


def shell(title: str, *content):
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


def input_row(label: str, name: str, value: str = "", *, placeholder: str = "", type: str = "text"):
    return Label(Span(label), Input(name=name, value=value, placeholder=placeholder, type=type), cls="field")


def textarea_row(label: str, name: str, value: str = "", *, rows: int = 4):
    return Label(Span(label), Textarea(value, name=name, rows=rows), cls="field")


def selected_option(value, label, selected=False):
    return Option(label, value=str(value), selected=selected)


def path_label(path: str | Path) -> str:
    resolved = Path(path)
    cwd = Path.cwd().resolve()
    try:
        return str(resolved.resolve().relative_to(cwd))
    except ValueError:
        return resolved.name


def prompt_picker(label: str, name: str, files: list[Path], selected: str | Path | None = None):
    selected_path = str(Path(selected).resolve()) if selected else None
    fallback = selected_path or (str(files[0].resolve()) if files else "")
    return Label(
        Span(label),
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
    return Input(name=name, value=value, placeholder="openai/gpt-4o-mini")


def config_card(kind: str, index: int, *, prompt_files: list[Path], defaults: dict[str, str], required: bool = False):
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
    return Span(status, cls=f"pill pill-{status}")


def empty_state(title: str, body: str, href: str | None = None, action: str | None = None):
    children = [H3(title), P(body, cls="muted")]
    if href and action:
        children.append(A(action, href=href, cls="button subtle"))
    return Div(*children, cls="empty-state")


@rt("/")
def get():
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
                input_row("Project name", "name", placeholder="Call coaching evals"),
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
                    A(
                        H3(project.name),
                        P(f"Created {project.created_at:%Y-%m-%d %H:%M}"),
                        href=f"/projects/{project.id}",
                        cls="list-card",
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
    return RedirectResponse("/", status_code=303)


@rt("/projects")
def post(name: str):
    if not name.strip():
        return RedirectResponse("/", status_code=303)
    with session() as db:
        project = create_project(db, name)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@rt("/projects/{project_id}")
def get(project_id: int):
    with session() as db:
        project = db.get(Project, project_id)
        tasks = db.exec(select(Task).where(Task.project_id == project_id)).all()
    return shell(
        project.name,
        Div(
            H1(project.name),
            A("Create task", href=f"/tasks/new?project_id={project_id}", cls="button"),
            cls="page-head",
        ),
        Section(
            H2("Tasks"),
            Div(
                *[
                    A(
                        H3(task.name),
                        P(Path(task.description_path).name),
                        href=f"/tasks/{task.id}",
                        cls="list-card",
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
                Span("Project"),
                Select(
                    *[selected_option(p.id, p.name, p.id == project_id) for p in projects],
                    name="project_id",
                ),
                cls="field",
            ),
            input_row("Task name", "name", placeholder="Cross-sell coaching feedback"),
            prompt_picker("Task description", "description_path", task_files, Path("prompts/tasks/example_task.md").resolve()),
            Label(
                Span("Transcript folder"),
                Input(name="transcript_root", value=str(transcript_root), placeholder="/path/to/transcripts"),
                cls="field",
            ),
            prompt_picker("Default judge prompt", "default_judge_prompt_path", judge_files, Path("prompts/judges/default_pairwise.md").resolve()),
            Button("Create task", type="submit"),
            action="/tasks",
            method="post",
            cls="panel form-stack",
        ),
    )


@rt("/tasks")
def post(project_id: int, name: str, description_path: str, transcript_root: str, default_judge_prompt_path: str):
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
        )
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@rt("/tasks/{task_id}")
def get(task_id: int):
    with session() as db:
        task = db.get(Task, task_id)
        runs = db.exec(select(Run).where(Run.task_id == task_id).order_by(Run.created_at.desc())).all()
    files = list_markdown_files(task.transcript_root)
    return shell(
        task.name,
        Div(
            Div(H1(task.name), P(task.description_snapshot[:240], cls="muted"), cls="hero-copy"),
            A("New run", href=f"/runs/new?task_id={task.id}", cls="button"),
            cls="page-head",
        ),
        Section(
            H2("Transcript Set"),
            P(f"{len(files)} markdown transcript files in {task.transcript_root}", cls="muted"),
            cls="section panel",
        ),
        Section(H2("Runs"), run_table(runs), cls="section"),
    )


@rt("/runs/new")
def get(task_id: int | None = None):
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
    generator_prompt_files = list_markdown_files("prompts/generators")
    judge_prompt_files = list_markdown_files("prompts/judges")
    default_generator_prompt = str(Path("prompts/generators/example_prompt.md").resolve())
    return shell(
        "New Run",
        H1("New Run"),
        Form(
            Label(
                Span("Task"),
                Select(*[selected_option(t.id, t.name, t.id == task_id) for t in tasks], name="task_id"),
                cls="field",
            ),
            input_row("Run name", "name", placeholder="gpt prompt v2 comparison"),
            input_row("Transcript sample size", "sample_size", placeholder="leave blank for all", type="number"),
            input_row("Max concurrent LLM calls", "max_concurrency", value=os.getenv("MAX_CONCURRENT_LLM_CALLS", "5"), type="number"),
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
            Label(Input(type="checkbox", name="swap_enabled", value="true", checked=True), Span("Validate each judge vote with swapped A/B positions"), cls="check"),
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
            max_concurrency=max_concurrency,
            swap_enabled=swap_enabled == "true",
        )
        run_id = run.id
    start_run_thread(run_id)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@rt("/runs")
def get():
    with session() as db:
        runs = db.exec(select(Run).order_by(Run.created_at.desc())).all()
    return shell("Runs", Div(H1("Runs"), A("New run", href="/runs/new", cls="button"), cls="page-head"), run_table(runs))


@rt("/runs/{run_id}")
def get(run_id: int):
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
    return shell(
        run.name,
        Div(
            Div(H1(run.name), P(task.name, cls="muted"), cls="hero-copy"),
            Div(status_pill(run.status.value), A("Refresh", href=f"/runs/{run.id}", cls="button subtle"), cls="actions"),
            cls="page-head",
        ),
        Section(
            H2("Progress"),
            progress_meter("Generations", progress["generations_complete"], progress["generations"]),
            progress_meter("Matches", progress["matches_complete"], progress["matches"]),
            P(f'{progress["judgements"]} judge calls recorded', cls="muted"),
            cls="section panel",
        ),
        Section(
            H2("Leaderboard"),
            Table(
                Thead(Tr(Th("Config"), Th("Model"), Th("Temp"), Th("ELO"), Th("W"), Th("L"), Th("T"))),
                Tbody(
                    *[
                        Tr(
                            Td(config.label),
                            Td(config.model_id),
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
            cls="section panel",
        ),
        Section(
            H2("Recent Matches"),
            Div(
                *[match_card(match.id) for match in matches],
                cls="stack",
            ),
            cls="section",
        ),
    )


@rt("/matches/{match_id}")
def get(match_id: int):
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
    pct = int((complete / total) * 100) if total else 0
    return Div(
        Div(Span(label), Span(f"{complete}/{total}"), cls="meter-label"),
        Div(Div(style=f"width:{pct}%"), cls="meter"),
        cls="meter-wrap",
    )


def match_card(match_id: int):
    with session() as db:
        match = db.get(Match, match_id)
        cfg_a = db.get(GeneratorConfig, match.config_a_id)
        cfg_b = db.get(GeneratorConfig, match.config_b_id)
        result = db.exec(select(MatchResult).where(MatchResult.match_id == match_id)).first()
    return A(
        H3(f"{cfg_a.label} vs {cfg_b.label}"),
        P(result.final_winner if result else match.status.value, cls="muted"),
        href=f"/matches/{match_id}",
        cls="list-card",
    )


def build_generator_specs(rows: list[tuple[str, str, str, str]]) -> list[GeneratorSpec]:
    specs = []
    for label, model_id, temperature, prompt_path in rows:
        if not label.strip() and not model_id.strip():
            continue
        if not label.strip() or not model_id.strip() or not prompt_path.strip():
            continue
        specs.append(GeneratorSpec(label.strip(), model_id.strip(), float(temperature or 0.0), prompt_path.strip()))
    return specs


def build_judge_specs(rows: list[tuple[str, str, str, str]]) -> list[JudgeSpec]:
    specs = []
    for label, model_id, temperature, prompt_path in rows:
        if not label.strip() and not model_id.strip():
            continue
        if not label.strip() or not model_id.strip() or not prompt_path.strip():
            continue
        specs.append(JudgeSpec(label.strip(), model_id.strip(), float(temperature or 0.0), prompt_path.strip()))
    return specs


def start_run_thread(run_id: int):
    if run_id in RUN_THREADS and RUN_THREADS[run_id].is_alive():
        return

    def target():
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
