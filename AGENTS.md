# Agent Guide

This repo is intentionally local, simple, and auditable. If you are an agent starting work here, use this as the shortest possible map.

## First Moves

1. Read `README.md`.
2. Inspect `backend/main.py` and the relevant `backend/api/` router for request boundaries.
3. Inspect `frontend/src/` for React screens and client-side graph behavior.
4. Inspect `council/graphs.py` for graph drafts, sockets, planning, and node/edge persistence.
5. Inspect `council/graph_runtime.py` for graph-native execution and leaderboards.
6. Look at prompt files in `prompts/` before changing evaluation behavior.
7. Run the tests that touch the area you edit.

## Mental Model

- `Project` groups local evaluation graphs.
- `ExperimentGraph` owns one editable graph draft.
- `GraphNode` stores dataset, prompt, constant, model, and judge nodes.
- `GraphEdge` stores socket-level graph connections.
- `GraphRun` owns one graph-native execution.
- `GraphInvocation` stores generator and judge model calls, prompts, outputs, token stats, errors, and timing.
- `GraphRunAnalysis` stores judge-summary analysis for graph run leaderboards.
- Traditional `Task`, `Run`, `Generation`, `Match`, `Judgement`, `MatchResult`, and `EloRating` models are legacy migration leftovers. Do not build new behavior on them.

## Where To Look

- API routes: `backend/api/`
- API schemas: `backend/schemas.py`
- React app shell and routes: `frontend/src/app.tsx`
- API client and frontend types: `frontend/src/api/`
- React Flow graph editor: `frontend/src/features/graphs/` and `frontend/src/features/graph-editor/`
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
- Legacy FastHTML UI: `app.py`
- Legacy traditional-run modules: `council/runner.py`, `council/generation.py`, `council/judging.py`, `council/leaderboard.py`, `council/run_rows.py`, `council/run_state.py`, `council/reports.py`

## Working Boundaries

- Keep FastAPI route handlers calm: validate, call a `council/` helper, and return typed schemas.
- Keep React UI state in `frontend/src/`; do not add new UI to legacy `app.py`.
- Keep model calls out of request handlers. Use `council/jobs.py` for local background work.
- Put new graph generation or judging behavior in `council/graph_runtime.py`.
- Put graph draft/planning changes in `council/graphs.py`.
- Put new judge-summary behavior in `council/analysis.py`.
- Put pure score math in `council/elo.py`.
- Keep legacy traditional-run modules stable until they are intentionally deleted in a cleanup phase.

## Editing Style

- Keep prompt templates simple markdown.
- Keep helper functions small and direct.
- Document new functions with one short docstring that explains why the helper exists.
- When a function starts to accumulate special cases, call that out. In this repo, clarity matters more than cleverness.

## Testing

The current tests are focused on the evaluation core. When changing behavior, update or add tests near:

- `tests/test_api.py`
- `tests/test_graphs.py`
- `tests/test_runner.py`
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
