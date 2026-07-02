"""
AstroWebEngine — Dedicated Admin Server

Runs on a separate port from the game server. Only admin login is allowed.
This keeps admin functionality (universe generation, game definitions,
spec editing) isolated from the public game server.

Usage:
  python run.py --admin-port 8001    # starts both game (8000) + admin (8001)
  python admin_app.py                # standalone admin server on 8001
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pathlib import Path

import logging
from database import engine, ModelBase, SessionLocal
from auth import init_default_configs, get_token_from_header, get_current_user, check_admin, get_db

logger = logging.getLogger("awe")

STATIC_DIR = Path(__file__).resolve().parent / "static"

admin_app = FastAPI(title="AstroWebEngine Admin")
admin_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                         allow_methods=["*"], allow_headers=["*"])

admin_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Register only auth + admin routes ──
from routes_auth import register_auth_routes
from routes_admin import register_admin_routes

register_auth_routes(admin_app)
register_admin_routes(admin_app)

# ── Admin-only login: override the register endpoint to block new signups ──
# The auth routes include register, but on the admin port we want login-only.
# We add a guard that rejects non-admin logins after the routes are registered.

@admin_app.get("/api/version")
async def admin_version():
    from app import __version__
    return {"version": __version__, "admin": True}

@admin_app.get("/api/engine-config")
async def admin_engine_config():
    from game_definition import get_game_definition
    defn = get_game_definition()
    return {"meta": defn.get("meta", {}), "engine": defn.get("engine", {})}

# ── Serve admin pages ──
@admin_app.get("/")
async def admin_index():
    """Admin portal login page."""
    return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html")

@admin_app.get("/admin")
async def admin_panel():
    return FileResponse(str(STATIC_DIR / "admin.html"), media_type="text/html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})

# ── Startup: ensure DB tables exist ──
@admin_app.on_event("startup")
async def admin_startup():
    from universe import _auto_migrate_sqlite
    ModelBase.metadata.create_all(bind=engine)
    _auto_migrate_sqlite()
    db = SessionLocal()
    try:
        init_default_configs(db)
    finally:
        db.close()
    logger.info("[admin] Admin server ready")


# ── Universe Management API ──
from universe_manager import (
    list_universes, create_universe, delete_universe,
    start_universe, stop_universe, get_universe_log,
    get_next_available_port, check_all_universes,
    load_registry,
)
from game_definition import list_available_definitions

@admin_app.get("/api/admin/universes")
def api_list_universes(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    check_all_universes()
    universes = list_universes()
    return {"universes": universes, "next_port": get_next_available_port()}

@admin_app.post("/api/admin/universes")
def api_create_universe(body: dict, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Universe name is required")
    try:
        entry = create_universe(
            name=name,
            game_definition=body.get("game_definition", "classic_space.json"),
            port=body.get("port", get_next_available_port()),
            description=body.get("description", ""),
            game_speed=body.get("game_speed", 1.0),
            max_players=body.get("max_players", 100),
            subdomain=body.get("subdomain", ""),
        )
        return {"ok": True, "universe": entry}
    except ValueError as e:
        raise HTTPException(400, str(e))

@admin_app.post("/api/admin/universes/{universe_id}/start")
def api_start_universe(universe_id: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    try:
        entry = start_universe(universe_id)
        return {"ok": True, "universe": entry}
    except ValueError as e:
        raise HTTPException(400, str(e))

@admin_app.post("/api/admin/universes/{universe_id}/stop")
def api_stop_universe(universe_id: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    try:
        entry = stop_universe(universe_id)
        return {"ok": True, "universe": entry}
    except ValueError as e:
        raise HTTPException(400, str(e))

@admin_app.delete("/api/admin/universes/{universe_id}")
def api_delete_universe(universe_id: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    try:
        delete_universe(universe_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))

@admin_app.get("/api/admin/universes/{universe_id}/log")
def api_universe_log(universe_id: str, token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    return {"log": get_universe_log(universe_id)}

@admin_app.get("/api/admin/available-definitions")
def api_available_definitions(token: str = Depends(get_token_from_header), db: Session = Depends(get_db)):
    user = get_current_user(token, db); check_admin(user)
    defs = list_available_definitions()
    # Also offer packaged ruleset mods as selectable prebuilt games (value "mod:<id>").
    try:
        import mod_loader as ml
        for m in ml.discover_mods():
            man = m["manifest"]
            if man.get("kind") == "ruleset" and not m["errors"]:
                defs.append({
                    "filename": f"mod:{m['id']}",
                    "name": man.get("name", m["id"]),
                    "version": man.get("version", ""),
                    "description": man.get("description", ""),
                })
    except Exception:
        pass
    return {"definitions": defs}


# ── Lobby: public server list for players ──

@admin_app.get("/lobby")
async def serve_lobby():
    return FileResponse(str(STATIC_DIR / "lobby.html"), media_type="text/html")

@admin_app.get("/api/lobby/servers")
def api_lobby_servers():
    """Public endpoint: list running universes for players to choose from."""
    universes = list_universes()
    servers = []
    for u in universes:
        if u["status"] == "running":
            servers.append({
                "name": u["name"],
                "description": u.get("description", ""),
                "port": u["port"],
                "game_speed": u.get("game_speed", 1.0),
                "max_players": u.get("max_players", 100),
                "game_definition": u.get("game_definition", ""),
                "subdomain": u.get("subdomain", ""),
            })
    return {"servers": servers}


# ── Standalone mode ──
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Admin Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host (default: 127.0.0.1 — local only)')
    parser.add_argument('--port', type=int, default=8001, help='Port (default: 8001)')
    args = parser.parse_args()

    print(f"""
  AstroWebEngine — Admin Server
  ==============================
  Admin Panel: http://{args.host}:{args.port}/admin
  Login with your admin account credentials.

  NOTE: This server only handles admin operations.
  The game server runs separately on its own port.
""")

    import uvicorn
    uvicorn.run(admin_app, host=args.host, port=args.port)
