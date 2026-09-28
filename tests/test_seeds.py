"""AGENTS.md invariant 9: pilot / exploration / confirmation / replication data never overlap."""

import pytest

from agents.common import EXPLORATION_SEEDS, PILOT_SEEDS, SEED_PURPOSES, slice_seed


def test_no_seed_is_used_for_two_purposes_or_two_slices():
    seen = {s: "pilot" for s in PILOT_SEEDS} | {s: "exploration" for s in EXPLORATION_SEEDS}
    for purpose in SEED_PURPOSES:
        for campaign in range(1, 51):
            for slot in range(10):
                s = slice_seed(purpose, campaign, slot)
                assert s not in seen, (purpose, campaign, slot, seen[s])
                seen[s] = purpose


def test_seed_outside_its_range_is_refused():
    with pytest.raises(ValueError):
        slice_seed("primary", 1, 1000)
    with pytest.raises(ValueError):
        slice_seed("primary", 1000, 0)
    with pytest.raises(ValueError):
        slice_seed("pilot", 1, 0)
