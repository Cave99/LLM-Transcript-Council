"""Local FastHTML GUI for LLM-Transcript-Council."""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from fasthtml.common import *
from sqlmodel import Session, select

from council.db import engine, init_db
from council.files import list_markdown_files
from council.graphs import (
    add_constant_node,
    add_dataset_node,
    add_judge_node,
    add_model_node,
    add_prompt_node,
    config as node_config,
    create_edge,
    create_graph,
    delete_graph,
    delete_edge,
    delete_node,
    delete_socket_edges,
    fork_graph,
    graph_edges as graph_edge_rows,
    graph_nodes,
    plan_graph,
    prompt_inputs,
    rename_graph,
    sync_graph_status,
    update_node,
    update_node_position,
)
from council.graph_runtime import (
    create_graph_native_run,
    graph_native_progress,
    graph_run_leaderboard,
    stop_graph_native_run,
)
from council.jobs import start_graph_run_thread
from council.models import (
    ExperimentGraph,
    GraphNode,
    GraphInvocation,
    GraphEdge,
    GraphRun,
    Project,
    Status,
)
from council.runner import create_project, delete_project, rename_project

load_dotenv()
init_db()

app, rt = fast_app(
    hdrs=(
        Link(rel="stylesheet", href="/static/app.css"),
        Script(src="/static/app.js"),
    )
)

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
                    A("New Graph", href="/graphs/new"),
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


def textarea_row(label: str, name: str, value: str = "", *, rows: int = 4, cls: str = "field"):
    """Render a labeled textarea row."""

    return Label(Span(label), Textarea(value, name=name, rows=rows), cls=cls)


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


def graph_run_card(run: GraphRun):
    """Render a previous graph run entry."""

    run_kind = "test run" if run.sample_size == 1 else "full run"
    if run.status != Status.complete:
        run_kind = f"incomplete {run_kind}"
    meta = f"{run_kind} · {run.created_at:%Y-%m-%d %H:%M}"
    return A(
        Div(H3(run.name), P(meta, cls="muted"), cls="run-history-copy"),
        status_pill(run.status.value),
        href=f"/graph-runs/{run.id}",
        cls="run-history-card",
    )


@rt("/")
def get():
    """Render the project index page."""

    with session() as db:
        projects = db.exec(select(Project).order_by(Project.created_at.desc())).all()
        graph_runs = db.exec(
            select(GraphRun).order_by(GraphRun.created_at.desc()).limit(5)
        ).all()
        graphs = {g.id: g for g in db.exec(select(ExperimentGraph)).all()}
    return shell(
        "Projects",
        Section(
            Div(
                H1("LLM-Transcript-Council"),
                P("Compare subjective LLM outputs with blind pairwise judges and ELO rankings."),
                cls="hero-copy",
            ),
            Form(
                input_row("Project name", "name", placeholder="Call coaching evals", help_text="A project groups related evaluation work. Use one for a product area, customer workflow, or experiment family."),
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
                        f"Delete project '{project.name}'? This will also delete its graphs and runs.",
                    )
                    for project in projects
                ]
                or [empty_state("No projects yet", "Create a project to group related graphs and runs.")],
                cls="grid",
            ),
            cls="section",
        ),
        Section(
            H2("Recent Graph Runs"),
            Div(
                *[graph_run_card(run, graphs.get(run.graph_id)) for run in graph_runs]
                or [P("No graph runs yet.", cls="muted")],
                cls="run-history-list",
            ),
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
        graphs = db.exec(select(ExperimentGraph).where(ExperimentGraph.project_id == project_id).order_by(ExperimentGraph.updated_at.desc())).all()
        graphs = [sync_graph_status(db, graph) for graph in graphs]
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
            A("New graph", href=f"/graphs/new?project_id={project_id}", cls="button"),
            cls="page-head",
        ),
        Section(
            H2("Graphs"),
            Div(
                *[
                    graph_card(graph)
                    for graph in graphs
                ]
                or [empty_state("No graphs yet", "Create a node graph to configure prompts, models, datasets, judges, and run counts.", f"/graphs/new?project_id={project_id}", "Create graph")],
                cls="grid",
            ),
            cls="section",
        ),
    )


@rt("/graphs/new")
def get(project_id: int | None = None):
    """Render graph creation for a project."""

    with session() as db:
        projects = db.exec(select(Project)).all()
    if not projects:
        return shell(
            "New Graph",
            Div(H1("New Graph"), P("Create a project first, then add a node graph inside it.", cls="muted"), cls="page-head"),
            empty_state("No projects available", "Graphs live inside projects so configs and results stay grouped.", "/", "Create project"),
        )
    return shell(
        "New Graph",
        H1("New Graph"),
        Form(
            Label(
                help_label("Project", "The project groups related graph drafts and runs."),
                Select(*[selected_option(p.id, p.name, p.id == project_id) for p in projects], name="project_id"),
                cls="field",
            ),
            input_row("Graph name", "name", placeholder="4 model coaching comparison"),
            Button("Create graph", type="submit"),
            action="/graphs",
            method="post",
            cls="panel form-stack",
        ),
    )


@rt("/graphs")
def post(project_id: int, name: str):
    """Create a draft graph and open the node editor."""

    with session() as db:
        graph = create_graph(db, project_id, name)
    return RedirectResponse(f"/graphs/{graph.id}", status_code=303)


