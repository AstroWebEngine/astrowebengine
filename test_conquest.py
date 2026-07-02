#!/usr/bin/env python3
"""Conquest mode: occupation escalating to permanent base loss (opt-in flags).

Covers the flag readers, the capture primitives (disband refunds the owner and
removes the base; transfer reassigns ownership), and the tick sweep that
escalates only occupations older than the threshold — and only when the
occupation_capture flag is on.

Run: python3 -m pytest test_conquest.py
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import ModelBase
import models  # noqa: F401 — register tables
from models import User, Colony

import auth
from game_definition import set_game_definition, build_default_definition
import conquest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _isolate_config():
    # Empty config cache so get_config reads the active definition's engine flags.
    saved = auth._config_cache, auth._config_cache_loaded
    auth._config_cache, auth._config_cache_loaded = {}, True
    yield
    auth._config_cache, auth._config_cache_loaded = saved
    set_game_definition(build_default_definition())


def _engine_flags(**flags):
    d = build_default_definition()
    d["engine"] = {**d.get("engine", {}), **flags}
    set_game_definition(d)


def _occupied_base(db, owner_name, occupier_id, occ_age_hours):
    owner = User(username=owner_name, hashed_password="x", is_admin=False, is_bot=False)
    db.add(owner)
    db.flush()
    col = Colony(
        user_id=owner.id,
        name=f"{owner_name}-base",
        occupied_by=occupier_id,
        occupation_start=datetime.utcnow() - timedelta(hours=occ_age_hours),
    )
    db.add(col)
    db.commit()
    return owner, col


def test_flag_readers_come_from_definition():
    _engine_flags(occupation_capture="true", occupation_capture_hours=3,
                  occupation_capture_mode="transfer", occupation_zero_production="true")
    db = None  # flag readers only need the definition here
    assert conquest.capture_enabled(db) is True
    assert conquest.capture_hours(db) == 3.0
    assert conquest.capture_mode(db) == "transfer"
    assert conquest.occupation_zero_production(db) is True


def test_capture_disabled_is_a_noop(db):
    _engine_flags(occupation_capture="false")
    _occupied_base(db, "victim", occupier_id=999, occ_age_hours=100)
    assert conquest.process_occupation_capture(db, now=datetime.utcnow()) == []


def test_disband_removes_base_and_credits_owner_exactly_the_refund(db):
    owner, col = _occupied_base(db, "victim", occupier_id=999, occ_age_hours=100)
    col_id = col.id
    before = owner.base_reserve or 0.0
    refund = conquest.disband_captured_colony(db, col)
    db.flush()
    assert db.query(Colony).filter(Colony.id == col_id).first() is None  # base is gone
    assert (owner.base_reserve or 0.0) == pytest.approx(before + refund)  # credited the refund


def test_transfer_reassigns_ownership_and_clears_occupation(db):
    owner, col = _occupied_base(db, "victim", occupier_id=777, occ_age_hours=100)
    conquest.transfer_colony(db, col, 777)
    db.flush()
    assert col.user_id == 777
    assert col.occupied_by is None and col.occupation_start is None
    assert col.is_home_base is False


def test_sweep_escalates_old_occupation_transfer_mode(db):
    _engine_flags(occupation_capture="true", occupation_capture_hours=6,
                  occupation_capture_mode="transfer")
    owner, col = _occupied_base(db, "victim", occupier_id=777, occ_age_hours=10)
    col_id = col.id
    events = conquest.process_occupation_capture(db, now=datetime.utcnow())
    assert len(events) == 1 and events[0]["mode"] == "transfer"
    assert db.query(Colony).filter(Colony.id == col_id).first().user_id == 777


def test_sweep_skips_young_occupation(db):
    _engine_flags(occupation_capture="true", occupation_capture_hours=6,
                  occupation_capture_mode="disband")
    _occupied_base(db, "victim", occupier_id=777, occ_age_hours=1)  # younger than threshold
    assert conquest.process_occupation_capture(db, now=datetime.utcnow()) == []


def test_conquest_overlay_mod_is_valid_and_flips_flags():
    """The one-click Conquest content mod enables the whole feature via flags."""
    from mod_loader import discover_mods, load_mod_definition
    mods = {m["id"]: m for m in discover_mods()}
    assert "conquest" in mods, "conquest mod not discovered"
    m = mods["conquest"]
    assert m["errors"] == [], m["errors"]
    assert m["manifest"]["kind"] == "content"  # pure data overlay, runs no code
    eng = load_mod_definition(m).get("engine", {})
    assert eng.get("occupation_capture") is True
    assert eng.get("occupation_zero_production") is True
    assert eng.get("win_condition") == "annihilation"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
