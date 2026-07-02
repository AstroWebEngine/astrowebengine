"""
Authentication and Configuration Helper Functions for AstroWebEngine
Extracted from main.py for modularity and reusability.
"""

from fastapi import HTTPException, Depends, Header
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import bcrypt as _bcrypt_lib
from jose import JWTError, jwt

from database import SessionLocal, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_HOURS
from models import User, GameConfig, EventLog, CreditLog, FleetAuditLog
from specs import SHIP_SPECS, DEFENSE_SPECS, BUILDING_SPECS, RESEARCH_SPECS, PLANET_TYPE_STATS
from combat_locks import release_session_locks


# ======================== DATABASE DEPENDENCY ========================

def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
        if db.in_transaction():
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        release_session_locks(db)
        db.close()


# ======================== PASSWORD HASHING ========================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return _bcrypt_lib.checkpw(password.encode(), hashed.encode())


# ======================== JWT TOKEN HANDLING ========================

def create_access_token(data: dict) -> str:
    """Create a JWT access token with expiration."""
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str, db: Session) -> User:
    """Decode JWT token and return the associated User object."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    # Support both old (username string) and new (user ID) token formats
    if isinstance(sub, int) or (isinstance(sub, str) and sub.isdigit()):
        user = db.query(User).filter(User.id == int(sub)).first()
    else:
        user = db.query(User).filter(User.username == sub).first()
    if not user:
        raise HTTPException(401, "User not found")
    # Update last_seen (throttle to once per 30s to reduce writes)
    now = datetime.utcnow()
    if not user.last_seen or (now - user.last_seen).total_seconds() > 30:
        user.last_seen = now
        db.commit()
    return user


def check_admin(user: User):
    """Check if a user has admin privileges."""
    if not user.is_admin:
        raise HTTPException(403, "Admin required")


# ======================== HEADER TOKEN EXTRACTION ========================

def get_token_from_header(authorization: Optional[str] = Header(None)) -> str:
    """Extract Bearer token from Authorization header (required)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    return authorization.split(" ", 1)[1]


