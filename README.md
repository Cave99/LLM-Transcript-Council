# LLM-Transcript-Council

Local LLM-as-judge framework for comparing subjective LLM outputs without building a labelled dataset for every prompt iteration.

The app runs multiple generator configurations over call transcripts, asks one or more judge models to compare two outputs at a time, validates votes with swapped A/B positions, and ranks configurations with ELO.

## Quick Start

```bash
cp .env.example .env
# Add OPENROUTER_API_KEY to .env
uv sync --extra dev --extra repair
uv run python app.py
```

Open `http://127.0.0.1:5001`.

## Mental Model

Use this when the output quality is subjective:

- coaching advice
- positive/negative feedback
- emotional interpretation
- qualitative summaries
- "which prompt/model produces the better answer?"

Instead of tuning a judge rubric for every project, the default judge prompt compares two blind outputs with universal quality lenses: specificity, actionability, coherence, groundedness, and completeness.

## Files

- Task descriptions are markdown files in `prompts/tasks/`.
- Generator prompts are markdown files in `prompts/generators/`.
- Judge prompts are markdown files in `prompts/judges/`.
- Transcripts are markdown files in `transcripts/`.

Templates support simple placeholders:

- `{{ task_description }}`
- `{{ transcript }}`
- `{{ output_a }}`
- `{{ output_b }}`

## Run Defaults

- SQLite database: `judge_council.db`
- 3 judge configs recommended
- A/B swap validation enabled
- ELO starts at 1500
- K-factor is 32
- Max concurrent LLM calls defaults to 5

## Notes

OpenRouter model IDs are entered manually. The app snapshots all prompt, transcript, model, and temperature settings at run creation, so previous results remain auditable even when files change later.
