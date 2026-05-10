"""Read-only reporting queries used by the local UI."""

from __future__ import annotations

from sqlmodel import Session, select

from council.elo import consistent_swapped_vote
from council.models import Generation, GeneratorConfig, JudgeConfig, Judgement, Match, Status


def generation_throughput(session: Session, run_id: int) -> list[dict[str, str]]:
    """Aggregate generation timing and token throughput by config."""

    rows = session.exec(
        select(Generation, GeneratorConfig)
        .where(Generation.run_id == run_id)
        .where(Generation.generator_config_id == GeneratorConfig.id)
        .where(Generation.status == Status.complete)
    ).all()
    by_config: dict[int, dict] = {}
    for generation, config in rows:
        if not generation.started_at or not generation.completed_at:
            continue
        seconds = max((generation.completed_at - generation.started_at).total_seconds(), 0.001)
        output_tokens = generation.completion_tokens or 0
        total_tokens = (generation.prompt_tokens or 0) + output_tokens
        bucket = by_config.setdefault(
            config.id,
            {
                "label": config.label,
                "model": config.model_id,
                "calls": 0,
                "seconds": 0.0,
                "output_tokens": 0,
                "total_tokens": 0,
                "recent_completed_at": None,
                "recent_tps": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["seconds"] += seconds
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        if not bucket["recent_completed_at"] or generation.completed_at > bucket["recent_completed_at"]:
            bucket["recent_completed_at"] = generation.completed_at
            bucket["recent_tps"] = output_tokens / seconds if output_tokens else 0.0
    return _format_throughput_rows(by_config)


def judgement_throughput(session: Session, run_id: int) -> list[dict[str, str]]:
    """Aggregate judge timing and token throughput by config."""

    rows = session.exec(
        select(Judgement, JudgeConfig, Match)
        .where(Match.run_id == run_id)
        .where(Judgement.match_id == Match.id)
        .where(Judgement.judge_config_id == JudgeConfig.id)
        .where(Judgement.error == None)  # noqa: E711
    ).all()
    by_config: dict[int, dict] = {}
    for judgement, judge, _match in rows:
        if not judgement.started_at or not judgement.completed_at:
            continue
        seconds = max((judgement.completed_at - judgement.started_at).total_seconds(), 0.001)
        output_tokens = judgement.completion_tokens or 0
        total_tokens = (judgement.prompt_tokens or 0) + output_tokens
        bucket = by_config.setdefault(
            judge.id,
            {
                "label": judge.label,
                "model": judge.model_id,
                "calls": 0,
                "seconds": 0.0,
                "output_tokens": 0,
                "total_tokens": 0,
                "recent_completed_at": None,
                "recent_tps": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["seconds"] += seconds
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        if not bucket["recent_completed_at"] or judgement.completed_at > bucket["recent_completed_at"]:
            bucket["recent_completed_at"] = judgement.completed_at
            bucket["recent_tps"] = output_tokens / seconds if output_tokens else 0.0
    return _format_throughput_rows(by_config)


def judge_favorite_map(session: Session, run_id: int, judges: list[JudgeConfig]) -> dict[int, list[tuple[JudgeConfig, int]]]:
    """Map each generator config to the judges that favor it most."""

    matches = session.exec(select(Match).where(Match.run_id == run_id, Match.status == Status.complete)).all()
    tallies: dict[int, dict[int, int]] = {judge.id: {} for judge in judges if judge.id is not None}
    judge_lookup = {judge.id: judge for judge in judges if judge.id is not None}

    for match in matches:
        for judge_id in judge_lookup:
            normal = session.exec(
                select(Judgement).where(
                    Judgement.match_id == match.id,
                    Judgement.judge_config_id == judge_id,
                    Judgement.direction == "normal",
                )
            ).first()
            swapped = session.exec(
                select(Judgement).where(
                    Judgement.match_id == match.id,
                    Judgement.judge_config_id == judge_id,
                    Judgement.direction == "swapped",
                )
            ).first()
            if not normal or not swapped:
                continue
            winner = consistent_swapped_vote(normal.winner, swapped.winner)
            if winner == "A":
                config_id = match.config_a_id
            elif winner == "B":
                config_id = match.config_b_id
            else:
                continue
            tallies[judge_id][config_id] = tallies[judge_id].get(config_id, 0) + 1

    favorites: dict[int, list[tuple[JudgeConfig, int]]] = {}
    for judge_id, config_counts in tallies.items():
        if not config_counts:
            continue
        favorite_id, wins = max(config_counts.items(), key=lambda item: item[1])
        favorites.setdefault(favorite_id, []).append((judge_lookup[judge_id], wins))
    return favorites


def generation_token_averages(session: Session, run_id: int) -> dict[int, str]:
    """Return average total tokens per completed generation by config."""

    rows = session.exec(
        select(Generation, GeneratorConfig)
        .where(Generation.run_id == run_id)
        .where(Generation.generator_config_id == GeneratorConfig.id)
        .where(Generation.status == Status.complete)
    ).all()
    by_config: dict[int, list[int]] = {}
    for generation, config in rows:
        total = (generation.prompt_tokens or 0) + (generation.completion_tokens or 0)
        by_config.setdefault(config.id, []).append(total)
    return {
        config_id: f"{sum(tokens) // len(tokens):,}"
        for config_id, tokens in by_config.items()
    }


def _format_throughput_rows(by_config: dict[int, dict]) -> list[dict[str, str]]:
    """Normalize raw timing buckets for table rendering."""

    metrics = []
    for bucket in by_config.values():
        avg_tps = bucket["output_tokens"] / bucket["seconds"] if bucket["seconds"] else 0.0
        avg_latency = bucket["seconds"] / bucket["calls"] if bucket["calls"] else 0.0
        metrics.append(
            {
                "label": bucket["label"],
                "model": bucket["model"],
                "calls": str(bucket["calls"]),
                "avg_tps": f"{avg_tps:.1f}",
                "recent_tps": f"{bucket['recent_tps']:.1f}",
                "avg_latency": f"{avg_latency:.1f}s",
                "output_tokens": f"{bucket['output_tokens']:,}",
                "total_tokens": f"{bucket['total_tokens']:,}",
            }
        )
    return sorted(metrics, key=lambda row: float(row["avg_tps"]), reverse=True)
