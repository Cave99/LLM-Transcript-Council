"""Create derived run work rows from snapshotted inputs."""

from __future__ import annotations

import itertools
import random

from sqlmodel import Session, select

from council.models import EloRating, Generation, GeneratorConfig, Match, Run, Transcript


def ensure_generation_rows(session: Session, run_id: int) -> None:
    """Create missing generation rows for every transcript/config pair."""

    transcripts = session.exec(select(Transcript).where(Transcript.run_id == run_id)).all()
    configs = session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
    existing = {
        (row.transcript_id, row.generator_config_id)
        for row in session.exec(select(Generation).where(Generation.run_id == run_id)).all()
    }
    for transcript, config in itertools.product(transcripts, configs):
        if (transcript.id, config.id) not in existing:
            session.add(
                Generation(
                    run_id=run_id,
                    transcript_id=transcript.id,
                    generator_config_id=config.id,
                )
            )
    session.commit()


def ensure_match_rows(session: Session, run_id: int) -> None:
    """Create sampled pairwise match rows for the current run."""

    run = session.get(Run, run_id)
    transcripts = session.exec(select(Transcript).where(Transcript.run_id == run_id)).all()
    configs = session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
    existing = {
        (row.transcript_id, row.config_a_id, row.config_b_id)
        for row in session.exec(select(Match).where(Match.run_id == run_id)).all()
    }
    generation_lookup = {
        (generation.transcript_id, generation.generator_config_id): generation
        for generation in session.exec(select(Generation).where(Generation.run_id == run_id)).all()
    }
    for transcript in transcripts:
        pairings = list(itertools.combinations(configs, 2))
        sample_pct = run.pairing_sample_pct if run else 100.0
        if sample_pct < 100.0 and pairings:
            sample_count = max(1, round(len(pairings) * (sample_pct / 100.0)))
            rng = random.Random(f"{run_id}:{transcript.id}:{sample_pct}")
            pairings = rng.sample(pairings, min(sample_count, len(pairings)))
        for config_a, config_b in pairings:
            if (transcript.id, config_a.id, config_b.id) in existing:
                continue
            gen_a = generation_lookup[(transcript.id, config_a.id)]
            gen_b = generation_lookup[(transcript.id, config_b.id)]
            session.add(
                Match(
                    run_id=run_id,
                    transcript_id=transcript.id,
                    generation_a_id=gen_a.id,
                    generation_b_id=gen_b.id,
                    config_a_id=config_a.id,
                    config_b_id=config_b.id,
                )
            )
    session.commit()


def ensure_elo_rows(session: Session, run_id: int) -> None:
    """Create missing leaderboard rows for each generator config."""

    run = session.get(Run, run_id)
    configs = session.exec(select(GeneratorConfig).where(GeneratorConfig.run_id == run_id)).all()
    existing = {
        row.generator_config_id
        for row in session.exec(select(EloRating).where(EloRating.run_id == run_id)).all()
    }
    for config in configs:
        if config.id not in existing:
            session.add(
                EloRating(
                    run_id=run_id,
                    generator_config_id=config.id,
                    rating=run.elo_start if run else 1500.0,
                )
            )
    session.commit()