@rt("/graphs/{graph_id}")
def get(graph_id: int, mode: str = "view"):
    """Render the node graph editor and planner."""

    with session() as db:
        graph = db.get(ExperimentGraph, graph_id)
        if not graph:
            return RedirectResponse("/", status_code=303)
        graph = sync_graph_status(db, graph)
        project = db.get(Project, graph.project_id)
        nodes = graph_nodes(db, graph_id)
        edges = graph_edge_rows(db, graph_id)
        plan = plan_graph(db, graph_id)
        graph_runs = db.exec(
            select(GraphRun)
            .where(GraphRun.graph_id == graph_id)
            .order_by(GraphRun.created_at.desc())
            .limit(12)
        ).all()
        last_graph_run = graph_runs[0] if graph_runs else None
    configure = mode == "configure"
    return shell(
        graph.name,
        Div(
            Div(
                H1(graph.name),
                P(f"{project.name} · updated {graph.updated_at:%Y-%m-%d %H:%M}", cls="muted"),
                cls="hero-copy",
            ),
            Div(
                status_pill(graph.status.value),
                A("Project", href=f"/projects/{project.id}", cls="button subtle"),
                A("Open run", href=f"/graph-runs/{last_graph_run.id}", cls="button subtle") if last_graph_run else "",
                A("Configure fullscreen", href=f"/graphs/{graph.id}?mode=configure", cls="button") if not configure else A("Exit configure", href=f"/graphs/{graph.id}", cls="button subtle"),
                cls="actions",
            ),
            cls="page-head",
        ),
        graph_surface(graph, nodes, edges, plan, configure=configure),
        Section(
            H2("Planner"),
            plan_panel(plan),
            cls="section panel",
        ),
        Section(
            H2("Run Graph"),
            Form(
                input_row("Max concurrent calls", "max_concurrency", value=os.getenv("MAX_CONCURRENT_LLM_CALLS", "5"), type="number", min="1", help_text="How many model calls can run at once."),
                Div(
                    Button("Test run", type="submit", name="run_mode", value="test", cls="button subtle", title="Run one dataset item through the graph and inspect outputs."),
                    Button("Full run", type="submit", name="run_mode", value="full", title="Run every selected dataset item through the graph."),
                    cls="run-action-row",
                ),
                action=f"/graphs/{graph.id}/native-launch",
                method="post",
                cls="run-control-form",
            ),
            cls="section panel",
        ),
        Section(
            H2("Previous Runs"),
            Div(
                *[graph_run_card(run) for run in graph_runs]
                or [P("No graph runs yet.", cls="muted")],
                cls="run-history-list",
            ),
            cls="section",
        ),
    )


@rt("/graphs/{graph_id}/rename")
def post(graph_id: int, name: str):
    """Rename a graph."""

    with session() as db:
        rename_graph(db, graph_id, name)
    return RedirectResponse(f"/graphs/{graph_id}", status_code=303)


@rt("/graphs/{graph_id}/fork")
def post(graph_id: int):
    """Create an editable draft from a graph."""

    with session() as db:
        graph = db.get(ExperimentGraph, graph_id)
        fork = fork_graph(db, graph_id, f"{graph.name} draft")
    return RedirectResponse(f"/graphs/{fork.id}", status_code=303)


@rt("/graphs/{graph_id}/delete")
def post(graph_id: int):
    """Delete a graph draft/config."""

    with session() as db:
        graph = db.get(ExperimentGraph, graph_id)
        project_id = graph.project_id if graph else None
        delete_graph(db, graph_id)
    return RedirectResponse(f"/projects/{project_id}" if project_id else "/", status_code=303)


@rt("/graphs/{graph_id}/models/{role}")
def post(graph_id: int, role: str, x: int | None = None, y: int | None = None):
    """Append a model node."""

    with session() as db:
        add_model_node(db, graph_id, title="New model", model_id="", role=role if role in {"generator", "judge"} else "generator", x=x, y=y)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/graphs/{graph_id}/constants")
def post(graph_id: int, x: int | None = None, y: int | None = None):
    """Append a text constant node."""

    with session() as db:
        add_constant_node(db, graph_id, title="New constant", body="", x=x, y=y)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/graphs/{graph_id}/prompts")
def post(graph_id: int, x: int | None = None, y: int | None = None):
    """Append a chained prompt stage."""

    with session() as db:
        add_prompt_node(db, graph_id, x=x, y=y)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/graphs/{graph_id}/datasets")
def post(graph_id: int, x: int | None = None, y: int | None = None):
    """Append a dataset node from the configure palette."""

    with session() as db:
        add_dataset_node(db, graph_id, x=x, y=y)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/graphs/{graph_id}/judges")
def post(graph_id: int, x: int | None = None, y: int | None = None):
    """Append a judge prompt node from the configure palette."""

    with session() as db:
        add_judge_node(db, graph_id, x=x, y=y)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/nodes/{node_id}/position")
def post(node_id: int, x: int, y: int, width: int | None = None, height: int | None = None):
    """Persist node canvas geometry."""

    with session() as db:
        node = update_node_position(db, node_id, x=x, y=y, width=width, height=height)
        graph_id = node.graph_id
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/graphs/{graph_id}/edges")
def post(graph_id: int, from_node_id: int, from_socket: str, to_node_id: int, to_socket: str):
    """Persist a socket connection."""

    with session() as db:
        create_edge(
            db,
            graph_id,
            from_node_id=from_node_id,
            from_socket=from_socket,
            to_node_id=to_node_id,
            to_socket=to_socket,
        )
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/edges/{edge_id}/delete")
def post(edge_id: int):
    """Delete a socket connection."""

    with session() as db:
        graph_id = delete_edge(db, edge_id)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure" if graph_id else "/", status_code=303)


@rt("/graphs/{graph_id}/socket-edges/delete")
def post(graph_id: int, node_id: int, socket: str, side: str):
    """Delete every edge attached to one socket."""

    with session() as db:
        delete_socket_edges(db, graph_id, node_id=node_id, socket=socket, side=side)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure", status_code=303)


