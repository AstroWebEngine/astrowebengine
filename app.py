"""
AstroWebEngine — Entry Point
Run with: python app.py   (or: uvicorn app:app --host 0.0.0.0 --port 8000)
"""
__version__ = "0.97.0"
import asyncio
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# ── Detailed logging setup ──
LOG_DIR = Path(__file__).resolve().parent
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "server.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
awe_logger = logging.getLogger("awe")
awe_logger.setLevel(logging.DEBUG)

from database import engine, ModelBase, SessionLocal
from engine_identity import ENGINE_NAME, engine_identity
import mod_hooks
from auth import init_default_configs, get_config_int, get_config_float
from universe import _auto_migrate_sqlite, ensure_wormholes
from config_defaults import *
from models import ShipQueue, Colony, User, Fleet

# ── App setup ──
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="AstroWebEngine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── Request logging middleware ──
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/static"):
            response = await call_next(request)
            response.headers["X-Powered-By"] = ENGINE_NAME
            if request.url.path.endswith((".js", ".css")):
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response
        start = time.time()
        response = await call_next(request)
        response.headers["X-Powered-By"] = ENGINE_NAME
        elapsed = (time.time() - start) * 1000
        status = response.status_code
        log_level = logging.WARNING if status >= 400 else logging.INFO
        awe_logger.log(log_level, f"{request.method} {request.url.path} -> {status} ({elapsed:.0f}ms) [{request.client.host if request.client else '?'}]")
        return response

app.add_middleware(RequestLogMiddleware)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Register all routes ──
from routes_auth import register_auth_routes
from routes_map import register_map_routes
from routes_player import register_player_routes
from routes_admin import register_admin_routes
from routes_guild import register_guild_routes
from routes_tutorial import register_tutorial_routes
from routes_fleet_utils import register_fleet_util_routes
from routes_galaxy_report import register_galaxy_report_routes
from routes_commanders import register_commander_routes
from routes_catalog import register_catalog_routes
from routes_ws import register_ws_routes

register_auth_routes(app)
register_map_routes(app)
register_player_routes(app)

# Admin routes: skip if running with separate admin server (--admin-port)
import os as _os
if not _os.environ.get("AWE_ADMIN_SEPARATE"):
    register_admin_routes(app)
else:
    awe_logger.info("Admin routes excluded — running on separate admin port")

register_guild_routes(app)
register_tutorial_routes(app)
register_fleet_util_routes(app)
register_galaxy_report_routes(app)
register_commander_routes(app)
register_catalog_routes(app)
register_ws_routes(app)

# ── Version endpoint ──
@app.get("/api/version")
async def get_version():
    return {"version": __version__}


# ── Engine identity / attribution (see engine_identity.py & LICENSE) ──
@app.get("/api/engine")
async def get_engine_identity():
    return engine_identity(__version__)


@app.get("/.well-known/astrowebengine")
async def get_engine_well_known():
    return engine_identity(__version__)

@app.get("/api/engine-config")
async def get_engine_config():
    """Public endpoint: returns the active game definition's engine config and meta.
    Used by the frontend to adapt UI based on game type (map depth, defense model, etc.)."""
    from game_definition import get_game_definition
    defn = get_game_definition()
    return {
        "meta": defn.get("meta", {}),
        "engine": defn.get("engine", {}),
        # Optional UI overrides a ruleset can set (e.g. nav.* tab labels) so the
        # shell isn't hardcoded to one game's vocabulary.
        "ui": defn.get("ui", {}),
    }

@app.get("/sw.js")
async def serve_sw():
    return FileResponse(str(STATIC_DIR / "sw.js"), media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})

# ── Static pages ──
# The SPA HTML shells must always be revalidated (no-cache = revalidate via
# etag, not "don't store"), so a deploy's renamed classes / bumped ?v= asset
# links are picked up immediately instead of a stale shell pinning old assets.
_SHELL_HEADERS = {"Cache-Control": "no-cache"}

@app.get("/")
async def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html", headers=_SHELL_HEADERS)

