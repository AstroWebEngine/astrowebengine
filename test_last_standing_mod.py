#!/usr/bin/env python3
"""Reference behavioral mod: the 'annihilation' (last-standing) win condition.

Verifies the mod is discoverable + valid, and that its compute_victory override
declares the last player holding any base the winner — but only in a contested
game, and only for the 'annihilation' condition (it defers otherwise, so the
engine's built-in domination/economic checks still run).

Run: python3 -m pytest test_last_standing_mod.py
"""
import os
import importlib.util

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import ModelBase
import models  # noqa: F401 — register tables on ModelBase.metadata
from models import User, Colony, Guild, GuildMember
from mod_hooks import HookContext

MOD_DIR = os.path.join(os.path.dirname(__file__), "mods", "last_standing")


def _load_handler():
    """Load the mod's compute_victory handler the way the engine wires it."""
    path = os.path.join(MOD_DIR, "hooks", "__init__.py")
    spec = importlib.util.spec_from_file_location("last_standing_hooks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = {}
    module.register_hooks(lambda name, fn, order=100: captured.__setitem__(name, fn))
    return captured["compute_victory"]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_player(db, name, with_base, guild_id=None):
    u = User(username=name, hashed_password="x", is_admin=False, is_bot=False)
    db.add(u)
    db.flush()
    if with_base:
        db.add(Colony(user_id=u.id, name=f"{name}-home"))
    if guild_id is not None:
        db.add(GuildMember(guild_id=guild_id, user_id=u.id))
    db.commit()
    return u


def _add_guild(db, name):
    leader = User(username=f"{name}-leader", hashed_password="x", is_admin=False, is_bot=False)
    db.add(leader)
    db.flush()
    g = Guild(name=name, tag=name[:5], leader_id=leader.id)
    db.add(g)
    db.commit()
    return g


def test_mod_is_discovered_and_valid():
    from mod_loader import discover_mods
    mods = {m["id"]: m for m in discover_mods()}
    assert "last_standing" in mods, "mod not discovered under mods/"
    m = mods["last_standing"]
    assert m["errors"] == [], m["errors"]
    assert m["manifest"]["kind"] == "behavioral"


def test_defers_when_condition_is_not_annihilation(db):
    handler = _load_handler()
    _add_player(db, "solo", with_base=True)
    # returning None lets the engine run its built-in domination/economic checks
    assert handler(HookContext({"db": db, "condition": "domination"})) is None


def test_last_standing_wins_contested_game(db):
    handler = _load_handler()
    _add_player(db, "winner", with_base=True)
    _add_player(db, "loser", with_base=False)  # eliminated: account exists, no base
    assert handler(HookContext({"db": db, "condition": "annihilation"})) == {"winner": "winner"}


def test_no_winner_while_two_players_still_hold_bases(db):
    handler = _load_handler()
    _add_player(db, "a", with_base=True)
    _add_player(db, "b", with_base=True)
    assert handler(HookContext({"db": db, "condition": "annihilation"})) == {"winner": None}


def test_solo_game_is_not_an_annihilation_win(db):
    handler = _load_handler()
    _add_player(db, "onlyone", with_base=True)  # never contested
    assert handler(HookContext({"db": db, "condition": "annihilation"})) == {"winner": None}


def test_last_guild_standing_wins_by_guild_name(db):
    handler = _load_handler()
    winners = _add_guild(db, "Vanguard")
    _add_player(db, "v1", with_base=True, guild_id=winners.id)
    _add_player(db, "v2", with_base=True, guild_id=winners.id)   # both survivors, same guild
    _add_player(db, "loser", with_base=False)                    # eliminated
    assert handler(HookContext({"db": db, "condition": "annihilation"})) == {"winner": "Vanguard"}


def test_guild_and_solo_survivor_is_two_teams_no_winner(db):
    handler = _load_handler()
    g = _add_guild(db, "Coalition")
    _add_player(db, "g1", with_base=True, guild_id=g.id)
    _add_player(db, "rogue", with_base=True)   # guildless survivor -> separate team
    assert handler(HookContext({"db": db, "condition": "annihilation"})) == {"winner": None}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
