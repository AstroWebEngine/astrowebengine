#!/usr/bin/env python3
"""map_depth=3 — flat galaxy:system:position generation (flat coordinate map).

The flat generator puts systems directly under a galaxy (numbered 1..N) with a
single synthetic Region kept only for the schema FK chain, and emits 3-part
coordinates (galaxy:system:position). The 4-level spiral path is untouched.

Run: python3 test_map_depth.py
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import ModelBase
from models import Cluster, Galaxy, Region, StarSystem, Planet
from game_definition import set_game_definition, build_default_definition
import auth
import universe


@pytest.fixture()
def db():
    # Pin the default (single-resource, map_depth=4) definition so _get_map_depth's
    # definition fallback isn't polluted by a map_depth=3 definition left active by
    # an earlier test.
    set_game_definition(build_default_definition())
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    auth.init_default_configs(s)
    yield s
    s.close()
    set_game_definition(build_default_definition())


def test_map_depth_default_is_4(db):
    assert universe._get_map_depth(db) == 4


def test_map_depth_reads_config(db):
    auth.set_config(db, "map_depth", "3")
    assert universe._get_map_depth(db) == 3


def test_flat_generation_galaxy_system_position(db):
    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    gal = Galaxy(name="A00", cluster_id=cl.id, galaxy_index=0); db.add(gal); db.flush()
    specs = auth.get_all_astro_specs(db)
    enabled = list(specs.keys())

    universe._generate_galaxy_content_flat(db, gal, 12, specs, enabled_types=enabled)
    db.commit()

    # Exactly one synthetic region holds all systems.
    regions = db.query(Region).filter(Region.galaxy_id == gal.id).all()
    assert len(regions) == 1

    systems = db.query(StarSystem).filter(StarSystem.region_id == regions[0].id).all()
    assert len(systems) == 12
    # Systems numbered galaxy-wide 001..012.
    assert {s.name for s in systems} == {f"{i:03d}" for i in range(1, 13)}
    # The system still reaches its galaxy through the (hidden) region.
    assert systems[0].region.galaxy_id == gal.id

    planets = db.query(Planet).join(StarSystem).filter(StarSystem.region_id == regions[0].id).all()
    assert len(planets) > 0
    # Coordinates are 3-part galaxy:system:position (no region segment).
    sample = planets[0].name
    assert sample.startswith("A00:") and sample.count(":") == 2, sample


def test_flat_generation_uniform_world(db):
    """Uniform worlds: no terrain variety — every position 1..N has
    one identical planet whose position sets the temperature band and a
    partially-random size; no moons at generation (those form from combat)."""
    defn = build_default_definition()
    defn["engine"]["world_model"] = "uniform"
    defn["engine"]["uniform_terrain"] = "earthly"
    defn["engine"]["uniform_positions"] = 15
    set_game_definition(defn)

    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    gal = Galaxy(name="A00", cluster_id=cl.id, galaxy_index=0); db.add(gal); db.flush()
    specs = auth.get_all_astro_specs(db)

    universe._generate_galaxy_content_flat(db, gal, 10, specs, enabled_types=list(specs.keys()))
    db.commit()

    planets = db.query(Planet).all()
    assert len(planets) == 10 * 15
    assert {p.planet_type for p in planets} == {"earthly"}
    assert all(p.orbit_row == 0 for p in planets)  # no moons at generation
    assert {p.orbit_position for p in planets} == set(range(1, 16))
    for p in planets:
        band = universe.UNIFORM_POSITION_PROFILES[p.orbit_position]
        assert band["area"][0] <= p.area <= band["area"][1]
        assert band["temperature"][0] <= p.temperature <= band["temperature"][1]
    # Hot inner slots, frozen outer slots.
    pos1 = next(p for p in planets if p.orbit_position == 1)
    pos15 = next(p for p in planets if p.orbit_position == 15)
    assert pos1.temperature > 0 > pos15.temperature


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
