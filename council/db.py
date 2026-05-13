"""SQLite setup and common query helpers."""

from __future__ import annotations

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///judge_council.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    """Create tables and apply lightweight SQLite migrations in place."""

    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        graph_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(experimentgraph)").all()}
        if graph_columns and "last_run_id" not in graph_columns:
            connection.execute(text("ALTER TABLE experimentgraph ADD COLUMN last_run_id INTEGER"))
        for column_name, column_type in {
            "spec_json": "TEXT DEFAULT '{}'",
            "layout_json": "TEXT DEFAULT '{}'",
            "spec_hash": "VARCHAR DEFAULT ''",
        }.items():
            if graph_columns and column_name not in graph_columns:
                connection.execute(text(f"ALTER TABLE experimentgraph ADD COLUMN {column_name} {column_type}"))
        graph_run_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(graphrun)").all()}
        if graph_run_columns and "sample_size" not in graph_run_columns:
            connection.execute(text("ALTER TABLE graphrun ADD COLUMN sample_size INTEGER"))
        for column_name, column_type in {
            "spec_snapshot_json": "TEXT DEFAULT '{}'",
            "prompts_snapshot_json": "TEXT DEFAULT '{}'",
            "dataset_hash": "VARCHAR DEFAULT ''",
        }.items():
            if graph_run_columns and column_name not in graph_run_columns:
                connection.execute(text(f"ALTER TABLE graphrun ADD COLUMN {column_name} {column_type}"))
        graph_invocation_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(graphinvocation)").all()}
        for column_name, column_type in {
            "kind": "VARCHAR DEFAULT 'generation'",
            "stage_id": "VARCHAR DEFAULT ''",
            "candidate_id": "VARCHAR",
            "evaluator_id": "VARCHAR",
            "lineage_key": "VARCHAR DEFAULT ''",
            "model_id": "VARCHAR DEFAULT ''",
            "error_category": "VARCHAR",
        }.items():
            if graph_invocation_columns and column_name not in graph_invocation_columns:
                connection.execute(text(f"ALTER TABLE graphinvocation ADD COLUMN {column_name} {column_type}"))
        if graph_invocation_columns and "duration_seconds" not in graph_invocation_columns:
            connection.execute(text("ALTER TABLE graphinvocation ADD COLUMN duration_seconds FLOAT"))
        if graph_invocation_columns and "output_tokens_per_second" not in graph_invocation_columns:
            connection.execute(text("ALTER TABLE graphinvocation ADD COLUMN output_tokens_per_second FLOAT"))
        graph_analysis_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(graphrunanalysis)").all()}
        for column_name, column_type in {
            "evaluator_id": "VARCHAR DEFAULT ''",
            "leaderboard_view": "VARCHAR DEFAULT 'aggregate'",
            "top_entity_key": "VARCHAR DEFAULT ''",
            "top_entity_label": "VARCHAR DEFAULT ''",
        }.items():
            if graph_analysis_columns and column_name not in graph_analysis_columns:
                connection.execute(text(f"ALTER TABLE graphrunanalysis ADD COLUMN {column_name} {column_type}"))


def get_session() -> Generator[Session, None, None]:
    """Yield a session bound to the shared application engine."""

    with Session(engine) as session:
        yield session
