"""Node graph drafts and planning helpers."""

from __future__ import annotations

import itertools
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from council.files import list_markdown_files, read_text_snapshot
from council.models import (
    EloRating,
    ExperimentGraph,
    GraphEdge,
    Generation,
    GeneratorConfig,
    GraphNode,
    GraphInvocation,
    GraphRun,
    GraphStatus,
    JudgeConfig,
    Project,
    Run,
    Task,
    Transcript,
    utc_now,
)
from council.run_rows import ensure_elo_rows, ensure_generation_rows, ensure_match_rows

PROMPT_INPUT_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


@dataclass(frozen=True)
class GraphPlan:
    """Computed work plan shown before a graph is launched."""

    transcript_count: int
    prompt_stage_count: int
    generator_model_count: int
    judge_model_count: int
    pair_count: int
    sampled_matches_per_transcript: int
    generation_calls: int
    match_count: int
    judge_calls: int
    swap_multiplier: int
    warnings: tuple[str, ...]


def config(node: GraphNode) -> dict:
    """Read a node config payload without leaking JSON handling to routes."""

    try:
        return json.loads(node.config_json or "{}")
    except json.JSONDecodeError:
        return {}


def dump_config(values: dict) -> str:
    """Serialize node config in one stable shape."""

    return json.dumps(values, sort_keys=True)


def prompt_inputs(template: str) -> list[str]:
    """Return unique template sockets in first-seen order."""

    seen = set()
    inputs = []
    for match in PROMPT_INPUT_RE.finditer(template):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            inputs.append(key)
    return inputs


def create_graph(session: Session, project_id: int, name: str) -> ExperimentGraph:
    """Create an empty draft graph."""

    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} does not exist")
    graph = ExperimentGraph(project_id=project_id, name=name.strip() or "Untitled graph")
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph


