#!/usr/bin/env python3
"""The admin-activated game definition must survive a restart without env vars.

set_game_definition() alone is in-memory only; persist_active_definition() writes
a runtime file + a game_config flag, and restore_persisted_definition() (called at
startup) brings it back. This guards that roundtrip and the reset/clear path.

Run: python3 -m pytest test_definition_persistence.py
"""
import pytest

from database import SessionLocal
from auth import init_default_configs
from game_definition import (
    build_default_definition, set_game_definition, get_game_definition,
    persist_active_definition, restore_persisted_definition, clear_persisted_definition,
)


def _db():
    db = SessionLocal()
    init_default_configs(db)
    return db


@pytest.fixture(autouse=True)
def _reset():
    yield
    db = _db()
    try:
        clear_persisted_definition(db)
    finally:
        db.close()
    set_game_definition(build_default_definition())


def _named(name):
    d = build_default_definition()
    d["meta"] = {**d.get("meta", {}), "name": name}
    return d


def test_persist_then_restore_roundtrip():
    db = _db()
    try:
        persist_active_definition(db, _named("Persisted Ruleset X"))
        # simulate a restart: memory reset, then startup restore
        set_game_definition(build_default_definition())
        assert get_game_definition()["meta"]["name"] != "Persisted Ruleset X"
        name = restore_persisted_definition(db)
        assert name == "Persisted Ruleset X"
        assert get_game_definition()["meta"]["name"] == "Persisted Ruleset X"
    finally:
        db.close()


def test_clear_reverts_to_default_on_restart():
    db = _db()
    try:
        persist_active_definition(db, _named("Temp Ruleset"))
        clear_persisted_definition(db)
        # after clear, a restart restores nothing (falls back to env/default)
        assert restore_persisted_definition(db) is None
    finally:
        db.close()


def test_restore_is_noop_when_nothing_persisted():
    db = _db()
    try:
        clear_persisted_definition(db)
        assert restore_persisted_definition(db) is None
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