@rt("/nodes/{node_id}/delete")
def post(node_id: int):
    """Delete a graph node and any connected edges."""

    with session() as db:
        graph_id = delete_node(db, node_id)
    return RedirectResponse(f"/graphs/{graph_id}?mode=configure" if graph_id else "/", status_code=303)


@rt("/nodes/{node_id}")
def post(
    node_id: int,
    title: str,
    body: str = "",
    cfg_path: str = "",
    cfg_source_type: str = "",
    cfg_sample_size: str = "",
    cfg_id_column: str = "",
    cfg_text_column: str = "",
    cfg_model_id: str = "",
    cfg_temperature: str = "",
    cfg_max_tokens: str = "",
    cfg_retry_count: str = "",
    cfg_reasoning_supported: str | None = None,
    cfg_reasoning_effort: str = "",
    cfg_input_price: str = "",
    cfg_output_price: str = "",
    cfg_role: str = "",
    cfg_pairing_sample_pct: str = "",
    cfg_seed: str = "",
    cfg_swap_enabled: str | None = None,
    cfg_winner_key: str = "",
    cfg_reasoning_key: str = "",
    cfg_socket: str = "",
    cfg_upstream_mode: str = "",
    return_to: str = "view",
):
    """Update a graph node from its card editor."""

    with session() as db:
        existing = db.get(GraphNode, node_id)
        if existing.kind == "dataset":
            config_values = {
                "source_type": cfg_source_type or "markdown",
                "path": cfg_path,
                "sample_size": cfg_sample_size,
                "id_column": cfg_id_column or "call_id",
                "text_column": cfg_text_column or "transcript",
            }
        elif existing.kind == "model":
            reasoning_supported = cfg_reasoning_supported == "true"
            config_values = {
                "model_id": cfg_model_id,
                "temperature": cfg_temperature,
                "max_tokens": cfg_max_tokens,
                "retry_count": cfg_retry_count,
                "reasoning_supported": reasoning_supported,
                "reasoning_effort": cfg_reasoning_effort if reasoning_supported else "",
                "input_price": cfg_input_price,
                "output_price": cfg_output_price,
                "role": cfg_role or node_config(existing).get("role", "generator"),
            }
        elif existing.kind == "judge":
            config_values = {
                "pairing_sample_pct": cfg_pairing_sample_pct,
                "seed": cfg_seed,
                "swap_enabled": cfg_swap_enabled == "true",
                "winner_key": cfg_winner_key,
                "reasoning_key": cfg_reasoning_key,
            }
        elif existing.kind == "constant":
            config_values = {"socket": cfg_socket}
        elif existing.kind == "prompt":
            config_values = {"upstream_mode": cfg_upstream_mode or "raw"}
        else:
            config_values = node_config(existing)
        node = update_node(db, node_id, title=title, body=body, config_values=config_values)
        graph_id = node.graph_id
    suffix = "?mode=configure" if return_to == "configure" else ""
    return RedirectResponse(f"/graphs/{graph_id}{suffix}", status_code=303)


@rt("/graphs/{graph_id}/launch")
def post(graph_id: int, max_concurrency: int = 5, run_mode: str = "full"):
    """Start graph-native execution over one item or the full dataset."""

    with session() as db:
        graph_run = create_graph_native_run(db, graph_id, max_concurrency=max_concurrency, sample_size=1 if run_mode == "test" else None)
        graph_run_id = graph_run.id
    start_graph_run_thread(graph_run_id, session)
    return RedirectResponse(f"/graph-runs/{graph_run_id}", status_code=303)


@rt("/graph-runs/{graph_run_id}")
def get(graph_run_id: int):
    """Render graph-native run progress and outputs."""

    with session() as db:
        graph_run = db.get(GraphRun, graph_run_id)
        if not graph_run:
            return RedirectResponse("/", status_code=303)
        graph = db.get(ExperimentGraph, graph_run.graph_id)
        if not graph:
            return RedirectResponse("/", status_code=303)
        progress = graph_native_progress(db, graph_run_id)
        invocations = db.exec(
            select(GraphInvocation)
            .where(GraphInvocation.graph_run_id == graph_run_id)
            .order_by(GraphInvocation.completed_at.desc())
        ).all()
        graph_node_list = graph_nodes(db, graph.id)
        edges = graph_edge_rows(db, graph.id)
        plan = plan_graph(db, graph.id)
        nodes = {node.id: node for node in graph_node_list}
        node_progress = graph_node_progress(graph_node_list, invocations)
        leaderboard = graph_run_leaderboard(db, graph_run_id, graph_node_list)
    return shell(
        graph_run.name,
            Div(
                Div(H1(graph_run.name), P("Graph run", cls="muted"), cls="hero-copy"),
                Div(
                    status_pill(graph_run.status.value),
                    run_action_button(graph_run, "Stop Run", f"/graph-runs/{graph_run.id}/stop", subtle=True) if graph_run.status == Status.running else "",
                    A("Graph", href=f"/graphs/{graph.id}", cls="button subtle"),
                    cls="actions",
                ),
            cls="page-head",
        ),
        Section(
            H2("Progress"),
            graph_run_diagnostics(graph_run, progress),
            progress_meter("Invocations", progress["complete"], progress["total"]),
            progress_breakdown(pending=progress["pending"], running=progress["running"], failed=progress["failed"]),
            cls="section panel",
        ),
        graph_surface(graph, graph_node_list, edges, plan, configure=False, node_progress=node_progress),
        Section(
            H2("Leaderboard"),
            Table(
                Thead(Tr(Th("Model"), Th("Temp"), Th("ELO"), Th("W"), Th("L"), Th("T"), Th("Avg Tok"), Th("Judge Favs"))),
                Tbody(
                    *[
                        Tr(
                            Td(node_config(row["node"]).get("model_id", row["node"].title)),
                            Td(str(node_config(row["node"]).get("temperature", "-"))),
                            Td(f"{row['rating']:.1f}"),
                            Td(str(row["wins"])),
                            Td(str(row["losses"])),
                            Td(str(row["ties"])),
                            Td(row["avg_tokens"]),
                            Td(graph_judge_favorite_badges(row["favorites"])),
                        )
                        for row in leaderboard
                    ]
                    or [Tr(Td("No completed judge votes yet.", colspan="8", cls="muted"))]
                ),
            ),
            cls="section panel",
        ),
        Section(
            H2("Model Outputs"),
            graph_run_output_browser(invocations, nodes),
            cls="section",
        ),
    )


