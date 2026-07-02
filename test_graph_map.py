#!/usr/bin/env python3
"""
Tests for graph map topology (graph_map.py).

Distance is tested against a hand-built adjacency (no DB). Generation +
connectivity run on a throwaway in-memory SQLite so the real DB is never touched.

Run: python3 test_graph_map.py
"""
import math

import graph_map as gm


def test_graph_distance_hops():
    # 0-1-2-3 chain + a shortcut 0-3 weight... here all weight 1 (hops)
    adj = {
        1: [(2, 1.0)], 2: [(1, 1.0), (3, 1.0)], 3: [(2, 1.0), (4, 1.0)], 4: [(3, 1.0)],
    }
    assert gm.graph_distance(1, 1, None, adj=adj) == 0.0
    assert gm.graph_distance(1, 4, None, adj=adj) == 3.0
    assert gm.graph_distance(1, 3, None, adj=adj) == 2.0


def test_graph_distance_weighted_prefers_cheaper_path():
    # 1->2 cost 10, 1->3->2 cost 1+1=2
    adj = {1: [(2, 10.0), (3, 1.0)], 3: [(1, 1.0), (2, 1.0)], 2: [(3, 1.0), (1, 10.0)]}
    assert gm.graph_distance(1, 2, None, adj=adj) == 2.0


def test_graph_distance_unreachable():
    adj = {1: [(2, 1.0)], 2: [(1, 1.0)], 5: [(6, 1.0)], 6: [(5, 1.0)]}
    assert gm.graph_distance(1, 5, None, adj=adj) == math.inf
    assert gm.reachable(1, 5, None, adj=adj) is False
    assert gm.reachable(1, 2, None, adj=adj) is True


def test_build_adjacency_respects_one_way_and_ignores_self_loop_for_reachability():
    gm.invalidate_graph_cache()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import ModelBase
    from models import Cluster, Galaxy, Region, StarSystem, SystemLink
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    gal = Galaxy(name="A00", cluster_id=cl.id, galaxy_index=0); db.add(gal); db.flush()
    reg = Region(name="00", galaxy_id=gal.id, grid_x=0, grid_y=0); db.add(reg); db.flush()
    s1 = StarSystem(name="00", region_id=reg.id); db.add(s1); db.flush()
    s2 = StarSystem(name="01", region_id=reg.id); db.add(s2); db.flush()
    db.add(SystemLink(system_a_id=s1.id, system_b_id=s1.id, weight=1.0, one_way=False))
    db.add(SystemLink(system_a_id=s1.id, system_b_id=s2.id, weight=1.0, one_way=True))
    db.commit()
    adj = gm._build_adjacency(db)
    assert gm.graph_distance(s1.id, s1.id, db, adj=adj) == 0.0
    assert gm.reachable(s1.id, s2.id, db, adj=adj) is True
    assert gm.reachable(s2.id, s1.id, db, adj=adj) is False
    db.close()


def _memory_db_with_systems(n_per_galaxy=6, galaxies=2):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import ModelBase
    from models import Cluster, Galaxy, Region, StarSystem
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    sid = 0
    for g in range(galaxies):
        gal = Galaxy(name=f"A0{g}", cluster_id=cl.id, galaxy_index=g); db.add(gal); db.flush()
        reg = Region(name=f"R{g}", galaxy_id=gal.id, grid_x=g, grid_y=0); db.add(reg); db.flush()
        for s in range(n_per_galaxy):
            sys = StarSystem(name=f"{s}{g}", region_id=reg.id); db.add(sys)
        db.flush()
    db.commit()
    return db


def test_generate_links_connects_all_systems():
    gm.invalidate_graph_cache()
    db = _memory_db_with_systems(n_per_galaxy=6, galaxies=2)  # 12 systems
    from models import StarSystem, SystemLink
    report = gm.generate_graph_links(db, {"links_per_system": [2, 4], "wormhole_ratio": 0.1,
                                          "link_cost_model": "hops"})
    assert report["systems"] == 12
    assert report["links"] > 0
    # every system reachable from the first (connectivity guarantee held)
    ids = [s.id for s in db.query(StarSystem).all()]
    adj = gm._build_adjacency(db)
    first = ids[0]
    for sid in ids[1:]:
        assert gm.reachable(first, sid, db, adj=adj), f"system {sid} unreachable"
    # links actually persisted
    assert db.query(SystemLink).count() == report["links"] + report["wormholes"]
    db.close()


def test_generate_links_handles_zero_and_one_system():
    gm.invalidate_graph_cache()
    db0 = _memory_db_with_systems(n_per_galaxy=0, galaxies=1)
    r0 = gm.generate_graph_links(db0, {"links_per_system": [2, 4], "wormhole_ratio": 0})
    assert r0 == {"systems": 0, "links": 0, "wormholes": 0, "components_merged": 0}
    db0.close()

    db1 = _memory_db_with_systems(n_per_galaxy=1, galaxies=1)
    r1 = gm.generate_graph_links(db1, {"links_per_system": [2, 4], "wormhole_ratio": 0})
    assert r1 == {"systems": 1, "links": 0, "wormholes": 0, "components_merged": 0}
    db1.close()


