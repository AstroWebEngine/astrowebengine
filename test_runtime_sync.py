"""Every uvicorn worker is its own process with its own copy of the game_config
cache and the active definition. A change made through one worker used to stay
invisible to the others until a restart. runtime_sync.sync_once() is what each
worker runs every few seconds to catch up; these tests play "the other worker"
by writing to the database and files directly, the way a second process would.
"""
import json
import uuid

import pytest

import auth
import data_paths
import game_definition as gd
import runtime_sync
from database import SessionLocal
from models import GameConfig


@pytest.fixture
def db():
    s = SessionLocal(); auth.init_default_configs(s)
    yield s
    s.close()


def _raw_set(db, key, value):
    """Write a config row without touching this process's cache (another worker)."""
    row = db.query(GameConfig).filter(GameConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(GameConfig(key=key, value=value))
    db.commit()


def test_config_changed_by_another_worker_is_picked_up(db):
    key = f"sync_test_{uuid.uuid4().hex[:6]}"
    runtime_sync.sync_once(db)
    _raw_set(db, key, "from-other-worker")
    assert auth.get_config(db, key, "unset") == "unset"      # stale cache, as before
    result = runtime_sync.sync_once(db)
    assert auth.get_config(db, key, "unset") == "from-other-worker"
    assert key in result["changed"]
    db.query(GameConfig).filter(GameConfig.key == key).delete(); db.commit()
    auth.refresh_config_cache(db)


def test_definition_activated_by_another_worker_is_reloaded(db, mod_state):
    runtime_sync.sync_once(db)                                # baseline
    other = gd.build_default_definition()
    other["meta"] = {**other["meta"], "name": "Activated Elsewhere"}
    gd.save_definition_to_file(other, str(data_paths.active_definition_path()))
    _raw_set(db, gd._ACTIVE_DEFINITION_FLAG, "persisted")
    _raw_set(db, runtime_sync.REVISION_KEY, uuid.uuid4().hex)

    result = runtime_sync.sync_once(db)

    assert result["reloaded"] is True
    assert gd.get_game_definition()["meta"]["name"] == "Activated Elsewhere"


def test_reset_by_another_worker_returns_to_default(db, mod_state):
    custom = gd.build_default_definition()
    custom["meta"] = {**custom["meta"], "name": "Custom Before Reset"}
    gd.set_game_definition(custom)
    runtime_sync.sync_once(db)
    _raw_set(db, gd._ACTIVE_DEFINITION_FLAG, "")              # what reset writes
    _raw_set(db, runtime_sync.REVISION_KEY, uuid.uuid4().hex)
    runtime_sync.sync_once(db)
    assert gd.get_game_definition()["meta"]["name"] == gd.build_default_definition()["meta"]["name"]


def test_own_activation_does_not_reload_itself(db, mod_state):
    runtime_sync.sync_once(db)
    mine = gd.build_default_definition()
    mine["meta"] = {**mine["meta"], "name": "Mine"}
    gd.set_game_definition(mine)
    gd.persist_active_definition(db, mine)                   # bumps the revision
    result = runtime_sync.sync_once(db)
    assert result["reloaded"] is False
    assert gd.get_game_definition()["meta"]["name"] == "Mine"


def test_no_change_means_no_reload(db):
    runtime_sync.sync_once(db)
    result = runtime_sync.sync_once(db)
    assert result == {"changed": set(), "reloaded": False}
