"""Spec-first graph definitions and validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


class ValidationMessage(BaseModel):
    code: str
    path: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationMessage] = Field(default_factory=list)
    warnings: list[ValidationMessage] = Field(default_factory=list)


class DatasetSpec(BaseModel):
    provider: Literal["markdown_folder", "csv"] = "markdown_folder"
    config: dict[str, Any] = Field(default_factory=lambda: {"path": "transcripts", "id_column": "call_id", "text_column": "transcript", "sample_size": None})


class ModelParams(BaseModel):
    temperature: float = 0.2
    retry_count: int = 2
    reasoning_effort: str | None = None


class CandidateSpec(BaseModel):
    id: str
    title: str = ""
    model: str = ""
    prompt_path: str | None = None
    prompt_inline: str | None = None
    params: ModelParams = Field(default_factory=ModelParams)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.match(value):
            raise ValueError("ID must start with a letter and contain only letters, numbers, underscores, or hyphens")
        return value


class StageSpec(BaseModel):
    id: str
    title: str = ""
    fanout: Literal["matrix"] = "matrix"
    upstream_output: Literal["raw", "json"] = "raw"
    candidates: list[CandidateSpec] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.match(value):
            raise ValueError("ID must start with a letter and contain only letters, numbers, underscores, or hyphens")
        return value


class PairingSpec(BaseModel):
    sample_pct: float = 100.0
    swap: bool = False
    seed: str | None = None


class EvaluatorOutputSpec(BaseModel):
    winner_key: str = "winner"
    reasoning_key: str = "reasoning"


class EvaluatorSpec(BaseModel):
    id: str
    title: str = ""
    type: Literal["llm_pairwise", "human_pairwise"] = "llm_pairwise"
    target_stage: str = ""
    model: str = ""
    prompt_path: str | None = None
    prompt_inline: str | None = None
    params: ModelParams = Field(default_factory=lambda: ModelParams(temperature=0.0))
    pairing: PairingSpec = Field(default_factory=PairingSpec)
    output: EvaluatorOutputSpec = Field(default_factory=EvaluatorOutputSpec)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.match(value):
            raise ValueError("ID must start with a letter and contain only letters, numbers, underscores, or hyphens")
        return value


class GraphSpec(BaseModel):
    version: Literal[1] = 1
    dataset: DatasetSpec = Field(default_factory=DatasetSpec)
    constants: dict[str, str] = Field(default_factory=dict)
    stages: list[StageSpec] = Field(default_factory=list)
    evaluators: list[EvaluatorSpec] = Field(default_factory=list)


@dataclass(frozen=True)
class LayoutNode:
    id: str
    kind: str
    title: str
    x: int
    y: int


def minimal_spec() -> GraphSpec:
    """Return the smallest valid draft graph spec."""

    return GraphSpec()


def parse_spec(value: dict[str, Any] | str | None) -> GraphSpec:
    """Parse a graph spec from database JSON or API payloads."""

    if not value:
        return minimal_spec()
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except json.JSONDecodeError:
            value = {}
    return GraphSpec.model_validate(value)


def dump_spec(spec: GraphSpec | dict[str, Any]) -> str:
    """Serialize the canonical spec in deterministic JSON form."""

    if not isinstance(spec, GraphSpec):
        spec = parse_spec(spec)
    return json.dumps(spec.model_dump(mode="json", exclude_none=True), sort_keys=True, separators=(",", ":"))


def spec_hash(spec: GraphSpec | dict[str, Any]) -> str:
    """Hash execution semantics without layout noise."""

    return hashlib.sha256(dump_spec(spec).encode("utf-8")).hexdigest()


def validate_spec_payload(payload: dict[str, Any] | str | None, *, check_prompt_paths: bool = False, require_executable: bool = True) -> ValidationResult:
    """Validate a spec and return stable machine-readable messages."""

    errors: list[ValidationMessage] = []
    warnings: list[ValidationMessage] = []
    try:
        spec = parse_spec(payload)
    except ValidationError as exc:
        for item in exc.errors():
            path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in item["loc"])
            errors.append(ValidationMessage(code="schema_error", path=path, message=str(item["msg"])))
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    seen_stage_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    for index, stage in enumerate(spec.stages):
        if stage.id in seen_stage_ids:
            errors.append(ValidationMessage(code="duplicate_stage_id", path=f"$.stages[{index}].id", message=f"Duplicate stage id {stage.id!r}."))
        seen_stage_ids.add(stage.id)
        if stage.fanout != "matrix":
            errors.append(ValidationMessage(code="unsupported_fanout", path=f"$.stages[{index}].fanout", message="Only matrix fanout is supported in spec v1."))
        if not stage.candidates:
            warnings.append(ValidationMessage(code="stage_has_no_candidates", path=f"$.stages[{index}].candidates", message=f"Stage {stage.id!r} has no candidates."))
        for candidate_index, candidate in enumerate(stage.candidates):
            if candidate.id in seen_candidate_ids:
                errors.append(ValidationMessage(code="duplicate_candidate_id", path=f"$.stages[{index}].candidates[{candidate_index}].id", message=f"Duplicate candidate id {candidate.id!r}."))
            seen_candidate_ids.add(candidate.id)
            _validate_prompt(candidate.prompt_path, candidate.prompt_inline, f"$.stages[{index}].candidates[{candidate_index}]", errors, warnings, check_prompt_paths, require_executable)

    seen_evaluator_ids: set[str] = set()
    for index, evaluator in enumerate(spec.evaluators):
        if evaluator.id in seen_evaluator_ids:
            errors.append(ValidationMessage(code="duplicate_evaluator_id", path=f"$.evaluators[{index}].id", message=f"Duplicate evaluator id {evaluator.id!r}."))
        seen_evaluator_ids.add(evaluator.id)
        if evaluator.target_stage not in seen_stage_ids:
            errors.append(ValidationMessage(code="unknown_target_stage", path=f"$.evaluators[{index}].target_stage", message=f"Evaluator target stage {evaluator.target_stage!r} does not exist."))
        if evaluator.type == "llm_pairwise":
            if not evaluator.model.strip():
                target = errors if require_executable else warnings
                target.append(ValidationMessage(code="missing_judge_model", path=f"$.evaluators[{index}].model", message="LLM evaluator needs a model."))
            _validate_prompt(evaluator.prompt_path, evaluator.prompt_inline, f"$.evaluators[{index}]", errors, warnings, check_prompt_paths, require_executable)
    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def generated_layout(spec: GraphSpec, layout: dict[str, Any] | None = None) -> tuple[list[LayoutNode], list[dict[str, str]]]:
    """Generate semantic canvas nodes and edges from a graph spec."""

    layout = layout or {}
    nodes = [_layout_node("dataset", "dataset", "Dataset", layout, 40, 160)]
    edges: list[dict[str, str]] = []
    previous_output_sources = ["dataset"]
    for index, stage in enumerate(spec.stages):
        source_nodes = [node for node in nodes if node.id in previous_output_sources]
        stage_x = max((node.x for node in source_nodes), default=40) + 360
        stage_y = int(sum(node.y for node in source_nodes) / len(source_nodes)) if source_nodes else 160
        stage_node = _layout_node(stage.id, "stage", stage.title or stage.id, layout, stage_x, stage_y)
        nodes.append(stage_node)
        for source in previous_output_sources:
            edges.append({"id": f"{source}->{stage.id}", "source": source, "target": stage.id})
        for candidate_index, candidate in enumerate(stage.candidates):
            fallback_y = stage_node.y + candidate_index * 140
            nodes.append(_layout_node(candidate.id, "candidate", candidate.title or candidate.id, layout, stage_node.x + 360, fallback_y))
            edges.append({"id": f"{stage.id}->{candidate.id}", "source": stage.id, "target": candidate.id})
        previous_output_sources = [candidate.id for candidate in stage.candidates] or [stage.id]
    stage_ids = {stage.id for stage in spec.stages}
    for index, evaluator in enumerate(spec.evaluators):
        target_stage = next((stage for stage in spec.stages if stage.id == evaluator.target_stage), None)
        source_ids = [candidate.id for candidate in target_stage.candidates] if target_stage and target_stage.candidates else ([target_stage.id] if target_stage else [])
        source_nodes = [node for node in nodes if node.id in source_ids]
        fallback_x = max((node.x for node in source_nodes), default=40) + 360
        fallback_y = int(sum(node.y for node in source_nodes) / len(source_nodes)) if source_nodes else 560 + index * 120
        nodes.append(_layout_node(evaluator.id, "evaluator", evaluator.title or evaluator.id, layout, fallback_x, fallback_y))
        if evaluator.target_stage in stage_ids:
            if target_stage and target_stage.candidates:
                for candidate in target_stage.candidates:
                    edges.append({"id": f"{candidate.id}->{evaluator.id}", "source": candidate.id, "target": evaluator.id})
            else:
                edges.append({"id": f"{evaluator.target_stage}->{evaluator.id}", "source": evaluator.target_stage, "target": evaluator.id})
    return nodes, edges


def legacy_graph_to_spec(raw_nodes: list[dict[str, Any]], raw_edges: list[dict[str, Any]]) -> tuple[GraphSpec, dict[str, Any]]:
    """Best-effort conversion from old low-level graph rows to spec/layout."""

    def cfg(node: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(node.get("config_json") or "{}")
        except json.JSONDecodeError:
            return {}

    nodes_by_id = {node["id"]: node for node in raw_nodes}
    dataset = next((node for node in raw_nodes if node.get("kind") == "dataset"), None)
    dataset_cfg = cfg(dataset) if dataset else {}
    provider = "csv" if dataset_cfg.get("source_type") == "csv" else "markdown_folder"
    spec_dataset = DatasetSpec(provider=provider, config={
        "path": dataset_cfg.get("path", "transcripts"),
        "sample_size": dataset_cfg.get("sample_size") or None,
        "id_column": dataset_cfg.get("id_column", "call_id"),
        "text_column": dataset_cfg.get("text_column", "transcript"),
    })

    constants = {cfg(node).get("socket") or node.get("title") or f"constant_{node['id']}": node.get("body") or "" for node in raw_nodes if node.get("kind") == "constant"}
    prompts = sorted([node for node in raw_nodes if node.get("kind") == "prompt"], key=lambda node: (node.get("x") or 0, node.get("y") or 0, node.get("id") or 0))
    generator_models = [node for node in raw_nodes if node.get("kind") == "model" and cfg(node).get("role", "generator") == "generator"]
    judge_models = [node for node in raw_nodes if node.get("kind") == "model" and cfg(node).get("role") == "judge"]

    incoming_by_target: dict[int, list[dict[str, Any]]] = {}
    outgoing_by_source: dict[int, list[dict[str, Any]]] = {}
    for edge in raw_edges:
        incoming_by_target.setdefault(edge["to_node_id"], []).append(edge)
        outgoing_by_source.setdefault(edge["from_node_id"], []).append(edge)

    stages: list[StageSpec] = []
    stage_by_prompt_id: dict[int, str] = {}
    for index, prompt in enumerate(prompts):
        prompt_id = prompt["id"]
        connected_model_ids = [edge["to_node_id"] for edge in outgoing_by_source.get(prompt_id, []) if nodes_by_id.get(edge["to_node_id"], {}).get("kind") == "model"]
        models = [node for node in generator_models if node["id"] in connected_model_ids] or generator_models
        stage_id = _slug(prompt.get("title") or f"stage_{index + 1}", fallback=f"stage_{index + 1}")
        stage_by_prompt_id[prompt_id] = stage_id
        candidates = []
        for model_index, model in enumerate(models):
            model_cfg = cfg(model)
            candidates.append(CandidateSpec(
                id=_slug(model.get("title") or f"candidate_{model_index + 1}", fallback=f"candidate_{index + 1}_{model_index + 1}"),
                title=model.get("title") or f"Candidate {model_index + 1}",
                model=model_cfg.get("model_id", ""),
                prompt_inline=prompt.get("body") or "",
                params=ModelParams(temperature=float(model_cfg.get("temperature") or 0.0), retry_count=int(model_cfg.get("retry_count") or 2), reasoning_effort=model_cfg.get("reasoning_effort") or None),
            ))
        stages.append(StageSpec(id=stage_id, title=prompt.get("title") or stage_id, fanout="matrix", upstream_output=cfg(prompt).get("upstream_mode", "raw"), candidates=candidates))

    evaluators: list[EvaluatorSpec] = []
    judges = [node for node in raw_nodes if node.get("kind") == "judge"]
    for index, judge in enumerate(judges):
        judge_cfg = cfg(judge)
        connected_prompt_ids = [edge["from_node_id"] for edge in incoming_by_target.get(judge["id"], []) if nodes_by_id.get(edge["from_node_id"], {}).get("kind") == "prompt"]
        target_stage = stage_by_prompt_id.get(connected_prompt_ids[-1]) if connected_prompt_ids else (stages[-1].id if stages else "")
        connected_judge_model_ids = [edge["to_node_id"] for edge in outgoing_by_source.get(judge["id"], []) if nodes_by_id.get(edge["to_node_id"], {}).get("kind") == "model"]
        judge_model = next((node for node in judge_models if node["id"] in connected_judge_model_ids), judge_models[0] if judge_models else None)
        model_cfg = cfg(judge_model) if judge_model else {}
        evaluators.append(EvaluatorSpec(
            id=_slug(judge.get("title") or f"judge_{index + 1}", fallback=f"judge_{index + 1}"),
            title=judge.get("title") or f"Judge {index + 1}",
            type="llm_pairwise",
            target_stage=target_stage,
            model=model_cfg.get("model_id", ""),
            prompt_inline=judge.get("body") or "",
            params=ModelParams(temperature=float(model_cfg.get("temperature") or 0.0), retry_count=int(model_cfg.get("retry_count") or 2)),
            pairing=PairingSpec(sample_pct=float(judge_cfg.get("pairing_sample_pct") or 100), swap=bool(judge_cfg.get("swap_enabled", False)), seed=judge_cfg.get("seed") or None),
            output=EvaluatorOutputSpec(winner_key=judge_cfg.get("winner_key", "winner"), reasoning_key=judge_cfg.get("reasoning_key", "reasoning")),
        ))

    layout = {"dataset": {"x": dataset.get("x", 40) if dataset else 40, "y": dataset.get("y", 160) if dataset else 160}}
    for prompt in prompts:
        stage_id = stage_by_prompt_id.get(prompt["id"])
        if stage_id:
            layout[stage_id] = {"x": prompt.get("x", 360), "y": prompt.get("y", 120)}
    for evaluator, judge in zip(evaluators, judges):
        layout[evaluator.id] = {"x": judge.get("x", 720), "y": judge.get("y", 440)}
    return GraphSpec(dataset=spec_dataset, constants=constants, stages=stages, evaluators=evaluators), layout


def _validate_prompt(path: str | None, inline: str | None, base_path: str, errors: list[ValidationMessage], warnings: list[ValidationMessage], check_prompt_paths: bool, require_executable: bool) -> None:
    if not path and not inline:
        target = errors if require_executable else warnings
        target.append(ValidationMessage(code="missing_prompt", path=f"{base_path}.prompt_path", message="Provide prompt_path or prompt_inline."))
    if check_prompt_paths and path and not Path(path).exists():
        errors.append(ValidationMessage(code="missing_prompt_path", path=f"{base_path}.prompt_path", message=f"Prompt path {path!r} does not exist."))


def _layout_node(node_id: str, kind: str, title: str, layout: dict[str, Any], fallback_x: int, fallback_y: int) -> LayoutNode:
    item = (layout.get(node_id) if isinstance(layout, dict) else {}) or {}
    return LayoutNode(id=node_id, kind=kind, title=title, x=int(item.get("x", fallback_x)), y=int(item.get("y", fallback_y)))


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = fallback
    return slug