@app.get("/game")
async def serve_game():
    return FileResponse(str(STATIC_DIR / "game.html"), media_type="text/html", headers=_SHELL_HEADERS)

@app.get("/setup")
async def serve_setup():
    """Galaxy selection + tutorial page (post-registration)."""
    return FileResponse(str(STATIC_DIR / "setup.html"), media_type="text/html")

@app.get("/gallery")
async def serve_gallery():
    """Public 'Made with AstroWebEngine' showcase gallery (links out to creator-hosted games)."""
    return FileResponse(str(STATIC_DIR / "gallery.html"), media_type="text/html")

if not _os.environ.get("AWE_ADMIN_SEPARATE"):
    @app.get("/admin")
    async def serve_admin():
        return FileResponse(str(STATIC_DIR / "admin.html"), media_type="text/html",
                            headers={"Cache-Control": "no-cache, must-revalidate"})

# ── Run sync DB work in thread pool to avoid blocking the event loop ──
async def _run_in_thread(func, *args):
    """Run a synchronous function in the default thread pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)

# ── Background bot tick task ──
def _bot_tick_sync():
    db = SessionLocal()
    try:
        from bot_logic import tick_bots
        tick_bots(db)
        mod_hooks.fire("on_tick", {"tick_type": "bots", "db": db})
        return get_config_int(db, "bot_tick_interval", 60)
    finally:
        db.close()

async def _bot_tick_loop():
    """Periodically run bot AI ticks in the background."""
    while True:
        try:
            bot_interval = await _run_in_thread(_bot_tick_sync)
        except Exception as e:
            awe_logger.error(f"[bot-tick] {e}")
            bot_interval = 60
        await asyncio.sleep(bot_interval)

def _npc_stability_tick_sync():
    db = SessionLocal()
    try:
        from bot_logic import process_settlers_stability
        result = process_settlers_stability(db)
        mod_hooks.fire("on_tick", {"tick_type": "daily_stability", "db": db, "result": result})
        return result
    finally:
        db.close()

async def _npc_stability_tick_loop():
    """Run NPC stability decay once per day at server midnight."""
    from datetime import datetime, timedelta
    while True:
        try:
            now = datetime.utcnow()
            next_tick = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            wait_secs = max(1, (next_tick - now).total_seconds())
            await asyncio.sleep(wait_secs)
            result = await _run_in_thread(_npc_stability_tick_sync)
            if result.get("processed") or result.get("disbanded") or result.get("created"):
                awe_logger.info(
                    f"[npc-stability] Processed {result.get('processed', 0)} Settlers bases, "
                    f"disbanded {result.get('disbanded', 0)}, "
                    f"created {result.get('created', 0)}"
                )
        except Exception as e:
            awe_logger.error(f"[npc-stability] {e}")
            await asyncio.sleep(60)

# ── Background galaxy-network reshuffle tick (dynamic_wormholes) ──
def _galaxy_reshuffle_sync():
    db = SessionLocal()
    try:
        import galaxy_network
        if galaxy_network.maybe_reshuffle_galaxy_links(db):
            awe_logger.info("[galaxy-reshuffle] regenerated the dynamic wormhole graph")
    finally:
        db.close()

async def _galaxy_reshuffle_tick_loop():
    """Reshuffle the galaxy-link graph when dynamic_wormholes is active and a new
    reshuffle period has begun (no-op for every other topology)."""
    while True:
        try:
            await _run_in_thread(_galaxy_reshuffle_sync)
        except Exception as e:
            awe_logger.error(f"[galaxy-reshuffle] {e}")
        await asyncio.sleep(300)  # check every 5 min; reshuffles only on epoch rollover


# ── Background debris collection tick (once per hour at :30) ──
def _recycler_tick_sync():
    db = SessionLocal()
    try:
        from game_scouting import process_recycler_tick
        process_recycler_tick(db)
        mod_hooks.fire("on_tick", {"tick_type": "recycler", "db": db})
    finally:
        db.close()

async def _recycler_tick_loop():
    """Run debris auto-collection once per hour at the :30 mark."""
    from datetime import datetime, timedelta
    while True:
        try:
            now = datetime.utcnow()
            if now.minute < 30:
                next_tick = now.replace(minute=30, second=0, microsecond=0)
            else:
                next_tick = (now + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
            wait_secs = max(1, (next_tick - now).total_seconds())
            await asyncio.sleep(wait_secs)
            await _run_in_thread(_recycler_tick_sync)
            awe_logger.info(f"[recycler-tick] Collected debris at {datetime.utcnow().strftime('%H:%M')}")
        except Exception as e:
            awe_logger.error(f"[recycler-tick] {e}")

# ── Background queue tick (every 10s) ──
def _queue_tick_sync():
    from datetime import datetime
    db = SessionLocal()
    try:
        from game_logic import _check_completions
        from models import User
        now = datetime.utcnow()
        users = db.query(User).all()
        for user in users:
            _check_completions(user, db, now)
        db.commit()
        mod_hooks.fire("on_tick", {"tick_type": "queue", "db": db, "now": now})
        return max(1, int(get_config_float(db, "QUEUE_TICK_INTERVAL", QUEUE_TICK_INTERVAL)))
    finally:
        db.close()

async def _queue_tick_loop():
    """Advance construction and research queues for all players."""
    while True:
        try:
            interval = await _run_in_thread(_queue_tick_sync)
        except Exception as e:
            awe_logger.error(f"[queue-tick] {e}")
            interval = QUEUE_TICK_INTERVAL
        await asyncio.sleep(max(1, interval))

# ── Background fleet-arrival tick (default every 1s) ──
def _fleet_arrival_tick_sync():
    from datetime import datetime
    db = SessionLocal()
    try:
        from game_logic import _process_fleet_arrivals

        now = datetime.utcnow()
        due_user_ids = [
            user_id
            for (user_id,) in (
                db.query(Fleet.user_id)
                .filter(
                    Fleet.is_moving == True,
                    Fleet.arrival_time != None,
                    Fleet.arrival_time <= now,
                )
                .distinct()
                .all()
            )
        ]
        processed_users = 0
        for user_id in due_user_ids:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                continue
            _process_fleet_arrivals(user, db)
            processed_users += 1
        interval = max(1, int(get_config_float(
            db, "FLEET_ARRIVAL_TICK_INTERVAL", FLEET_ARRIVAL_TICK_INTERVAL
        )))
        mod_hooks.fire("on_tick", {"tick_type": "fleet_arrival", "db": db, "now": now,
                                   "processed_users": processed_users})
        return {"processed_users": processed_users, "interval": interval}
    finally:
        db.close()

async def _fleet_arrival_tick_loop():
    """Process due fleet arrivals independently of player page loads."""
    while True:
        try:
            result = await _run_in_thread(_fleet_arrival_tick_sync)
            interval = result["interval"]
        except Exception as e:
            awe_logger.error(f"[fleet-arrival-tick] {e}")
            interval = FLEET_ARRIVAL_TICK_INTERVAL
        await asyncio.sleep(max(1, interval))

# ── Background autoscout tick (every 10s) ──
def _autoscout_tick_sync():
    db = SessionLocal()
    try:
        from game_scouting import process_autoscout_tick
        process_autoscout_tick(db)
        mod_hooks.fire("on_tick", {"tick_type": "autoscout", "db": db})
        return max(1, int(get_config_float(db, "AUTOSCOUT_TICK_INTERVAL", AUTOSCOUT_TICK_INTERVAL)))
    finally:
        db.close()

async def _autoscout_tick_loop():
    """Move autoscout fleets through the galaxy."""
    while True:
        try:
            interval = await _run_in_thread(_autoscout_tick_sync)
        except Exception as e:
            awe_logger.error(f"[autoscout-tick] {e}")
            interval = AUTOSCOUT_TICK_INTERVAL
        await asyncio.sleep(max(1, interval))

# ── Background guild-history tick (once per hour) ──
def _guild_history_tick_sync():
    db = SessionLocal()
    try:
        from routes_guild import capture_guild_history_snapshots
        captured = capture_guild_history_snapshots(db)
        mod_hooks.fire("on_tick", {"tick_type": "guild_history", "db": db, "captured": captured})
        return captured
    finally:
        db.close()

async def _guild_history_tick_loop():
    """Capture guild graph history once per hour on a clean minute boundary."""
    from datetime import datetime, timedelta
    while True:
        try:
            now = datetime.utcnow()
            next_tick = (now + timedelta(hours=1)).replace(minute=5, second=0, microsecond=0)
            if now.minute < 5:
                next_tick = now.replace(minute=5, second=0, microsecond=0)
            wait_secs = max(1, (next_tick - now).total_seconds())
            await asyncio.sleep(wait_secs)
            captured = await _run_in_thread(_guild_history_tick_sync)
            if captured:
                awe_logger.info(f"[guild-history] Captured guild graph snapshot at {datetime.utcnow().strftime('%H:%M')}")
        except Exception as e:
            awe_logger.error(f"[guild-history] {e}")

# ── Background income tick (every 5 minutes) ──
def _income_tick_sync():
    db = SessionLocal()
    try:
        from game_logic import collect_resources
        game_speed = get_config_float(db, "game_speed", 1.0)
        users = db.query(User).filter(User.is_bot == False).all()
        credited_users = 0
        total_earned = 0.0
        for user in users:
            earned = collect_resources(user, db, game_speed, include_completions=False)
            if earned > 0:
                credited_users += 1
                total_earned += earned
        # Conquest mode (opt-in): escalate long-held occupations to permanent
        # capture. No-op unless the occupation_capture engine flag is set.
        try:
            import conquest
            captures = conquest.process_occupation_capture(db, now=datetime.utcnow())
            if captures:
                db.commit()
                awe_logger.info(f"[conquest] {len(captures)} base(s) captured this tick")
        except Exception as e:
            awe_logger.error(f"[conquest] capture sweep failed: {e}")
            db.rollback()
        mod_hooks.fire("on_tick", {"tick_type": "income", "db": db, "game_speed": game_speed,
                                   "credited_users": credited_users, "total_earned": total_earned})
        return {"credited_users": credited_users, "total_earned": round(total_earned, 2)}
    finally:
        db.close()

async def _income_tick_loop():
    """Sweep hourly income for offline players so credits accrue while logged out."""
    while True:
        await asyncio.sleep(300)
        try:
            result = await _run_in_thread(_income_tick_sync)
            if result["credited_users"] > 0:
                awe_logger.info(
                    f"[income-tick] Credited {result['credited_users']} players for {result['total_earned']}"
                )
        except Exception as e:
            awe_logger.error(f"[income-tick] {e}")

def _migrate_research_queue_colony_ids(db):
    """One-time migration: assign colony_id to research queue items that don't have one."""
    from models import ResearchQueue, Colony
    from game_logic import get_building_level
    orphans = db.query(ResearchQueue).filter(ResearchQueue.colony_id == None).all()
    if not orphans:
        return
    # Group by user_id
    by_user = {}
    for rq in orphans:
        by_user.setdefault(rq.user_id, []).append(rq)
    for user_id, items in by_user.items():
        # Find best research base for this user
        colonies = db.query(Colony).filter(Colony.user_id == user_id).all()
        best = max(colonies, key=lambda c: get_building_level(c, "research_labs"), default=None)
        if best:
            for rq in items:
                rq.colony_id = best.id
        else:
            # No colonies — delete orphaned queue items
            for rq in items:
                db.delete(rq)
    db.commit()
    awe_logger.info(f"[migration] Assigned colony_id to {len(orphans)} research queue items")

