"""Shared pytest setup.

Several tests talk to the database directly through `SessionLocal()` rather than
through the app, and the schema is only created in `app.py`'s startup path. On a
developer machine that has already run the server the tables happen to exist, so
the tests pass; on a clean checkout they fail with "no such table: game_config".

That made `pytest` on a fresh clone fail for reasons unrelated to any change,
which is a poor first five minutes for a contributor. Creating the schema here
costs nothing when it already exists - `create_all` only adds missing tables.
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """Create any missing tables before the suite runs."""
    from database import engine
    from models import ModelBase

    ModelBase.metadata.create_all(bind=engine)
    yield