def rename_graph(session: Session, graph_id: int, name: str) -> ExperimentGraph | None:
    """Rename a graph draft or completed graph."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        return None
    cleaned = name.strip()
    if cleaned:
        graph.name = cleaned
        graph.updated_at = utc_now()
        session.add(graph)
        session.commit()
        session.refresh(graph)
    return graph


def delete_graph(session: Session, graph_id: int) -> None:
    """Delete only the graph draft/configuration record."""

    graph_run_ids = list(session.exec(select(GraphRun.id).where(GraphRun.graph_id == graph_id)).all())
    for graph_run_id in graph_run_ids:
        for invocation in session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id)).all():
            session.delete(invocation)
        graph_run = session.get(GraphRun, graph_run_id)
        if graph_run:
            session.delete(graph_run)
    for edge in session.exec(select(GraphEdge).where(GraphEdge.graph_id == graph_id)).all():
        session.delete(edge)
    nodes = session.exec(select(GraphNode).where(GraphNode.graph_id == graph_id)).all()
    for node in nodes:
        session.delete(node)
    graph = session.get(ExperimentGraph, graph_id)
    if graph:
        session.delete(graph)
    session.commit()


def fork_graph(session: Session, graph_id: int, name: str | None = None) -> ExperimentGraph:
    """Create an editable draft copy of an existing graph."""

    source = session.get(ExperimentGraph, graph_id)
    if not source:
        raise ValueError(f"Graph {graph_id} does not exist")
    fork = ExperimentGraph(
        project_id=source.project_id,
        name=(name or f"{source.name} draft").strip(),
        status=GraphStatus.draft,
    )
    session.add(fork)
    session.commit()
    session.refresh(fork)
    node_id_map: dict[int, int] = {}
    for node in session.exec(select(GraphNode).where(GraphNode.graph_id == graph_id)).all():
        copied = GraphNode(
            graph_id=fork.id,
            kind=node.kind,
            title=node.title,
            body=node.body,
            config_json=node.config_json,
            x=node.x,
            y=node.y,
            width=node.width,
            height=node.height,
        )
        session.add(copied)
        session.commit()
        session.refresh(copied)
        if node.id and copied.id:
            node_id_map[node.id] = copied.id
    for edge in session.exec(select(GraphEdge).where(GraphEdge.graph_id == graph_id)).all():
        if edge.from_node_id in node_id_map and edge.to_node_id in node_id_map:
            session.add(
                GraphEdge(
                    graph_id=fork.id,
                    from_node_id=node_id_map[edge.from_node_id],
                    from_socket=edge.from_socket,
                    to_node_id=node_id_map[edge.to_node_id],
                    to_socket=edge.to_socket,
                )
            )
    session.commit()
    session.refresh(fork)
    return fork


def graph_nodes(session: Session, graph_id: int) -> list[GraphNode]:
    """Return graph nodes in display order."""

    return session.exec(select(GraphNode).where(GraphNode.graph_id == graph_id).order_by(GraphNode.x, GraphNode.id)).all()


def graph_edges(session: Session, graph_id: int) -> list[GraphEdge]:
    """Return persisted graph socket connections."""

    return session.exec(select(GraphEdge).where(GraphEdge.graph_id == graph_id).order_by(GraphEdge.id)).all()


def create_edge(session: Session, graph_id: int, *, from_node_id: int, from_socket: str, to_node_id: int, to_socket: str) -> GraphEdge:
    """Connect one output socket to one input socket."""

    if from_node_id == to_node_id:
        raise ValueError("Cannot connect a node to itself")
    existing = session.exec(
        select(GraphEdge).where(
            GraphEdge.graph_id == graph_id,
            GraphEdge.from_node_id == from_node_id,
            GraphEdge.from_socket == from_socket,
            GraphEdge.to_node_id == to_node_id,
            GraphEdge.to_socket == to_socket,
        )
    ).first()
    if existing:
        return existing
    edge = GraphEdge(
        graph_id=graph_id,
        from_node_id=from_node_id,
        from_socket=from_socket,
        to_node_id=to_node_id,
        to_socket=to_socket,
    )
    session.add(edge)
    _touch_graph(session, graph_id)
    session.commit()
    session.refresh(edge)
    return edge


def delete_edge(session: Session, edge_id: int) -> int | None:
    """Delete one graph connection and return its graph id."""

    edge = session.get(GraphEdge, edge_id)
    if not edge:
        return None
    graph_id = edge.graph_id
    session.delete(edge)
    _touch_graph(session, graph_id)
    session.commit()
    return graph_id


def delete_socket_edges(session: Session, graph_id: int, *, node_id: int, socket: str, side: str) -> None:
    """Delete every connection attached to one node socket."""

    if side == "input":
        query = select(GraphEdge).where(
            GraphEdge.graph_id == graph_id,
            GraphEdge.to_node_id == node_id,
            GraphEdge.to_socket == socket,
        )
    elif side == "output":
        query = select(GraphEdge).where(
            GraphEdge.graph_id == graph_id,
            GraphEdge.from_node_id == node_id,
            GraphEdge.from_socket == socket,
        )
    else:
        return
    for edge in session.exec(query).all():
        session.delete(edge)
    _touch_graph(session, graph_id)
    session.commit()


def delete_node(session: Session, node_id: int) -> int | None:
    """Delete a node and any edges connected to it, returning its graph id."""

    node = session.get(GraphNode, node_id)
    if not node:
        return None
    graph_id = node.graph_id
    for edge in session.exec(
        select(GraphEdge).where(
            (GraphEdge.from_node_id == node_id) | (GraphEdge.to_node_id == node_id)
        )
    ).all():
        session.delete(edge)
    session.delete(node)
    _touch_graph(session, graph_id)
    session.commit()
    return graph_id


def update_node(session: Session, node_id: int, *, title: str, body: str, config_values: dict) -> GraphNode:
    """Persist one edited node after the user clicks done."""

    node = session.get(GraphNode, node_id)
    if not node:
        raise ValueError(f"Node {node_id} does not exist")
    node.title = title.strip() or node.title
    node.body = body
    node.config_json = dump_config(config_values)
    node.updated_at = utc_now()
    session.add(node)
    graph = session.get(ExperimentGraph, node.graph_id)
    if graph:
        graph.updated_at = utc_now()
        graph.status = GraphStatus.draft if graph.status == GraphStatus.complete else graph.status
        session.add(graph)
    session.commit()
    session.refresh(node)
    return node


def add_model_node(session: Session, graph_id: int, *, title: str, model_id: str, role: str, x: int | None = None, y: int | None = None) -> GraphNode:
    """Add a reusable model config node."""

    count = len([n for n in graph_nodes(session, graph_id) if n.kind == "model"])
    node = GraphNode(
        graph_id=graph_id,
        kind="model",
        title=title.strip() or model_id.strip() or "Model",
        config_json=dump_config(
            {
                "model_id": model_id.strip(),
                "temperature": 0.2 if role == "generator" else 0.0,
                "max_tokens": "",
                "retry_count": 2,
                "reasoning_supported": False,
                "reasoning_effort": "",
                "input_price": "",
                "output_price": "",
                "role": role,
            }
        ),
        x=x if x is not None else (620 if role == "generator" else 1220),
        y=y if y is not None else 24 + count * 96,
    )
    session.add(node)
    _touch_graph(session, graph_id)
    session.commit()
    session.refresh(node)
    return node


def add_constant_node(session: Session, graph_id: int, *, title: str, body: str, x: int | None = None, y: int | None = None) -> GraphNode:
    """Add a text node that can fill prompt sockets."""

    node = GraphNode(graph_id=graph_id, kind="constant", title=title.strip() or "Constant", body=body, x=x if x is not None else 24, y=y if y is not None else 260)
    session.add(node)
    _touch_graph(session, graph_id)
    session.commit()
    session.refresh(node)
    return node


def add_prompt_node(session: Session, graph_id: int, *, title: str = "Next prompt", x: int | None = None, y: int | None = None) -> GraphNode:
    """Add another prompt stage for chained graph flows."""

    prompts = [node for node in graph_nodes(session, graph_id) if node.kind == "prompt"]
    node = GraphNode(
        graph_id=graph_id,
        kind="prompt",
        title=title,
        body="## Input\n{{ transcript }}\n\n## Previous output\n{{ previous_output }}",
        config_json=dump_config({"upstream_mode": "raw"}),
        x=x if x is not None else 320 + len(prompts) * 300,
        y=y if y is not None else 160,
    )
    session.add(node)
    _touch_graph(session, graph_id)
    session.commit()
    session.refresh(node)
    return node


def add_judge_node(session: Session, graph_id: int, *, title: str = "Pairwise judge prompt", x: int | None = None, y: int | None = None) -> GraphNode:
    """Add a judge prompt node with explicit winner/reasoning output config."""

    node = GraphNode(
        graph_id=graph_id,
        kind="judge",
        title=title,
        body="## Task\n{{ task_description }}\n\n## Transcript\n{{ transcript }}\n\n## Output A\n{{ output_a }}\n\n## Output B\n{{ output_b }}\n\nReturn JSON with `reasoning` and `winner` as A, B, or TIE.",
        config_json=dump_config({"pairing_sample_pct": 20, "swap_enabled": True, "seed": "", "winner_key": "winner", "reasoning_key": "reasoning"}),
        x=x if x is not None else 920,
        y=y if y is not None else 24,
    )
    session.add(node)
    _touch_graph(session, graph_id)
    session.commit()
    session.refresh(node)
    return node


def add_dataset_node(session: Session, graph_id: int, *, x: int | None = None, y: int | None = None) -> GraphNode:
    """Add a dataset node from the configure palette."""

    node = GraphNode(
        graph_id=graph_id,
        kind="dataset",
        title="Dataset",
        config_json=dump_config({"source_type": "markdown", "path": str(Path("transcripts").resolve()), "sample_size": "", "id_column": "call_id", "text_column": "transcript"}),
        x=x if x is not None else 24,
        y=y if y is not None else 24,
    )
    session.add(node)
    _touch_graph(session, graph_id)
    session.commit()
    session.refresh(node)
    return node


def update_node_position(session: Session, node_id: int, *, x: int, y: int, width: int | None = None, height: int | None = None) -> GraphNode:
    """Persist canvas geometry after a node is moved or resized."""

    node = session.get(GraphNode, node_id)
    if not node:
        raise ValueError(f"Node {node_id} does not exist")
    node.x = x
    node.y = y
    if width is not None:
        node.width = max(300, min(1100, width))
    if height is not None:
        node.height = max(160, min(1000, height))
    node.updated_at = utc_now()
    session.add(node)
    _touch_graph(session, node.graph_id)
    session.commit()
    session.refresh(node)
    return node


def plan_graph(session: Session, graph_id: int) -> GraphPlan:
    """Calculate call counts and validation warnings for the visible graph."""

    nodes = graph_nodes(session, graph_id)
    dataset = _one(nodes, "dataset")
    prompt_stages = _prompt_stages(nodes)
    generator_prompt = prompt_stages[0] if prompt_stages else None
    judge_prompt = _one(nodes, "judge")
    generator_models = _models(nodes, "generator")
    judge_models = _models(nodes, "judge")
    settings = config(judge_prompt) if judge_prompt else {}
    transcript_count = _transcript_count(dataset)
    pair_count = math.comb(len(generator_models), 2) if len(generator_models) >= 2 else 0
    sample_pct = _sample_pct(settings)
    sampled_per_transcript = _sampled_pair_count(pair_count, sample_pct)
    generation_calls = transcript_count * len(generator_models) * max(1, len(prompt_stages))
    match_count = transcript_count * sampled_per_transcript
    swap_multiplier = 2 if settings.get("swap_enabled", True) else 1
    judge_calls = match_count * len(judge_models) * swap_multiplier
    warnings = list(_plan_warnings(dataset, generator_prompt, judge_prompt, generator_models, judge_models, transcript_count))
    if pair_count and sampled_per_transcript < pair_count and transcript_count * sampled_per_transcript < pair_count:
        warnings.append("Sampling is too low to cover every model pair at least once.")
    return GraphPlan(
        transcript_count=transcript_count,
        prompt_stage_count=len(prompt_stages),
        generator_model_count=len(generator_models),
        judge_model_count=len(judge_models),
        pair_count=pair_count,
        sampled_matches_per_transcript=sampled_per_transcript,
        generation_calls=generation_calls,
        match_count=match_count,
        judge_calls=judge_calls,
        swap_multiplier=swap_multiplier,
        warnings=tuple(warnings),
    )


def launch_graph_run(session: Session, graph_id: int, *, max_concurrency: int = 5) -> Run:
    """Compile a graph draft into the current auditable run tables."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        raise ValueError(f"Graph {graph_id} does not exist")
    nodes = graph_nodes(session, graph_id)
    dataset = _require_one(nodes, "dataset")
    prompt_stages = _prompt_stages(nodes)
    generator_prompt = prompt_stages[0] if prompt_stages else None
    if not generator_prompt:
        raise ValueError("Graph needs a prompt node")
    judge_prompt = _require_one(nodes, "judge")
    generator_models = _models(nodes, "generator")
    judge_models = _models(nodes, "judge")
    if len(generator_models) < 2:
        raise ValueError("At least two generator model nodes are required")
    if not judge_models:
        raise ValueError("At least one judge model node is required")

    dataset_cfg = config(dataset)
    judge_cfg = config(judge_prompt)
    if dataset_cfg.get("source_type", "markdown") != "markdown":
        raise ValueError("Compiled ELO runs currently support markdown-folder datasets only")
    paths = list_markdown_files(dataset_cfg.get("path", ""))
    sample_size = int(dataset_cfg.get("sample_size") or 0)
    if sample_size:
        paths = paths[:sample_size]
    if not paths:
        raise ValueError("No transcript markdown files selected")
    task_description = _task_description(nodes)
    task = Task(
        project_id=graph.project_id,
        name=f"{graph.name} task snapshot",
        description_path=f"graph://{graph.id}/task_description",
        description_snapshot=task_description,
        description_hash=f"graph-{graph.id}-{len(task_description)}",
        transcript_root=dataset_cfg.get("path", ""),
        default_judge_prompt_path=f"graph://node/{judge_prompt.id}",
        default_pairing_sample_pct=_sample_pct(judge_cfg),
        default_swap_enabled=bool(judge_cfg.get("swap_enabled", True)),
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    run = Run(
        task_id=task.id,
        name=graph.name,
        max_concurrency=max_concurrency,
        pairing_sample_pct=_sample_pct(judge_cfg),
        swap_enabled=bool(judge_cfg.get("swap_enabled", True)),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    for model in generator_models:
        model_cfg = config(model)
        session.add(
            GeneratorConfig(
                run_id=run.id,
                label=model.title,
                model_id=model_cfg.get("model_id", "").strip(),
                temperature=float(model_cfg.get("temperature") or 0.0),
                prompt_path=f"graph://node/{generator_prompt.id}",
                prompt_snapshot=generator_prompt.body,
                prompt_hash=f"graph-node-{generator_prompt.id}-{len(generator_prompt.body)}",
            )
        )
    for model in judge_models:
        model_cfg = config(model)
        session.add(
            JudgeConfig(
                run_id=run.id,
                label=model.title,
                model_id=model_cfg.get("model_id", "").strip(),
                temperature=float(model_cfg.get("temperature") or 0.0),
                prompt_path=f"graph://node/{judge_prompt.id}",
                prompt_snapshot=judge_prompt.body,
                prompt_hash=f"graph-node-{judge_prompt.id}-{len(judge_prompt.body)}",
            )
        )

    for path in paths:
        snapshot = read_text_snapshot(path)
        session.add(Transcript(run_id=run.id, path=snapshot.path, content_snapshot=snapshot.content, content_hash=snapshot.content_hash))
    session.commit()
    ensure_generation_rows(session, run.id)
    ensure_match_rows(session, run.id)
    ensure_elo_rows(session, run.id)

    graph.status = GraphStatus.running
    graph.last_run_id = run.id
    graph.updated_at = utc_now()
    session.add(graph)
    session.commit()
    session.refresh(run)
    return run


def sync_graph_status(session: Session, graph: ExperimentGraph) -> ExperimentGraph:
    """Mirror the latest run status onto graph cards."""

    if graph.last_run_id:
        run = session.get(Run, graph.last_run_id)
        if run and run.status.value in {status.value for status in GraphStatus}:
            graph.status = GraphStatus(run.status.value)
            session.add(graph)
            session.commit()
            session.refresh(graph)
    return graph


def _touch_graph(session: Session, graph_id: int) -> None:
    graph = session.get(ExperimentGraph, graph_id)
    if graph:
        graph.updated_at = utc_now()
        session.add(graph)


def _one(nodes: list[GraphNode], kind: str) -> GraphNode | None:
    return next((node for node in nodes if node.kind == kind), None)


def _require_one(nodes: list[GraphNode], kind: str) -> GraphNode:
    node = _one(nodes, kind)
    if not node:
        raise ValueError(f"Graph needs a {kind} node")
    return node


def _models(nodes: list[GraphNode], role: str) -> list[GraphNode]:
    return [node for node in nodes if node.kind == "model" and config(node).get("role") == role and config(node).get("model_id", "").strip()]


def _prompt_stages(nodes: list[GraphNode]) -> list[GraphNode]:
    return sorted([node for node in nodes if node.kind == "prompt"], key=lambda node: (node.x, node.y, node.id or 0))


def _transcript_count(dataset: GraphNode | None) -> int:
    if not dataset:
        return 0
    cfg = config(dataset)
    if cfg.get("source_type", "markdown") == "csv":
        rows = _csv_rows(cfg.get("path", ""), cfg.get("sample_size", ""))
        return len(rows)
    paths = list_markdown_files(cfg.get("path", ""))
    sample_size = int(cfg.get("sample_size") or 0)
    if sample_size:
        paths = paths[:sample_size]
    return len(paths)


def _sample_pct(settings: dict) -> float:
    try:
        return max(1.0, min(100.0, float(settings.get("pairing_sample_pct") or 100)))
    except (TypeError, ValueError):
        return 100.0


def _sampled_pair_count(pair_count: int, sample_pct: float) -> int:
    if pair_count == 0:
        return 0
    if sample_pct >= 100:
        return pair_count
    return max(1, round(pair_count * (sample_pct / 100.0)))


def _plan_warnings(
    dataset: GraphNode | None,
    generator_prompt: GraphNode | None,
    judge_prompt: GraphNode | None,
    generator_models: list[GraphNode],
    judge_models: list[GraphNode],
    transcript_count: int,
):
    if not dataset:
        yield "Add a dataset node."
    elif transcript_count == 0:
        yield "Dataset has no selected markdown transcripts."
    elif config(dataset).get("source_type", "markdown") == "csv":
        yield "CSV datasets can run with chained graph launch; ELO launch currently expects a markdown folder."
    if not generator_prompt:
        yield "Add a generator prompt node."
    if not judge_prompt:
        yield "Add a judge prompt node."
    elif not config(judge_prompt).get("winner_key") or not config(judge_prompt).get("reasoning_key"):
        yield "Judge output is not configured. Set winner and reasoning keys before launching ELO judging."
    if len(generator_models) < 2:
        yield "Add at least two generator model nodes."
    if not judge_models:
        yield "Add at least one judge model node."


def _task_description(nodes: list[GraphNode]) -> str:
    task_node = next((node for node in nodes if node.kind == "constant" and config(node).get("socket") == "task_description"), None)
    return task_node.body if task_node else ""


def _csv_rows(path: str, sample_size: str | int | None = None) -> list[dict[str, str]]:
    if not path:
        return []
    csv_path = Path(path).expanduser()
    if not csv_path.exists() or not csv_path.is_file():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    limit = int(sample_size or 0)
    return rows[:limit] if limit else rows
