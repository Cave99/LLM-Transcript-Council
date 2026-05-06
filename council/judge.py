"""Prompt rendering and judge response parsing."""

from __future__ import annotations

from dataclasses import dataclass

from council.elo import Winner
from council.json_tools import parse_json_object


@dataclass(frozen=True)
class ParsedJudgement:
    """Parsed result from a judge response."""

    winner: Winner
    reasoning: str


def render_template(template: str, values: dict[str, str]) -> str:
    """Render simple double-brace markdown templates.

    Keeping this tiny makes prompt files easy for non-app engineers to edit
    without learning a separate templating language.
    """

    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def render_generation_prompt(prompt: str, *, transcript: str, task_description: str) -> str:
    """Render a generator prompt with the task description and transcript."""

    return render_template(
        prompt,
        {
            "transcript": transcript,
            "task_description": task_description,
        },
    )


def render_judge_prompt(
    prompt: str,
    *,
    task_description: str,
    transcript: str,
    output_a: str,
    output_b: str,
) -> str:
    """Render a judge prompt with the task, transcript, and both outputs."""

    return render_template(
        prompt,
        {
            "task_description": task_description,
            "transcript": transcript,
            "output_a": output_a,
            "output_b": output_b,
        },
    )


def parse_judgement_response(text: str) -> ParsedJudgement:
    """Parse a judge response into a winner and short reasoning string."""

    parsed = parse_json_object(text)
    winner = str(parsed.get("winner", "TIE")).upper()
    if winner not in {"A", "B", "TIE"}:
        winner = "TIE"
    reasoning = str(parsed.get("reasoning", "")).strip()
    return ParsedJudgement(winner=winner, reasoning=reasoning)
