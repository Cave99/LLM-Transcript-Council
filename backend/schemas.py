"""Pydantic schemas for the graph-native API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


NodeKind = Literal["dataset", "prompt", "constant", "model", "judge"]
StatusValue = Literal["pending", "running", "complete", "failed", "paused"]
GraphStatusValue = Literal["draft", "running", "complete", "failed", "paused"]
LeaderboardView = Literal["aggregate", "overall", "chain"]


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


class GraphUpdate(BaseModel):
    name: str


class GraphNodeDto(BaseModel):
    id: int
    graph_id: int
    kind: str
    title: str
    body: str
    config: dict[str, Any]
    x: int
    y: int
    width: int
    height: int
    input_sockets: list[str]
    output_sockets: list[str]
    created_at: datetime
    updated_at: datetime


class GraphEdgeDto(BaseModel):
    id: int
    graph_id: int
    from_node_id: int
    from_socket: str
    to_node_id: int
    to_socket: str
    created_at: datetime


class GraphPlanDto(BaseModel):
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
    warnings: list[str]


class GraphDetail(BaseModel):
    graph: GraphSummary
    nodes: list[GraphNodeDto]
    edges: list[GraphEdgeDto]
    plan: GraphPlanDto
    latest_run: GraphRunSummary | None = None
    graph_runs: list[GraphRunSummary] = Field(default_factory=list)


class LaunchGraphRunRequest(BaseModel):
    run_mode: Literal["test", "full"] = "full"
    max_concurrency: int = Field(default=5, ge=1, le=50)


class CreateNodeRequest(BaseModel):
    kind: NodeKind
    title: str | None = None
    x: int | None = None
    y: int | None = None


class UpdateNodeRequest(BaseModel):
    title: str
    body: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class UpdateNodePositionRequest(BaseModel):
    x: int
    y: int
    width: int | None = None
    height: int | None = None


class CreateEdgeRequest(BaseModel):
    from_node_id: int
    from_socket: str
    to_node_id: int
    to_socket: str


class DeleteSocketEdgesRequest(BaseModel):
    node_id: int
    socket: str
    side: Literal["input", "output"]


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
    node_id: int | None
    rating: float
    wins: int
    losses: int
    ties: int
    avg_tokens: str
    favorites: list[LeaderboardFavorite]


class GraphLeaderboardGroup(BaseModel):
    title: str
    judge_prompt_node_id: int | None
    view_mode: LeaderboardView
    rows: list[GraphLeaderboardRow]


class GraphInvocationDto(BaseModel):
    id: int
    graph_run_id: int
    node_id: int
    model_node_id: int | None
    node_title: str
    model_title: str | None
    item_key: str
    stage_index: int
    status: StatusValue
    rendered_prompt: str
    output_raw: str | None
    output_json: str | None
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_seconds: float | None
    output_tokens_per_second: float | None
    cost: float | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class GraphRunAnalysisDto(BaseModel):
    id: int
    graph_run_id: int
    top_model_node_id: int
    judge_prompt_node_id: int | None
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
    nodes: list[GraphNodeDto]
    edges: list[GraphEdgeDto]
    progress: GraphProgress
    node_progress: dict[int, GraphProgress]
    diagnostics: list[GraphDiagnostic]
    leaderboards: list[GraphLeaderboardGroup]
    invocations: list[GraphInvocationDto]
    analyses: list[GraphRunAnalysisDto]


class StartJudgeSummaryRequest(BaseModel):
    judge_prompt_node_id: int | None = None
    leaderboard_view: LeaderboardView = "aggregate"
    top_entity_key: str = ""
