"""
AstroClone OS-Rush Bot Test Script
====================================
Drives 4 existing bot accounts through the optimized Medium Ship 3 rush build
order from awe_simulator.py (Uriel/MR6 variant).

Usage:
    python test_os_rush.py [--url http://localhost:8001] [--speed 100]

The server must already be running with:
  - Admin account: admin / admin@test.com / admin123
  - Bot accounts: os_bot_alpha/beta/gamma/delta already registered + homeworlds assigned

The script:
  1. Logs in admin + 4 bot accounts.
  2. Skips tutorial for each bot (idempotent).
  3. Polls each bot's state and queues the next build/research/production action
     whenever a queue slot becomes free and credits allow.
  4. Bots create trade routes with each other once Spaceports 1 is built.
  5. Logs timestamps of every key milestone for comparison with awe_simulator.py.

Build order (Uriel/MR6 variant from awe_simulator.py):
  Construction: MR1-5, GP1, US2, SPO1, Labs1, SPO2, SP1, SPO3, MR6, SPO4,
                US3, GP2, SPO5, RF1, RF2, SP2, Labs2, US4, SY1-2, MR7,
                GP3, RF3-4, SY3-8, US5-6, GP4, Labs3-8, ...
  Research:     Computer1-2, Energy1-8, Laser1-2, Armour1-2, SD1-4, WarpDrive1
  Production:   Goods (credit farming), Small Ship 1 (tutorial), Small Ship 5 (tutorial),
                Medium Ship 3 (goal)
  Trade:        After SPO1 (distance ~4 to nearest bot), after SPO5 (2nd route)

API summary:
  POST /api/login                  {email, password}  -> {access_token}
  POST /api/tutorial/skip          {}                 -> {ok}
  GET  /api/bases                  -> list of base objects (with construction_queue, ship_queue, buildings)
  GET  /api/research               ?base_id=N         -> list of research objects
  GET  /api/research-queue         ?base_id=N         -> list of queue items
  POST /api/bases/upgrade          {base_id, building_type}
  POST /api/research               {tech_type, base_id}
  POST /api/fleets/build           {base_id, ship_type, count}
  POST /api/trade-routes           {base_a_id, base_b_id}
  POST /api/trade-routes/{id}/accept {}
  GET  /api/trade-routes           -> {routes: [...], total_income, num_players}
  GET  /api/galaxies/list          -> {galaxies: [...]}
  GET  /api/my-bases-coords        -> list of {base_id, planet_name, galaxy_id, region_id, system_id}
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_URL = "http://localhost:8001"
POLL_INTERVAL_SECONDS = 1
LOG_FILE = "test_os_rush_log.json"

# Max items in each queue — must match server's config_defaults.py
CONSTRUCTION_QUEUE_MAX = 6   # Server: 1 active + 5 queued
RESEARCH_QUEUE_MAX = 6       # Server: 1 active + 5 queued
PRODUCTION_QUEUE_MAX = 12    # Server: 1 active + 11 queued

# Bot accounts (must already exist on server)
BOTS = [
    {"username": "os_bot_alpha",   "email": "os_bot_alpha@example.com",   "password": "osbot1234!"},
    {"username": "os_bot_beta",    "email": "os_bot_beta@example.com",    "password": "osbot1234!"},
    {"username": "os_bot_gamma",   "email": "os_bot_gamma@example.com",   "password": "osbot1234!"},
    {"username": "os_bot_delta",   "email": "os_bot_delta@example.com",   "password": "osbot1234!"},
]

ADMIN = {"username": "admin", "email": "admin@test.com", "password": "admin123"}

# ─────────────────────────────────────────────────────────────────────────────
# Build order definition (Uriel/MR6 variant from awe_simulator.py)
# ─────────────────────────────────────────────────────────────────────────────
#
# Format: list of dicts with keys:
#   queue:       "construction" | "research" | "production"
#   type:        building_type / tech_type / ship_type / "goods"
#   note:        human-readable label for logging
#   count:       (production only) how many to build
#   trade_after: (construction only) open a trade route when this level completes
#
# Building type names match AstroClone specs.py keys:
#   metal_refineries, solar_plants, gas_plants, crystal_mines,
#   urban_structures, spaceports, research_labs, robotic_factories,
#   shipyard, fusion_plants, ...
#
# Research tech type names match specs.py RESEARCH_SPECS keys:
#   computer, energy, laser, armour, stellar_drive, warp_drive, ...
#
# Ship types: small_ship_1, small_ship_5, medium_ship_3, goods (special)

BUILD_PLAN = [
    # ── Phase 1: MR rush ──────────────────────────────────────────────────
    {"queue": "construction", "type": "metal_refineries",  "note": "MR1"},
    {"queue": "construction", "type": "metal_refineries",  "note": "MR2"},
    {"queue": "construction", "type": "solar_plants",      "note": "SP1 (energy+tut)"},
    {"queue": "construction", "type": "metal_refineries",  "note": "MR3"},
    {"queue": "construction", "type": "metal_refineries",  "note": "MR4"},
    {"queue": "construction", "type": "metal_refineries",  "note": "MR5"},
    {"queue": "construction", "type": "gas_plants",        "note": "GP1"},
    {"queue": "construction", "type": "urban_structures",  "note": "US1 (HW has 1, skip)"},
    {"queue": "construction", "type": "urban_structures",  "note": "US2 (pop for SPO)"},

    # ── Phase 2: Spaceports + Research ───────────────────────────────────
    {"queue": "construction", "type": "spaceports",        "note": "SPO1", "trade_after": True},
    {"queue": "construction", "type": "research_labs",     "note": "Labs1"},
    {"queue": "research",     "type": "computer",          "note": "Computer1"},
    {"queue": "construction", "type": "spaceports",        "note": "SPO2"},
    {"queue": "construction", "type": "solar_plants",      "note": "SP2"},
    {"queue": "construction", "type": "spaceports",        "note": "SPO3"},
    {"queue": "research",     "type": "computer",          "note": "Computer2"},
    {"queue": "construction", "type": "metal_refineries",  "note": "MR6"},
    {"queue": "construction", "type": "spaceports",        "note": "SPO4"},
    {"queue": "research",     "type": "energy",            "note": "Energy1"},
    {"queue": "construction", "type": "urban_structures",  "note": "US3"},
    {"queue": "research",     "type": "energy",            "note": "Energy2"},
    {"queue": "construction", "type": "gas_plants",        "note": "GP2"},
    {"queue": "construction", "type": "spaceports",        "note": "SPO5", "trade_after": True},
    {"queue": "research",     "type": "energy",            "note": "Energy3"},

    # ── Phase 3: RFs + early shipyard ────────────────────────────────────
    {"queue": "construction", "type": "robotic_factories", "note": "RF1"},
    {"queue": "construction", "type": "robotic_factories", "note": "RF2"},
    {"queue": "construction", "type": "solar_plants",      "note": "SP3"},
    {"queue": "construction", "type": "research_labs",     "note": "Labs2"},
    {"queue": "research",     "type": "laser",             "note": "Laser1"},
    {"queue": "construction", "type": "urban_structures",  "note": "US4"},
    {"queue": "construction", "type": "shipyard",          "note": "SY1"},
    {"queue": "production",   "type": "small_ship_1",          "note": "Small Ship 1 (tutorial)", "count": 1},
    {"queue": "construction", "type": "shipyard",          "note": "SY2"},
    {"queue": "construction", "type": "metal_refineries",  "note": "MR7"},
    {"queue": "construction", "type": "gas_plants",        "note": "GP3"},
    {"queue": "production",   "type": "goods",             "note": "Goods1", "count": 1},
    {"queue": "construction", "type": "robotic_factories", "note": "RF3"},
    {"queue": "construction", "type": "robotic_factories", "note": "RF4"},

    # ── Phase 4: SY rush + credit farming ────────────────────────────────
    {"queue": "construction", "type": "shipyard",          "note": "SY3"},
    {"queue": "construction", "type": "urban_structures",  "note": "US5"},
    {"queue": "production",   "type": "goods",             "note": "Goods2", "count": 1},
    {"queue": "construction", "type": "shipyard",          "note": "SY4"},
    {"queue": "research",     "type": "armour",            "note": "Armour1"},
    {"queue": "construction", "type": "solar_plants",      "note": "SP4"},
    {"queue": "construction", "type": "shipyard",          "note": "SY5"},
    {"queue": "production",   "type": "goods",             "note": "Goods3", "count": 1},
    {"queue": "construction", "type": "shipyard",          "note": "SY6"},
    {"queue": "production",   "type": "goods",             "note": "Goods4", "count": 1},
    {"queue": "research",     "type": "energy",            "note": "Energy4"},
    {"queue": "production",   "type": "goods",             "note": "Goods5", "count": 1},
    {"queue": "production",   "type": "goods",             "note": "Goods6", "count": 1},
    {"queue": "construction", "type": "shipyard",          "note": "SY7"},
    {"queue": "research",     "type": "energy",            "note": "Energy5"},
    {"queue": "production",   "type": "goods",             "note": "Goods7", "count": 1},
    {"queue": "production",   "type": "goods",             "note": "Goods8", "count": 1},
    {"queue": "construction", "type": "research_labs",     "note": "Labs3"},
    {"queue": "production",   "type": "goods",             "note": "Goods9", "count": 1},
    {"queue": "production",   "type": "goods",             "note": "Goods10", "count": 1},
    {"queue": "construction", "type": "shipyard",          "note": "SY8"},   # KEY: SY8 needed for OS
    {"queue": "production",   "type": "goods",             "note": "Goods11", "count": 1},
    {"queue": "production",   "type": "goods",             "note": "Goods12", "count": 1},
    {"queue": "research",     "type": "energy",            "note": "Energy6"},
    {"queue": "production",   "type": "goods",             "note": "Goods13", "count": 1},

    # ── Phase 5: Late labs + research push ───────────────────────────────
    {"queue": "construction", "type": "urban_structures",  "note": "US6"},
    {"queue": "construction", "type": "gas_plants",        "note": "GP4"},
    {"queue": "construction", "type": "research_labs",     "note": "Labs4"},
    {"queue": "construction", "type": "research_labs",     "note": "Labs5"},
    {"queue": "production",   "type": "goods",             "note": "Goods14", "count": 1},
    {"queue": "research",     "type": "laser",             "note": "Laser2"},
    {"queue": "research",     "type": "armour",            "note": "Armour2"},
    {"queue": "production",   "type": "goods",             "note": "Goods15", "count": 1},
    {"queue": "research",     "type": "stellar_drive",     "note": "SD1"},
    {"queue": "production",   "type": "goods",             "note": "Goods16", "count": 1},
    {"queue": "research",     "type": "energy",            "note": "Energy7"},
    {"queue": "production",   "type": "small_ship_5",         "note": "Small Ship 5 (tutorial)", "count": 1},
    {"queue": "research",     "type": "energy",            "note": "Energy8"},
    {"queue": "production",   "type": "goods",             "note": "Goods17", "count": 1},
    {"queue": "production",   "type": "goods",             "note": "Goods18", "count": 1},
    {"queue": "construction", "type": "research_labs",     "note": "Labs6"},
    {"queue": "research",     "type": "stellar_drive",     "note": "SD2"},
    {"queue": "production",   "type": "goods",             "note": "Goods19", "count": 1},
    {"queue": "construction", "type": "research_labs",     "note": "Labs7"},
    {"queue": "production",   "type": "goods",             "note": "Goods20", "count": 1},
    {"queue": "research",     "type": "stellar_drive",     "note": "SD3"},
    {"queue": "production",   "type": "goods",             "note": "Goods21", "count": 1},
    {"queue": "construction", "type": "research_labs",     "note": "Labs8"},
    {"queue": "production",   "type": "goods",             "note": "Goods22", "count": 1},
    {"queue": "production",   "type": "goods",             "note": "Goods23", "count": 1},
    {"queue": "research",     "type": "stellar_drive",     "note": "SD4"},
    {"queue": "production",   "type": "goods",             "note": "Goods24", "count": 1},
    {"queue": "research",     "type": "warp_drive",        "note": "Warp Drive 1 (KEY prereq)"},

    # ── GOAL: Medium Ship 3 ────────────────────────────────────────────────
    {"queue": "production",   "type": "medium_ship_3",     "note": "*** OUTPOST SHIP ***", "count": 1},
]

# Milestones to log for comparison with awe_simulator.py predictions
MILESTONE_EVENTS = {
    "construction": {
        "metal_refineries": {2: "MR2_done", 5: "MR5_done", 6: "MR6_done"},
        "spaceports":       {1: "SPO1_done", 5: "SPO5_done"},
        "research_labs":    {1: "Labs1_done", 2: "Labs2_done", 5: "Labs5_done", 8: "Labs8_done"},
        "robotic_factories":{1: "RF1_done", 4: "RF4_done"},
        "shipyard":         {1: "SY1_done", 4: "SY4_done", 8: "SY8_done"},
    },
    "research": {
        "computer":       {1: "Computer1_done", 2: "Computer2_done"},
        "energy":         {2: "Energy2_done", 4: "Energy4_done", 6: "Energy6_done", 8: "Energy8_done"},
        "laser":          {1: "Laser1_done", 2: "Laser2_done"},
        "armour":         {2: "Armour2_done"},
        "stellar_drive":  {1: "SD1_done", 4: "SD4_done"},
        "warp_drive":     {1: "WarpDrive1_done"},
    },
    "production": {
        "small_ship_1":       {1: "Small_Ship_1_built"},
        "small_ship_5":      {1: "Corvette_built"},
        "medium_ship_3":  {1: "OutpostShip_built"},
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (using Session for connection pooling — ~10x faster)
# ─────────────────────────────────────────────────────────────────────────────

_session = requests.Session()

class APIError(Exception):
    def __init__(self, msg, status_code=0):
        super().__init__(msg)
        self.status_code = status_code


def _post(url, endpoint, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = _session.post(f"{url}{endpoint}", json=body if body is not None else {}, headers=headers, timeout=10)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise APIError(f"POST {endpoint} -> {r.status_code}: {detail}", r.status_code)
    return r.json()


def _get(url, endpoint, token=None, params=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = _session.get(f"{url}{endpoint}", headers=headers, params=params or {}, timeout=10)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise APIError(f"GET {endpoint} -> {r.status_code}: {detail}", r.status_code)
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc():
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_complete(finish_at_str: Optional[str]) -> bool:
    """Return True if finish_at is in the past (i.e., the item is done)."""
    t = _parse_iso(finish_at_str)
    if t is None:
        return True
    return _now_utc() >= t


def _seconds_remaining(finish_at_str: Optional[str]) -> float:
    t = _parse_iso(finish_at_str)
    if t is None:
        return 0.0
    delta = (t - _now_utc()).total_seconds()
    return max(0.0, delta)


def _elapsed_str(start_ts: float) -> str:
    s = time.time() - start_ts
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# Bot state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BotState:
    name: str
    token: str = ""
    base_id: int = 0
    planet_name: str = ""

    # Plan indices — next item to attempt in each queue
    plan_index_construction: int = 0
    plan_index_research: int = 0
    plan_index_production: int = 0

    # Track milestones already logged
    milestones: dict = field(default_factory=dict)

    # Trade state
    trade_routes_created: int = 0
    pending_trade_after_spo1: bool = False
    pending_trade_after_spo5: bool = False

    # Whether this bot has finished (Medium Ship 3 built or queued)
    finished: bool = False
    finish_real_time: float = 0.0

    # Misc
    error_count: int = 0
    last_action: str = ""

    # Consecutive no-progress ticks (for diagnostics)
    stall_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# State accessors
# ─────────────────────────────────────────────────────────────────────────────

def _get_base_state(base_url: str, token: str):
    """Fetch /api/bases and return the first base's full data dict."""
    bases = _get(base_url, "/api/bases", token=token)
    if not bases:
        raise APIError("No bases found")
    return bases[0]