@rt("/graph-runs/{graph_run_id}/stop")
def post(graph_run_id: int):
    """Pause a graph-native run."""

    with session() as db:
        stop_graph_native_run(db, graph_run_id)
    return RedirectResponse(f"/graph-runs/{graph_run_id}", status_code=303)






























def graph_card(graph: ExperimentGraph):
    """Render a project graph card."""

    meta = f"{graph.status.value} · updated {graph.updated_at:%Y-%m-%d %H:%M}"
    return Div(
        A(H3(graph.name), P(meta, cls="muted"), href=f"/graphs/{graph.id}", cls="card-link"),
        delete_form(f"/graphs/{graph.id}/delete", f"Delete graph '{graph.name}'? Existing runs are not deleted."),
        cls="list-card list-card-with-actions",
    )


def graph_surface(graph: ExperimentGraph, nodes: list[GraphNode], edges: list[GraphEdge], plan, *, configure: bool, node_progress: dict[int, dict] | None = None):
    """Render either the view-only graph or the fullscreen configure surface."""

    palette = graph_palette(graph) if configure else ""
    zoom_controls = Div(
        Button("−", type="button", title="Zoom out", cls="button subtle zoom-btn", data_zoom="-"),
        Button("100%", type="button", title="Reset zoom", cls="button subtle zoom-btn", data_zoom="1"),
        Button("+", type="button", title="Zoom in", cls="button subtle zoom-btn", data_zoom="+"),
        cls="canvas-zoom-controls",
    )
    configure_header = Div(
        Div(
            H2("Configure Graph"),
            P("Drag nodes from the palette, connect outputs to prompt inputs, then return to run controls.", cls="muted"),
            cls="configure-title",
        ),
        A("Back to graph", href=f"/graphs/{graph.id}", cls="button"),
        cls="configure-header",
    ) if configure else H2("Graph")
    return Section(
        configure_header,
        Div(
            palette,
            Div(
                Div(
                    Div(
                        graph_edge_layer(edges, nodes, configure=configure),
                *[node_canvas_card(node, edges=edges, configure=configure, progress=(node_progress or {}).get(node.id)) for node in nodes],
                        cls="canvas-scaler",
                    ),
                    cls="node-canvas",
                    data_graph_canvas="true" if configure else "view",
                    data_graph_id=str(graph.id),
                ),
                zoom_controls,
                cls="canvas-wrap",
            ),
            cls="graph-config-shell" if configure else "graph-view-shell",
        ),
        graph_edges(plan),
        cls="section graph-config-section" if configure else "section",
    )


def graph_edge_layer(edges: list[GraphEdge], nodes: list[GraphNode], *, configure: bool):
    """Render persisted connections as canvas SVG paths."""

    node_lookup = {node.id: node for node in nodes}
    paths = []
    for edge in edges:
        source = node_lookup.get(edge.from_node_id)
        target = node_lookup.get(edge.to_node_id)
        if not source or not target:
            continue
        sx = source.x + node_canvas_width(source)
        sy = source.y + socket_offset(output_sockets(source), edge.from_socket)
        tx = target.x
        ty = target.y + socket_offset(input_sockets(target), edge.to_socket)
        mid = max(40, abs(tx - sx) / 2)
        paths.append(
            f'<path d="M {sx} {sy} C {sx + mid} {sy}, {tx - mid} {ty}, {tx} {ty}" '
            f'class="graph-edge-path" data-from-node="{edge.from_node_id}" data-from-socket="{edge.from_socket}" '
            f'data-to-node="{edge.to_node_id}" data-to-socket="{edge.to_socket}" />'
        )
    return NotStr(f'<svg class="graph-edge-layer" width="12000" height="8000" aria-hidden="true">{"".join(paths)}</svg>')


def socket_offset(sockets: list[str], socket: str) -> int:
    """Map a socket name to its approximate vertical location in a node."""

    try:
        index = sockets.index(socket)
    except ValueError:
        index = 0
    return 52 + index * 26


def node_canvas_width(node: GraphNode) -> int:
    """Return a node width with a default for older saved graphs."""

    return getattr(node, "width", 460) or 460


def node_canvas_height(node: GraphNode) -> int:
    """Return a node height with a default for older saved graphs."""

    return getattr(node, "height", 260) or 260


def graph_palette(graph: ExperimentGraph):
    """Render draggable node creation palette for configure mode."""

    items = [
        ("Dataset", "Transcript or CSV rows", f"/graphs/{graph.id}/datasets", "dataset"),
        ("Prompt", "Template with {{ inputs }}", f"/graphs/{graph.id}/prompts", "prompt"),
        ("Constant", "Reusable text value", f"/graphs/{graph.id}/constants", "constant"),
        ("Generator model", "Model used for prompt outputs", f"/graphs/{graph.id}/models/generator", "model"),
        ("Judge prompt", "Pairwise comparison template", f"/graphs/{graph.id}/judges", "judge"),
        ("Judge model", "Model used for judging", f"/graphs/{graph.id}/models/judge", "model"),
    ]
    return Aside(
        H3("Nodes"),
        P("Drag a node type onto the canvas.", cls="muted"),
        *[
            Form(
                Input(type="hidden", name="x", value="80", data_palette_x="true"),
                Input(type="hidden", name="y", value="80", data_palette_y="true"),
                Button(Span(label), Small(description), type="submit", cls=f"palette-node palette-node-{kind}", draggable="true", data_palette_node="true"),
                action=action,
                method="post",
                cls="palette-form",
            )
            for label, description, action, kind in items
        ],
        cls="node-palette",
    )