def _repair_stuck_queues(db):
    """Fix ship queue items that lost next_complete during a server restart."""
    from game_logic import _ship_build_time
    from auth import get_config_float
    from datetime import datetime, timedelta
    game_speed = get_config_float(db, "game_speed", 1.0)
    stuck = db.query(ShipQueue).filter(
        ShipQueue.position == 0,
        ShipQueue.started_at != None,
        ShipQueue.next_complete == None,
    ).all()
    if not stuck:
        return
    now = datetime.utcnow()
    for q in stuck:
        colony = db.query(Colony).filter(Colony.id == q.colony_id).first()
        user = db.query(User).filter(User.id == q.user_id).first()
        if not colony or not user:
            continue
        remaining = q.count - q.built
        per_ship = _ship_build_time(q.ship_type, colony, user, game_speed, db)
        q.next_complete = q.started_at + timedelta(seconds=per_ship * remaining)
    db.commit()
    if stuck:
        awe_logger.info(f"[startup] Repaired {len(stuck)} stuck ship queue items")

# ── Startup ──
def _registry_sync():
    db = SessionLocal()
    try:
        from awe_registry import register_sync, is_registry_enabled
        if not is_registry_enabled(db):
            return {"ok": False, "reason": "disabled"}
        return register_sync(db, __version__)
    finally:
        db.close()

