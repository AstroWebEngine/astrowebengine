"""
AstroWebEngine registry client (OPT-IN, disabled by default).

Lets an operator list their game in a public AstroWebEngine registry — the
shared directory of AWE-powered games (and, later, mods). The operator turns it
on in the admin panel and sets their public URL; the engine then POSTs a small
registration payload to the registry and refreshes it on a heartbeat.

Design contract:
  * OPT-IN — does nothing unless AWE_REGISTRY_ENABLED is true (LICENSE §4).
  * FAIL-SOFT — registry errors are logged and swallowed; they never affect the
    running game.
  * VERIFIABLE — the payload points at this deployment's /api/engine, so the
    registry can fetch it to confirm the listing is genuinely AWE (anti-spoof).

See docs/registry_protocol.md for the server-side contract.
"""
import logging

from engine_identity import ENGINE_NAME, ENGINE_HOMEPAGE

logger = logging.getLogger("awe")

# Default public registry. Operators may point AWE_REGISTRY_URL elsewhere.
DEFAULT_REGISTRY_URL = "https://registry.astrowebengine.com"


def _config_bool(db, key: str, default: bool = False) -> bool:
    from auth import get_config
    raw = (get_config(db, key, "true" if default else "false") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_registry_enabled(db) -> bool:
    return _config_bool(db, "AWE_REGISTRY_ENABLED", False)


def build_registration(db, version: str) -> dict:
    """Assemble the registration payload for this deployment."""
    from auth import get_config
    from models import User
    public_url = (get_config(db, "AWE_REGISTRY_PUBLIC_URL", "") or "").strip().rstrip("/")
    players = db.query(User).filter(User.is_bot == False).count()
    return {
        "engine": ENGINE_NAME,
        "engine_url": ENGINE_HOMEPAGE,
        "engine_version": version,
        "game_name": get_config(db, "game_name", ENGINE_NAME),
        "public_url": public_url,                 # registry verifies via {public_url}/api/engine
        "description": get_config(db, "AWE_REGISTRY_DESCRIPTION", ""),
        "status": get_config(db, "game_status", "setup"),
        "players": players,
        "max_players": get_config(db, "max_players", ""),
    }


def register_sync(db, version: str) -> dict:
    """Register/refresh this game with the configured registry. Safe to call any
    time; returns a small status dict and never raises."""
    if not is_registry_enabled(db):
        return {"ok": False, "reason": "disabled"}
    from auth import get_config
    registry_url = (get_config(db, "AWE_REGISTRY_URL", DEFAULT_REGISTRY_URL) or DEFAULT_REGISTRY_URL).strip().rstrip("/")
    payload = build_registration(db, version)
    if not payload["public_url"]:
        logger.warning("[registry] enabled but AWE_REGISTRY_PUBLIC_URL is empty — skipping registration")
        return {"ok": False, "reason": "no_public_url"}
    try:
        import httpx
        resp = httpx.post(f"{registry_url}/api/register", json=payload, timeout=10.0)
        if resp.status_code >= 400:
            logger.warning(f"[registry] {registry_url} returned {resp.status_code}")
            return {"ok": False, "reason": f"http_{resp.status_code}"}
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        logger.info(f"[registry] registered '{payload['game_name']}' at {registry_url} (listing: {data.get('listing_url', '?')})")
        return {"ok": True, "registry_url": registry_url, "response": data}
    except Exception as e:
        logger.warning(f"[registry] registration failed: {e}")
        return {"ok": False, "reason": str(e)}
