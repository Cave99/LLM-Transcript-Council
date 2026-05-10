"""Graph-native execution for chained prompt stages."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import select

from council.elo import update_elo
from council.graphs import config, graph_edges, graph_nodes, prompt_inputs
from council.judge import render_template
from council.json_tools import maybe_repair_json
from council.models import ExperimentGraph, GraphEdge, GraphInvocation, GraphNode, GraphRun, GraphStatus, Status, utc_now
from council.openrouter import OpenRouterClient


@dataclass(frozen=True)
class DatasetItem:
    """One dataset row normalized for graph prompt rendering."""

    key: str
    values: dict[str, str]


@dataclass(frozen=True)
class RuntimeNode:
    """Detached graph node data safe to use outside a database session."""

    id: int
    kind: str
    title: str
    body: str
    config_json: str
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class RuntimeEdge:
    """Detached graph edge data safe to use outside a database session."""

    from_node_id: int
    from_socket: str
    to_node_id: int
    to_socket: str


def create_graph_native_run(session, graph_id: int, *, max_concurrency: int = 5, sample_size: int | None = None) -> GraphRun:
    """Create a resumable graph-native run for chained prompt stages."""

    graph = session.get(ExperimentGraph, graph_id)
    if not graph:
        raise ValueError(f"Graph {graph_id} does not exist")
    run_name = f"{graph.name} test run" if sample_size == 1 else graph.name
    run = GraphRun(graph_id=graph_id, name=run_name, max_concurrency=max_concurrency, sample_size=sample_size)
    session.add(run)
    graph.status = GraphStatus.running
    session.add(graph)
    session.commit()
    session.refresh(run)
    return run


def stop_graph_native_run(session, graph_run_id: int) -> GraphRun:
    """Pause a graph-native run so no new chained calls are scheduled."""

    run = session.get(GraphRun, graph_run_id)
    if not run:
        raise ValueError(f"Graph run {graph_run_id} does not exist")
    run.status = Status.paused
    session.add(run)
    _sync_graph_status(session, run)
    session.commit()
    session.refresh(run)
    return run


async def execute_graph_native_run(graph_run_id: int, session_factory, client: OpenRouterClient | None = None) -> None:
    """Run chained prompt stages over each dataset item and model node."""

    client = client or OpenRouterClient()
    if not client.api_key:
        with session_factory() as session:
            run = session.get(GraphRun, graph_run_id)
            if run:
                run.status = Status.failed
                run.error = "OPENROUTER_API_KEY is not set"
                session.add(run)
                _sync_graph_status(session, run)
                session.commit()
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    with session_factory() as session:
        run = session.get(GraphRun, graph_run_id)
        run.status = Status.running
        run.started_at = run.started_at or utc_now()
        session.add(run)
        session.commit()
        max_concurrency = run.max_concurrency
        nodes = [_runtime_node(node) for node in graph_nodes(session, run.graph_id)]
        edges = [_runtime_edge(edge) for edge in graph_edges(session, run.graph_id)]
        items = dataset_items(nodes)
        if run.sample_size:
            items = items[: run.sample_size]
        prompt_stages = sorted([node for node in nodes if node.kind == "prompt"], key=lambda node: (node.x, node.y, node.id or 0))
        judge_prompts = sorted([node for node in nodes if node.kind == "judge"], key=lambda node: (node.x, node.y, node.id or 0))
        model_nodes = [node for node in nodes if node.kind == "model" and config(node).get("role") == "generator" and config(node).get("model_id", "").strip()]
        judge_models = [node for node in nodes if node.kind == "model" and config(node).get("role") == "judge" and config(node).get("model_id", "").strip()]
        constants = {config(node).get("socket", node.title): node.body for node in nodes if node.kind == "constant"}
        preflight_error = _graph_preflight_error(items, prompt_stages, model_nodes, judge_prompts, judge_models)
        if preflight_error:
            run.status = Status.failed
            run.error = preflight_error
            run.completed_at = utc_now()
            session.add(run)
            _sync_graph_status(session, run)
            session.commit()
            return

    semaphore = asyncio.Semaphore(max_concurrency)
    previous: dict[tuple[str, int], str] = {}
    for stage_index, prompt in enumerate(prompt_stages):
        with session_factory() as session:
            run = session.get(GraphRun, graph_run_id)
            if run and run.status == Status.paused:
                _sync_graph_status(session, run)
                session.commit()
                return
        tasks = []
        for item in items:
            for model in model_nodes:
                tasks.append(
                    _run_invocation(
                        graph_run_id,
                        stage_index,
                        prompt,
                        model,
                        item,
                        constants,
                        nodes,
                        edges,
                        previous.get((item.key, model.id), ""),
                        session_factory,
                        client,
                        semaphore,
                    )
                )
        results = await asyncio.gather(*tasks)
        previous = {(item_key, model_id): output for item_key, model_id, output in results}

    for judge_prompt in judge_prompts:
        tasks = []
        for item in items:
            model_pairs = [(a, b) for index, a in enumerate(model_nodes) for b in model_nodes[index + 1 :]]
            for model_a, model_b in model_pairs:
                output_a = previous.get((item.key, model_a.id), "")
                output_b = previous.get((item.key, model_b.id), "")
                if not output_a or not output_b:
                    continue
                for judge_model in judge_models:
                    tasks.append(
                        _run_judge_invocation(
                            graph_run_id,
                            judge_prompt,
                            judge_model,
                            item,
                            constants,
                            nodes,
                            edges,
                            model_a,
                            model_b,
                            output_a,
                            output_b,
                            session_factory,
                            client,
                            semaphore,
                        )
                    )
        if tasks:
            await asyncio.gather(*tasks)

    with session_factory() as session:
        run = session.get(GraphRun, graph_run_id)
        if run and run.status != Status.paused:
            run.status = Status.complete
            run.completed_at = utc_now()
            session.add(run)
            _sync_graph_status(session, run)
            session.commit()


def dataset_items(nodes: list[GraphNode | RuntimeNode]) -> list[DatasetItem]:
    """Load markdown or CSV dataset items for graph-native execution."""

    dataset = next((node for node in nodes if node.kind == "dataset"), None)
    if not dataset:
        return []
    cfg = config(dataset)
    if cfg.get("source_type", "markdown") == "csv":
        return _csv_items(cfg)
    return _markdown_items(cfg)


def graph_native_progress(session, graph_run_id: int) -> dict[str, int]:
    """Count graph-native invocations for progress displays."""

    rows = session.exec(select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id)).all()
    return {
        "total": len(rows),
        "pending": sum(1 for row in rows if row.status == Status.pending),
        "running": sum(1 for row in rows if row.status == Status.running),
        "complete": sum(1 for row in rows if row.status == Status.complete),
        "failed": sum(1 for row in rows if row.status == Status.failed),
    }


def _render_values_for_node(
    target: RuntimeNode,
    item: DatasetItem,
    constants: dict[str, str],
    nodes: list[RuntimeNode],
    edges: list[RuntimeEdge],
    *,
    previous_output: str = "",
) -> dict[str, str]:
    """Build prompt values from actual graph edges, then fall back to common names."""

    by_id = {node.id: node for node in nodes}
    values = {
        **item.values,
        **constants,
        "input": item.values.get("transcript", ""),
        "previous_output": previous_output,
    }
    for edge in edges:
        if edge.to_node_id != target.id:
            continue
        source = by_id.get(edge.from_node_id)
        if not source:
            continue
        edge_value = _edge_value(source, edge.from_socket, item, constants, previous_output)
        if edge_value is not None:
            values[edge.to_socket] = edge_value
    return values


def _edge_value(source: RuntimeNode, socket: str, item: DatasetItem, constants: dict[str, str], previous_output: str) -> str | None:
    """Resolve the value carried by one incoming edge."""

    if source.kind == "constant":
        return source.body
    if source.kind == "dataset":
        if socket in item.values:
            return item.values[socket]
        if socket == "row_json":
            import json

            return json.dumps(item.values, sort_keys=True)
        return None
    if source.kind == "prompt":
        if socket in {"full_prompt", "template"}:
            return source.body
        return previous_output
    return constants.get(socket)


def _runtime_node(node: GraphNode) -> RuntimeNode:
    """Copy graph node fields before the SQLModel session expires them."""

    return RuntimeNode(
        id=node.id,
        kind=node.kind,
        title=node.title,
        body=node.body,
        config_json=node.config_json,
        x=node.x,
        y=node.y,
    )


def _runtime_edge(edge: GraphEdge) -> RuntimeEdge:
    """Copy graph edge fields before the SQLModel session expires them."""

    return RuntimeEdge(
        from_node_id=edge.from_node_id,
        from_socket=edge.from_socket,
        to_node_id=edge.to_node_id,
        to_socket=edge.to_socket,
    )


def _graph_preflight_error(
    items: list[DatasetItem],
    prompt_stages: list[RuntimeNode],
    model_nodes: list[RuntimeNode],
    judge_prompts: list[RuntimeNode],
    judge_models: list[RuntimeNode],
) -> str | None:
    """Explain why a graph run would create zero invocation rows."""

    if not items:
        return "No dataset items were selected. Check the dataset node path, source type, and sample size."
    if not prompt_stages:
        return "No prompt nodes are configured, so there is nothing to run."
    if not model_nodes:
        return "No generator model nodes have a model ID configured."
    if judge_prompts and not judge_models:
        return "A judge prompt exists, but no judge model nodes have a model ID configured."
    return None


async def _run_invocation(
    graph_run_id: int,
    stage_index: int,
    prompt: GraphNode,
    model: GraphNode,
    item: DatasetItem,
    constants: dict[str, str],
    nodes: list[RuntimeNode],
    edges: list[RuntimeEdge],
    previous_output: str,
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> tuple[str, int, str]:
    model_cfg = config(model)
    prompt_cfg = config(prompt)
    values = _render_values_for_node(prompt, item, constants, nodes, edges, previous_output=previous_output)
    rendered = render_template(prompt.body, values)
    unresolved = prompt_inputs(rendered)
    with session_factory() as session:
        run = session.get(GraphRun, graph_run_id)
        if run and run.status == Status.paused:
            return item.key, model.id, ""
        existing = session.exec(
            select(GraphInvocation).where(
                GraphInvocation.graph_run_id == graph_run_id,
                GraphInvocation.node_id == prompt.id,
                GraphInvocation.model_node_id == model.id,
                GraphInvocation.item_key == item.key,
                GraphInvocation.stage_index == stage_index,
            )
        ).first()
        if existing and existing.status == Status.complete:
            output = existing.output_json if prompt_cfg.get("upstream_mode") == "json" else existing.output_raw
            return item.key, model.id, output or ""
        invocation = existing or GraphInvocation(
            graph_run_id=graph_run_id,
            node_id=prompt.id,
            model_node_id=model.id,
            item_key=item.key,
            stage_index=stage_index,
        )
        invocation.status = Status.running
        invocation.rendered_prompt = rendered
        if unresolved:
            invocation.status = Status.failed
            invocation.error = f"Unresolved prompt inputs after edge rendering: {', '.join(unresolved)}"
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
            return item.key, model.id, ""
        invocation.started_at = utc_now()
        invocation.error = None
        session.add(invocation)
        session.commit()
        invocation_id = invocation.id

    try:
        async with semaphore:
            call_started = time.perf_counter()
            response = await client.chat(
                model=model_cfg.get("model_id", ""),
                temperature=float(model_cfg.get("temperature") or 0.0),
                reasoning_effort=model_cfg.get("reasoning_effort") if model_cfg.get("reasoning_supported") else None,
                retries=int(model_cfg.get("retry_count") or 2),
                messages=[{"role": "user", "content": rendered}],
            )
            duration = max(time.perf_counter() - call_started, 0.001)
        repaired = maybe_repair_json(response.text)
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.complete
            invocation.output_raw = response.text
            invocation.output_json = repaired
            invocation.prompt_tokens = response.prompt_tokens
            invocation.completion_tokens = response.completion_tokens
            invocation.duration_seconds = duration
            invocation.output_tokens_per_second = (response.completion_tokens or 0) / duration if response.completion_tokens else None
            invocation.cost = response.cost
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
        return item.key, model.id, repaired if prompt_cfg.get("upstream_mode") == "json" else response.text
    except Exception as exc:
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.failed
            invocation.error = str(exc)
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
        return item.key, model.id, ""


async def _run_judge_invocation(
    graph_run_id: int,
    judge_prompt: GraphNode,
    judge_model: GraphNode,
    item: DatasetItem,
    constants: dict[str, str],
    nodes: list[RuntimeNode],
    edges: list[RuntimeEdge],
    model_a: GraphNode,
    model_b: GraphNode,
    output_a: str,
    output_b: str,
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> None:
    model_cfg = config(judge_model)
    values = {
        **_render_values_for_node(judge_prompt, item, constants, nodes, edges),
        "output_a": output_a,
        "output_b": output_b,
        "model_a": model_a.title,
        "model_b": model_b.title,
    }
    rendered = render_template(judge_prompt.body, values)
    unresolved = prompt_inputs(rendered)
    item_key = f"{item.key}:{model_a.id}-vs-{model_b.id}"
    with session_factory() as session:
        existing = session.exec(
            select(GraphInvocation).where(
                GraphInvocation.graph_run_id == graph_run_id,
                GraphInvocation.node_id == judge_prompt.id,
                GraphInvocation.model_node_id == judge_model.id,
                GraphInvocation.item_key == item_key,
                GraphInvocation.stage_index == 10_000,
            )
        ).first()
        if existing and existing.status == Status.complete:
            return
        invocation = existing or GraphInvocation(
            graph_run_id=graph_run_id,
            node_id=judge_prompt.id,
            model_node_id=judge_model.id,
            item_key=item_key,
            stage_index=10_000,
        )
        invocation.status = Status.running
        invocation.rendered_prompt = rendered
        if unresolved:
            invocation.status = Status.failed
            invocation.error = f"Unresolved judge prompt inputs after edge rendering: {', '.join(unresolved)}"
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
            return
        invocation.started_at = utc_now()
        invocation.error = None
        session.add(invocation)
        session.commit()
        invocation_id = invocation.id
    try:
        async with semaphore:
            call_started = time.perf_counter()
            response = await client.chat(
                model=model_cfg.get("model_id", ""),
                temperature=float(model_cfg.get("temperature") or 0.0),
                reasoning_effort=model_cfg.get("reasoning_effort") if model_cfg.get("reasoning_supported") else None,
                retries=int(model_cfg.get("retry_count") or 2),
                messages=[{"role": "user", "content": rendered}],
            )
            duration = max(time.perf_counter() - call_started, 0.001)
        repaired = maybe_repair_json(response.text)
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.complete
            invocation.output_raw = response.text
            invocation.output_json = repaired
            invocation.prompt_tokens = response.prompt_tokens
            invocation.completion_tokens = response.completion_tokens
            invocation.duration_seconds = duration
            invocation.output_tokens_per_second = (response.completion_tokens or 0) / duration if response.completion_tokens else None
            invocation.cost = response.cost
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.failed
            invocation.error = str(exc)
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()


def _markdown_items(cfg: dict) -> list[DatasetItem]:
    root = Path(cfg.get("path", "")).expanduser()
    if not root.exists():
        return []
    paths = sorted(path for path in root.rglob("*.md") if path.is_file())
    limit = int(cfg.get("sample_size") or 0)
    if limit:
        paths = paths[:limit]
    return [
        DatasetItem(
            key=path.stem,
            values={"call_id": path.stem, "transcript": path.read_text(encoding="utf-8")},
        )
        for path in paths
    ]


def _csv_items(cfg: dict) -> list[DatasetItem]:
    import csv

    path = Path(cfg.get("path", "")).expanduser()
    if not path.exists():
        return []
    id_column = cfg.get("id_column") or "call_id"
    text_column = cfg.get("text_column") or "transcript"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    limit = int(cfg.get("sample_size") or 0)
    if limit:
        rows = rows[:limit]
    items = []
    for index, row in enumerate(rows):
        key = row.get(id_column) or f"row-{index + 1}"
        values = {name: value or "" for name, value in row.items()}
        values.setdefault("call_id", key)
        values["transcript"] = row.get(text_column, "")
        items.append(DatasetItem(key=key, values=values))
    return items


def _sync_graph_status(session, run: GraphRun) -> None:
    graph = session.get(ExperimentGraph, run.graph_id)
    if graph and run.status.value in {status.value for status in GraphStatus}:
        graph.status = GraphStatus(run.status.value)
        session.add(graph)


def graph_run_leaderboard(session, graph_run_id: int, nodes: list[GraphNode]) -> list[dict]:
    """Compute ELO leaderboard and per-model stats from graph-native judge invocations."""

    model_lookup = {node.id: node for node in nodes}
    generator_nodes = [n for n in nodes if n.kind == "model" and config(n).get("role") == "generator"]
    judge_nodes = [n for n in nodes if n.kind == "model" and config(n).get("role") == "judge"]
    generator_ids = {n.id for n in generator_nodes}

    invocations = session.exec(
        select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id)
    ).all()

    # Token averages for generator models
    token_totals: dict[int, list[int]] = {n.id: [] for n in generator_nodes}
    for inv in invocations:
        model = model_lookup.get(inv.model_node_id)
        if model and model.id in generator_ids and inv.status == Status.complete:
            total = (inv.prompt_tokens or 0) + (inv.completion_tokens or 0)
            token_totals[model.id].append(total)

    # Parse judge invocations to build match history
    wins: dict[int, int] = {n.id: 0 for n in generator_nodes}
    losses: dict[int, int] = {n.id: 0 for n in generator_nodes}
    ties: dict[int, int] = {n.id: 0 for n in generator_nodes}
    ratings: dict[int, float] = {n.id: 1500.0 for n in generator_nodes}
    judge_tallies: dict[int, dict[int, int]] = {n.id: {} for n in judge_nodes}

    judge_invs = [
        inv for inv in invocations
        if inv.status == Status.complete and inv.output_json
        and model_lookup.get(inv.node_id)
        and model_lookup[inv.node_id].kind == "judge"
    ]

    for inv in judge_invs:
        judge_prompt = model_lookup[inv.node_id]
        winner_key = config(judge_prompt).get("winner_key") or "winner"

        # item_key format: "dataset-item-key:model_a_id-vs-model_b_id"
        try:
            _, pair = inv.item_key.rsplit(":", 1)
            model_a_id_str, model_b_id_str = pair.split("-vs-")
            model_a_id = int(model_a_id_str)
            model_b_id = int(model_b_id_str)
        except ValueError:
            continue

        if model_a_id not in generator_ids or model_b_id not in generator_ids:
            continue

        try:
            result = json.loads(inv.output_json)
            winner = str(result.get(winner_key, "TIE")).upper()
        except (json.JSONDecodeError, AttributeError):
            continue

        judge_model = model_lookup.get(inv.model_node_id)

        if winner == "A":
            wins[model_a_id] += 1
            losses[model_b_id] += 1
            ratings[model_a_id], ratings[model_b_id] = update_elo(
                ratings[model_a_id], ratings[model_b_id], "A"
            )
            if judge_model:
                judge_tallies[judge_model.id][model_a_id] = judge_tallies[judge_model.id].get(model_a_id, 0) + 1
        elif winner == "B":
            wins[model_b_id] += 1
            losses[model_a_id] += 1
            ratings[model_a_id], ratings[model_b_id] = update_elo(
                ratings[model_a_id], ratings[model_b_id], "B"
            )
            if judge_model:
                judge_tallies[judge_model.id][model_b_id] = judge_tallies[judge_model.id].get(model_b_id, 0) + 1
        else:
            ties[model_a_id] += 1
            ties[model_b_id] += 1
            ratings[model_a_id], ratings[model_b_id] = update_elo(
                ratings[model_a_id], ratings[model_b_id], "TIE"
            )

    # Compute judge favorites
    favorites: dict[int, list[GraphNode]] = {n.id: [] for n in generator_nodes}
    for judge_id, tallies in judge_tallies.items():
        if not tallies:
            continue
        favorite_id = max(tallies.items(), key=lambda x: x[1])[0]
        judge_model = model_lookup.get(judge_id)
        if judge_model:
            favorites[favorite_id].append(judge_model)

    rows = []
    for node in generator_nodes:
        rows.append(
            {
                "node": node,
                "rating": ratings[node.id],
                "wins": wins[node.id],
                "losses": losses[node.id],
                "ties": ties[node.id],
                "avg_tokens": f"{sum(token_totals[node.id]) // len(token_totals[node.id]):,}" if token_totals[node.id] else "-",
                "favorites": favorites.get(node.id, []),
            }
        )

    rows.sort(key=lambda r: r["rating"], reverse=True)
    return rows