def _get_research_state(base_url: str, token: str, base_id: int) -> dict:
    """Return dict of {tech_type: research_item} from GET /api/research."""
    data = _get(base_url, "/api/research", token=token, params={"base_id": base_id})
    return {item["tech_type"]: item for item in data}


def _get_research_queue(base_url: str, token: str, base_id: int) -> list:
    """Return list of research queue items for this base from GET /api/research-queue."""
    try:
        return _get(base_url, "/api/research-queue", token=token, params={"base_id": base_id})
    except APIError:
        return []


def _get_ship_queue(base_url: str, token: str) -> list:
    """Return list of ship queue items from GET /api/ship-queue."""
    try:
        return _get(base_url, "/api/ship-queue", token=token)
    except APIError:
        return []


def _effective_building_level(base_data: dict, btype: str) -> int:
    """Return effective_level (current + queued) for a building type."""
    for b in base_data.get("buildings", []):
        if b["type"] == btype:
            return b.get("effective_level", b.get("level", 0))
    return 0


def _actual_building_level(base_data: dict, btype: str) -> int:
    """Return actual built level (not counting queued upgrades)."""
    for b in base_data.get("buildings", []):
        if b["type"] == btype:
            return b.get("level", 0)
    return 0


def _construction_queue_size(base_data: dict) -> int:
    return len(base_data.get("construction_queue", []))