def graph_lane(title: str, nodes: list[GraphNode]):
    """Render one column of the node graph."""

    return Div(
        H3(title),
        Div(*[node_card(node) for node in nodes] or [P("No nodes", cls="muted")], cls="node-stack"),
        cls="node-lane",
    )


def node_canvas_card(node: GraphNode, *, edges: list[GraphEdge] | None = None, configure: bool = True, progress: dict | None = None):
    """Render a positioned node for the lightweight graph canvas."""

    return Div(
        node_sockets(node, side="input", edges=edges or [], configure=configure),
        node_card(node, configure=configure, progress=progress),
        node_sockets(node, side="output", edges=edges or [], configure=configure),
        Form(
            Input(type="hidden", name="x", value=str(node.x), data_node_x="true"),
            Input(type="hidden", name="y", value=str(node.y), data_node_y="true"),
            Input(type="hidden", name="width", value=str(node_canvas_width(node)), data_node_width="true"),
            Input(type="hidden", name="height", value=str(node_canvas_height(node)), data_node_height="true"),
            action=f"/nodes/{node.id}/position",
            method="post",
            data_node_position_form="true",
        ),
        Button("", type="button", cls="node-resize-handle", title="Resize node", data_resize_handle="true") if configure else "",
        cls=f"canvas-node{' is-config' if configure else ''}",
        style=f"--node-x:{node.x}; --node-y:{node.y}; --node-w:{node_canvas_width(node)}; --node-h:{node_canvas_height(node)};",
        data_node_id=str(node.id),
    )


def node_card(node: GraphNode, *, configure: bool = True, progress: dict | None = None):
    """Render a graph node with its editable config."""

    cfg = node_config(node)
    if not configure:
        return Div(
            Div(
                Span(node.title, cls="node-title"),
                Span(node.kind, cls=f"node-kind node-kind-{node.kind}"),
                node_progress_badge(progress),
                cls="node-header",
            ),
            node_readonly_body(node, cfg),
            cls=f"node-card node-card-{node.kind}",
        )
    body_field = textarea_row("Prompt / text", "body", node.body, rows=7, cls="field node-body-field") if node.kind in {"prompt", "judge", "constant"} else Input(type="hidden", name="body", value=node.body)
    delete_button = Button(
        "×",
        type="submit",
        cls="icon-button node-delete-btn",
        title="Delete node",
        form=f"node-delete-{node.id}",
    ) if configure else ""
    return Div(
        Div(
            Span(node.title, cls="node-title"),
            Span(node.kind, cls=f"node-kind node-kind-{node.kind}"),
            node_progress_badge(progress),
            delete_button,
            cls="node-header",
        ),
        Form(
            input_row("Title", "title", value=node.title),
            *node_config_fields(node, cfg),
            body_field,
            Input(type="hidden", name="return_to", value="configure" if configure else "view"),
            Button("Done", type="submit"),
            action=f"/nodes/{node.id}",
            method="post",
            cls="node-form",
        ),
        Form(
            Input(type="hidden", name="confirm", value="true"),
            action=f"/nodes/{node.id}/delete",
            method="post",
            cls="delete-form",
            id=f"node-delete-{node.id}",
            data_confirm_message=f"Delete node '{node.title}'?",
        ) if configure else "",
        cls=f"node-card node-card-{node.kind}",
    )


def input_sockets(node: GraphNode) -> list[str]:
    """Return visible input socket labels for a node."""

    if node.kind == "prompt":
        return prompt_inputs(node.body)
    if node.kind == "judge":
        template_inputs = [socket for socket in prompt_inputs(node.body) if socket not in {"output_a", "output_b"}]
        return unique_sockets(["models", *template_inputs])
    if node.kind == "model":
        return ["judge_prompt"] if node_config(node).get("role") == "judge" else ["prompt"]
    return []


def output_sockets(node: GraphNode) -> list[str]:
    """Return visible output socket labels for a node."""

    if node.kind == "dataset":
        cfg = node_config(node)
        if cfg.get("source_type", "markdown") == "csv":
            return [cfg.get("text_column") or "transcript", cfg.get("id_column") or "call_id", "row_json"]
        return ["transcript", "file_name"]
    if node.kind == "constant":
        return [node_config(node).get("socket", node.title.lower().replace(" ", "_"))]
    if node.kind == "prompt":
        return ["full_prompt", "template"]
    if node.kind == "model":
        return ["winner", "reasoning", "raw"] if node_config(node).get("role") == "judge" else ["raw", "json"]
    if node.kind == "judge":
        return ["judge_prompt", "template"]
    return []


def unique_sockets(sockets: list[str]) -> list[str]:
    """Keep socket labels unique while preserving their visible order."""

    seen = set()
    result = []
    for socket in sockets:
        if socket and socket not in seen:
            seen.add(socket)
            result.append(socket)
    return result


