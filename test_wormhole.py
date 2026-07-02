#!/usr/bin/env python3
"""Wormhole traverse-damage math (pure core, no DB).

Run: python3 test_wormhole.py
"""
from wormhole import compute_losses


def test_no_damage_when_pct_not_positive():
    assert compute_losses({"scout_ship": 3}, 0.0) == {}
    assert compute_losses({"scout_ship": 3}, -0.5) == {}


def test_anti_scout_any_positive_pct_costs_at_least_one_of_each():
    losses = compute_losses({"scout_ship": 2, "light_warship": 1}, 0.01)
    assert losses == {"scout_ship": 1, "light_warship": 1}


def test_big_fleet_pays_the_percentage():
    assert compute_losses({"heavy_warship": 1000}, 0.1)["heavy_warship"] == 100  # ceil(1000*0.1)


def test_never_destroys_more_than_present():
    assert compute_losses({"scout_ship": 3}, 1.0) == {"scout_ship": 3}


def test_skips_zero_counts_and_ceils():
    assert compute_losses({"a": 0, "b": 5}, 0.5) == {"b": 3}  # ceil(5*0.5)=3, a skipped


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL WORMHOLE TESTS PASSED!")
    print("=" * 60)