def _construction_queue_has_type(base_data: dict, btype: str) -> int:
    """Count how many times btype appears in the construction queue."""
    return sum(1 for q in base_data.get("construction_queue", []) if q.get("type") == btype)


def _building_can_build(base_data: dict, btype: str) -> tuple:
    """Return (can_build: bool, reason: str) for a building type."""
    for b in base_data.get("buildings", []):
        if b["type"] == btype:
            return b.get("can_build", True), b.get("cannot_reason", "")
    return True, ""  # building not in list = might still be buildable, let server decide


# ─────────────────────────────────────────────────────────────────────────────
# Action helpers
# ─────────────────────────────────────────────────────────────────────────────

def _attempt_construction(base_url: str, bot: BotState, base_data: dict, plan_item: dict, log) -> bool:
    """
    Try to queue a construction item. Returns True if successfully queued OR if
    the item should be skipped (tech blocked, resource blocked — advance past it).
    Returns False if we should wait (queue full, insufficient credits).
    """
    btype = plan_item["type"]
    queue_size = _construction_queue_size(base_data)

    # Queue full — wait
    if queue_size >= CONSTRUCTION_QUEUE_MAX:
        return False

    # Check can_build flag
    can_build, reason = _building_can_build(base_data, btype)
    if not can_build:
        # Tech prereq not met yet — skip this item (advance plan, try next tick)
        if "requires" in reason.lower() or "tech" in reason.lower() or "disabled" in reason.lower():
            log(f"  [SKIP-C] {plan_item['note']}: {reason}")
            return True   # advance plan index
        # Planet lacks resource — skip permanently
        if "planet" in reason.lower() or "lacks" in reason.lower() or "resource" in reason.lower():
            log(f"  [SKIP-C] {plan_item['note']}: {reason} (planet incompatible — skipping)")
            return True
        log(f"  [WAIT-C] {plan_item['note']}: {reason}")
        return False

    try:
        _post(base_url, "/api/bases/upgrade",
              {"base_id": bot.base_id, "building_type": btype},
              bot.token)
        eff = _effective_building_level(base_data, btype)
        log(f"  [BUILD] Queued {plan_item['note']} (-> Lv{eff + 1})")
        return True
    except APIError as e:
        err = str(e).lower()
        if "queue full" in err:
            return False
        if "credits" in err or "need " in err:
            log(f"  [WAIT-C] {plan_item['note']}: {e}")
            return False
        if "requires" in err or "tech" in err or "level" in err:
            log(f"  [SKIP-C] {plan_item['note']}: tech prereq — {e}")
            return True   # advance (server says prereq not met)
        if "energy" in err or "population" in err or "area" in err:
            log(f"  [SKIP-C] {plan_item['note']}: resource prereq — {e}")
            return True   # advance (queue more energy/pop/area first)
        if "disabled" in err:
            log(f"  [SKIP-C] {plan_item['note']}: disabled — skipping")
            return True
        if "planet" in err or "lacks" in err:
            log(f"  [SKIP-C] {plan_item['note']}: planet incompatible — {e}")
            return True
        if "max level" in err or "maxed" in err:
            log(f"  [SKIP-C] {plan_item['note']}: already at max level")
            return True
        log(f"  [ERR-C] {plan_item['note']}: {e}")
        return False


