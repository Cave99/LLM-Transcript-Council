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


@dataclass(frozen=True)
class OutputBranch:
    """One item-scoped output branch flowing between prompt stages."""

    item: DatasetItem
    chain: tuple[int, ...]
    output: str
    prompt_id: int | None = None
    stage_index: int = -1


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
    branches = [OutputBranch(item=item, chain=(), output="") for item in items]
    stage_outputs: dict[int, list[OutputBranch]] = {}
    for stage_index, prompt in enumerate(prompt_stages):
        with session_factory() as session:
            run = session.get(GraphRun, graph_run_id)
            if run and run.status == Status.paused:
                _sync_graph_status(session, run)
                session.commit()
                return
        tasks = []
        prompt_models = _connected_models(prompt, model_nodes, edges)
        for branch in branches:
            for model in prompt_models:
                tasks.append(
                    _run_invocation(
                        graph_run_id,
                        stage_index,
                        prompt,
                        model,
                        branch,
                        constants,
                        nodes,
                        edges,
                        session_factory,
                        client,
                        semaphore,
                    )
                )
        results = await asyncio.gather(*tasks)
        branches = [branch for branch in results if branch.output]
        stage_outputs[prompt.id] = branches

    for judge_prompt in judge_prompts:
        target_prompt = _judge_target_prompt(judge_prompt, prompt_stages, model_nodes, edges)
        target_branches = stage_outputs.get(target_prompt.id if target_prompt else -1, branches)
        if not target_prompt:
            continue
        tasks = []
        scoped_judge_models = _connected_models(judge_prompt, judge_models, edges)
        branches_by_item: dict[str, list[OutputBranch]] = {}
        for branch in target_branches:
            branches_by_item.setdefault(branch.item.key, []).append(branch)
        for item_branches in branches_by_item.values():
            branch_pairs = [(a, b) for index, a in enumerate(item_branches) for b in item_branches[index + 1 :]]
            for branch_a, branch_b in branch_pairs:
                for judge_model in scoped_judge_models:
                    tasks.append(
                        _run_judge_invocation(
                            graph_run_id,
                            judge_prompt,
                            target_prompt,
                            judge_model,
                            constants,
                            nodes,
                            edges,
                            branch_a,
                            branch_b,
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


def _branch_input_key(branch: OutputBranch) -> str:
    """Keep resumed invocation rows distinct for each upstream branch."""

    if not branch.chain:
        return branch.item.key
    return f"{branch.item.key}|{_chain_key(branch.chain)}"


def _chain_key(chain: tuple[int, ...]) -> str:
    return ">".join(str(node_id) for node_id in chain)


def _judge_target_prompt(judge_prompt: RuntimeNode, prompt_stages: list[RuntimeNode], model_nodes: list[RuntimeNode], edges: list[RuntimeEdge]) -> RuntimeNode | None:
    """Find the prompt stage a judge is visually connected to."""

    prompt_by_id = {prompt.id: prompt for prompt in prompt_stages}
    incoming_prompt_ids = [
        edge.from_node_id
        for edge in edges
        if edge.to_node_id == judge_prompt.id and edge.from_node_id in prompt_by_id
    ]
    if incoming_prompt_ids:
        return prompt_by_id[incoming_prompt_ids[-1]]
    model_ids = {node.id for node in model_nodes}
    incoming_model_ids = [
        edge.from_node_id
        for edge in edges
        if edge.to_node_id == judge_prompt.id and edge.from_node_id in model_ids
    ]
    if incoming_model_ids:
        prompt_ids = [
            edge.from_node_id
            for edge in edges
            if edge.to_node_id in incoming_model_ids and edge.from_node_id in prompt_by_id
        ]
        if prompt_ids:
            return prompt_by_id[prompt_ids[-1]]
    return prompt_stages[-1] if prompt_stages else None


def _connected_models(source: RuntimeNode, candidates: list[RuntimeNode], edges: list[RuntimeEdge]) -> list[RuntimeNode]:
    """Return model nodes visually connected from a prompt or judge node."""

    candidate_by_id = {node.id: node for node in candidates}
    connected_ids = [
        edge.to_node_id
        for edge in edges
        if edge.from_node_id == source.id and edge.to_node_id in candidate_by_id
    ]
    if not connected_ids:
        return candidates
    seen = set()
    scoped = []
    for node_id in connected_ids:
        if node_id in seen:
            continue
        seen.add(node_id)
        scoped.append(candidate_by_id[node_id])
    return scoped


def _leaderboard_entity_key(branch: OutputBranch, _prompt: RuntimeNode) -> str:
    """Persist the full model chain so leaderboard views can aggregate later."""

    if not branch.chain:
        return ""
    return _chain_key(branch.chain)


def _leaderboard_entity_label(branch: OutputBranch, prompt: RuntimeNode, nodes: list[RuntimeNode]) -> str:
    """Return the human label for a leaderboard entity."""

    by_id = {node.id: node for node in nodes}
    entity_key = _leaderboard_entity_key(branch, prompt)
    if not entity_key:
        return "Unknown"
    return " -> ".join(by_id.get(node_id).title if by_id.get(node_id) else str(node_id) for node_id in branch.chain)


async def _run_invocation(
    graph_run_id: int,
    stage_index: int,
    prompt: GraphNode,
    model: GraphNode,
    branch: OutputBranch,
    constants: dict[str, str],
    nodes: list[RuntimeNode],
    edges: list[RuntimeEdge],
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> OutputBranch:
    model_cfg = config(model)
    prompt_cfg = config(prompt)
    item_key = _branch_input_key(branch)
    values = _render_values_for_node(prompt, branch.item, constants, nodes, edges, previous_output=branch.output)
    rendered = render_template(prompt.body, values)
    unresolved = prompt_inputs(rendered)
    with session_factory() as session:
        run = session.get(GraphRun, graph_run_id)
        if run and run.status == Status.paused:
            return OutputBranch(item=branch.item, chain=branch.chain + (model.id,), output="", prompt_id=prompt.id, stage_index=stage_index)
        existing = session.exec(
            select(GraphInvocation).where(
                GraphInvocation.graph_run_id == graph_run_id,
                GraphInvocation.node_id == prompt.id,
                GraphInvocation.model_node_id == model.id,
                GraphInvocation.item_key == item_key,
                GraphInvocation.stage_index == stage_index,
            )
        ).first()
        if existing and existing.status == Status.complete:
            output = existing.output_json if prompt_cfg.get("upstream_mode") == "json" else existing.output_raw
            return OutputBranch(item=branch.item, chain=branch.chain + (model.id,), output=output or "", prompt_id=prompt.id, stage_index=stage_index)
        invocation = existing or GraphInvocation(
            graph_run_id=graph_run_id,
            node_id=prompt.id,
            model_node_id=model.id,
            item_key=item_key,
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
            return OutputBranch(item=branch.item, chain=branch.chain + (model.id,), output="", prompt_id=prompt.id, stage_index=stage_index)
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
        return OutputBranch(item=branch.item, chain=branch.chain + (model.id,), output=repaired if prompt_cfg.get("upstream_mode") == "json" else response.text, prompt_id=prompt.id, stage_index=stage_index)
    except Exception as exc:
        with session_factory() as session:
            invocation = session.get(GraphInvocation, invocation_id)
            invocation.status = Status.failed
            invocation.error = str(exc)
            invocation.completed_at = utc_now()
            session.add(invocation)
            session.commit()
        return OutputBranch(item=branch.item, chain=branch.chain + (model.id,), output="", prompt_id=prompt.id, stage_index=stage_index)


async def _run_judge_invocation(
    graph_run_id: int,
    judge_prompt: GraphNode,
    target_prompt: GraphNode,
    judge_model: GraphNode,
    constants: dict[str, str],
    nodes: list[RuntimeNode],
    edges: list[RuntimeEdge],
    branch_a: OutputBranch,
    branch_b: OutputBranch,
    session_factory,
    client: OpenRouterClient,
    semaphore: asyncio.Semaphore,
) -> None:
    model_cfg = config(judge_model)
    values = {
        **_render_values_for_node(judge_prompt, branch_a.item, constants, nodes, edges),
        "output_a": branch_a.output,
        "output_b": branch_b.output,
        "model_a": _leaderboard_entity_label(branch_a, target_prompt, nodes),
        "model_b": _leaderboard_entity_label(branch_b, target_prompt, nodes),
    }
    rendered = render_template(judge_prompt.body, values)
    unresolved = prompt_inputs(rendered)
    item_key = f"{branch_a.item.key}:{_leaderboard_entity_key(branch_a, target_prompt)}-vs-{_leaderboard_entity_key(branch_b, target_prompt)}"
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
    """Compute the aggregate ELO leaderboard from graph-native judge invocations."""

    return graph_run_leaderboards(session, graph_run_id, nodes, view_mode="aggregate")[0]["rows"]


def graph_run_leaderboards(session, graph_run_id: int, nodes: list[GraphNode], *, view_mode: str = "aggregate") -> list[dict]:
    """Compute aggregate and judge-prompt-scoped leaderboards."""

    model_lookup = {node.id: node for node in nodes}
    generator_nodes = [n for n in nodes if n.kind == "model" and config(n).get("role") == "generator"]
    judge_nodes = [n for n in nodes if n.kind == "model" and config(n).get("role") == "judge"]
    generator_ids = {n.id for n in generator_nodes}
    run = session.get(GraphRun, graph_run_id)
    edges = graph_edges(session, run.graph_id) if run else []
    prompt_stages = sorted([node for node in nodes if node.kind == "prompt"], key=lambda node: (node.x, node.y, node.id or 0))
    target_depths = _judge_target_depths([node for node in nodes if node.kind == "judge"], prompt_stages, generator_nodes, edges)

    invocations = session.exec(
        select(GraphInvocation).where(GraphInvocation.graph_run_id == graph_run_id)
    ).all()

    token_totals: dict[str, list[int]] = {str(n.id): [] for n in generator_nodes}
    for inv in invocations:
        model = model_lookup.get(inv.model_node_id)
        if model and model.id in generator_ids and inv.status == Status.complete:
            total = (inv.prompt_tokens or 0) + (inv.completion_tokens or 0)
            token_totals[str(model.id)].append(total)

    judge_invs = [
        inv for inv in invocations
        if inv.status == Status.complete and inv.output_json
        and model_lookup.get(inv.node_id)
        and model_lookup[inv.node_id].kind == "judge"
    ]
    groups = [("Overall", None, judge_invs)]
    for judge_prompt in [node for node in nodes if node.kind == "judge"]:
        scoped = [inv for inv in judge_invs if inv.node_id == judge_prompt.id]
        if scoped:
            groups.append((judge_prompt.title, judge_prompt.id, scoped))
    return [
        {
            "title": title,
            "judge_prompt_node_id": judge_prompt_id,
            "rows": _leaderboard_rows_for_invocations(scoped, model_lookup, judge_nodes, token_totals, view_mode=view_mode, target_depth=target_depths.get(judge_prompt_id) if judge_prompt_id else None),
        }
        for title, judge_prompt_id, scoped in groups
    ]


def _leaderboard_rows_for_invocations(
    judge_invs: list[GraphInvocation],
    model_lookup: dict[int, GraphNode],
    judge_nodes: list[GraphNode],
    token_totals: dict[str, list[int]],
    *,
    view_mode: str,
    target_depth: int | None,
) -> list[dict]:
    entities: set[str] = set()
    for inv in judge_invs:
        parsed = _parse_judge_pair(inv.item_key)
        if parsed:
            display_a, display_b = _display_entities(parsed, view_mode, target_depth)
            if display_a != display_b:
                entities.update((display_a, display_b))
    wins: dict[str, int] = {entity: 0 for entity in entities}
    losses: dict[str, int] = {entity: 0 for entity in entities}
    ties: dict[str, int] = {entity: 0 for entity in entities}
    ratings: dict[str, float] = {entity: 1500.0 for entity in entities}
    judge_tallies: dict[int, dict[str, int]] = {n.id: {} for n in judge_nodes}
    for inv in judge_invs:
        judge_prompt = model_lookup[inv.node_id]
        winner_key = config(judge_prompt).get("winner_key") or "winner"
        parsed = _parse_judge_pair(inv.item_key)
        if not parsed:
            continue
        entity_a, entity_b = _display_entities(parsed, view_mode, target_depth)
        if entity_a == entity_b:
            continue
        try:
            result = json.loads(inv.output_json)
            winner = str(result.get(winner_key, "TIE")).upper()
        except (json.JSONDecodeError, AttributeError):
            continue
        judge_model = model_lookup.get(inv.model_node_id)
        if winner == "A":
            wins[entity_a] += 1
            losses[entity_b] += 1
            ratings[entity_a], ratings[entity_b] = update_elo(ratings[entity_a], ratings[entity_b], "A")
            if judge_model:
                judge_tallies[judge_model.id][entity_a] = judge_tallies[judge_model.id].get(entity_a, 0) + 1
        elif winner == "B":
            wins[entity_b] += 1
            losses[entity_a] += 1
            ratings[entity_a], ratings[entity_b] = update_elo(ratings[entity_a], ratings[entity_b], "B")
            if judge_model:
                judge_tallies[judge_model.id][entity_b] = judge_tallies[judge_model.id].get(entity_b, 0) + 1
        else:
            ties[entity_a] += 1
            ties[entity_b] += 1
            ratings[entity_a], ratings[entity_b] = update_elo(ratings[entity_a], ratings[entity_b], "TIE")

    favorites: dict[str, list[GraphNode]] = {entity: [] for entity in entities}
    for judge_id, tallies in judge_tallies.items():
        if not tallies:
            continue
        favorite_id = max(tallies.items(), key=lambda x: x[1])[0]
        judge_model = model_lookup.get(judge_id)
        if judge_model:
            favorites[favorite_id].append(judge_model)

    rows = []
    for entity in entities:
        node = _entity_last_node(entity, model_lookup)
        totals = token_totals.get(entity, []) or token_totals.get(str(node.id) if node else "", [])
        rows.append(
            {
                "entity_key": entity,
                "label": _entity_label(entity, model_lookup),
                "node": node,
                "rating": ratings[entity],
                "wins": wins[entity],
                "losses": losses[entity],
                "ties": ties[entity],
                "avg_tokens": f"{sum(totals) // len(totals):,}" if totals else "-",
                "favorites": favorites.get(entity, []),
            }
        )

    rows.sort(key=lambda r: r["rating"], reverse=True)
    return rows


def _parse_judge_pair(item_key: str) -> tuple[str, str] | None:
    try:
        _item, pair = item_key.rsplit(":", 1)
        entity_a, entity_b = pair.split("-vs-", 1)
        return entity_a, entity_b
    except ValueError:
        return None


def _display_entities(pair: tuple[str, str], view_mode: str, target_depth: int | None) -> tuple[str, str]:
    pair = (_truncate_entity(pair[0], target_depth), _truncate_entity(pair[1], target_depth))
    if view_mode == "chain":
        return pair
    return _entity_final_model(pair[0]), _entity_final_model(pair[1])


def _truncate_entity(entity: str, target_depth: int | None) -> str:
    if not target_depth:
        return entity
    return ">".join(entity.split(">")[:target_depth])


def _entity_final_model(entity: str) -> str:
    return entity.split(">")[-1]


def _judge_target_depths(
    judge_prompts: list[GraphNode],
    prompt_stages: list[GraphNode],
    generator_models: list[GraphNode],
    edges: list[GraphEdge],
) -> dict[int, int]:
    """Map judge prompt ids to the prompt-stage depth they visually judge."""

    prompt_by_id = {prompt.id: prompt for prompt in prompt_stages}
    generator_model_ids = {node.id for node in generator_models}
    depths = {}
    for judge_prompt in judge_prompts:
        target = None
        incoming = [edge.from_node_id for edge in edges if edge.to_node_id == judge_prompt.id and edge.from_node_id in prompt_by_id]
        if incoming:
            target = prompt_by_id[incoming[-1]]
        else:
            incoming_models = [edge.from_node_id for edge in edges if edge.to_node_id == judge_prompt.id and edge.from_node_id in generator_model_ids]
            prompt_ids = [edge.from_node_id for edge in edges if edge.to_node_id in incoming_models and edge.from_node_id in prompt_by_id]
            if prompt_ids:
                target = prompt_by_id[prompt_ids[-1]]
        if target and judge_prompt.id:
            depths[judge_prompt.id] = prompt_stages.index(target) + 1
    return depths


def _entity_last_node(entity: str, model_lookup: dict[int, GraphNode]) -> GraphNode | None:
    try:
        return model_lookup.get(int(entity.split(">")[-1]))
    except ValueError:
        return None


def _entity_label(entity: str, model_lookup: dict[int, GraphNode]) -> str:
    labels = []
    for part in entity.split(">"):
        try:
            node = model_lookup.get(int(part))
        except ValueError:
            node = None
        labels.append(node.title if node else part)
    return " -> ".join(labels)
