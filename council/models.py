"""Database models.

The database is both the app state and the audit trail. Runs snapshot file
contents and config values so old leaderboards remain explainable after prompt
files or transcripts evolve.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for database defaults."""

    return datetime.now(timezone.utc)


class Status(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"
    paused = "paused"


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utc_now)


class GraphStatus(str, Enum):
    draft = "draft"
    running = "running"
    complete = "complete"
    failed = "failed"
    paused = "paused"


class ExperimentGraph(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    status: GraphStatus = GraphStatus.draft
    last_run_id: Optional[int] = Field(default=None, foreign_key="run.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphNode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: int = Field(foreign_key="experimentgraph.id")
    kind: str
    title: str
    body: str = ""
    config_json: str = "{}"
    x: int = 0
    y: int = 0
    width: int = 460
    height: int = 260
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphEdge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: int = Field(foreign_key="experimentgraph.id")
    from_node_id: int = Field(foreign_key="graphnode.id")
    from_socket: str
    to_node_id: int = Field(foreign_key="graphnode.id")
    to_socket: str
    created_at: datetime = Field(default_factory=utc_now)


class GraphRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: int = Field(foreign_key="experimentgraph.id")
    name: str
    status: Status = Status.pending
    max_concurrency: int = 5
    sample_size: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GraphInvocation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_run_id: int = Field(foreign_key="graphrun.id")
    node_id: int = Field(foreign_key="graphnode.id")
    model_node_id: Optional[int] = Field(default=None, foreign_key="graphnode.id")
    item_key: str
    stage_index: int = 0
    status: Status = Status.pending
    rendered_prompt: str = ""
    output_raw: Optional[str] = None
    output_json: Optional[str] = None
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    duration_seconds: Optional[float] = None
    output_tokens_per_second: Optional[float] = None
    cost: Optional[float] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    description_path: str
    description_snapshot: str
    description_hash: str
    transcript_root: str
    default_judge_prompt_path: str
    default_pairing_sample_pct: float = 100.0
    default_swap_enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id")
    name: str
    status: Status = Status.pending
    pairing_strategy: str = "round_robin_sampled"
    swap_enabled: bool = True
    elo_start: float = 1500.0
    k_factor: float = 32.0
    max_concurrency: int = 5
    sample_size: Optional[int] = None
    pairing_sample_pct: float = 100.0
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class RunLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    level: str = "info"
    message: str
    created_at: datetime = Field(default_factory=utc_now)


class RunAnalysis(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    model_id: str
    sample_size: int
    summary: str
    prompt_snapshot: str
    created_at: datetime = Field(default_factory=utc_now)


class GraphRunAnalysis(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_run_id: int = Field(foreign_key="graphrun.id")
    top_model_node_id: int = Field(foreign_key="graphnode.id")
    judge_prompt_node_id: Optional[int] = Field(default=None, foreign_key="graphnode.id")
    leaderboard_view: str = "aggregate"
    top_entity_key: str = ""
    top_entity_label: str = ""
    model_id: str
    win_sample_size: int = 0
    loss_sample_size: int = 0
    summary: str
    prompt_snapshot: str
    created_at: datetime = Field(default_factory=utc_now)


class GeneratorConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    label: str
    model_id: str
    temperature: float = 0.2
    prompt_path: str
    prompt_snapshot: str
    prompt_hash: str


class JudgeConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    label: str
    model_id: str
    temperature: float = 0.0
    prompt_path: str
    prompt_snapshot: str
    prompt_hash: str


class Transcript(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    path: str
    content_snapshot: str
    content_hash: str


class Generation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    transcript_id: int = Field(foreign_key="transcript.id")
    generator_config_id: int = Field(foreign_key="generatorconfig.id")
    status: Status = Status.pending
    output_raw: Optional[str] = None
    output_repaired: Optional[str] = None
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost: Optional[float] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Match(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    transcript_id: int = Field(foreign_key="transcript.id")
    generation_a_id: int = Field(foreign_key="generation.id")
    generation_b_id: int = Field(foreign_key="generation.id")
    config_a_id: int = Field(foreign_key="generatorconfig.id")
    config_b_id: int = Field(foreign_key="generatorconfig.id")
    status: Status = Status.pending


class Judgement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id")
    judge_config_id: int = Field(foreign_key="judgeconfig.id")
    direction: str
    winner: str
    reasoning: str
    raw_response: str
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)


class MatchResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", unique=True)
    final_winner: str
    agreement: float
    votes_json: str
    created_at: datetime = Field(default_factory=utc_now)


class EloRating(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    generator_config_id: int = Field(foreign_key="generatorconfig.id")
    rating: float = 1500.0
    wins: int = 0
    losses: int = 0
    ties: int = 0