def node_sockets(node: GraphNode, *, side: str, edges: list[GraphEdge], configure: bool):
    """Render connectable sockets for configure mode."""

    sockets = input_sockets(node) if side == "input" else output_sockets(node)
    if not configure:
        return ""
    if not sockets:
        return Div(cls=f"node-sockets node-sockets-{side} node-sockets-empty")
    port_cls = "socket-port"
    label_cls = "socket-label"

    def socket_button(socket: str):
        connected = any(
            (side == "input" and edge.to_node_id == node.id and edge.to_socket == socket)
            or (side == "output" and edge.from_node_id == node.id and edge.from_socket == socket)
            for edge in edges
        )
        port = Span(cls=f"{port_cls} {port_cls}-{side}")
        label = Span(socket, cls=label_cls)
        children = [port, label] if side == "input" else [label, port]
        return Button(
            *children,
            type="button",
                title=socket_tooltip(node, side, socket),
            cls=f"socket socket-{side}{' is-connected' if connected else ''}",
            data_socket_side=side,
            data_node_id=str(node.id),
            data_socket_name=socket,
        )

    return Div(
        *[socket_button(socket) for socket in sockets],
        cls=f"node-sockets node-sockets-{side}",
    )


def socket_tooltip(node: GraphNode, side: str, socket: str) -> str:
    """Explain what a graph socket carries."""

    descriptions = {
        "transcript": "Transcript text from the selected dataset item.",
        "file_name": "Markdown file name for the current transcript.",
        "call_id": "Stable item identifier from the dataset.",
        "row_json": "Full CSV row serialized as JSON for advanced prompt inputs.",
        "raw": "Raw model response text from this prompt stage.",
        "json": "JSON-repaired version of the model response.",
        "full_prompt": "The fully rendered prompt sent to the model.",
        "template": "The prompt template before input values are filled.",
        "models": "Connect every generator model output here. The judge will build pairwise A/B comparisons from the connected models.",
        "judge_prompt": "Rendered pairwise judge prompt. Connect this to each judge model you want to vote.",
        "winner": "Judge winner value, usually A, B, or TIE.",
        "reasoning": "Judge explanation for the selected winner.",
        "prompt": "Rendered prompt text to run on this model.",
        "previous_output": "Output from an earlier prompt stage.",
        "input": "Generic input value. Rename this placeholder in the prompt for clarity.",
    }
    return f"{side}: {socket}. {descriptions.get(socket, 'Connect this value to a matching prompt input.')}"


def node_readonly_body(node: GraphNode, cfg: dict):
    """Render a compact read-only node inspection panel."""

    if node.kind == "model":
        details = [
            ("Model", cfg.get("model_id", "No model configured")),
            ("Temp", cfg.get("temperature", "-")),
        ]
        if cfg.get("reasoning_supported"):
            details.append(("Reasoning", cfg.get("reasoning_effort") or "default"))
        return Div(*[node_summary_row(label, value) for label, value in details], cls="node-readonly")
    if node.kind == "dataset":
        return Div(
            node_summary_row("Source", cfg.get("source_type", "markdown")),
            node_summary_row("Path", cfg.get("path", "No dataset path")),
            cls="node-readonly",
        )
    if node.kind in {"prompt", "judge", "constant"}:
        return Div(
            node_summary_row("Template", node.body or "No text configured"),
            cls="node-readonly",
        )
    return Div(node_summary_row("Details", "No details configured."), cls="node-readonly")


def node_summary_row(label: str, value: str):
    """Render a readable preview row inside graph nodes."""

    return Div(Span(label), P(str(value)), cls="node-summary-row")


