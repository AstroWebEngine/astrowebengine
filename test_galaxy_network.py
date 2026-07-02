#!/usr/bin/env python3
"""Galaxy-network topology distance math (pure core, no DB).

Run: python3 test_galaxy_network.py
"""
import math

from galaxy_network import (
    compute_distance, WORMHOLE_ONLY_DISTANCE,
    build_links, galaxy_graph_distance, GRAPH_TOPOLOGIES, reshuffle_epoch,
)

STEP, CROSS, NGAL, NCLU = 200.0, 1000.0, 10, 4


def d(topo, same, ia, ib, ca=0, cb=0):
    return compute_distance(topo, same, ia, ib, ca, cb, STEP, CROSS, NGAL, NCLU)


def test_line_scales_with_gap_flat_cross():
    assert d("line", True, 0, 3) == 600        # 200 * 3
    assert d("line", False, 0, 0, 0, 2) == 1000  # flat cross-cluster


def test_equal_distance_is_flat_both_levels():
    assert d("equal_distance", True, 0, 3) == 200
    assert d("equal_distance", False, 0, 0, 0, 2) == 1000


def test_ring_takes_shorter_way_around():
    assert d("ring", True, 0, 8) == 400        # min(8, 10-8)=2 -> 200*2
    assert d("ring", True, 0, 3) == 600        # min(3, 7)=3 -> 200*3
    assert d("ring", False, 0, 0, 0, 3) == 1000  # clusters: min(3, 4-3)=1 -> 1000


def test_pumpkin_preserves_historical_behavior():
    # same-cluster linear, cross-cluster flat — the legacy pre-split behavior
    assert d("pumpkin", True, 0, 3) == 600
    assert d("pumpkin", False, 0, 0, 0, 2) == 1000


def test_wormhole_only_is_prohibitive():
    assert d("wormhole_only", True, 0, 1) == WORMHOLE_ONLY_DISTANCE
    assert d("wormhole_only", False, 0, 0, 0, 1) == WORMHOLE_ONLY_DISTANCE


# ---- Class 2: graph / link-based topologies ----

IDS = list(range(1, 13))  # 12 galaxies


def _adj(edges):
    adj = {}
    for a, b, w in edges:
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))
    return adj


def _connected(ids, edges):
    if len(ids) <= 1:
        return True
    adj = _adj(edges)
    seen, stack = {ids[0]}, [ids[0]]
    while stack:
        for nb, _ in adj.get(stack.pop(), ()):
            if nb not in seen:
                seen.add(nb); stack.append(nb)
    return seen == set(ids)


def test_all_graph_topologies_are_connected():
    for topo in GRAPH_TOPOLOGIES:
        assert _connected(IDS, build_links(IDS, topo, seed=7)), f"{topo} not connected"


def test_tree_has_exactly_n_minus_1_edges():
    assert len(build_links(IDS, "tree", seed=1)) == len(IDS) - 1


def test_graph_distance_is_multi_hop_shortest_path():
    # explicit chain 1-2-3-4 (weight 200) -> dist(1,4) = 600 over three hops
    adj = _adj([(1, 2, 200), (2, 3, 200), (3, 4, 200)])
    assert galaxy_graph_distance(1, 4, adj) == 600
    assert galaxy_graph_distance(1, 1, adj) == 0.0


def test_graph_distance_unreachable_is_inf():
    assert galaxy_graph_distance(1, 3, _adj([(1, 2, 200)])) == math.inf


def test_build_links_is_deterministic_by_seed():
    assert build_links(IDS, "k_random", seed=42) == build_links(IDS, "k_random", seed=42)


# ---- Class 3: dynamic wormholes (reshuffle) ----

def test_reshuffle_epoch_rolls_over_on_interval():
    hr = 168.0                      # weekly
    period = hr * 3600
    assert reshuffle_epoch(0, hr) == 0
    assert reshuffle_epoch(period - 1, hr) == 0
    assert reshuffle_epoch(period, hr) == 1
    assert reshuffle_epoch(period * 3 + 5, hr) == 3


def test_dynamic_wormholes_stable_within_epoch_changes_between():
    e1a = build_links(IDS, "dynamic_wormholes", seed=1)
    e1b = build_links(IDS, "dynamic_wormholes", seed=1)
    e2 = build_links(IDS, "dynamic_wormholes", seed=2)
    assert e1a == e1b               # stable within a reshuffle period
    assert e1a != e2                # the map changes between periods
    assert _connected(IDS, e1a) and _connected(IDS, e2)  # never strands anyone


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print(f"OK {t.__name__}")
    print("\n" + "=" * 60)
    print(" ALL GALAXY-NETWORK TESTS PASSED!")
    print("=" * 60)