def _attempt_research(base_url: str, bot: BotState, base_id: int, plan_item: dict,
                      research_state: dict, research_queue: list, log) -> bool:
    """
    Try to queue a research item.
    Returns True if queued successfully OR if blocked by a permanent condition (skip).
    Returns False if we should wait (credits, prereqs not met yet, queue full).
    """
    ttype = plan_item["type"]
    rdata = research_state.get(ttype, {})

    # No labs = can't research anything — wait
    if not rdata:
        log(f"  [WAIT-R] {plan_item['note']}: tech type not found in research list (no labs?)")
        return False

    # Lab requirement check
    if not rdata.get("lab_met", True):
        req = rdata.get("lab_req", 1)
        log(f"  [WAIT-R] {plan_item['note']}: need Lab Lv{req}")
        return False

    # Prereq check
    if not rdata.get("prereqs_met", True):
        log(f"  [WAIT-R] {plan_item['note']}: prerequisites not met yet")
        return False

    # Research queue full at this base
    if len(research_queue) >= RESEARCH_QUEUE_MAX:
        return False

    try:
        _post(base_url, "/api/research",
              {"tech_type": ttype, "base_id": base_id},
              bot.token)
        eff = rdata.get("effective_level", 0)
        log(f"  [RESEARCH] Queued {plan_item['note']} (-> Lv{eff + 1})")
        return True
    except APIError as e:
        err = str(e).lower()
        if "queue full" in err:
            return False
        if "credits" in err or "need " in err:
            log(f"  [WAIT-R] {plan_item['note']}: insufficient credits")
            return False
        if "prereq" in err or "requires" in err:
            log(f"  [WAIT-R] {plan_item['note']}: prereq blocked — {e}")
            return False
        if "lab" in err:
            log(f"  [WAIT-R] {plan_item['note']}: lab level — {e}")
            return False
        if "disabled" in err:
            log(f"  [SKIP-R] {plan_item['note']}: disabled — skipping")
            return True
        if "initialized" in err:
            log(f"  [WAIT-R] {plan_item['note']}: research not initialized yet")
            return False
        log(f"  [ERR-R] {plan_item['note']}: {e}")
        return False


