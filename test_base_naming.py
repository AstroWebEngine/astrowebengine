#!/usr/bin/env python3
"""Base naming: the starting base is 'Homeworld'; players name their colonies.

The homeworld name is deliberately plain (no "<player>'s " prefix) because it is
repeated in every base list, and mobile base tables have no room to spare. Every
later base is named by the player at colonize time, falling back to the astro's
designation rather than an auto-generated label.

Run: python3 -m pytest test_base_naming.py
"""
import pytest

from game_logic import resolve_base_name, MAX_BASE_NAME


def test_player_name_is_used():
    assert resolve_base_name("New Terra", "A00:49:14:10") == "New Terra"


def test_surrounding_whitespace_is_trimmed():
    assert resolve_base_name("  New Terra  ", "A00:49:14:10") == "New Terra"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", None])
def test_blank_falls_back_to_the_astro_designation(blank):
    # A base is never nameless — an empty box means "name it after the astro".
    assert resolve_base_name(blank, "A00:49:14:10") == "A00:49:14:10"


def test_long_name_is_capped_at_the_rename_limit():
    capped = resolve_base_name("x" * 200, "A00:49:14:10")
    assert capped == "x" * MAX_BASE_NAME
    assert len(capped) == 40  # matches the /api/bases/{id}/rename cap


def test_homeworld_seeding_uses_the_plain_name():
    """universe.py seeds the starting base as exactly 'Homeworld'."""
    import re
    from pathlib import Path
    src = Path(__file__).with_name("universe.py").read_text(encoding="utf-8")
    seeds = re.findall(r'Colony\(planet_id=planet\.id, user_id=user\.id, name=([^)]+)\)', src)
    assert seeds, "no homeworld seeding call found in universe.py"
    for expr in seeds:
        assert expr.strip() == '"Homeworld"', f"homeworld seeded with {expr!r}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
