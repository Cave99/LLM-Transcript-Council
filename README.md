# LLM-Transcript-Council

Local LLM-as-judge framework for comparing subjective LLM outputs without building a labelled dataset for every prompt iteration.

The app runs multiple generator configurations over call transcripts, asks one or more judge models to compare two outputs at a time, validates votes with swapped A/B positions, and ranks configurations with ELO.

## Start Here

If you are an agent jumping into the repo, read these in order:

1. `README.md` for the end-to-end mental model.
2. `AGENTS.md` for the shortest path to the code paths that matter.
3. `prompts/` for the markdown templates that drive runs.
4. `council/runner.py` for the generation and judging pipeline.
5. `app.py` for the local UI and route handlers.

## Quick Start

```bash
cp .env.example .env
# Add OPENROUTER_API_KEY to .env
uv sync --extra dev --extra repair
uv run python app.py
```

Open `http://127.0.0.1:5001`.

## What This App Does

Use this when the output quality is subjective:

- coaching advice
- positive or negative feedback
- emotional interpretation
- qualitative summaries
- "which prompt/model produces the better answer?"

Instead of tuning a judge rubric for every project, the default judge prompt compares two blind outputs with universal quality lenses: specificity, actionability, coherence, groundedness, and completeness.

## Repo Map

- Task descriptions live in `prompts/tasks/`.
- Generator prompts live in `prompts/generators/`.
- Judge prompts live in `prompts/judges/`.
- Transcript markdown lives in `transcripts/`.
- The SQLite schema and entity definitions live in `council/models.py`.
- The run orchestration pipeline lives in `council/runner.py`.
- Prompt rendering and judge parsing live in `council/judge.py`.
- File snapshotting lives in `council/files.py`.
- JSON repair and parsing helpers live in `council/json_tools.py`.
- ELO and vote logic live in `council/elo.py`.
- The local FastHTML app shell and routes live in `app.py`.

## Prompt Placeholders

Templates support a small set of placeholders:

- `{{ task_description }}`
- `{{ transcript }}`
- `{{ output_a }}`
- `{{ output_b }}`

Keep prompt files markdown-only and simple. The renderer does straight string replacement, so there is no looping, conditionals, or expression language.

## Run Defaults

- SQLite database: `judge_council.db`
- 3 judge configs recommended
- A/B swap validation enabled
- ELO starts at 1500
- K-factor is 32
- Max concurrent LLM calls defaults to 5

## Data Flow

1. A task snapshots a task description, transcript root, and default judge prompt.
2. A run snapshots generator prompts, judge prompts, model IDs, temperatures, and transcripts.
3. Generation jobs produce one output per transcript per generator config.
4. Match jobs compare generator pairs with one or more judge models.
5. Swapped A/B votes are remapped back into the original positions.
6. Match results update the leaderboard through ELO.
7. Everything is stored as historical evidence so earlier runs stay explainable after files change.

## Editing Rules

- Prefer small markdown prompts over complex prompt frameworks.
- Prefer snapshotting inputs at run creation over live references.
- Prefer single-purpose helpers in `council/` and thin UI code in `app.py`.
- If you add new runtime behavior, document the function and add a test where practical.

## Notes

OpenRouter model IDs are entered manually. The app snapshots all prompt, transcript, model, and temperature settings at run creation, so previous results remain auditable even when files change later.
