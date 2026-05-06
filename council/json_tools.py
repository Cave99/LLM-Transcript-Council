"""Small JSON parsing helpers for LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM response.

    The judge prompt asks for exact JSON, but this helper accepts fenced blocks
    and surrounding prose so one mildly untidy judge response does not break a
    whole run.
    """

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed


def maybe_repair_json(text: str) -> str:
    """Repair JSON-like output when json_repair is installed; otherwise no-op."""

    try:
        from json_repair import repair_json
    except ImportError:
        return text
    try:
        return repair_json(text)
    except Exception:
        return text

