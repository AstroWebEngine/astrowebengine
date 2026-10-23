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


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _write_bytes(path, data):
    if data is None:
        try:
            import os
            os.remove(path)
        except OSError:
            pass
    else:
        with open(path, "wb") as f:
            f.write(data)


@pytest.fixture
def mod_state():
    """Snapshot and restore everything a mod/definition test can change: enabled mods,
    the active ruleset mod, the persisted definition (flag + file), the recorded mod
    base, and the in-memory active definition."""
    import game_definition as gd
    from auth import get_config, set_config, init_default_configs
    from database import SessionLocal

    db = SessionLocal(); init_default_configs(db)
    keys = ("enabled_mods", "active_ruleset_mod", gd._ACTIVE_DEFINITION_FLAG)
    saved = {k: get_config(db, k, "") or "" for k in keys}
    import data_paths
    files = {str(p): _read_bytes(str(p)) for p in (data_paths.active_definition_path(), data_paths.mod_base_path())}
    live = gd.get_game_definition()
    db.close()
    yield
    db = SessionLocal()
    for k, v in saved.items():
        set_config(db, k, v)
    db.commit(); db.close()
    for p, data in files.items():
        _write_bytes(p, data)
    gd.set_game_definition(live)
