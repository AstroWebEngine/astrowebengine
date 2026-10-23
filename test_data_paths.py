"""Runtime state must live in AWE_DATA_DIR so it survives a container being replaced.

In Docker the app code is in /app (rebuilt on every image update) and only /data
is a volume. The active ruleset, the recorded mod base and creator-saved
definitions used to be written next to the code, so an image update silently
reverted the game to its default rules while the database kept the old world.
"""
import json
from pathlib import Path

import pytest

import data_paths


def test_default_data_dir_is_the_project_folder(monkeypatch):
    monkeypatch.delenv("AWE_DATA_DIR", raising=False)
    assert data_paths.data_dir() == data_paths.PROJECT_ROOT
    assert data_paths.user_definitions_dir() == data_paths.BUNDLED_DEFINITIONS_DIR


def test_env_moves_runtime_files(monkeypatch, tmp_path):
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    assert data_paths.data_dir() == tmp_path.resolve()
    assert data_paths.active_definition_path() == tmp_path.resolve() / "_active_definition.json"
    assert data_paths.mod_base_path() == tmp_path.resolve() / "_mod_base_definition.json"
    assert data_paths.user_definitions_dir() == tmp_path.resolve() / "game_definitions"


def test_find_definition_prefers_user_copy_then_bundled(monkeypatch, tmp_path):
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    assert data_paths.find_definition_file("deep_frontier.json") == \
        data_paths.BUNDLED_DEFINITIONS_DIR / "deep_frontier.json"
    user = tmp_path / "game_definitions"; user.mkdir()
    (user / "deep_frontier.json").write_text("{}", encoding="utf-8")
    assert data_paths.find_definition_file("deep_frontier.json") == user.resolve() / "deep_frontier.json"


@pytest.mark.parametrize("bad", ["", "../x.json", "a/b.json", "a\\b.json", "C:x.json", "missing.json"])
def test_find_definition_rejects_paths_and_missing(monkeypatch, tmp_path, bad):
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    assert data_paths.find_definition_file(bad) is None


def test_migration_moves_legacy_files_once(monkeypatch, tmp_path):
    legacy = tmp_path / "app"; (legacy / "game_definitions").mkdir(parents=True)
    (legacy / "_active_definition.json").write_text('{"meta":{"name":"Old"}}', encoding="utf-8")
    (legacy / "_mod_base_definition.json").write_text('{"meta":{"name":"Base"}}', encoding="utf-8")
    (legacy / "game_definitions" / "ai_draft.json").write_text("{}", encoding="utf-8")
    (legacy / "game_definitions" / "deep_frontier.json").write_text("{}", encoding="utf-8")  # bundled: stays
    data = tmp_path / "data"
    monkeypatch.setattr(data_paths, "PROJECT_ROOT", legacy)
    monkeypatch.setattr(data_paths, "BUNDLED_DEFINITIONS_DIR", legacy / "game_definitions")
    monkeypatch.setenv("AWE_DATA_DIR", str(data))

    moved = data_paths.migrate_legacy_runtime_files()

    assert json.loads((data / "_active_definition.json").read_text())["meta"]["name"] == "Old"
    assert (data / "_mod_base_definition.json").exists()
    assert (data / "game_definitions" / "ai_draft.json").exists()
    assert not (legacy / "_active_definition.json").exists()
    assert (legacy / "game_definitions" / "deep_frontier.json").exists()
    assert len(moved) == 3
    assert data_paths.migrate_legacy_runtime_files() == []   # idempotent


def test_migration_never_overwrites_existing_data(monkeypatch, tmp_path):
    legacy = tmp_path / "app"; legacy.mkdir()
    (legacy / "_active_definition.json").write_text('{"meta":{"name":"Stale"}}', encoding="utf-8")
    data = tmp_path / "data"; data.mkdir()
    (data / "_active_definition.json").write_text('{"meta":{"name":"Current"}}', encoding="utf-8")
    monkeypatch.setattr(data_paths, "PROJECT_ROOT", legacy)
    monkeypatch.setattr(data_paths, "BUNDLED_DEFINITIONS_DIR", legacy / "game_definitions")
    monkeypatch.setenv("AWE_DATA_DIR", str(data))
    data_paths.migrate_legacy_runtime_files()
    assert json.loads((data / "_active_definition.json").read_text())["meta"]["name"] == "Current"
    assert (legacy / "_active_definition.json").exists()   # left for the operator to inspect


def test_migration_is_a_no_op_without_a_separate_data_dir(monkeypatch):
    monkeypatch.delenv("AWE_DATA_DIR", raising=False)
    assert data_paths.migrate_legacy_runtime_files() == []


def test_persisted_definition_round_trips_through_data_dir(monkeypatch, tmp_path):
    import game_definition as gd
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    gd.persist_mod_base({"meta": {"name": "In Data"}})
    assert (tmp_path / "_mod_base_definition.json").exists()
    assert gd.load_mod_base()["meta"]["name"] == "In Data"
    gd.clear_mod_base()
    assert not (tmp_path / "_mod_base_definition.json").exists()


def test_dockerfile_points_data_dir_at_the_volume():
    docker = (Path(__file__).parent / "Dockerfile").read_text(encoding="utf-8")
    assert "AWE_DATA_DIR=/data" in docker


def test_saved_definition_in_data_dir_can_extend_bundled_fragments(monkeypatch, tmp_path):
    import game_definition as gd
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    user = data_paths.user_definitions_dir(); user.mkdir(parents=True)
    (user / "my_game.json").write_text(json.dumps(
        {"extends": ["deep_frontier.json", "fragments/combat/single_round.json"],
         "meta": {"name": "My Game"}}), encoding="utf-8")
    compiled = gd.load_definition_from_file(str(user / "my_game.json"))
    assert compiled["meta"]["name"] == "My Game" and compiled["ships"]
    names = [d["filename"] for d in gd.list_available_definitions()]
    assert "my_game.json" in names and "deep_frontier.json" in names


# -- signing key ----------------------------------------------------------------

def test_env_secret_key_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AWE_SECRET_KEY", "from-env")
    assert data_paths.load_or_create_secret_key() == "from-env"
    assert not (tmp_path / ".secret_key").exists()


def test_generated_secret_key_is_stable_across_restarts(monkeypatch, tmp_path):
    """Without AWE_SECRET_KEY a random key per start logged every player out on
    each restart, and gave every uvicorn worker a different key."""
    monkeypatch.setenv("AWE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AWE_SECRET_KEY", raising=False)
    first = data_paths.load_or_create_secret_key()
    assert len(first) >= 64
    assert data_paths.load_or_create_secret_key() == first
    assert (tmp_path / ".secret_key").read_text().strip() == first
