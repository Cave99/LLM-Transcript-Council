# Agent Guide

This repo is intentionally local, simple, and auditable. If you are an agent starting work here, use this as the shortest possible map.

## First Moves

1. Read `README.md`.
2. Inspect `backend/main.py` and the relevant `backend/api/` router for request boundaries.
3. Inspect `frontend/src/` for React screens and client-side graph behavior.
4. Inspect `council/graph_spec.py` for the canonical graph spec and validation.
5. Inspect `council/graphs.py` for graph drafts, layout, planning, and persistence.
6. Inspect `council/graph_runtime.py` for graph-native execution and leaderboards.
7. Look at prompt files in `prompts/` before changing evaluation behavior.
8. Run the tests that touch the area you edit.

## Mental Model

- `Project` groups local evaluation graphs.
- `ExperimentGraph` owns one editable graph draft.
- `ExperimentGraph.spec_json` stores the canonical dataset, constants, stages, candidates, and evaluators.
- `ExperimentGraph.layout_json` stores canvas positions for generated semantic graph nodes.
- `GraphRun` owns one graph-native execution.
- `GraphInvocation` stores generator and judge model calls, prompts, outputs, token stats, errors, and timing.
- `GraphRunAnalysis` stores judge-summary analysis for graph run leaderboards.

## Where To Look

- API routes: `backend/api/`
- API schemas: `backend/schemas.py`
- React app shell and routes: `frontend/src/app.tsx`
- API client and frontend types: `frontend/src/api/`
- React Flow graph editor: `frontend/src/features/graphs/`
- Graph run report UI: `frontend/src/features/graph-runs/`
- Background thread startup: `council/jobs.py`
- Graph drafts, sockets, and planning: `council/graphs.py`
- Graph-native execution and leaderboards: `council/graph_runtime.py`
- Judge-summary analysis: `council/analysis.py`
- Models and status enums: `council/models.py`
- Prompt rendering and parsing: `council/judge.py`
- ELO logic: `council/elo.py`
- File snapshots: `council/files.py`
- JSON helpers: `council/json_tools.py`
- Database bootstrap: `council/db.py`

## Working Boundaries

- Keep FastAPI route handlers calm: validate, call a `council/` helper, and return typed schemas.
- Keep React UI state in `frontend/src/`.
- Keep model calls out of request handlers. Use `council/jobs.py` for local background work.
- Put new graph generation or judging behavior in `council/graph_runtime.py`.
- Put graph draft/planning changes in `council/graphs.py`.
- Put new judge-summary behavior in `council/analysis.py`.
- Put pure score math in `council/elo.py`.

## Editing Style

- Keep prompt templates simple markdown.
- Keep helper functions small and direct.
- Document new functions with one short docstring that explains why the helper exists.
- When a function starts to accumulate special cases, call that out. In this repo, clarity matters more than cleverness.

## Testing

The current tests are focused on the evaluation core. When changing behavior, update or add tests near:

- `tests/test_api.py`
- `tests/test_graphs.py`
- `tests/test_elo.py`
- `tests/test_judge.py`
- `tests/test_files.py`

For frontend changes, run:

- `pnpm --filter ./frontend build`

For backend/core changes, run:

- `uv run pytest`

## Things To Preserve

- Keep graph runs explainable after graph files or node drafts change.
- Preserve persisted `GraphInvocation` evidence.
- Keep the UI calm and inspectable rather than decorative.
