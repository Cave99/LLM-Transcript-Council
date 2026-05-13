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
    last_run_id: Optional[int] = Field(default=None)
    spec_json: str = "{}"
    layout_json: str = "{}"
    spec_hash: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: int = Field(foreign_key="experimentgraph.id")
    name: str
    status: Status = Status.pending
    max_concurrency: int = 5
    sample_size: Optional[int] = None
    spec_snapshot_json: str = "{}"
    prompts_snapshot_json: str = "{}"
    dataset_hash: str = ""
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GraphInvocation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_run_id: int = Field(foreign_key="graphrun.id")
    node_id: int = 0
    model_node_id: Optional[int] = None
    kind: str = "generation"
    stage_id: str = ""
    candidate_id: Optional[str] = None
    evaluator_id: Optional[str] = None
    lineage_key: str = ""
    model_id: str = ""
    item_key: str
    stage_index: int = 0
    status: Status = Status.pending
    rendered_prompt: str = ""
    output_raw: Optional[str] = None
    output_json: Optional[str] = None
    error: Optional[str] = None
    error_category: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    duration_seconds: Optional[float] = None
    output_tokens_per_second: Optional[float] = None
    cost: Optional[float] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GraphPair(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_run_id: int = Field(foreign_key="graphrun.id")
    evaluator_id: str
    target_stage_id: str
    item_key: str
    pair_key: str
    a_invocation_id: int = Field(foreign_key="graphinvocation.id")
    b_invocation_id: int = Field(foreign_key="graphinvocation.id")
    a_lineage_key: str
    b_lineage_key: str
    direction: str = "normal"
    status: Status = Status.pending
    created_at: datetime = Field(default_factory=utc_now)


class GraphJudgement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int = Field(foreign_key="graphpair.id")
    evaluator_type: str
    judge_invocation_id: Optional[int] = Field(default=None, foreign_key="graphinvocation.id")
    human_reviewer: Optional[str] = None
    winner: Optional[str] = None
    reasoning: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphRunAnalysis(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_run_id: int = Field(foreign_key="graphrun.id")
    top_model_node_id: Optional[int] = None
    judge_prompt_node_id: Optional[int] = None
    evaluator_id: str = ""
    leaderboard_view: str = "aggregate"
    top_entity_key: str = ""
    top_entity_label: str = ""
    model_id: str
    win_sample_size: int = 0
    loss_sample_size: int = 0
    summary: str
    prompt_snapshot: str
    created_at: datetime = Field(default_factory=utc_now)