async def _registry_heartbeat_loop():
    """Opt-in: refresh this game's listing in the AstroWebEngine registry."""
    await asyncio.sleep(15)  # let the server settle before the first ping
    while True:
        try:
            await _run_in_thread(_registry_sync)
        except Exception as e:
            awe_logger.error(f"[registry] {e}")
        await asyncio.sleep(3600)  # hourly heartbeat


@app.on_event("startup")
async def startup():
    ModelBase.metadata.create_all(bind=engine)
    _auto_migrate_sqlite()
    # SQLite PRAGMAs (WAL, busy_timeout) are set per-connection in database.py
    db = SessionLocal()
    init_default_configs(db)
    ensure_wormholes(db)
    # Behavioral-mod hooks (opt-in, default off — see mod_hooks.load_mod_hooks)
    try:
        import mod_hooks
        hook_report = mod_hooks.load_mod_hooks(db)
        if hook_report.get("loaded"):
            awe_logger.info(f"[mods] loaded hooks from: {hook_report['loaded']}")
    except Exception as e:
        awe_logger.error(f"[startup mod-hooks] {e}")
    try:
        from routes_guild import capture_guild_history_snapshots
        capture_guild_history_snapshots(db)
    except Exception as e:
        awe_logger.error(f"[startup guild-history] {e}")
    _migrate_research_queue_colony_ids(db)
    _repair_stuck_queues(db)
    try:
        from bot_logic import process_settlers_stability
        process_settlers_stability(db)
    except Exception as e:
        awe_logger.error(f"[startup npc-stability] {e}")
    db.close()

    # Resolve the active game definition:
    #   1. AWE_GAME_DEFINITION env  (universe manager / ops override)
    #   2. admin-persisted selection (Build Game / import / mods) — survives restart
    #   3. built-in default
    game_def_path = _os.environ.get("AWE_GAME_DEFINITION")
    if game_def_path and _os.path.exists(game_def_path):
        from game_definition import load_definition_from_file, set_game_definition
        defn = load_definition_from_file(game_def_path)
        set_game_definition(defn)
        awe_logger.info(f"Loaded game definition from env: {defn.get('meta', {}).get('name', game_def_path)}")
    else:
        from game_definition import restore_persisted_definition
        _rdb = SessionLocal()
        try:
            _restored = restore_persisted_definition(_rdb)
        finally:
            _rdb.close()
        if _restored:
            awe_logger.info(f"Restored persisted game definition: {_restored}")
    # Start background tick loops
    asyncio.create_task(_bot_tick_loop())
    asyncio.create_task(_npc_stability_tick_loop())
    asyncio.create_task(_recycler_tick_loop())
    asyncio.create_task(_galaxy_reshuffle_tick_loop())
    asyncio.create_task(_queue_tick_loop())
    asyncio.create_task(_fleet_arrival_tick_loop())
    asyncio.create_task(_autoscout_tick_loop())
    asyncio.create_task(_guild_history_tick_loop())
    asyncio.create_task(_income_tick_loop())
    asyncio.create_task(_registry_heartbeat_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