def get_optional_token_dep(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract Bearer token from Authorization header (optional)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.split(" ", 1)[1]


# ======================== EVENT LOGGING ========================

def log_event(db: Session, user_id: int, event_type: str, message: str, data: dict = None):
    """Add an event to the player's event log."""
    import json as _json
    ev = EventLog(user_id=user_id, event_type=event_type, message=message,
                  data=_json.dumps(data) if data else "{}")
    db.add(ev)
    from ws_manager import ws_manager
    ws_manager.queue_event(user_id, {
        "type": "event",
        "event_type": event_type,
        "message": message,
    })


def log_credits(db: Session, user_id: int, amount, description: str, category: str = "other"):
    """Record a credit transaction in the ledger. Call AFTER modifying user resources."""
    from resources import get_user_resources, total_cost_value
    user = db.query(User).filter(User.id == user_id).first()
    balance = sum(get_user_resources(user).values()) if user else 0
    # Normalize amount to scalar for ledger storage
    if isinstance(amount, dict):
        amount = total_cost_value(amount)
    db.add(CreditLog(user_id=user_id, description=description,
                     amount=round(amount), balance=round(balance), category=category))


def log_fleet_change(db: Session, user_id: int, fleet, action: str, ships_before: dict, details: str = ""):
    """Record a fleet composition change. Pass ships_before BEFORE the change happened."""
    import json as _json
    from specs import ALL_SHIP_TYPES
    ships_after = fleet.get_all_ship_counts() if hasattr(fleet, 'get_all_ship_counts') else {st: getattr(fleet, st, 0) for st in ALL_SHIP_TYPES if getattr(fleet, st, 0) > 0}
    db.add(FleetAuditLog(
        user_id=user_id, fleet_id=fleet.id, fleet_name=fleet.name,
        action=action,
        ships_before=_json.dumps(ships_before),
        ships_after=_json.dumps(ships_after),
        details=details
    ))


# ======================== GAME CONFIG HELPERS ========================

DEFAULT_CONFIG = {
    "game_name": "AstroWebEngine",
    "game_status": "setup",
    "game_started_at": "",
    "NPC_SETTLERS_AUTO_MAINTAIN_ENABLED": "true",
    "AWE_REGISTRY_ENABLED": "false",  # opt-in: list this game in the public AstroWebEngine registry
    "registration_open": "true",
    # Universe structure:
    #   Server = one letter (A=Alpha, B=Beta, etc.)
    #   Cluster = group of 10 galaxies (x0-x9). E.g. A00-A09, A10-A19, A20-A29...
    #   Galaxy = individual galaxy within a cluster (A00, A01, etc.)
    #   map_topology: "pumpkin" (x0↔x0, x9↔x9 between clusters) or "classic" (x9→x0)
    "server_letter": "A",         # A=Alpha, B=Beta, C=Gamma, etc.
    "num_clusters": "4",          # number of clusters (each = 10 galaxies)
    "map_topology": "pumpkin",    # how clusters connect to each other
    "galaxy_preset": "standard",  # standard, mss, or custom
    "regions_per_galaxy": "100",  # default 10x10 grid
    "systems_per_region": "44",   # max systems per region (~44 in dense core)
    "planets_per_system_min": "1",
    "planets_per_system_max": "11",
    "game_speed": "1.0",
    "starting_credits": "500",
    "colonize_cost": "200",
    "max_players": "100",
    "win_condition": "domination",
    "domination_threshold": "0.75",
    "economic_target": "100000",
    "time_limit_hours": "168",
}


def init_default_configs(db: Session):
    """Initialize default game configuration values if not already present."""
    for k, v in DEFAULT_CONFIG.items():
        if not db.query(GameConfig).filter(GameConfig.key == k).first():
            db.add(GameConfig(key=k, value=v))
    db.commit()
    _load_config_cache(db)


# ── In-memory config cache (loaded once at startup, refreshed on set_config) ──
_config_cache = {}
_config_cache_loaded = False


def _load_config_cache(db: Session):
    """Load all game_config rows into memory."""
    global _config_cache, _config_cache_loaded
    rows = db.query(GameConfig).all()
    _config_cache = {r.key: r.value for r in rows}
    _config_cache_loaded = True


def refresh_config_cache(db: Session = None):
    """Force-reload the config cache. Call after bulk changes."""
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        try:
            _load_config_cache(db)
        finally:
            db.close()
    else:
        _load_config_cache(db)


def _engine_flag_from_definition(key: str):
    """Return the active game definition's ``engine[key]`` as a string, or None.

    Lets engine flags authored in a game definition (e.g. galaxy_shape,
    galaxy_network, map_topology, wormhole_model and their numeric tuning
    params) take effect through the config-read path. Lazy import avoids a
    circular dependency with game_definition."""
    try:
        from game_definition import get_game_definition
        engine = (get_game_definition() or {}).get("engine", {}) or {}
    except Exception:
        return None
    val = engine.get(key)
    return None if val is None else str(val)


def get_config(db: Session, key: str, default: str = "") -> str:
    """Get a configuration value by key.

    Precedence: admin ``game_config`` override (in-memory cache) > the active
    game definition's ``engine`` section > the caller-supplied default. This
    makes engine flags set in a game definition actually take effect, while an
    operator can still override them at runtime via the admin panel. Non-engine
    keys aren't present in ``engine`` and fall through to the default unchanged."""
    global _config_cache_loaded
    if not _config_cache_loaded:
        _load_config_cache(db)
    if key in _config_cache:
        return _config_cache[key]
    from_def = _engine_flag_from_definition(key)
    if from_def is not None:
        return from_def
    return default


def get_config_float(db: Session, key: str, default: float = 1.0) -> float:
    """Get a configuration value as a float."""
    try:
        return float(get_config(db, key, str(default)))
    except (ValueError, TypeError):
        return default


def get_config_int(db: Session, key: str, default: int = 0) -> int:
    """Get a configuration value as an integer."""
    try:
        return int(float(get_config(db, key, str(default))))
    except (ValueError, TypeError):
        return default


def set_config(db: Session, key: str, value: str):
    """Set a configuration value and update the in-memory cache."""
    c = db.query(GameConfig).filter(GameConfig.key == key).first()
    if c:
        c.value = value
    else:
        db.add(GameConfig(key=key, value=value))
    db.commit()
    _config_cache[key] = value
    _maybe_invalidate_catalog_for_config(key)


def _maybe_invalidate_catalog_for_config(key: str):
    spec_prefixes = (
        "ship_override_", "def_override_", "building_override_",
        "research_override_", "astro_override_", "commander_",
    )
    spec_keys = {
        "custom_ship_specs", "custom_def_specs", "custom_building_specs",
        "custom_research_specs", "custom_astro_specs",
        "disabled_ships", "disabled_defs", "disabled_defenses", "disabled_buildings",
        "disabled_research", "disabled_astros",
    }
    if key in spec_keys or key.startswith(spec_prefixes):
        try:
            from catalog_sync import invalidate_all_online
            invalidate_all_online(["specs"], f"config:{key}")
        except Exception:
            pass


# ======================== GENERIC SPEC HELPERS ========================
# Pattern: hardcoded defaults in specs.py + DB overrides + DB custom types + disable toggle.
# Config keys:
#   {category}_override_{key}  — JSON overrides for a built-in type
#   disabled_{category}s       — comma-separated list of disabled keys
#   custom_{category}_specs    — JSON dict of entirely new types added by admin
#
# Categories: ship, def (defense), building, research, astro

def _get_effective_spec(db: Session, category: str, key: str, base_specs: dict) -> dict:
    """Get a spec with admin overrides applied.  Works for any category."""
    base = base_specs.get(key, {})
    # Also check custom types
    if not base:
        custom_raw = get_config(db, f"custom_{category}_specs")
        if custom_raw:
            try:
                customs = json.loads(custom_raw)
                base = customs.get(key, {})
            except:
                pass
    if not base:
        return {}
    override_raw = get_config(db, f"{category}_override_{key}")
    if override_raw:
        try:
            overrides = json.loads(override_raw)
            return {**base, **overrides}
        except:
            pass
    return dict(base)


def _is_disabled(db: Session, category: str, key: str) -> bool:
    """Check if a type is disabled.  Works for any category."""
    disabled_raw = get_config(db, f"disabled_{category}s") or ""
    disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
    return key in disabled_set


def _get_all_specs(db: Session, category: str, base_specs: dict) -> dict:
    """Return merged dict: built-in defaults + custom types, each with overrides applied.
    Does NOT filter out disabled types — caller can do that if needed."""
    result = {}
    # Start with built-in defaults
    for key in base_specs:
        result[key] = _get_effective_spec(db, category, key, base_specs)
    # Add custom types
    custom_raw = get_config(db, f"custom_{category}_specs")
    if custom_raw:
        try:
            customs = json.loads(custom_raw)
            for key, spec in customs.items():
                if key not in result:
                    # Apply overrides to custom types too
                    override_raw = get_config(db, f"{category}_override_{key}")
                    if override_raw:
                        try:
                            overrides = json.loads(override_raw)
                            result[key] = {**spec, **overrides}
                        except:
                            result[key] = dict(spec)
                    else:
                        result[key] = dict(spec)
        except:
            pass
    return result


def _add_custom_spec(db: Session, category: str, key: str, spec: dict):
    """Add a new custom type.  Stored in DB as JSON."""
    custom_raw = get_config(db, f"custom_{category}_specs") or "{}"
    try:
        customs = json.loads(custom_raw)
    except:
        customs = {}
    customs[key] = spec
    set_config(db, f"custom_{category}_specs", json.dumps(customs))


def _remove_custom_spec(db: Session, category: str, key: str) -> bool:
    """Remove a custom type.  Returns True if found and removed."""
    custom_raw = get_config(db, f"custom_{category}_specs") or "{}"
    try:
        customs = json.loads(custom_raw)
    except:
        return False
    if key in customs:
        del customs[key]
        set_config(db, f"custom_{category}_specs", json.dumps(customs))
        # Also clean up any override
        set_config(db, f"{category}_override_{key}", "")
        return True
    return False


# ======================== SHIP SPEC HELPERS ========================

def get_effective_ship_spec(db: Session, ship_key: str) -> dict:
    return _get_effective_spec(db, "ship", ship_key, SHIP_SPECS)

def is_ship_disabled(db: Session, ship_key: str) -> bool:
    return _is_disabled(db, "ship", ship_key)

def get_all_ship_specs(db: Session) -> dict:
    return _get_all_specs(db, "ship", SHIP_SPECS)


# ======================== SHIP CAPABILITIES ========================
# Data-driven feature gating: instead of hard-coding roster keys, a ship spec
# flags the capability (can_colonize / can_recycle / can_autoscout). This lets a
# ruleset mod's own roster drive these features.

def ships_with_capability(db: Session, capability: str) -> list:
    """Active ship keys whose spec flags `capability` truthy."""
    return [k for k, s in get_all_ship_specs(db).items() if s.get(capability)]

def fleet_capability_ship(fleet, db: Session, capability: str):
    """A ship key present in `fleet` that has `capability`, else None."""
    for k in ships_with_capability(db, capability):
        if fleet.get_ship_count(k) > 0:
            return k
    return None


# ======================== DEFENSE SPEC HELPERS ========================

def get_effective_defense_spec(db: Session, def_key: str) -> dict:
    return _get_effective_spec(db, "def", def_key, DEFENSE_SPECS)

def is_defense_disabled(db: Session, def_key: str) -> bool:
    return _is_disabled(db, "def", def_key)

def get_all_defense_specs(db: Session) -> dict:
    return _get_all_specs(db, "def", DEFENSE_SPECS)


# ======================== BUILDING SPEC HELPERS ========================

def get_effective_building_spec(db: Session, key: str) -> dict:
    return _get_effective_spec(db, "building", key, BUILDING_SPECS)

def is_building_disabled(db: Session, key: str) -> bool:
    return _is_disabled(db, "building", key)

def get_all_building_specs(db: Session) -> dict:
    return _get_all_specs(db, "building", BUILDING_SPECS)


# ======================== RESEARCH SPEC HELPERS ========================

def get_effective_research_spec(db: Session, key: str) -> dict:
    return _get_effective_spec(db, "research", key, RESEARCH_SPECS)

def is_research_disabled(db: Session, key: str) -> bool:
    return _is_disabled(db, "research", key)

def get_all_research_specs(db: Session) -> dict:
    return _get_all_specs(db, "research", RESEARCH_SPECS)


# ======================== ASTRO TYPE SPEC HELPERS ========================

def get_effective_astro_spec(db: Session, key: str) -> dict:
    return _get_effective_spec(db, "astro", key, PLANET_TYPE_STATS)

def is_astro_disabled(db: Session, key: str) -> bool:
    return _is_disabled(db, "astro", key)

def get_all_astro_specs(db: Session) -> dict:
    return _get_all_specs(db, "astro", PLANET_TYPE_STATS)
