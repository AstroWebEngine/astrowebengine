#!/usr/bin/env python3
"""Smoke test for the normalized client catalog (/api/catalog/*).

The catalog is the frontend's single source of truth for display names — every
UI module resolves ship/building/research/defense/astro names through it instead
of hardcoding them. This guards the contract those resolvers depend on: the spec
sections exist, entries carry a stable ``key`` + a display ``name``, astros carry
``colonizable`` (the Astros-report terrain filter reads that), and asking for
disabled items never drops visible ones.

Run: python3 -m pytest test_catalog.py
"""
import pytest

from database import SessionLocal
from auth import init_default_configs
from game_definition import set_game_definition, build_default_definition
from routes_catalog import _build_spec_catalog

SPEC_KINDS = ["ships", "defenses", "buildings", "research",
              "astros", "weapons", "commanders", "goods"]


@pytest.fixture(autouse=True)
def _default_definition():
    set_game_definition(build_default_definition())
    yield
    set_game_definition(build_default_definition())


def _db():
    db = SessionLocal()
    init_default_configs(db)
    return db


def _catalog(**kw):
    db = _db()
    try:
        return _build_spec_catalog(db, **kw)
    finally:
        db.close()


def test_catalog_shape_and_sections():
    cat = _catalog()
    assert cat["schema_version"] == 1
    assert "meta" in cat and "engine" in cat
    for kind in SPEC_KINDS:
        assert kind in cat["specs"], f"missing catalog section: {kind}"
    # Core rosters are non-empty on the default definition.
    for kind in ("ships", "buildings", "research", "astros"):
        assert cat["specs"][kind], f"catalog section {kind} unexpectedly empty"


def test_entries_have_self_key_and_display_name():
    cat = _catalog()
    for kind in ("ships", "buildings", "research", "defenses", "astros"):
        for key, item in cat["specs"][kind].items():
            assert item.get("key") == key, f"{kind}/{key} missing self key"
            assert item.get("name"), f"{kind}/{key} has no display name"


def test_astros_carry_colonizable_flag():
    """The Astros-report terrain filter builds its options from colonizable astros."""
    astros = _catalog()["specs"]["astros"]
    colonizable = [k for k, s in astros.items() if s.get("colonizable") is not False]
    non_colonizable = [k for k, s in astros.items() if s.get("colonizable") is False]
    assert colonizable, "no colonizable terrains in catalog"
    # Primary non-colonizable bodies (asteroid belt / gas giant) are present but
    # excluded from the terrain filter, so the flag must be there to filter on.
    assert non_colonizable, "expected non-colonizable bodies to be flagged"


def test_include_disabled_never_drops_entries():
    visible = _catalog(include_disabled=False)
    everything = _catalog(include_disabled=True)
    for kind in SPEC_KINDS:
        assert len(everything["specs"][kind]) >= len(visible["specs"][kind]), \
            f"include_disabled dropped entries in {kind}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
