"""
Graph map topology — engine option (engine.map_topology == "graph").

Instead of the coordinate hierarchy (distance = Pythagorean on a grid), systems
are connected by explicit SystemLink edges and "distance" is the shortest-path
cost over those links. Wormholes are long-range edges. Inert in hierarchy mode.

This module is self-contained: configuration reads the active game definition,
distance queries the SystemLink table, and generation builds links over existing
systems. The engine call-sites that consume these (travel's _calc_distance,
universe generation) wire in separately.
"""
import heapq
import math

from game_definition import get_game_definition

_DEFAULT_GRAPH = {
    "links_per_system": [2, 6],
    "allow_one_way": False,
    "wormhole_ratio": 0.03,
    "link_cost_model": "hops",  # "hops" (each edge = 1) | "weighted" (edge.weight)
    "hop_distance": 15,          # travel-distance units per graph hop (feeds travel time)
}


def _engine(db) -> dict:
    return get_game_definition().get("engine", {}) or {}


def map_topology(db) -> str:
    return _engine(db).get("map_topology", "hierarchy")


def is_graph_map(db) -> bool:
    return map_topology(db) == "graph"


def graph_config(db) -> dict:
    cfg = dict(_DEFAULT_GRAPH)
    cfg.update(_engine(db).get("graph", {}) or {})
    return cfg


# ---------------------------------------------------------------------------
# Adjacency cache + shortest-path distance
# ---------------------------------------------------------------------------

_adj_cache = None


def invalidate_graph_cache():
    """Drop the cached adjacency (call after generating/changing links)."""
    global _adj_cache
    _adj_cache = None


def _build_adjacency(db) -> dict:
    from models import SystemLink
    adj = {}
    for link in db.query(SystemLink).all():
        w = float(link.weight or 1.0)
        adj.setdefault(link.system_a_id, []).append((link.system_b_id, w))
        if not link.one_way:
            adj.setdefault(link.system_b_id, []).append((link.system_a_id, w))
    return adj


def adjacency(db) -> dict:
    global _adj_cache
    if _adj_cache is None:
        _adj_cache = _build_adjacency(db)
    return _adj_cache


def graph_distance(system_a_id, system_b_id, db, adj=None) -> float:
    """Shortest-path cost between two systems over SystemLink.

    Returns 0 for same system and math.inf when unreachable. Pass a prebuilt
    `adj` to avoid recomputing within a batch.
    """
    if system_a_id == system_b_id:
        return 0.0
    adj = adj if adj is not None else adjacency(db)
    dist = {system_a_id: 0.0}
    pq = [(0.0, system_a_id)]
    while pq:
        d, node = heapq.heappop(pq)
        if node == system_b_id:
            return d
        if d > dist.get(node, math.inf):
            continue
        for nb, w in adj.get(node, ()):  # neighbors
            nd = d + w
            if nd < dist.get(nb, math.inf):
                dist[nb] = nd
                heapq.heappush(pq, (nd, nb))
    return math.inf


def reachable(system_a_id, system_b_id, db, adj=None) -> bool:
    return graph_distance(system_a_id, system_b_id, db, adj=adj) != math.inf


# ---------------------------------------------------------------------------
# Link generation (over existing systems)
# ---------------------------------------------------------------------------

def _system_xy(system) -> tuple:
    """2D layout position of a system, matching the UI/universe convention:
    the 2-digit system name is row(tens)+col(ones) (map.js: subRow=pos//10,
    subCol=pos%10), offset by the region grid. Used to seed nearest-neighbour
    links and as node positions for the graph map view.

    (Distance/generation is invariant under swapping x/y, but the exposed x/y
    must match the grid so a node-link overlay aligns with it.)"""
    region = system.region
    gx = (region.grid_x if region else 0) * 10
    gy = (region.grid_y if region else 0) * 10
    name = system.name or "00"
    col = int(name[1]) if len(name) >= 2 and name[1].isdigit() else 0  # ones digit = column (x)
    row = int(name[0]) if len(name) >= 2 and name[0].isdigit() else 0  # tens digit = row (y)
    galaxy_id = region.galaxy_id if region else 0
    return (galaxy_id, gx + col, gy + row)


