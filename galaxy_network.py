"""Galaxy-network topology — the map's TOP layer: how galaxies and clusters are
arranged, and the travel distance between them.

This is the engine option `engine.galaxy_network` (setup-only). It is DISTINCT
from two other axes it used to be conflated with:
  - intra-galaxy system placement (galaxy_shape), and
  - the whole-map structure `map_topology` (hierarchy vs graph).

Distance between two DIFFERENT galaxies, by topology (same-galaxy distance is the
hierarchical 2D-grid calc handled upstream in game_logic):
  - "ring"           : galaxies on a circle within a cluster, clusters on a circle;
                       distance is the shorter way around. Neutral public default.
  - "equal_distance" : every galaxy in a cluster equidistant; every cluster equidistant.
  - "line"           : sequential chain; distance grows with index separation.
  - "pumpkin"        : classic asymmetric arrangement (private preset; the historical
                       same-cluster-linear / flat-cross-cluster behavior).
  - "wormhole_only"  : galaxies are NOT directly connected; only wormholes / jump
                       gates cross galaxies (direct distance is prohibitive).
"""
import heapq
import math
import random
from datetime import datetime

from sqlalchemy.orm import object_session

from auth import get_config, get_config_float, get_config_int, set_config
from config_defaults import SAME_CLUSTER_GALAXY_DISTANCE, CROSS_CLUSTER_DISTANCE

# Direct inter-galaxy travel is effectively impossible under wormhole_only, so the
# fleet-travel layer falls through to wormhole / jump-gate routing.
WORMHOLE_ONLY_DISTANCE = 1_000_000_000

# Graph/link-based topologies: distance is the shortest path over GalaxyLink edges
# (vs the static geometric topologies, whose distance is a closed-form function).
GRAPH_TOPOLOGIES = {"lane_network", "tree", "small_world", "k_random", "dynamic_wormholes"}


def is_graph_topology(db) -> bool:
    return galaxy_network(db) in GRAPH_TOPOLOGIES


def galaxy_network(db) -> str:
    """Active galaxy-network topology. Honors the new `galaxy_network` flag, then
    falls back to the legacy `map_topology` (pumpkin/classic) values for
    back-compat, and finally to the neutral ring default."""
    val = (get_config(db, "galaxy_network", "") or "").strip()
    if val:
        return val
    legacy = (get_config(db, "map_topology", "") or "").strip()
    if legacy == "pumpkin":
        return "pumpkin"
    if legacy == "classic":
        return "line"
    return "ring"


def _ring_steps(a, b, n) -> int:
    """Hops between two positions on a circle of size n (shorter way around)."""
    gap = abs(int(a) - int(b))
    return max(1, min(gap, n - gap))


def _cluster_index(gal) -> int:
    c = getattr(gal, "cluster", None)
    idx = getattr(c, "cluster_index", None) if c is not None else None
    return int(idx) if idx is not None else 0


def compute_distance(topo, same_cluster, ia, ib, ca, cb, step, cross, n_gal, n_clu) -> float:
    """Pure distance core (no DB) so topologies are unit-testable."""
    if topo == "wormhole_only":
        return WORMHOLE_ONLY_DISTANCE
    if same_cluster:
        if topo == "equal_distance":
            return step
        if topo == "ring":
            return step * _ring_steps(ia, ib, n_gal)
        # line / pumpkin: linear separation (historical behavior)
        return step * max(1, abs(int(ia) - int(ib)))
    # Cross-cluster
    if topo == "equal_distance":
        return cross
    if topo == "ring":
        return cross * _ring_steps(ca, cb, n_clu)
    # line / pumpkin: flat cross-cluster (historical behavior)
    return cross


def galaxy_distance(gal_a, gal_b, db=None) -> float:
    """Travel distance between two DIFFERENT galaxies under the active topology."""
    if db is None:
        db = object_session(gal_a)
    topo = galaxy_network(db)
    if topo in GRAPH_TOPOLOGIES:
        hops = galaxy_graph_distance(gal_a.id, gal_b.id, _galaxy_adjacency(db))
        return WORMHOLE_ONLY_DISTANCE if hops == math.inf else hops
    return compute_distance(
        topo,
        bool(gal_a.cluster_id and gal_b.cluster_id and gal_a.cluster_id == gal_b.cluster_id),
        gal_a.galaxy_index or 0, gal_b.galaxy_index or 0,
        _cluster_index(gal_a), _cluster_index(gal_b),
        get_config_float(db, "same_cluster_galaxy_distance", SAME_CLUSTER_GALAXY_DISTANCE),
        get_config_float(db, "cross_cluster_distance", CROSS_CLUSTER_DISTANCE),
        max(1, get_config_int(db, "galaxies_per_cluster", 10)),
        max(1, get_config_int(db, "num_clusters", 4)),
    )


# ===========================================================================
# Graph / link-based topologies — shortest path over GalaxyLink edges.
# Mirrors graph_map.py (which does the same over SystemLink at the system level).
# ===========================================================================

_galaxy_adj_cache = None


def invalidate_galaxy_graph_cache():
    """Drop the cached galaxy adjacency. Call after (re)generating GalaxyLinks."""
    global _galaxy_adj_cache
    _galaxy_adj_cache = None


def _build_galaxy_adjacency(db) -> dict:
    from models import GalaxyLink
    adj = {}
    for link in db.query(GalaxyLink).all():
        w = float(link.distance or 1)
        adj.setdefault(link.galaxy_a_id, []).append((link.galaxy_b_id, w))
        adj.setdefault(link.galaxy_b_id, []).append((link.galaxy_a_id, w))  # bidirectional
    return adj


