# LLM-Transcript-Council

Local LLM-as-judge framework for comparing subjective LLM outputs without building a labelled dataset for every prompt iteration.

The app runs multiple generator configurations over call transcripts, asks one or more judge models to compare two outputs at a time, validates votes with swapped A/B positions, and ranks configurations with ELO.

## Start Here

If you are an agent jumping into the repo, read these in order:

1. `README.md` for the end-to-end mental model.
2. `AGENTS.md` for the shortest path to the code paths that matter.
3. `prompts/` for the markdown templates that drive runs.
4. `council/runner.py` for the top-level run lifecycle.
5. `council/generation.py`, `council/judging.py`, and `council/leaderboard.py` for execution phases.
6. `app.py` for the local UI and route handlers.

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
- `app.py` is the local FastHTML shell: routes, forms, tables, and page rendering.
- `council/models.py` defines the SQLite entities and status enums.
- `council/runner.py` owns run creation, reset/recover/stop, and the top-level execution sequence.
- `council/run_rows.py` creates derived generation, match, and leaderboard rows when a run is created.
- `council/generation.py` runs generator model calls and stores outputs.
- `council/judging.py` runs pairwise judge calls, including swapped A/B validation.
- `council/leaderboard.py` applies and rebuilds ELO leaderboard state.
- `council/run_state.py` contains shared run progress, pause checks, and run logging.
- `council/jobs.py` starts local background threads for runs and judge-pattern analysis.
- `council/analysis.py` samples judge reasoning traces and persists judge-pattern summaries.
- `council/reports.py` contains read-only reporting queries for UI tables.
- `council/judge.py` renders prompts and parses judge responses.
- `council/files.py` snapshots markdown files.
- `council/json_tools.py` repairs and parses JSON-ish model output.
- `council/elo.py` contains pure ELO and vote reconciliation logic.

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
3. `council/run_rows.py` prebuilds generation rows, sampled match rows, and initial leaderboard rows.
4. `council/jobs.py` starts a local background worker.
5. `council/runner.py` marks the run active and coordinates generation, judging, and leaderboard phases.
6. `council/generation.py` produces one output per transcript per generator config.
7. `council/judging.py` compares generator pairs with one or more judge models.
8. Swapped A/B votes are remapped back into the original positions.
9. `council/leaderboard.py` updates ELO from completed match results.
10. Everything is stored as historical evidence so earlier runs stay explainable after files change.

## Node Graphs

The newer setup path is project-scoped graphs. A graph is a local visual draft made of dataset, prompt, constant, model, and judge nodes. The graph page shows the execution plan before launch, including transcript counts, generation calls, sampled pairwise matches, and judge calls.

Current graph launch support covers:

- markdown-folder transcript datasets
- CSV datasets for chained graph runs
- in-app generator and judge prompt templates
- `{{ socket }}` discovery after prompt save
- reusable model nodes for generator or judge roles
- pairwise sample percentage and run-level A/B swap validation
- compilation into the existing run, generation, match, judgement, and ELO tables
- graph-native chained prompt runs that pass `{{ previous_output }}` between prompt stages
- raw-text or repaired-JSON upstream output mode on prompt nodes
- draggable node positioning persisted on the graph
- completed graph configs that can be forked into editable drafts

Planned extensions:

- SQL-backed test sets with stable call IDs
- labelled datasets and evaluator nodes
- BAML-backed typed parsing for structured outputs while keeping schemas simple in the UI
- batch-job submission for models that support it

## BAML Direction

BAML is a good fit for the structured-output layer, not for owning the graph itself. The graph should remain the local experiment topology: datasets, prompt stages, model configs, judge configs, sampling, and visible call counts. BAML can be introduced underneath prompt nodes later to improve typed parsing and generated output formats while keeping schemas hidden behind simple UI controls.

## Working Boundaries

- Put route handlers and HTML-rendering helpers in `app.py`.
- Put background-thread launch mechanics in `council/jobs.py`.
- Put model-call phases in `council/generation.py`, `council/judging.py`, or `council/analysis.py`.
- Put read-only UI metrics in `council/reports.py`.
- Keep `council/runner.py` as the short lifecycle coordinator rather than a home for every run detail.
- Keep pure scoring/vote math in `council/elo.py`.

## Editing Rules

- Prefer small markdown prompts over complex prompt frameworks.
- Prefer snapshotting inputs at run creation over live references.
- Prefer single-purpose helpers in `council/` and thin UI code in `app.py`.
- If you add new runtime behavior, document the function and add a test where practical.

## Notes

OpenRouter model IDs are entered manually. The app snapshots all prompt, transcript, model, and temperature settings at run creation, so previous results remain auditable even when files change later.
