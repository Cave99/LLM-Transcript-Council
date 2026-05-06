"""File loading and snapshot helpers for markdown-backed projects."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class FileSnapshot:
    """Immutable content snapshot captured from disk at run creation."""

    path: str
    content: str
    content_hash: str


def read_text_snapshot(path: str | Path) -> FileSnapshot:
    """Read a UTF-8 markdown file and return content plus a stable hash."""

    resolved = Path(path).expanduser().resolve()
    content = resolved.read_text(encoding="utf-8")
    return FileSnapshot(
        path=str(resolved),
        content=content,
        content_hash=sha256(content.encode("utf-8")).hexdigest(),
    )


def list_markdown_files(root: str | Path) -> list[Path]:
    """Return markdown files under a directory in stable order."""

    resolved = Path(root).expanduser().resolve()
    if not resolved.exists():
        return []
    if resolved.is_file():
        return [resolved] if resolved.suffix.lower() == ".md" else []
    return sorted(path for path in resolved.rglob("*.md") if path.is_file())