class _UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self):
        g = {}
        for i in self.parent:
            g.setdefault(self.find(i), []).append(i)
        return list(g.values())


def generate_graph_links(db, cfg=None, rng=None):
    """(Re)build SystemLink edges over all existing systems. Returns a report.

    Deterministic given the same systems + cfg (no RNG needed): nearest-neighbour
    links + a connectivity-guaranteeing spanning pass + long-range wormholes.
    Replaces any existing links.
    """
    from models import StarSystem, SystemLink
    cfg = cfg or _DEFAULT_GRAPH
    lo, hi = (cfg.get("links_per_system") or [2, 6])[:2] if isinstance(cfg.get("links_per_system"), list) else (2, 6)
    weighted = cfg.get("link_cost_model") == "weighted"

    systems = db.query(StarSystem).all()
    coords = {s.id: _system_xy(s) for s in systems}
    ids = list(coords.keys())
    db.query(SystemLink).delete(synchronize_session=False)

    if len(ids) < 2:
        db.commit()
        invalidate_graph_cache()
        return {"systems": len(ids), "links": 0, "wormholes": 0, "components_merged": 0}

    def euclid(a, b):
        (ga, ax, ay), (gb, bx, by) = coords[a], coords[b]
        d = math.hypot(ax - bx, ay - by)
        if ga != gb:
            # Keep nearest-neighbour links intra-galaxy; cross-galaxy pairs are
            # far and get bridged by the connectivity pass + wormhole edges.
            d += 1000.0
        return d

    edges = set()  # frozenset({a,b})

    def add_edge(a, b, kind="link"):
        if a == b:
            return
        key = frozenset((a, b))
        if key in edges:
            return
        edges.add(key)
        w = round(euclid(a, b), 2) if weighted else 1.0
        db.add(SystemLink(system_a_id=a, system_b_id=b, weight=w or 1.0, kind=kind, one_way=False))

    # 1) nearest-neighbour links — only WITHIN a galaxy (keeps generation
    # O(Σ n_g²) instead of O(N²); cross-galaxy is bridged by the connectivity
    # pass + wormholes, which also yields the right "local networks" topology).
    by_galaxy = {}
    for i in ids:
        by_galaxy.setdefault(coords[i][0], []).append(i)
    degree = {i: 0 for i in ids}
    want = max(lo, min(hi, hi))
    for gal_ids in by_galaxy.values():
        for a in gal_ids:
            nearest = sorted((b for b in gal_ids if b != a), key=lambda b: euclid(a, b))
            added = 0
            for b in nearest:
                if added >= want:
                    break
                if degree[a] >= hi or degree[b] >= hi:
                    continue
                if frozenset((a, b)) in edges:
                    continue
                add_edge(a, b)
                degree[a] += 1
                degree[b] += 1
                added += 1

    # 2) connectivity guarantee — union-find, bridge disjoint components by nearest pair
    uf = _UnionFind(ids)
    for key in edges:
        a, b = tuple(key)
        uf.union(a, b)
    comps = uf.groups()
    merged = 0
    while len(comps) > 1:
        base = comps[0]
        # connect base to the nearest node in any other component
        best = None
        for other in comps[1:]:
            for a in base:
                for b in other:
                    d = euclid(a, b)
                    if best is None or d < best[0]:
                        best = (d, a, b)
        if not best:
            break
        add_edge(best[1], best[2])
        uf.union(best[1], best[2])
        merged += 1
        comps = uf.groups()

    # 3) long-range wormhole edges
    wh_target = int(len(ids) * float(cfg.get("wormhole_ratio", 0.0)))
    wormholes = 0
    for i in range(wh_target):
        a = ids[(i * 7919) % len(ids)]          # deterministic spread, no RNG
        b = ids[(i * 104729 + 1) % len(ids)]
        if a != b and frozenset((a, b)) not in edges:
            add_edge(a, b, kind="wormhole")
            wormholes += 1

    db.commit()
    invalidate_graph_cache()
    return {
        "systems": len(ids),
        "links": len(edges) - wormholes,
        "wormholes": wormholes,
        "components_merged": merged,
    }