def node_config_fields(node: GraphNode, cfg: dict):
    """Render config controls appropriate to a node kind."""

    if node.kind == "dataset":
        source_type = cfg.get("source_type", "markdown")
        return [
            Label(
                Span("Source type"),
                Select(
                    selected_option("markdown", "Markdown folder", source_type == "markdown"),
                    selected_option("csv", "CSV file", source_type == "csv"),
                    name="cfg_source_type",
                    data_dataset_source="true",
                ),
                cls="field",
            ),
            input_row("Path", "cfg_path", value=cfg.get("path", ""), placeholder="/path/to/transcripts or calls.csv", help_text="Markdown uses a folder. CSV uses a single file."),
            input_row("Sample size", "cfg_sample_size", value=str(cfg.get("sample_size", "")), placeholder="blank for all", type="number", min="1"),
            Div(
                input_row("ID column", "cfg_id_column", value=cfg.get("id_column", "call_id"), placeholder="call_id", help_text="CSV only. Used as the stable item identifier."),
                input_row("Text column", "cfg_text_column", value=cfg.get("text_column", "transcript"), placeholder="transcript", help_text="CSV only. This column is exposed as transcript text."),
                cls="csv-only-fields",
                hidden=source_type != "csv",
            ),
            Input(type="hidden", name="body", value=node.body),
        ]
    if node.kind == "model":
        reasoning_supported = bool(cfg.get("reasoning_supported", False))
        return [
            input_row("Model ID", "cfg_model_id", value=cfg.get("model_id", ""), placeholder="openai/gpt-4o-mini", help_text="OpenRouter model slug. The same node can serve generator or judge flows depending on what it connects to."),
            input_row("Temperature", "cfg_temperature", value=str(cfg.get("temperature", "0.2")), type="number", step="0.1", min="0", max="2", help_text="Sampling temperature for this model call."),
            input_row("Max tokens", "cfg_max_tokens", value=str(cfg.get("max_tokens", "")), type="number", min="1", help_text="Optional output token cap. Leave blank to use provider defaults."),
            input_row("Retries", "cfg_retry_count", value=str(cfg.get("retry_count", "2")), type="number", min="0", help_text="Retry count for transient API failures."),
            Label(
                Input(type="checkbox", name="cfg_reasoning_supported", value="true", checked=reasoning_supported, data_reasoning_toggle="true"),
                Span("Supports reasoning effort"),
                cls="check",
            ),
            Div(
                Label(
                    help_label("Reasoning effort", "Manual setting for reasoning-capable models. Leave blank to use provider defaults."),
                    Select(
                        selected_option("", "Provider default", not cfg.get("reasoning_effort")),
                        selected_option("low", "Low", cfg.get("reasoning_effort") == "low"),
                        selected_option("medium", "Medium", cfg.get("reasoning_effort") == "medium"),
                        selected_option("high", "High", cfg.get("reasoning_effort") == "high"),
                        name="cfg_reasoning_effort",
                    ),
                    cls="field",
                ),
                cls="reasoning-effort-field",
                hidden=not reasoning_supported,
            ),
            input_row("Input $ / 1M tokens", "cfg_input_price", value=str(cfg.get("input_price", "")), type="number", step="0.000001", min="0", help_text="Manual pricing metadata for estimates."),
            input_row("Output $ / 1M tokens", "cfg_output_price", value=str(cfg.get("output_price", "")), type="number", step="0.000001", min="0", help_text="Manual pricing metadata for estimates."),
            Input(type="hidden", name="cfg_role", value=cfg.get("role", "generator")),
        ]
    if node.kind == "judge":
        return [
            input_row("Pairwise sample %", "cfg_pairing_sample_pct", value=str(cfg.get("pairing_sample_pct", "20")), type="number", min="1", max="100", step="1", help_text="Percent of generator pairings to judge per dataset item."),
            input_row("Seed", "cfg_seed", value=str(cfg.get("seed", "")), placeholder="optional", help_text="Optional deterministic sampling seed."),
            input_row("Winner JSON key", "cfg_winner_key", value=str(cfg.get("winner_key", "")), placeholder="winner", help_text="Judge response field that contains A, B, or TIE."),
            input_row("Reasoning JSON key", "cfg_reasoning_key", value=str(cfg.get("reasoning_key", "")), placeholder="reasoning", help_text="Judge response field that explains the vote."),
            Label(
                Input(type="checkbox", name="cfg_swap_enabled", value="true", checked=bool(cfg.get("swap_enabled", True))),
                Span("Run swapped A/B robustness checks"),
                cls="check",
            ),
        ]
    if node.kind == "prompt":
        return [
            Label(
                help_label("Previous-stage input", "When this prompt follows another prompt, choose whether {{ previous_output }} receives raw text or repaired JSON."),
                Select(
                    selected_option("raw", "Raw text", cfg.get("upstream_mode", "raw") == "raw"),
                    selected_option("json", "Repaired JSON", cfg.get("upstream_mode") == "json"),
                    name="cfg_upstream_mode",
                ),
                cls="field",
            )
        ]
    if node.kind == "constant":
        return [input_row("Output name", "cfg_socket", value=cfg.get("socket", node.title.lower().replace(" ", "_")), help_text="Name of the value this node exposes to prompt inputs.")]
    return []


def graph_edges(plan):
    """Render computed edge counts so users can inspect what will run."""

    return Div(
        edge_count("Dataset -> generator prompt", f"{plan.transcript_count} items"),
        edge_count("Prompt stages -> generator models", f"{plan.generation_calls} calls"),
        edge_count("Generator outputs -> judge", f"{plan.match_count} matches"),
        edge_count("Judge -> judge models", f"{plan.judge_calls} judge calls"),
        cls="edge-counts",
    )


def edge_count(label: str, value: str):
    """Render one planner edge count."""

    return Div(Span(label), Strong(value), cls="edge-count")


def plan_panel(plan):
    """Render the graph planner summary."""

    return Div(
        Div(
            planner_stat("Dataset items", plan.transcript_count),
            planner_stat("Prompt stages", plan.prompt_stage_count),
            planner_stat("Generator models", plan.generator_model_count),
            planner_stat("Judge models", plan.judge_model_count),
            planner_stat("Model pairs", plan.pair_count),
            planner_stat("Sampled pairs / item", plan.sampled_matches_per_transcript),
            planner_stat("Generation calls", plan.generation_calls),
            planner_stat("Matches", plan.match_count),
            planner_stat("Judge calls", plan.judge_calls),
            cls="planner-grid",
        ),
        P("A/B swap is enabled, so judge-call totals include normal and swapped calls.", cls="muted") if plan.swap_multiplier == 2 else P("A/B swap is disabled for this run.", cls="muted"),
        Div(*[P(warning, cls="warning-text") for warning in plan.warnings], cls="warning-list") if plan.warnings else P("Graph is ready to launch.", cls="muted"),
        cls="planner-panel",
    )


def planner_stat(label: str, value: int):
    """Render one planner metric."""

    return Div(Span(label), Strong(f"{value:,}"), cls="planner-stat")


def graph_invocation_card(invocation: GraphInvocation, nodes: dict[int, GraphNode]):
    """Render one graph-native invocation output."""

    prompt = nodes.get(invocation.node_id)
    model = nodes.get(invocation.model_node_id)
    title = f"{prompt.title if prompt else 'Prompt'} · {model.title if model else 'Model'} · {invocation.item_key}"
    output = invocation.output_json or invocation.output_raw or invocation.error or ""
    return Details(
        Summary(
            Span(title),
            status_pill(invocation.status.value),
            Small(f"{invocation.duration_seconds:.1f}s") if invocation.duration_seconds is not None else "",
            Small(f"{invocation.output_tokens_per_second:.1f} tok/s") if invocation.output_tokens_per_second is not None else "",
        ),
        Div(
            H3("Rendered Prompt"),
            Pre(invocation.rendered_prompt),
            H3("Output"),
            Pre(output),
            cls="prompt-body",
        ),
        cls="panel",
        data_details_key=f"graph-invocation-{invocation.id}",
    )


