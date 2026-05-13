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


def _validate_prompt(path: str | None, inline: str | None, base_path: str, errors: list[ValidationMessage], warnings: list[ValidationMessage], check_prompt_paths: bool, require_executable: bool) -> None:
    if not path and not inline:
        target = errors if require_executable else warnings
        target.append(ValidationMessage(code="missing_prompt", path=f"{base_path}.prompt_path", message="Provide prompt_path or prompt_inline."))
    if check_prompt_paths and path and not Path(path).exists():
        errors.append(ValidationMessage(code="missing_prompt_path", path=f"{base_path}.prompt_path", message=f"Prompt path {path!r} does not exist."))


def _layout_node(node_id: str, kind: str, title: str, layout: dict[str, Any], fallback_x: int, fallback_y: int) -> LayoutNode:
    item = (layout.get(node_id) if isinstance(layout, dict) else {}) or {}
    return LayoutNode(id=node_id, kind=kind, title=title, x=int(item.get("x", fallback_x)), y=int(item.get("y", fallback_y)))