def _galaxy_adjacency(db) -> dict:
    global _galaxy_adj_cache
    if _galaxy_adj_cache is None:
        _galaxy_adj_cache = _build_galaxy_adjacency(db)
    return _galaxy_adj_cache


def galaxy_graph_distance(gal_a_id, gal_b_id, adj) -> float:
    """Dijkstra shortest-path cost over a galaxy adjacency map; inf if unreachable.

    `adj` maps galaxy_id -> list of (neighbor_id, weight). Pure (no DB)."""
    if gal_a_id == gal_b_id:
        return 0.0
    dist = {gal_a_id: 0.0}
    pq = [(0.0, gal_a_id)]
    while pq:
        d, node = heapq.heappop(pq)
        if node == gal_b_id:
            return d
        if d > dist.get(node, math.inf):
            continue
        for nb, w in adj.get(node, ()):  # neighbors
            nd = d + w
            if nd < dist.get(nb, math.inf):
                dist[nb] = nd
                heapq.heappush(pq, (nd, nb))
    return math.inf


# ---- Link generation per graph topology (pure: returns an edge list) ----

def _pair(a, b):
    return (a, b) if a <= b else (b, a)


def _ensure_connected(ids, edges, rng):
    """Union-find: add edges until every galaxy sits in one component."""
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    # Stitch each remaining component to the first.
    comp = {}
    for i in ids:
        comp.setdefault(find(i), i)
    reps = list(comp.values())
    for i in range(1, len(reps)):
        edges.add(_pair(reps[0], reps[i]))
        parent[find(reps[0])] = find(reps[i])


def build_links(galaxy_ids, topology, *, k=2, seed=0, weight=200):
    """Edges [(a_id, b_id, weight)] for a graph topology, guaranteed connected.

    `galaxy_ids` should be in a stable order (e.g. by galaxy_index). Pure — no DB.
    """
    ids = list(galaxy_ids)
    n = len(ids)
    if n <= 1:
        return []
    rng = random.Random(seed)
    edges = set()
    if topology == "tree":
        # Random spanning tree: each node links to one earlier node (n-1 edges,
        # exactly one path between any two galaxies — chokepoints everywhere).
        for i in range(1, n):
            edges.add(_pair(ids[rng.randrange(i)], ids[i]))
    elif topology in ("k_random", "dynamic_wormholes"):
        # Each galaxy gets k random links; connectivity stitched afterwards.
        # dynamic_wormholes uses this shape but is regenerated each reshuffle epoch.
        for i in range(n):
            for _ in range(k):
                j = rng.randrange(n)
                if j != i:
                    edges.add(_pair(ids[i], ids[j]))
        _ensure_connected(ids, edges, rng)
    elif topology == "small_world":
        # Ring lattice + a few random long-range shortcuts (Watts-Strogatz-ish).
        for i in range(n):
            edges.add(_pair(ids[i], ids[(i + 1) % n]))
        for i in range(n):
            if rng.random() < 0.2:
                edges.add(_pair(ids[i], ids[rng.randrange(n)]))
    else:  # lane_network (default graph): a backbone chain + extra lanes
        for i in range(n - 1):
            edges.add(_pair(ids[i], ids[i + 1]))
        for _ in range(max(1, n // 5)):
            a, b = rng.randrange(n), rng.randrange(n)
            if a != b:
                edges.add(_pair(ids[a], ids[b]))
        _ensure_connected(ids, edges, rng)
    return [(a, b, weight) for (a, b) in sorted(edges)]


# ===========================================================================
# Class 3 — dynamic wormholes: periodically reshuffle the galaxy-link graph.
# ===========================================================================
# In-flight fleets are grandfathered automatically: a fleet's arrival_time is
# fixed at send-time, so a reshuffle only changes distances for FUTURE moves —
# nothing already in transit is stranded or rerouted.

DEFAULT_RESHUFFLE_HOURS = 168.0  # weekly


def reshuffle_epoch(now_ts: float, interval_hours: float) -> int:
    """Which reshuffle period `now` falls in. Stable within a period, so every
    worker agrees and regeneration is deterministic (seed = epoch)."""
    period = max(1.0, interval_hours * 3600.0)
    return int(now_ts // period)


def reshuffle_galaxy_links(db, seed: int):
    """Regenerate every GalaxyLink from scratch for the active graph topology,
    seeded by `seed` (the epoch), and drop the adjacency cache."""
    from models import Galaxy, GalaxyLink
    topo = galaxy_network(db)
    gids = [g.id for g in db.query(Galaxy).order_by(Galaxy.cluster_id, Galaxy.galaxy_index).all()]
    db.query(GalaxyLink).delete()
    for a, b, w in build_links(gids, topo, seed=seed):
        db.add(GalaxyLink(galaxy_a_id=a, galaxy_b_id=b, distance=w))
    invalidate_galaxy_graph_cache()


def maybe_reshuffle_galaxy_links(db, now=None) -> bool:
    """If the active topology reshuffles and a new period has begun, regenerate
    the link graph. Returns True if it reshuffled. Safe to call frequently and
    from multiple workers — idempotent within an epoch (same seed -> same graph)."""
    if galaxy_network(db) != "dynamic_wormholes":
        return False
    interval = get_config_float(db, "galaxy_reshuffle_hours", DEFAULT_RESHUFFLE_HOURS)
    now_ts = (now or datetime.utcnow()).timestamp()
    epoch = reshuffle_epoch(now_ts, interval)
    if epoch <= get_config_int(db, "galaxy_reshuffle_epoch", -1):
        return False
    reshuffle_galaxy_links(db, seed=epoch)
    set_config(db, "galaxy_reshuffle_epoch", str(epoch))
    db.commit()
    return True