def graph_run_diagnostics(graph_run: GraphRun, progress: dict[str, int]):
    """Render explicit graph-run errors and zero-work explanations."""

    messages = []
    if graph_run.error:
        messages.append(Details(Summary("Run error"), Pre(graph_run.error), open=True, cls="run-error-details"))
    if progress["total"] == 0 and graph_run.status in {Status.failed, Status.complete}:
        messages.append(
            P(
                "No invocation rows were created. This usually means the graph failed preflight: missing dataset items, prompt nodes, or model IDs. The launch POST returning 303 is only the browser redirect to this run page.",
                cls="warning-text",
            )
        )
    return Div(*messages, cls="run-diagnostics") if messages else ""


def graph_node_progress(nodes: list[GraphNode], invocations: list[GraphInvocation]) -> dict[int, dict]:
    """Summarize run progress for each graph node shown in the run preview."""

    progress: dict[int, dict] = {}
    by_prompt: dict[int, list[GraphInvocation]] = {}
    by_model: dict[int, list[GraphInvocation]] = {}
    for invocation in invocations:
        by_prompt.setdefault(invocation.node_id, []).append(invocation)
        if invocation.model_node_id:
            by_model.setdefault(invocation.model_node_id, []).append(invocation)
    for node in nodes:
        rows = by_model.get(node.id, []) if node.kind == "model" else by_prompt.get(node.id, [])
        if not rows:
            continue
        complete = sum(1 for row in rows if row.status == Status.complete)
        running = sum(1 for row in rows if row.status == Status.running)
        failed = sum(1 for row in rows if row.status == Status.failed)
        durations = [row.duration_seconds for row in rows if row.duration_seconds]
        throughputs = [row.output_tokens_per_second for row in rows if row.output_tokens_per_second]
        progress[node.id] = {
            "complete": complete,
            "total": len(rows),
            "running": running,
            "failed": failed,
            "avg_seconds": sum(durations) / len(durations) if durations else None,
            "avg_tps": sum(throughputs) / len(throughputs) if throughputs else None,
        }
    return progress


def node_progress_badge(progress: dict | None):
    """Render compact node-level run progress."""

    if not progress:
        return ""
    status_cls = " is-running" if progress["running"] else " is-failed" if progress["failed"] else " is-complete" if progress["complete"] == progress["total"] else ""
    metrics = []
    if progress.get("avg_seconds") is not None:
        metrics.append(f"{progress['avg_seconds']:.1f}s avg")
    if progress.get("avg_tps") is not None:
        metrics.append(f"{progress['avg_tps']:.1f} tok/s")
    return Span(
        f"{progress['complete']}/{progress['total']}",
        Small(" · ".join(metrics)) if metrics else "",
        cls=f"node-progress{status_cls}",
        title=f"{progress['running']} running, {progress['failed']} failed",
    )


def graph_run_output_browser(invocations: list[GraphInvocation], nodes: dict[int, GraphNode]):
    """Render nested model and invocation output details."""

    by_role: dict[str, dict[int, list[GraphInvocation]]] = {"Generator models": {}, "Judge models": {}}
    for invocation in invocations:
        model = nodes.get(invocation.model_node_id)
        if not model:
            continue
        role = node_config(model).get("role", "generator")
        label = "Judge models" if role == "judge" else "Generator models"
        by_role[label].setdefault(model.id, []).append(invocation)
    groups = []
    for label, model_rows in by_role.items():
        if not model_rows:
            continue
        groups.append(
            Details(
                Summary(label),
                *[
                    model_output_group(nodes[model_id], rows, nodes)
                    for model_id, rows in sorted(model_rows.items(), key=lambda item: nodes[item[0]].title)
                ],
                cls="panel output-browser-group",
            )
        )
    return Div(*groups or [P("No model outputs yet.", cls="muted")], cls="output-browser")


def model_output_group(model: GraphNode, invocations: list[GraphInvocation], nodes: dict[int, GraphNode]):
    """Render one model's invocation outputs."""

    complete = [row for row in invocations if row.status == Status.complete]
    avg_seconds = sum(row.duration_seconds or 0 for row in complete) / len(complete) if complete else None
    avg_tps = sum(row.output_tokens_per_second or 0 for row in complete if row.output_tokens_per_second) / len([row for row in complete if row.output_tokens_per_second]) if any(row.output_tokens_per_second for row in complete) else None
    return Details(
        Summary(
            Span(model.title),
            Small(f"{len(complete)}/{len(invocations)} complete"),
            Small(f"{avg_seconds:.1f}s avg") if avg_seconds is not None else "",
            Small(f"{avg_tps:.1f} tok/s") if avg_tps is not None else "",
        ),
        *[graph_invocation_card(invocation, nodes) for invocation in invocations],
        cls="output-model-group",
        data_details_key=f"graph-model-output-{model.id}",
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


def run_action_button(run: GraphRun, label: str, action: str, *, subtle: bool = False):
    """Render a one-click action form for run controls."""

    return Form(
        Button(label, type="submit", cls="button subtle" if subtle else None),
        action=action,
        method="post",
        cls="inline-form",
    )


def graph_judge_favorite_badges(favorites: list[GraphNode]):
    """Render badges that show which judge models favored a generator model."""

    if not favorites:
        return Span("None yet", cls="muted")
    return Span(
        *[
            Span(
                node_config(judge).get("model_id", judge.title),
                title="Favored this model",
                cls="judge-fav",
            )
            for judge in favorites
        ],
        cls="judge-favs",
    )


















def vote_summary(votes_json: str) -> str:
    """Summarize raw vote JSON for table display."""

    try:
        votes = json.loads(votes_json)
    except Exception:
        return "-"
    return " / ".join(f"{label}:{votes.count(label)}" for label in ("A", "B", "TIE") if votes.count(label))


if __name__ == "__main__":
    serve(host="127.0.0.1", port=5001)
