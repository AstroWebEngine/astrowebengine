#!/usr/bin/env python3
"""Engine-flag read precedence: admin game_config > definition.engine > default.

Guards the data-driven contract that engine flags authored in a game definition
(galaxy_shape, galaxy_network, wormhole_model and their numeric tuning params)
actually take effect through the config-read path, while an admin override in
game_config still wins.

Run: python3 test_engine_flag_precedence.py
"""
import pytest

import auth
import game_definition as gd


@pytest.fixture(autouse=True)
def _isolate_config_and_definition():
    """Save/restore the in-memory config cache and active definition so these
    tests neither read the real DB nor leak global state into other tests."""
    saved_cache = dict(auth._config_cache)
    saved_loaded = auth._config_cache_loaded
    saved_def = gd._active_definition
    yield
    auth._config_cache = saved_cache
    auth._config_cache_loaded = saved_loaded
    gd._active_definition = saved_def


def _set(engine, cache=None):
    """Point the active definition at a minimal engine section (no spec sync)
    and seed the config cache directly (bypasses the DB)."""
    gd._active_definition = {"engine": dict(engine)}
    auth._config_cache = dict(cache or {})
    auth._config_cache_loaded = True


def test_definition_engine_flag_is_read():
    _set({"galaxy_shape": "templates"})
    assert auth.get_config(None, "galaxy_shape", "procedural_spiral") == "templates"


def test_admin_config_overrides_definition():
    _set({"galaxy_shape": "templates"}, cache={"galaxy_shape": "procedural_spiral"})
    assert auth.get_config(None, "galaxy_shape", "x") == "procedural_spiral"


def test_falls_back_to_default_when_neither_set():
    _set({})
    assert auth.get_config(None, "galaxy_shape", "procedural_spiral") == "procedural_spiral"


def test_non_engine_key_is_unaffected():
    # A key that isn't an engine flag must still return the caller default.
    _set({"galaxy_shape": "templates"})
    assert auth.get_config(None, "some_balance_knob", "1.5") == "1.5"


def test_typed_float_reads_from_definition():
    # get_config_float is built on get_config, so it inherits the fallback.
    _set({"wormhole_damage_percent": 0.25})
    assert auth.get_config_float(None, "wormhole_damage_percent", 0.0) == 0.25


def test_typed_int_reads_from_definition():
    _set({"galaxies_per_cluster": 12})
    assert auth.get_config_int(None, "galaxies_per_cluster", 10) == 12


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
