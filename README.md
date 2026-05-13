# LLM-Transcript-Council

Local LLM-as-judge framework for comparing subjective LLM outputs without building a labelled dataset for every prompt iteration.

The app lets users draft graph-native LLM evaluation workflows, run prompt/model chains over transcript or CSV datasets, ask judge models to compare outputs, and rank configurations with ELO-style leaderboards.

## Start Here

If you are an agent jumping into the repo, read these in order:

1. `README.md` for the end-to-end mental model.
2. `AGENTS.md` for the shortest path to the code paths that matter.
3. `prompts/` for the markdown templates that drive runs.
4. `backend/main.py` and `backend/api/` for the JSON API layer.
5. `frontend/src/` for the React UI.
6. `council/graphs.py` and `council/graph_runtime.py` for graph planning and execution.

## Quick Start

```bash
cp .env.example .env
# Add OPENROUTER_API_KEY to .env
uv sync --extra dev --extra repair
pnpm install
pnpm dev
```

Open `http://127.0.0.1:5173`.

The split app runs a FastAPI backend on `http://127.0.0.1:8000` and a Vite React frontend on `http://127.0.0.1:5173`. Vite proxies `/api` requests to FastAPI during local development.

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
- `backend/` is the FastAPI API layer for the graph-native workflow.
- `frontend/` is the React, TypeScript, Tailwind, shadcn-style, and React Flow UI.
- `council/models.py` defines the SQLite entities and status enums.
- `council/graph_spec.py` defines the canonical graph spec, validation, hashing, and generated semantic layout.
- `council/graphs.py` owns graph drafts, layout, and planning.
- `council/graph_runtime.py` executes graph-native runs and computes graph-native leaderboards.
- `council/jobs.py` starts local background threads for graph runs and judge-summary analysis.
- `council/analysis.py` samples graph judge reasoning traces and persists judge summaries.
- `council/judge.py` renders prompts and parses judge responses.
- `council/files.py` snapshots markdown files.
- `council/json_tools.py` repairs and parses JSON-ish model output.
- `council/elo.py` contains pure ELO math used by graph-native leaderboards.

## Prompt Placeholders

Templates support a small set of placeholders:

- `{{ task_description }}`
- `{{ transcript }}`
- `{{ output_a }}`
- `{{ output_b }}`

Keep prompt files markdown-only and simple. The renderer does straight string replacement, so there is no looping, conditionals, or expression language.

## Run Defaults

- SQLite database: `judge_council.db`
- graph-native runs default to max concurrency 5
- test runs use one dataset item
- full runs use the dataset node selection
- judge prompts can sample pairwise comparisons
- ELO starts at 1500

## Data Flow

1. A project owns one or more local experiment graphs.
2. A graph stores dataset config, constants, prompt stages, model candidates, and evaluators in one canonical spec.
3. `council/graphs.py` computes the launch plan and warnings from the persisted spec.
4. The React UI launches a graph run through `POST /api/graphs/{id}/launch`.
5. `council/jobs.py` starts a local background thread.
6. `council/graph_runtime.py` executes prompt stages over each dataset item and model branch.
7. Judge prompt nodes compare branch pairs and persist each judge call as a `GraphInvocation`.
8. Graph run pages compute progress, diagnostics, model output groups, judge summaries, and ELO-style leaderboards from persisted invocation evidence.

## Frontend / Backend Split

The graph-native workflow is now exposed through JSON APIs under `/api`:

- `/api/projects` for project CRUD and recent graph runs
- `/api/graphs` for graph drafts, planning, launch, fork, and delete
- `/api/graph-runs` for run reports, stop, continue, retry failures, and progress events
- `/api/graph-runs/{id}/judge-summary` for background judge-summary analysis

The React app is intentionally styled to match the original calm local workbench. Tailwind design tokens mirror the OKLCH colors in `DESIGN.md`; shadcn-style primitives are local components in `frontend/src/components/ui/`.

## Node Graphs

The setup path is project-scoped graphs. A graph is a local visual draft generated from a canonical spec with dataset config, constants, prompt stages, model candidates, and evaluators. The graph page shows the execution plan before launch, including transcript counts, generation calls, sampled pairwise matches, and judge calls.

Current graph launch support covers:

- markdown-folder transcript datasets
- CSV datasets for chained graph runs
- in-app generator and judge prompt templates
- reusable model nodes for generator or judge roles
- pairwise sample percentage and run-level A/B swap validation
- graph-native chained prompt runs that pass `{{ previous_output }}` between prompt stages
- raw-text or repaired-JSON upstream output mode on prompt nodes
- draggable semantic node positioning persisted on the graph
- completed graph configs that can be forked into editable drafts
- React Flow graph editing through the Vite frontend

Planned extensions:

- SQL-backed test sets with stable call IDs
- labelled datasets and evaluator nodes
- BAML-backed typed parsing for structured outputs while keeping schemas simple in the UI
- batch-job submission for models that support it

## BAML Direction

BAML is a good fit for the structured-output layer, not for owning the graph itself. The graph should remain the local experiment topology: datasets, prompt stages, model configs, judge configs, sampling, and visible call counts. BAML can be introduced underneath prompt nodes later to improve typed parsing and generated output formats while keeping schemas hidden behind simple UI controls.

## Working Boundaries

- Put API route handlers in `backend/api/`.
- Put React screens and graph UI in `frontend/src/`.
- Put background-thread launch mechanics in `council/jobs.py`.
- Put graph runtime behavior in `council/graph_runtime.py`.
- Put graph draft/planning behavior in `council/graphs.py`.
- Put judge-summary behavior in `council/analysis.py`.
- Keep pure scoring/vote math in `council/elo.py`.

## Editing Rules

- Prefer small markdown prompts over complex prompt frameworks.
- Prefer snapshotting inputs at run creation over live references.
- Prefer single-purpose helpers in `council/`, thin FastAPI route handlers, and typed React API calls.
- If you add new runtime behavior, document the function and add a test where practical.

## Notes

OpenRouter model IDs are entered manually. Graph run evidence is persisted in `GraphInvocation` rows so previous results remain auditable even when graph drafts change later.