def _attempt_production(base_url: str, bot: BotState, base_data: dict,
                        ship_queue: list, plan_item: dict, log) -> bool:
    """
    Try to queue a production item (goods or ship).
    Returns True if queued. Returns False if we should wait.
    """
    stype = plan_item["type"]
    count = plan_item.get("count", 1)

    # Production queue full — wait
    if len(ship_queue) >= PRODUCTION_QUEUE_MAX:
        return False

    sy_level = base_data.get("shipyard_level", 0)

    # Pre-check shipyard level to avoid pointless API calls
    sy_required = {
        "goods":         1,
        "small_ship_1":      1,
        "small_ship_5":     4,
        "medium_ship_3": 8,
    }.get(stype, 1)

    if sy_level < sy_required:
        log(f"  [WAIT-P] {plan_item['note']}: need SY{sy_required}, have SY{sy_level}")
        return False

    try:
        _post(base_url, "/api/fleets/build",
              {"base_id": bot.base_id, "ship_type": stype, "count": count},
              bot.token)
        log(f"  [PROD] Queued {plan_item['note']}")
        return True
    except APIError as e:
        err = str(e).lower()
        if "credits" in err or "need " in err:
            log(f"  [WAIT-P] {plan_item['note']}: insufficient credits")
            return False
        if "shipyard" in err or "need shipyard" in err:
            log(f"  [WAIT-P] {plan_item['note']}: shipyard level — {e}")
            return False
        if "requires" in err or "tech" in err:
            log(f"  [WAIT-P] {plan_item['note']}: tech prereq — {e}")
            return False
        if "limit" in err or "fleet limit" in err:
            log(f"  [SKIP-P] {plan_item['note']}: fleet limit — {e}")
            return True   # advance (fleet full; can try again later)
        if "queue full" in err or "production queue" in err:
            return False
        if "disabled" in err:
            log(f"  [SKIP-P] {plan_item['note']}: disabled — skipping")
            return True
        log(f"  [ERR-P] {plan_item['note']}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Trade helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_and_accept_incoming_trades(base_url: str, bot: BotState, log):
    """Accept any pending incoming trade route requests."""
    try:
        data = _get(base_url, "/api/trade-routes", token=bot.token)
        for r in data.get("routes", []):
            if r.get("is_incoming") and r.get("is_pending"):
                route_id = r["id"]
                try:
                    _post(base_url, f"/api/trade-routes/{route_id}/accept", {}, bot.token)
                    log(f"  [TRADE] Accepted incoming trade route #{route_id}")
                    bot.trade_routes_created += 1
                except APIError as e:
                    err = str(e).lower()
                    if "credits" in err:
                        log(f"  [WAIT-T] Insufficient credits to accept trade #{route_id}")
                    elif "already" in err:
                        pass  # already accepted, ignore
                    else:
                        log(f"  [ERR-T] Accept trade #{route_id}: {e}")
    except APIError:
        pass


def _create_trade_route(base_url: str, bot: BotState, partner_base_id: int, log) -> bool:
    """Create a trade route from our base to partner's base. Returns True on success/skip."""
    try:
        result = _post(base_url, "/api/trade-routes",
                       {"base_a_id": bot.base_id, "base_b_id": partner_base_id},
                       bot.token)
        income = result.get("income", 0)
        dist = result.get("distance", 0)
        pending = result.get("is_pending", True)
        log(f"  [TRADE] Created route to base#{partner_base_id} dist={dist:.1f} income={income:.1f} pending={pending}")
        bot.trade_routes_created += 1
        return True
    except APIError as e:
        err = str(e).lower()
        if "already exists" in err:
            return True   # already done
        if "credits" in err:
            log(f"  [WAIT-T] Insufficient credits to create trade route")
            return False
        if "spaceport" in err or "max" in err:
            log(f"  [SKIP-T] Trade blocked (slots full?): {e}")
            return True
        if "pirated" in err or "pillage" in err:
            log(f"  [SKIP-T] Pillage cooldown: {e}")
            return True
        log(f"  [ERR-T] Create trade route: {e}")
        return False


def _try_open_trades_with_partners(base_url: str, bot: BotState, all_bots: list,
                                   target_count: int, log):
    """Create trade routes with other bots until we have target_count routes."""
    for partner in all_bots:
        if partner.name == bot.name:
            continue
        if partner.base_id == 0:
            continue
        if bot.trade_routes_created >= target_count:
            break
        _create_trade_route(base_url, bot, partner.base_id, log)


# ─────────────────────────────────────────────────────────────────────────────
# Milestone tracking
# ─────────────────────────────────────────────────────────────────────────────

def _check_milestone(bot: BotState, queue: str, item_type: str, level: int,
                     start_ts: float, log):
    """Log a milestone if not already logged."""
    event = MILESTONE_EVENTS.get(queue, {}).get(item_type, {}).get(level)
    if event and event not in bot.milestones:
        elapsed = time.time() - start_ts
        bot.milestones[event] = elapsed
        log(f"  *** MILESTONE: {event} at T+{_elapsed_str(start_ts)} ({elapsed:.0f}s) ***")
        if event == "OutpostShip_built":
            bot.finished = True
            bot.finish_real_time = time.time()


def _scan_milestones(bot: BotState, base_data: dict, research_state: dict, start_ts: float, log):
    """Scan current state and trigger any newly-reached milestones."""
    # Building milestones (based on actual built level, not effective)
    for btype, level_map in MILESTONE_EVENTS.get("construction", {}).items():
        actual_lv = _actual_building_level(base_data, btype)
        for lvl in sorted(level_map.keys()):
            if actual_lv >= lvl:
                _check_milestone(bot, "construction", btype, lvl, start_ts, log)

    # Research milestones
    for ttype, level_map in MILESTONE_EVENTS.get("research", {}).items():
        actual_lv = research_state.get(ttype, {}).get("level", 0)
        for lvl in sorted(level_map.keys()):
            if actual_lv >= lvl:
                _check_milestone(bot, "research", ttype, lvl, start_ts, log)


# ─────────────────────────────────────────────────────────────────────────────
# Main bot tick
# ─────────────────────────────────────────────────────────────────────────────

def _tick_bot(base_url: str, bot: BotState, all_bots: list, start_ts: float, log):
    """One polling tick for a single bot. Returns True if bot has finished."""
    if bot.finished:
        return True

    # ── Fetch current state ──────────────────────────────────────────────
    try:
        base_data = _get_base_state(base_url, bot.token)
        bot.base_id = base_data["id"]
    except APIError as e:
        log(f"  [ERR] Failed to fetch base state: {e}")
        bot.error_count += 1
        return False

    try:
        research_state = _get_research_state(base_url, bot.token, bot.base_id)
    except APIError as e:
        log(f"  [ERR] Failed to fetch research state: {e}")
        research_state = {}

    # Research queue: use dedicated endpoint for accurate count
    try:
        research_queue = _get_research_queue(base_url, bot.token, bot.base_id)
    except APIError:
        research_queue = []

    # Ship queue from base_data (already populated by /api/bases)
    ship_queue = base_data.get("ship_queue", [])

    construction_queue = base_data.get("construction_queue", [])

    # ── Accept incoming trade routes ──────────────────────────────────────
    _check_and_accept_incoming_trades(base_url, bot, log)

    # ── Set trade flags when spaceport levels reached ─────────────────────
    spo_actual = _actual_building_level(base_data, "spaceports")
    if spo_actual >= 1 and not bot.pending_trade_after_spo1:
        bot.pending_trade_after_spo1 = True
        log(f"  [FLAG] SPO1 built — will open first trade route")
    if spo_actual >= 5 and not bot.pending_trade_after_spo5:
        bot.pending_trade_after_spo5 = True
        log(f"  [FLAG] SPO5 built — will open second trade route")

    # ── Try to open trade routes ──────────────────────────────────────────
    if bot.pending_trade_after_spo1 and bot.trade_routes_created < 1:
        _try_open_trades_with_partners(base_url, bot, all_bots, 1, log)
    if bot.pending_trade_after_spo5 and bot.trade_routes_created < 2:
        _try_open_trades_with_partners(base_url, bot, all_bots, 2, log)

    # ── Scan for milestones ───────────────────────────────────────────────
    _scan_milestones(bot, base_data, research_state, start_ts, log)
    if bot.finished:
        return True

    # ── Track what changed this tick ─────────────────────────────────────
    did_something = False

    # ── Queue next construction items ─────────────────────────────────────
    constr_plan = [p for p in BUILD_PLAN if p["queue"] == "construction"]

    # Fill available construction slots greedily
    max_attempts = len(constr_plan)  # prevent infinite loop
    attempt_count = 0
    while attempt_count < max_attempts:
        attempt_count += 1

        if bot.plan_index_construction >= len(constr_plan):
            break

        queue_size = _construction_queue_size(base_data)
        if queue_size >= CONSTRUCTION_QUEUE_MAX:
            break

        plan_item = constr_plan[bot.plan_index_construction]
        btype = plan_item["type"]

        # How many times does this btype appear in the plan up to (and including)
        # the current index? That's how many levels we need to have queued/built.
        target_count = sum(
            1 for p in constr_plan[:bot.plan_index_construction + 1]
            if p["type"] == btype
        )

        # effective_level already includes queued upgrades
        eff_lv = _effective_building_level(base_data, btype)

        if eff_lv >= target_count:
            # Already queued or built — advance
            note = plan_item.get("note", btype)
            log(f"  [SKIP-C] {note} already done (eff={eff_lv} >= target={target_count})")
            # Handle trade_after flag when skipping
            if plan_item.get("trade_after"):
                if target_count == 1:
                    bot.pending_trade_after_spo1 = True
                else:
                    bot.pending_trade_after_spo5 = True
            bot.plan_index_construction += 1
            continue

        # Try to queue it
        success = _attempt_construction(base_url, bot, base_data, plan_item, log)
        if success:
            did_something = True
            bot.plan_index_construction += 1
            if plan_item.get("trade_after"):
                # Will be triggered by spaceport level check above on next tick
                pass
            # Re-fetch base_data to get updated queue size + effective levels
            try:
                base_data = _get_base_state(base_url, bot.token)
                construction_queue = base_data.get("construction_queue", [])
            except APIError:
                break
        else:
            # Can't queue right now (credits/queue full) — stop trying construction
            break

    # ── Queue next research items ──────────────────────────────────────────
    research_plan = [p for p in BUILD_PLAN if p["queue"] == "research"]

    # Only try research if we have labs
    labs_lv = _actual_building_level(base_data, "research_labs")
    if labs_lv >= 1:
        # Re-fetch research queue to get accurate count after any changes
        try:
            research_queue = _get_research_queue(base_url, bot.token, bot.base_id)
        except APIError:
            pass

        max_attempts = len(research_plan)
        attempt_count = 0
        while attempt_count < max_attempts:
            attempt_count += 1

            if bot.plan_index_research >= len(research_plan):
                break

            if len(research_queue) >= RESEARCH_QUEUE_MAX:
                break

            plan_item = research_plan[bot.plan_index_research]
            ttype = plan_item["type"]

            # How many times this tech appears in plan up to current index
            target_count = sum(
                1 for p in research_plan[:bot.plan_index_research + 1]
                if p["type"] == ttype
            )

            rdata = research_state.get(ttype, {})
            effective_lv = rdata.get("effective_level", 0)

            if effective_lv >= target_count:
                note = plan_item.get("note", ttype)
                log(f"  [SKIP-R] {note} already done (eff={effective_lv} >= target={target_count})")
                bot.plan_index_research += 1
                continue

            success = _attempt_research(base_url, bot, bot.base_id, plan_item,
                                        research_state, research_queue, log)
            if success:
                did_something = True
                bot.plan_index_research += 1
                # Refresh research state + queue
                try:
                    research_state = _get_research_state(base_url, bot.token, bot.base_id)
                    research_queue = _get_research_queue(base_url, bot.token, bot.base_id)
                except APIError:
                    break
            else:
                # Can't research right now — stop trying research
                break

    # ── Queue next production items ────────────────────────────────────────
    prod_plan = [p for p in BUILD_PLAN if p["queue"] == "production"]
    sy_level = base_data.get("shipyard_level", 0)

    # Opportunistic goods: keep production queue fed with goods for credit
    # farming. Goods don't need a shipyard — they use base industrial rate.
    # This prevents deadlocks where construction needs credits but goods
    # are gated behind later plan items. Queue up to 3 goods at a time.
    try:
        ship_queue = _get_ship_queue(base_url, bot.token)
        ship_queue = [q for q in ship_queue if q.get("base_id") == bot.base_id]
    except APIError:
        ship_queue = []

    # Get player credits from /api/player/stats
    try:
        player_stats = _get(base_url, "/api/player/stats", token=bot.token)
        credits = player_stats.get("credits", 0)
    except APIError:
        credits = 0

    # Count goods already in queue
    goods_in_queue = sum(1 for q in ship_queue if q.get("ship_type") == "goods")
    AUTO_GOODS_MAX = 3  # Keep up to 3 goods queued for continuous credit farming

    # Check if the research queue has items waiting to activate (need credits)
    # If so, reserve credits for research instead of spending on goods
    research_needs_credits = False
    try:
        rq = _get_research_queue(base_url, bot.token, bot.base_id)
        for rqi in rq:
            if rqi.get("position") == 0 and not rqi.get("finish_at") and not rqi.get("started_at"):
                research_needs_credits = True
                break
    except APIError:
        pass

    if goods_in_queue < AUTO_GOODS_MAX and credits >= 20 and len(ship_queue) < PRODUCTION_QUEUE_MAX and not research_needs_credits:
        # Check if construction or research is waiting on credits
        constr_plan_items = [p for p in BUILD_PLAN if p["queue"] == "construction"]
        waiting_for_credits = False
        if bot.plan_index_construction < len(constr_plan_items):
            waiting_for_credits = True  # there's more to build
        if bot.plan_index_research < len([p for p in BUILD_PLAN if p["queue"] == "research"]):
            waiting_for_credits = True

        # Don't produce goods if OS is ready to build
        wd_lv = research_state.get("warp_drive", {}).get("level", 0)
        os_ready = wd_lv >= 1 and sy_level >= 8

        if waiting_for_credits and not os_ready:
            # Queue goods (up to AUTO_GOODS_MAX slots)
            to_queue = min(AUTO_GOODS_MAX - goods_in_queue,
                          PRODUCTION_QUEUE_MAX - len(ship_queue),
                          int(credits // 20))  # can afford this many
            for _ in range(to_queue):
                try:
                    _post(base_url, "/api/fleets/build",
                          {"base_id": bot.base_id, "ship_type": "goods", "count": 1},
                          token=bot.token)
                    log(f"  [GOODS-AUTO] Queued goods (credits={credits:.0f}, q={goods_in_queue+1})")
                    did_something = True
                    goods_in_queue += 1
                    credits -= 20
                except APIError as e:
                    break  # stop if can't produce (credits, queue full, etc.)

    if sy_level >= 1:
        # Refresh ship queue
        try:
            ship_queue = _get_ship_queue(base_url, bot.token)
            # Filter to our base
            ship_queue = [q for q in ship_queue if q.get("base_id") == bot.base_id]
        except APIError:
            ship_queue = base_data.get("ship_queue", [])

        max_attempts = len(prod_plan)
        attempt_count = 0
        while attempt_count < max_attempts:
            attempt_count += 1

            if bot.plan_index_production >= len(prod_plan):
                break

            if len(ship_queue) >= PRODUCTION_QUEUE_MAX:
                break

            plan_item = prod_plan[bot.plan_index_production]
            stype = plan_item["type"]

            # Preempt goods if Warp Drive 1 + SY8 are ready — jump to Medium Ship 3
            if stype == "goods":
                wd_lv = research_state.get("warp_drive", {}).get("level", 0)
                if wd_lv >= 1 and sy_level >= 8:
                    log(f"  [PREEMPT] WD1+SY8 ready — skipping goods, jumping to Medium Ship 3")
                    while bot.plan_index_production < len(prod_plan):
                        if prod_plan[bot.plan_index_production]["type"] == "medium_ship_3":
                            break
                        bot.plan_index_production += 1
                    if bot.plan_index_production >= len(prod_plan):
                        break
                    plan_item = prod_plan[bot.plan_index_production]
                    stype = plan_item["type"]

            # Extra prereq check for Medium Ship 3
            if stype == "medium_ship_3":
                wd_lv = research_state.get("warp_drive", {}).get("level", 0)
                if wd_lv < 1:
                    log(f"  [WAIT-P] medium_ship_3: waiting for Warp Drive 1")
                    break
                if sy_level < 8:
                    log(f"  [WAIT-P] medium_ship_3: need SY8, have SY{sy_level}")
                    break

            success = _attempt_production(base_url, bot, base_data, ship_queue, plan_item, log)
            if success:
                did_something = True
                bot.plan_index_production += 1
                # Milestone tracking
                if stype == "medium_ship_3":
                    _check_milestone(bot, "production", "medium_ship_3", 1, start_ts, log)
                    bot.last_action = "*** OUTPOST SHIP QUEUED ***"
                elif stype == "small_ship_1":
                    _check_milestone(bot, "production", "small_ship_1", 1, start_ts, log)
                elif stype == "small_ship_5":
                    _check_milestone(bot, "production", "small_ship_5", 1, start_ts, log)

                # Refresh ship queue
                try:
                    ship_queue = _get_ship_queue(base_url, bot.token)
                    ship_queue = [q for q in ship_queue if q.get("base_id") == bot.base_id]
                    base_data = _get_base_state(base_url, bot.token)
                    sy_level = base_data.get("shipyard_level", 0)
                except APIError:
                    break
            else:
                break

    # ── Stall tracking ────────────────────────────────────────────────────
    if did_something:
        bot.stall_count = 0
    else:
        bot.stall_count += 1
        if bot.stall_count > 0 and bot.stall_count % 30 == 0:
            # Log diagnostics every 30 ticks
            try:
                ps = _get(base_url, "/api/player/stats", token=bot.token)
                cr = ps.get("credits", "?")
                econ = ps.get("economy", "?")
            except APIError:
                cr, econ = "?", "?"
            log(f"  [STALL] No progress for {bot.stall_count} ticks. "
                f"constr_idx={bot.plan_index_construction}/{len(constr_plan)}, "
                f"research_idx={bot.plan_index_research}/{len(research_plan)}, "
                f"prod_idx={bot.plan_index_production}/{len(prod_plan)}, "
                f"cq={_construction_queue_size(base_data)}/{CONSTRUCTION_QUEUE_MAX}, "
                f"rq={len(research_queue)}/{RESEARCH_QUEUE_MAX}, "
                f"sq={len(ship_queue)}/{PRODUCTION_QUEUE_MAX}, "
                f"credits={cr}, econ={econ}/hr")

    return bot.finished


# ─────────────────────────────────────────────────────────────────────────────
# Setup helpers
# ─────────────────────────────────────────────────────────────────────────────

def _login(base_url: str, email: str, password: str, log) -> Optional[str]:
    """Login and return JWT token."""
    try:
        result = _post(base_url, "/api/login", {"email": email, "password": password})
        token = result.get("access_token")
        log(f"  [SETUP] Logged in (email={email})")
        return token
    except APIError as e:
        log(f"  [ERR] Login failed: {e}")
        return None


def _register_or_login(base_url: str, username: str, email: str, password: str, log) -> Optional[str]:
    """Register account or login if already exists. Returns JWT token."""
    # Try register first
    try:
        result = _post(base_url, "/api/register",
                       {"username": username, "email": email, "password": password})
        token = result.get("access_token")
        log(f"  [SETUP] Registered {username}")
        return token
    except APIError as e:
        err_str = str(e).lower()
        if "taken" in err_str or "registered" in err_str or "400" in str(e.status_code):
            pass  # Already registered, try login
        else:
            log(f"  [WARN] Register {username}: {e}")

    return _login(base_url, email, password, log)


def _ensure_homeworld(base_url: str, token: str, galaxy_id: int, log) -> bool:
    """Ensure the player has a homeworld; select galaxy if they don't."""
    try:
        bases = _get(base_url, "/api/bases", token=token)
        if bases:
            log(f"  [SETUP] Homeworld: {bases[0].get('planet_name', '?')} (id={bases[0]['id']})")
            return True
    except APIError:
        pass

    try:
        _post(base_url, "/api/select-galaxy", {"galaxy_id": galaxy_id}, token)
        log(f"  [SETUP] Selected galaxy {galaxy_id}, homeworld assigned")
        return True
    except APIError as e:
        if "already" in str(e).lower():
            return True
        log(f"  [ERR] select-galaxy: {e}")
        return False


def _skip_tutorial(base_url: str, token: str, log):
    """Skip tutorial — idempotent."""
    try:
        _post(base_url, "/api/tutorial/skip", {}, token)
        log(f"  [SETUP] Tutorial skipped")
    except APIError as e:
        # "No tutorial in progress" is fine
        log(f"  [SETUP] Skip tutorial: {e} (may already be done)")


def _get_available_galaxies(base_url: str, token: str) -> list:
    """Return list of galaxy dicts. Uses /api/galaxies/list endpoint."""
    try:
        data = _get(base_url, "/api/galaxies/list", token=token)
        return data.get("galaxies", [])
    except APIError:
        # Fallback: try /api/galaxies (old endpoint)
        try:
            data = _get(base_url, "/api/galaxies", token=token)
            if isinstance(data, list):
                return data
            return data.get("galaxies", [])
        except APIError:
            return []


def _get_planet_coords(base_url: str, token: str) -> dict:
    """Return {base_id, planet_name, galaxy_id, region_id, system_id} for home base."""
    try:
        coords_list = _get(base_url, "/api/my-bases-coords", token=token)
        if coords_list:
            return coords_list[0]
    except APIError:
        pass
    return {}


def _calc_rough_distance(a: dict, b: dict) -> float:
    """Rough distance between two coord dicts (same system=1, same region=5, else 20)."""
    if not a or not b:
        return 999.0
    if a.get("system_id") == b.get("system_id"):
        return 1.0
    if a.get("region_id") == b.get("region_id"):
        return 5.0
    return 20.0


# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────

_log_entries = []


def _make_logger(bot_name: str, start_ts: float):
    def log(msg: str):
        elapsed = _elapsed_str(start_ts)
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}|T+{elapsed}] [{bot_name}] {msg}"
        print(line, flush=True)
        _log_entries.append({"time": ts, "elapsed": elapsed, "bot": bot_name, "msg": msg})
    return log


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AstroClone OS-Rush Bot Test")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"Server base URL (default: {DEFAULT_URL})")
    parser.add_argument("--speed", type=float, default=None,
                        help="Expected game speed (for display/comparison only)")
    parser.add_argument("--max-hours", type=float, default=48.0,
                        help="Stop after this many real hours (default: 48)")
    parser.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SECONDS,
                        help=f"Polling interval in seconds (default: {POLL_INTERVAL_SECONDS})")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    poll_interval = args.poll_interval
    max_real_seconds = args.max_hours * 3600
    start_ts = time.time()

    global_log = _make_logger("MAIN", start_ts)
    global_log(f"AstroClone OS-Rush Bot Test")
    global_log(f"Server: {base_url}")
    global_log(f"Poll interval: {poll_interval}s")
    if args.speed:
        global_log(f"Expected game speed: {args.speed}x")
    global_log(f"Max runtime: {args.max_hours:.0f} real hours")
    global_log("")

    # ── Step 1: Verify server is up ──────────────────────────────────────
    global_log("Checking server health...")
    try:
        r = requests.get(f"{base_url}/", timeout=5)
        global_log(f"Server responded: HTTP {r.status_code}")
    except Exception as e:
        global_log(f"ERROR: Cannot reach server at {base_url}: {e}")
        sys.exit(1)

    # ── Step 2: Login admin ───────────────────────────────────────────────
    global_log("\n--- Logging in admin ---")
    admin_log = _make_logger("ADMIN", start_ts)
    admin_token = _register_or_login(base_url, ADMIN["username"],
                                     ADMIN["email"], ADMIN["password"], admin_log)
    if not admin_token:
        global_log("FATAL: Cannot login admin account. Is admin@test.com / admin123 correct?")
        sys.exit(1)

    # ── Step 3: Get available galaxies ────────────────────────────────────
    global_log("\n--- Getting galaxy list ---")
    galaxies = _get_available_galaxies(base_url, admin_token)
    if not galaxies:
        global_log("No galaxies found. Universe may not be generated yet.")
        global_log("Login to admin panel and generate the universe first.")
        sys.exit(1)

    galaxy_id = galaxies[0]["id"]
    global_log(f"Using galaxy ID {galaxy_id}: {galaxies[0].get('name', 'Unknown')}")

    # ── Step 4: Login bot accounts ────────────────────────────────────────
    global_log("\n--- Logging in bot accounts ---")
    bot_states: list[BotState] = []

    for bot_cfg in BOTS:
        name = bot_cfg["username"]
        bot_log = _make_logger(name, start_ts)

        token = _register_or_login(base_url, name, bot_cfg["email"],
                                   bot_cfg["password"], bot_log)
        if not token:
            global_log(f"FATAL: Cannot login {name}. Create the bot account first via admin panel.")
            sys.exit(1)

        # Ensure homeworld (for freshly created bots that need galaxy selection)
        if not _ensure_homeworld(base_url, token, galaxy_id, bot_log):
            global_log(f"FATAL: Cannot assign homeworld for {name}")
            sys.exit(1)

        # Skip tutorial
        _skip_tutorial(base_url, token, bot_log)

        # Get base info
        try:
            bases = _get(base_url, "/api/bases", token=token)
            base_id = bases[0]["id"] if bases else 0
            planet_name = bases[0].get("planet_name", "?") if bases else "?"
        except Exception as e:
            bot_log(f"  [WARN] Could not fetch bases: {e}")
            base_id = 0
            planet_name = "?"

        bot = BotState(name=name, token=token, base_id=base_id, planet_name=planet_name)
        bot_states.append(bot)
        bot_log(f"  Homeworld: {planet_name} (base_id={base_id})")

    # ── Step 5: Log inter-bot distances ──────────────────────────────────
    global_log("\n--- Bot placement ---")
    coords_list = []
    for bot in bot_states:
        coords = _get_planet_coords(base_url, bot.token)
        coords_list.append(coords)
        global_log(f"  {bot.name}: {coords.get('planet_name', '?')} "
                   f"(sys={coords.get('system_id', '?')}, "
                   f"reg={coords.get('region_id', '?')})")

    global_log("\n--- Inter-bot distances (rough) ---")
    for i in range(len(bot_states)):
        for j in range(i + 1, len(bot_states)):
            dist = _calc_rough_distance(coords_list[i], coords_list[j])
            global_log(f"  {bot_states[i].name} <-> {bot_states[j].name}: ~{dist:.0f} astros")

    if args.speed:
        expected_wall = 18.083 / args.speed
        eh, er = divmod(int(expected_wall * 3600), 3600)
        em, es = divmod(er, 60)
        global_log(f"\nAt game_speed={args.speed}x, awe_simulator predicts OS at ~{eh:02d}:{em:02d}:{es:02d} wall time")

    # ── Step 6: Main polling loop ─────────────────────────────────────────
    global_log(f"\n--- Starting OS-Rush build loop (poll every {poll_interval}s) ---\n")

    bot_loggers = [_make_logger(b.name, start_ts) for b in bot_states]
    last_status_time = start_ts

    while True:
        now_real = time.time()
        elapsed_real = now_real - start_ts

        if elapsed_real > max_real_seconds:
            global_log(f"Max runtime of {args.max_hours:.0f}h reached. Stopping.")
            break

        all_finished = all(b.finished for b in bot_states)
        if all_finished:
            global_log(f"\n*** ALL BOTS FINISHED *** T+{_elapsed_str(start_ts)}")
            break

        # Periodic status line every 60s
        if now_real - last_status_time >= 60:
            last_status_time = now_real
            status_parts = []
            for b in bot_states:
                ci = b.plan_index_construction
                ri = b.plan_index_research
                pi = b.plan_index_production
                status_parts.append(f"{b.name}(C{ci}/R{ri}/P{pi})")
            global_log(f"[STATUS T+{_elapsed_str(start_ts)}] " + " | ".join(status_parts))

        # Tick each bot
        for i, bot in enumerate(bot_states):
            if bot.finished:
                continue
            log = bot_loggers[i]
            try:
                _tick_bot(base_url, bot, bot_states, start_ts, log)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"  [EXC] Unexpected error in tick: {type(e).__name__}: {e}")
                bot.error_count += 1
                if bot.error_count > 30:
                    log(f"  [FATAL] Too many errors — disabling bot")
                    bot.finished = True

        time.sleep(poll_interval)

    # ── Step 7: Final summary ─────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"OS-RUSH TEST RESULTS  (T+{_elapsed_str(start_ts)})")
    print(f"{'='*70}")

    for bot in bot_states:
        status = "FINISHED" if bot.finished else "DID NOT FINISH"
        print(f"\nBot: {bot.name} [{status}]")
        print(f"  Homeworld: {bot.planet_name}")
        if bot.finish_real_time > 0:
            fe = bot.finish_real_time - start_ts
            fh, fr = divmod(int(fe), 3600)
            fm, fs = divmod(fr, 60)
            print(f"  Medium Ship 3 queued at T+{fh:02d}:{fm:02d}:{fs:02d} ({fe:.0f}s real)")
        print(f"  Errors: {bot.error_count}")
        print(f"  Build indices: C={bot.plan_index_construction}, "
              f"R={bot.plan_index_research}, P={bot.plan_index_production}")
        if bot.milestones:
            print(f"  Milestones:")
            for event, elapsed_s in sorted(bot.milestones.items(), key=lambda x: x[1]):
                h, rem = divmod(int(elapsed_s), 3600)
                m, s = divmod(rem, 60)
                print(f"    {event:<30} T+{h:02d}:{m:02d}:{s:02d} ({elapsed_s:.0f}s)")

    # ── Step 8: Milestone comparison table ────────────────────────────────
    print(f"\n{'='*70}")
    print(f"MILESTONE COMPARISON (awe_simulator predictions at 1x speed)")
    print(f"{'='*70}")

    awe_predictions_minutes = {
        "MR2_done":          8,
        "MR5_done":         25,
        "SPO1_done":        65,
        "Labs1_done":       90,
        "MR6_done":        130,
        "SPO5_done":       155,
        "SY1_done":        240,
        "SY4_done":        320,
        "Labs5_done":      570,
        "SY8_done":        460,
        "WarpDrive1_done": 1020,
        "OutpostShip_built": 1085,
    }

    def _fmt_m(minutes):
        if minutes is None:
            return "n/a"
        h, m = divmod(int(minutes), 60)
        return f"{h}h{m:02d}m"

    header = f"{'Milestone':<30} {'awe_sim(1x)':>12}"
    for b in bot_states:
        header += f" {b.name[:10]:>12}"
    print(header)
    print("-" * (30 + 12 + 12 * len(bot_states) + 3 * len(bot_states)))

    for event, awe_mins in sorted(awe_predictions_minutes.items(), key=lambda x: x[1]):
        # Adjust for game speed if provided
        display_mins = awe_mins
        if args.speed and args.speed != 1.0:
            display_mins = awe_mins / args.speed

        row = f"{event:<30} {_fmt_m(display_mins):>12}"
        for b in bot_states:
            val = b.milestones.get(event)
            if val is not None:
                row += f" {_fmt_m(val / 60):>12}"
            else:
                row += f" {'pending':>12}"
        print(row)

    # ── Step 9: Save log ──────────────────────────────────────────────────
    report = {
        "run_time_real": _elapsed_str(start_ts),
        "server_url": base_url,
        "game_speed_arg": args.speed,
        "bots": [
            {
                "name": b.name,
                "planet": b.planet_name,
                "finished": b.finished,
                "errors": b.error_count,
                "milestones": {k: round(v, 1) for k, v in b.milestones.items()},
                "plan_index_construction": b.plan_index_construction,
                "plan_index_research": b.plan_index_research,
                "plan_index_production": b.plan_index_production,
                "trade_routes_created": b.trade_routes_created,
            }
            for b in bot_states
        ],
        "log_entries": _log_entries[-1000:],
    }
    with open(LOG_FILE, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nLog saved to {LOG_FILE}")
    print("Done.")


if __name__ == "__main__":
    main()
