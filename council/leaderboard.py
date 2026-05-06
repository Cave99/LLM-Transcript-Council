"""Leaderboard persistence for completed pairwise matches."""

from __future__ import annotations

from sqlmodel import Session, select

from council.elo import update_elo
from council.models import EloRating, Match, MatchResult, Run, Status


def recalculate_elo(session: Session, run_id: int) -> None:
    """Rebuild leaderboard rows from completed match results."""

    run = session.get(Run, run_id)
    ratings = {
        row.generator_config_id: row
        for row in session.exec(select(EloRating).where(EloRating.run_id == run_id)).all()
    }
    for row in ratings.values():
        row.rating = run.elo_start if run else 1500.0
        row.wins = row.losses = row.ties = 0
        session.add(row)

    matches = session.exec(select(Match).where(Match.run_id == run_id, Match.status == Status.complete)).all()
    for match in matches:
        result = session.exec(select(MatchResult).where(MatchResult.match_id == match.id)).first()
        if not result:
            continue
        apply_match_elo(session, match, result.final_winner)
    session.commit()


def apply_match_elo(session: Session, match: Match, final_winner: str) -> None:
    """Apply one completed match result to the live leaderboard rows."""

    run = session.get(Run, match.run_id)
    rating_a = session.exec(
        select(EloRating).where(
            EloRating.run_id == match.run_id,
            EloRating.generator_config_id == match.config_a_id,
        )
    ).first()
    rating_b = session.exec(
        select(EloRating).where(
            EloRating.run_id == match.run_id,
            EloRating.generator_config_id == match.config_b_id,
        )
    ).first()
    if not rating_a or not rating_b:
        return

    rating_a.rating, rating_b.rating = update_elo(
        rating_a.rating,
        rating_b.rating,
        final_winner,  # type: ignore[arg-type]
        k_factor=run.k_factor if run else 32.0,
    )
    if final_winner == "A":
        rating_a.wins += 1
        rating_b.losses += 1
    elif final_winner == "B":
        rating_b.wins += 1
        rating_a.losses += 1
    else:
        rating_a.ties += 1
        rating_b.ties += 1
    session.add(rating_a)
    session.add(rating_b)
