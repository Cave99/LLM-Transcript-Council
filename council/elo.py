"""ELO and pairwise voting helpers.

These functions are deliberately small and dependency-free so they are easy to
trust. The app treats subjective evaluation as repeated pairwise preferences:
each match is a win, loss, or tie between two generator configurations.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

Winner = Literal["A", "B", "TIE"]


def update_elo(
    rating_a: float,
    rating_b: float,
    winner: Winner,
    *,
    k_factor: float = 32.0,
) -> tuple[float, float]:
    """Return updated ELO ratings for the two compared configs."""

    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    expected_b = 1 - expected_a

    if winner == "A":
        score_a, score_b = 1.0, 0.0
    elif winner == "B":
        score_a, score_b = 0.0, 1.0
    else:
        score_a, score_b = 0.5, 0.5

    return (
        rating_a + k_factor * (score_a - expected_a),
        rating_b + k_factor * (score_b - expected_b),
    )


def majority_vote(votes: list[Winner]) -> Winner:
    """Return the majority winner, or TIE when no winner has a strict majority."""

    if not votes:
        return "TIE"
    counts = Counter(votes)
    top_vote, top_count = counts.most_common(1)[0]
    tied_top = [vote for vote, count in counts.items() if count == top_count]
    if len(tied_top) > 1:
        return "TIE"
    return top_vote  # type: ignore[return-value]


def remap_swapped_vote(swapped_winner: Winner) -> Winner:
    """Map a swapped vote back to the original A/B positions."""

    if swapped_winner == "A":
        return "B"
    if swapped_winner == "B":
        return "A"
    return "TIE"


def consistent_swapped_vote(first: Winner, swapped: Winner) -> Winner:
    """Return a judge vote after A/B swap validation.

    If the judge changes preference after accounting for swapped positions, the
    safest interpretation is that the comparison was too close or unstable.
    """

    remapped = remap_swapped_vote(swapped)
    return first if first == remapped else "TIE"
