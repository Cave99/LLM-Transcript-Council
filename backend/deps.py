"""Backend request dependencies."""

from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session

from council.db import engine


def get_session() -> Generator[Session, None, None]:
    """Yield one database session for a request."""

    with Session(engine) as session:
        yield session

