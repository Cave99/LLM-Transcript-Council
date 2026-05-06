# Agent Guide

This repo is intentionally local, simple, and auditable. If you are an agent starting work here, use this as the shortest possible map.

## First Moves

1. Read `README.md`.
2. Inspect `council/runner.py` for the top-level run lifecycle.
3. Inspect `app.py` for the UI and route handlers.
4. Inspect the phase module for the thing you are changing.
5. Look at the prompt files in `prompts/` before changing evaluation behavior.
6. Run the tests that touch the area you edit.

## Mental Model

- `Task` owns the snapshot of the evaluation question.
- `Run` owns one experiment with fixed generator and judge configs.
- `Generation` stores one model output for one transcript.
- `Match` stores one pairwise comparison between two generator configs.
- `Judgement` stores each judge vote, including swapped A/B validation.
- `MatchResult` stores the final winner and agreement.
- `EloRating` stores the leaderboard state for a run.

## Where To Look

- UI routes and rendering: `app.py`
- Run lifecycle and public run actions: `council/runner.py`
- Background thread startup: `council/jobs.py`
- Derived work rows: `council/run_rows.py`
- Generation phase: `council/generation.py`
- Judging phase and swapped A/B calls: `council/judging.py`
- Leaderboard persistence: `council/leaderboard.py`
- Run progress, pause checks, and logs: `council/run_state.py`
- Judge-pattern analysis: `council/analysis.py`
- Read-only UI metrics and report queries: `council/reports.py`
- Models and status enums: `council/models.py`
- Prompt rendering and parsing: `council/judge.py`
- ELO logic: `council/elo.py`
- File snapshots: `council/files.py`
- JSON helpers: `council/json_tools.py`
- Database bootstrap: `council/db.py`

## Working Boundaries

- Keep `app.py` calm: route handlers should validate, call a `council/` helper, and render or redirect.
- Keep model calls out of request handlers. Use `council/jobs.py` for local background work.
- Keep `council/runner.py` short. It should coordinate phases, not own phase details.
- Put new generation behavior in `council/generation.py`.
- Put new judge behavior in `council/judging.py`.
- Put new analysis/reporting behavior in `council/analysis.py` or `council/reports.py`.
- Put pure score math in `council/elo.py`; put persisted leaderboard changes in `council/leaderboard.py`.

## Editing Style

- Keep prompt templates simple markdown.
- Keep helper functions small and direct.
- Document new functions with one short docstring that explains why the helper exists.
- When a function starts to accumulate special cases, call that out. In this repo, clarity matters more than cleverness.

## Testing

The current tests are focused on the evaluation core. When changing behavior, update or add tests near:

- `tests/test_runner.py`
- `tests/test_elo.py`
- `tests/test_judge.py`
- `tests/test_files.py`

## Things To Preserve

- Snapshot inputs at run creation.
- Keep runs explainable after files change.
- Preserve swapped A/B validation for judging.
- Keep the UI calm and inspectable rather than decorative.