def test_generate_links_bridges_two_single_system_galaxies():
    gm.invalidate_graph_cache()
    db = _memory_db_with_systems(n_per_galaxy=1, galaxies=2)
    from models import StarSystem, SystemLink
    report = gm.generate_graph_links(db, {"links_per_system": [2, 4], "wormhole_ratio": 0,
                                          "link_cost_model": "hops"})
    ids = [s.id for s in db.query(StarSystem).order_by(StarSystem.id).all()]
    assert report["systems"] == 2
    assert report["components_merged"] == 1
    assert db.query(SystemLink).count() == 1
    assert gm.reachable(ids[0], ids[1], db, adj=gm._build_adjacency(db)) is True
    db.close()


def test_wormhole_ratio_above_one_is_finite_and_unique():
    gm.invalidate_graph_cache()
    db = _memory_db_with_systems(n_per_galaxy=5, galaxies=1)
    from models import SystemLink
    report = gm.generate_graph_links(db, {"links_per_system": [1, 1], "wormhole_ratio": 10,
                                          "link_cost_model": "hops"})
    total_unique_pairs = 5 * 4 // 2
    assert db.query(SystemLink).count() <= total_unique_pairs
    assert report["wormholes"] == db.query(SystemLink).filter(SystemLink.kind == "wormhole").count()
    db.close()


def test_generate_is_idempotent_replaces_links():
    gm.invalidate_graph_cache()
    db = _memory_db_with_systems(n_per_galaxy=5, galaxies=1)
    from models import SystemLink
    r1 = gm.generate_graph_links(db, {"links_per_system": [2, 3], "wormhole_ratio": 0.0})
    c1 = db.query(SystemLink).count()
    r2 = gm.generate_graph_links(db, {"links_per_system": [2, 3], "wormhole_ratio": 0.0})
    c2 = db.query(SystemLink).count()
    assert c1 == c2  # regenerated, not duplicated
    db.close()


def _memory_db_chain(n=4):
    """1 galaxy, n systems in a chain (link i—i+1), one planet per system."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import ModelBase
    from models import Cluster, Galaxy, Region, StarSystem, Planet, SystemLink
    eng = create_engine("sqlite:///:memory:")
    ModelBase.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    cl = Cluster(name="A", cluster_index=0); db.add(cl); db.flush()
    gal = Galaxy(name="A00", cluster_id=cl.id, galaxy_index=0); db.add(gal); db.flush()
    reg = Region(name="R0", galaxy_id=gal.id, grid_x=0, grid_y=0); db.add(reg); db.flush()
    sys_ids, planet_ids = [], []
    for s in range(n):
        sysrow = StarSystem(name=f"{s}0", region_id=reg.id); db.add(sysrow); db.flush()
        sys_ids.append(sysrow.id)
        p = Planet(name=f"A00:00:{s}0:1", system_id=sysrow.id, orbit_position=1); db.add(p); db.flush()
        planet_ids.append(p.id)
    for i in range(n - 1):
        db.add(SystemLink(system_a_id=sys_ids[i], system_b_id=sys_ids[i + 1], weight=1.0, kind="link"))
    db.commit()
    return db, planet_ids


def test_calc_distance_uses_graph_in_graph_mode():
    gm.invalidate_graph_cache()
    from game_definition import set_game_definition
    import game_logic
    db, planets = _memory_db_chain(4)
    from models import Planet
    p0 = db.query(Planet).filter(Planet.id == planets[0]).first()
    p3 = db.query(Planet).filter(Planet.id == planets[3]).first()
    p1 = db.query(Planet).filter(Planet.id == planets[1]).first()
    # graph mode: 3 hops * hop_distance(10) = 30; 1 hop = 10
    set_game_definition({"engine": {"map_topology": "graph", "graph": {"hop_distance": 10}}})
    gm.invalidate_graph_cache()
    assert game_logic._calc_distance(p0, p3) == 30
    assert game_logic._calc_distance(p0, p1) == 10
    # hierarchy mode: falls back to Pythagorean (different, smaller number here)
    set_game_definition({"engine": {"map_topology": "hierarchy"}})
    d_hier = game_logic._calc_distance(p0, p3)
    assert d_hier != 30, "should use hierarchy distance when not graph mode"
    set_game_definition(None) if False else None
    db.close()


def test_solar_empire_mod_is_graph():
    from game_definition import load_definition_from_file, set_game_definition
    defn = load_definition_from_file("mods/solar_empire/definition.json")
    set_game_definition(defn)
    assert gm.is_graph_map(None) is True
    assert gm.graph_config(None).get("hop_distance") == 20


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL GRAPH-MAP TESTS PASSED!")
    print("=" * 60)
