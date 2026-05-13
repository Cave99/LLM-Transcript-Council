"""Pydantic schemas for the spec-backed graph API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

StatusValue = Literal["pending", "running", "complete", "failed", "paused"]
GraphStatusValue = Literal["draft", "running", "complete", "failed", "paused"]
LeaderboardView = Literal["aggregate"]


class ApiErrorDetail(BaseModel):
    code: str
    message: str


class OkResponse(BaseModel):
    ok: bool = True


class HealthResponse(BaseModel):
    ok: bool = True
    app: str = "LLM-Transcript-Council"


class GraphRunSummary(BaseModel):
    id: int
    graph_id: int
    name: str
    status: StatusValue
    max_concurrency: int
    sample_size: int | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ProjectSummary(BaseModel):
    id: int
    name: str
    created_at: datetime
    graph_count: int
    recent_graph_runs: list[GraphRunSummary] = Field(default_factory=list)


class GraphSummary(BaseModel):
    id: int
    project_id: int
    name: str
    status: GraphStatusValue
    last_run_id: int | None
    spec_hash: str
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectSummary):
    graphs: list[GraphSummary] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    name: str


class GraphCreate(BaseModel):
    project_id: int
    name: str
    spec: dict[str, Any] | None = None


class GraphUpdate(BaseModel):
    name: str | None = None
    spec: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None


class ValidationMessageDto(BaseModel):
    code: str
    path: str
    message: str


class ValidationResultDto(BaseModel):
    valid: bool
    errors: list[ValidationMessageDto] = Field(default_factory=list)
    warnings: list[ValidationMessageDto] = Field(default_factory=list)


class SemanticNodeDto(BaseModel):
    id: str
    kind: str
    title: str
    x: int
    y: int


class SemanticEdgeDto(BaseModel):
    id: str
    source: str
    target: str


class GraphPlanDto(BaseModel):
    transcript_count: int
    stage_count: int
    candidate_count: int
    evaluator_count: int
    generation_calls: int
    pair_count: int
    judge_calls: int
    human_review_count: int
    warnings: list[str]


class GraphDetail(BaseModel):
    graph: GraphSummary
    spec: dict[str, Any]
    layout: dict[str, Any]
    nodes: list[SemanticNodeDto]
    edges: list[SemanticEdgeDto]
    plan: GraphPlanDto
    latest_run: GraphRunSummary | None = None
    graph_runs: list[GraphRunSummary] = Field(default_factory=list)


class LaunchGraphRunRequest(BaseModel):
    run_mode: Literal["test", "full"] = "full"
    max_concurrency: int = Field(default=5, ge=1, le=50)


class GraphProgress(BaseModel):
    total: int
    pending: int
    running: int
    complete: int
    failed: int


class GraphDiagnostic(BaseModel):
    level: Literal["info", "warning", "error"]
    message: str


class LeaderboardFavorite(BaseModel):
    id: int
    title: str


class GraphLeaderboardRow(BaseModel):
    entity_key: str
    label: str
    rating: float
    wins: int
    losses: int
    ties: int
    avg_tokens: str
    favorites: list[LeaderboardFavorite]


class GraphLeaderboardGroup(BaseModel):
    title: str
    view_mode: LeaderboardView
    rows: list[GraphLeaderboardRow]


class GraphInvocationDto(BaseModel):
    id: int
    graph_run_id: int
    kind: str
    stage_id: str
    candidate_id: str | None
    evaluator_id: str | None
    lineage_key: str
    model_id: str
    item_key: str
    stage_index: int
    status: StatusValue
    rendered_prompt: str
    output_raw: str | None
    output_json: str | None
    error: str | None
    error_category: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_seconds: float | None
    output_tokens_per_second: float | None
    cost: float | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class GraphPairDto(BaseModel):
    id: int
    graph_run_id: int
    evaluator_id: str
    target_stage_id: str
    item_key: str
    pair_key: str
    a_lineage_key: str
    b_lineage_key: str
    direction: str
    status: StatusValue
    output_a: str | None
    output_b: str | None
    winner: str | None
    reasoning: str
    human_reviewer: str | None


class HumanJudgementSubmit(BaseModel):
    winner: Literal["A", "B", "TIE"]
    reasoning: str = ""
    human_reviewer: str = ""


class GraphRunAnalysisDto(BaseModel):
    id: int
    graph_run_id: int
    evaluator_id: str
    leaderboard_view: str
    top_entity_key: str
    top_entity_label: str
    model_id: str
    win_sample_size: int
    loss_sample_size: int
    summary: str
    created_at: datetime


class GraphRunDetail(BaseModel):
    run: GraphRunSummary
    graph: GraphSummary
    nodes: list[SemanticNodeDto]
    edges: list[SemanticEdgeDto]
    progress: GraphProgress
    diagnostics: list[GraphDiagnostic]
    leaderboards: list[GraphLeaderboardGroup]
    invocations: list[GraphInvocationDto]
    human_evals: list[GraphPairDto]
    analyses: list[GraphRunAnalysisDto]


class StartJudgeSummaryRequest(BaseModel):
    leaderboard_view: LeaderboardView = "aggregate"
    top_entity_key: str = ""
