from council.elo import consistent_swapped_vote, majority_vote, remap_swapped_vote, update_elo


def test_update_elo_win_loss_from_equal_ratings():
    """A direct win should move ratings apart."""

    new_a, new_b = update_elo(1500, 1500, "A")

    assert new_a == 1516
    assert new_b == 1484


def test_update_elo_tie_from_equal_ratings():
    """A tie should leave equal ratings unchanged."""

    new_a, new_b = update_elo(1500, 1500, "TIE")

    assert new_a == 1500
    assert new_b == 1500


def test_majority_vote_returns_tie_without_strict_winner():
    """No strict majority should collapse to a tie."""

    assert majority_vote(["A", "B"]) == "TIE"
    assert majority_vote(["A", "B", "TIE"]) == "TIE"


def test_majority_vote_returns_winner():
    """A strict majority should produce the winning label."""

    assert majority_vote(["A", "A", "B"]) == "A"


def test_swap_vote_mapping():
    """Swapping the prompt sides should invert A and B."""

    assert remap_swapped_vote("A") == "B"
    assert remap_swapped_vote("B") == "A"
    assert remap_swapped_vote("TIE") == "TIE"


def test_consistent_swapped_vote():
    """Disagreement across swap validation should become a tie."""

    assert consistent_swapped_vote("A", "B") == "A"
    assert consistent_swapped_vote("B", "A") == "B"
    assert consistent_swapped_vote("A", "A") == "TIE"
