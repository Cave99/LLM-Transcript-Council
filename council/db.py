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
        generation_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(generation)").all()}
        if "started_at" not in generation_columns:
            connection.execute(text("ALTER TABLE generation ADD COLUMN started_at DATETIME"))
        run_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(run)").all()}
        if "pairing_sample_pct" not in run_columns:
            connection.execute(text("ALTER TABLE run ADD COLUMN pairing_sample_pct FLOAT DEFAULT 100.0"))
        task_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(task)").all()}
        if "default_pairing_sample_pct" not in task_columns:
            connection.execute(text("ALTER TABLE task ADD COLUMN default_pairing_sample_pct FLOAT DEFAULT 100.0"))
        if "default_swap_enabled" not in task_columns:
            connection.execute(text("ALTER TABLE task ADD COLUMN default_swap_enabled BOOLEAN DEFAULT 1"))
        judgement_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(judgement)").all()}
        for column_name, column_type in {
            "prompt_tokens": "INTEGER",
            "completion_tokens": "INTEGER",
            "cost": "FLOAT",
            "started_at": "DATETIME",
            "completed_at": "DATETIME",
        }.items():
            if column_name not in judgement_columns:
                connection.execute(text(f"ALTER TABLE judgement ADD COLUMN {column_name} {column_type}"))


def get_session() -> Generator[Session, None, None]:
    """Yield a session bound to the shared application engine."""

    with Session(engine) as session:
        yield session
