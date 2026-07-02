#!/usr/bin/env python3
"""MSS galaxy preset — wormhole gating.

MSS games are one galaxy, an active-region picker (2/4/6/8), and no wormholes.
The wormholes flag defaults from the galaxy preset; the admin config key
``wormholes_enabled`` overrides it. ``ensure_wormholes`` (the startup repair
hook) must also remove stale wormholes when the flag is off, not re-add them.

Run: python3 test_mss_preset.py
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import universe
from database import ModelBase
from models import Wormhole
from specs import GALAXY_PRESETS


@pytest.fixture()
def db():
    saved_cache, saved_loaded = auth._config_cache, auth._config_cache_loaded
    auth._config_cache, auth._config_cache_loaded = {}, True
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    auth._config_cache, auth._config_cache_loaded = saved_cache, saved_loaded


def test_mss_preset_shape():
    mss = GALAXY_PRESETS["mss"]
    assert mss["num_clusters"] == 1
    assert mss["galaxies_per_cluster"] == 1
    assert mss["wormholes"] is False
    assert mss["active_region_size"] in (2, 4, 6, 8)


def test_wormholes_default_on_for_standard(db):
    assert universe._wormholes_enabled(db) is True


def test_mss_preset_disables_wormholes(db):
    auth._config_cache["galaxy_preset"] = "mss"
    assert universe._wormholes_enabled(db) is False


def test_admin_override_beats_preset(db):
    auth._config_cache["galaxy_preset"] = "mss"
    auth._config_cache["wormholes_enabled"] = "true"
    assert universe._wormholes_enabled(db) is True

    auth._config_cache["galaxy_preset"] = "standard"
    auth._config_cache["wormholes_enabled"] = "false"
    assert universe._wormholes_enabled(db) is False


def test_ensure_wormholes_removes_stale_when_disabled(db):
    auth._config_cache["galaxy_preset"] = "mss"
    db.add(Wormhole(planet_id=1, galaxy_id=1, wormhole_type="inner"))
    db.add(Wormhole(planet_id=2, galaxy_id=1, wormhole_type="outer"))
    db.commit()
    universe.ensure_wormholes(db)
    assert db.query(Wormhole).count() == 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
