"""Common pages must not repeat the same database lookup for every row.

A query audit (one player, one base, a fresh world per game) found the bases
list spending 25 of its 45 queries asking for the base commander once per
building row, and the research page 19 of 28 asking for the research queue once
per technology. Both grow with the player's empire - a 10-base player paid
hundreds of queries per page load.
"""
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event

import game_logic
from database import SessionLocal, engine
from models import Commander, User, Colony, ResearchQueue


@contextmanager
def count_queries():
    n = {"q": 0}
    def _c(*_a, **_k):
        n["q"] += 1
    event.listen(engine, "before_cursor_execute", _c)
    try:
        yield n
    finally:
        event.remove(engine, "before_cursor_execute", _c)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback(); s.close()


def test_base_commander_is_looked_up_once_per_request(db):
    colony_id = 987654321          # any id: the lookup runs either way
    with count_queries() as n:
        for skill in ("construction", "production", "research") * 10:
            game_logic.get_commander_level_at_base(db, colony_id, skill)
    assert n["q"] == 1


def test_commander_cache_is_dropped_after_a_write(db):
    """A request that assigns a commander and then prices a building must see it."""
    u = User(username=f"cmdr_{uuid.uuid4().hex[:6]}", hashed_password="x")
    db.add(u); db.flush()
    colony = db.query(Colony).first()
    if colony is None:
        pytest.skip("no colony in the dev database")
    before = game_logic.get_commander_level_at_base(db, colony.id, "construction")
    db.add(Commander(user_id=u.id, name="Test", skill_type="construction", level=before + 5,
                     colony_id=colony.id, is_assigned=True, is_traveling=False))
    db.flush()
    assert game_logic.get_commander_level_at_base(db, colony.id, "construction") == before + 5


def test_research_queue_levels_are_one_query(db):
    with count_queries() as n:
        levels = game_logic.max_queued_research_levels(db, user_id=987654321)
    assert levels == {} and n["q"] == 1
