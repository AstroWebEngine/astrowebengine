"""MCP endpoint for game creators' AI assistants.

Mounted at /mcp on the game (and separate admin) app. Every request needs an admin
API token (see api_tokens.py). Tools design and activate rulesets through the same
definition_service gate as the admin UI. Deliberately absent: universe generation,
resets, player admin - those stay with the human.
"""
import contextlib
import functools
import json
import os
import re

import anyio
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

import api_tokens
import data_paths
import definition_service as ds
import schema_doc
from game_definition import save_definition_to_file
from database import SessionLocal
from models import User

AI_MARKER = "ai-assistant"
AI_PREFIX = "ai_"  # every AI draft file is game_definitions/ai_*.json (gitignored)
_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")

mcp = FastMCP(
    "AstroWebEngine",
    instructions=(
        "Design games for this AstroWebEngine server. Start with get_engine_guide, "
        "read get_schema for any section before editing it, iterate with check_definition, "
        "save drafts with save_definition, and only call activate_definition or apply_mod "
        "when the creator has explicitly said to. You cannot generate or reset the universe; "
        "if a roster changed, tell the creator to click Launch in the admin panel."
    ),
    stateless_http=True,          # 2 uvicorn workers, no session affinity
    json_response=True,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


_WORKERS_NOTE = ("If the server runs multiple workers, restart it so every worker picks up "
                 "the change.")
_WORKERS_NOTE_SHORT = ("If the server runs multiple workers, restart it so every worker picks up "
                       "the change; no new universe needed.")
_UNAUTHORIZED = "Unauthorized: API token missing, revoked, or owner is no longer admin"


def _bearer(headers) -> str:
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _verify_actor(raw: str):
    """Check a bearer token (blocking DB work); return the actor dict or None."""
    db = SessionLocal()
    try:
        found = api_tokens.verify_token(db, raw)
        if not found:
            return None
        user, tok = found
        return {"user_id": user.id, "token_id": tok.id, "token_name": tok.name}
    finally:
        db.close()


def _caller(ctx: Context) -> dict:
    """Who is calling, read on the event loop: the actor the guard verified, else the raw
    bearer token (then verified in the worker thread)."""
    request = ctx.request_context.request
    actor = getattr(request.state, "awe_actor", None)
    if actor:
        return dict(actor)
    return {"bearer": _bearer(request.headers)}


@contextlib.contextmanager
def _session(caller: dict):
    """Yield (db, user, token_name) for the caller. Runs in a worker thread.

    Normally the guard already verified the token and left the actor on the request, so
    this only reloads the user and re-checks is_admin; without an actor it verifies the
    bearer token itself."""
    db = SessionLocal()
    try:
        if "user_id" in caller:
            user = db.get(User, caller["user_id"])
            if not user or not user.is_admin:
                raise ValueError(_UNAUTHORIZED)
            yield db, user, caller["token_name"]
        else:
            found = api_tokens.verify_token(db, caller.get("bearer"))
            if not found:
                raise ValueError(_UNAUTHORIZED)
            yield db, found[0], found[1].name
    finally:
        db.close()


async def _off_loop(fn, *args):
    """Run a tool's blocking work (DB, file IO, compiling) in a worker thread."""
    return await anyio.to_thread.run_sync(functools.partial(fn, *args))


def _rejected(exc: ds.DefinitionRejected) -> ValueError:
    lines = [exc.message] + [f"- {e}" for e in exc.errors] + [f"- blocked: {b}" for b in exc.blocked]
    return ValueError("\n".join(dict.fromkeys(lines)))


# ---------------------------------------------------------------- learn

def _engine_guide(caller):
    with _session(caller):
        return {
            "engine": "AstroWebEngine: a data-driven engine for multiplayer browser space-strategy "
                      "games. All rules live in one JSON game definition.",
            "overview": schema_doc.get_section("overview"),
            "sections": schema_doc.SECTIONS,
            "engine_flag_safety": ds.list_building_blocks()["safety"],
            "workflow": [
                "Ask the creator what game they want (fantasy, scale, pacing).",
                "list_building_blocks, then start from the closest base definition + fragments.",
                "get_schema(section) before editing a section.",
                "check_definition until ok is true AND blocked is empty; explain errors/warnings in plain language.",
                "save_definition to keep a draft (it appears in the admin Build Game UI).",
                "activate_definition only on the creator's explicit go-ahead.",
                "If roster_changed is true, the creator must click Launch in the admin panel.",
            ],
        }


@mcp.tool()
async def get_engine_guide(ctx: Context) -> dict:
    """Start here. What AstroWebEngine is, the definition's sections, every engine flag
    with whether it can change mid-game, and the recommended workflow."""
    return await _off_loop(_engine_guide, _caller(ctx))


def _schema(caller, section):
    with _session(caller):
        text = schema_doc.get_section(section)
        if text is None:
            raise ValueError(f"Unknown section '{section}'. Valid: {', '.join(schema_doc.SECTIONS)}")
        return {"section": section, "text": text}


@mcp.tool()
async def get_schema(ctx: Context, section: str) -> dict:
    """Field-by-field reference for one definition section, e.g. 'ships' or 'engine'."""
    return await _off_loop(_schema, _caller(ctx), section)


def _building_blocks(caller):
    with _session(caller) as (db, _u, _t):
        out = ds.list_building_blocks()
        out["mods"] = ds.list_mods(db)["mods"]
        return out


@mcp.tool()
async def list_building_blocks(ctx: Context) -> dict:
    """Base definitions, rule fragments, and mods available on this server."""
    return await _off_loop(_building_blocks, _caller(ctx))


def _active_definition(caller, section):
    from game_definition import get_game_definition
    with _session(caller):
        defn = get_game_definition()
        if section is None:
            return defn
        if section not in defn:
            raise ValueError(f"Active definition has no section '{section}'. Has: {', '.join(defn)}")
        return {section: defn[section]}


@mcp.tool()
async def get_active_definition(ctx: Context, section: str | None = None) -> dict:
    """The ruleset running now - all of it, or one top-level section."""
    return await _off_loop(_active_definition, _caller(ctx), section)


# ---------------------------------------------------------------- draft & check

def _check(caller, definition, include_compiled):
    with _session(caller) as (db, _u, _t):
        try:
            result = ds.check_definition(definition, db)
        except ds.DefinitionRejected as exc:
            return {"ok": False, "errors": exc.errors or [exc.message], "warnings": [], "blocked": []}
        if not include_compiled:
            result.pop("definition", None)
        return result


@mcp.tool()
async def check_definition(ctx: Context, definition: dict, include_compiled: bool = False) -> dict:
    """Compile extends, validate, and safety-check a definition. Changes nothing."""
    return await _off_loop(_check, _caller(ctx), definition, include_compiled)


def _save(caller, filename, definition):
    from auth import log_event
    with _session(caller) as (db, user, token_name):
        if not _NAME_RE.match(filename or ""):
            raise ValueError("filename must match [a-z0-9_-]{1,64} (no extension, no folders)")
        name = filename if filename.startswith(AI_PREFIX) else AI_PREFIX + filename
        path = str(data_paths.user_definitions_dir() / f"{name}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
            except (OSError, ValueError):
                existing = None
            owner = (existing.get("meta") or {}).get("saved_by") if isinstance(existing, dict) else None
            if owner != AI_MARKER:
                raise ValueError(f"'{name}.json' already exists and was not created by the AI "
                                 "assistant; choose another filename")
        try:
            result = ds.check_definition(definition, db)
        except ds.DefinitionRejected as exc:
            raise _rejected(exc)
        if not result["ok"]:
            raise ValueError("Not saved - invalid definition:\n" + "\n".join(f"- {e}" for e in result["errors"]))
        draft = dict(definition)
        draft["meta"] = {**(definition.get("meta") or {}), "saved_by": AI_MARKER}
        save_definition_to_file(draft, path)   # atomic; creates the folder
        log_event(db, user.id, "game_definition_draft_mcp",
                  f"Saved draft {name}.json via AI token '{token_name}'")
        db.commit()
        return {"ok": True, "filename": f"{name}.json", "path": path,
                "note": f"Saved as {name}.json in the server's data folder (kept out of git). "
                        "Activate it with activate_definition(filename)."}


@mcp.tool()
async def save_definition(ctx: Context, filename: str, definition: dict) -> dict:
    """Save a draft as ai_<filename>.json in the server's definitions folder (lowercase letters, digits, - and _;
    the ai_ prefix is added unless the name already has it). Never overwrites files this
    assistant did not create. Validates first."""
    return await _off_loop(_save, _caller(ctx), filename, definition)


# ---------------------------------------------------------------- apply

def _activate(caller, filename, definition):
    from game_definition import load_definition_from_file
    with _session(caller) as (db, user, token_name):
        if filename is not None:
            name = filename[:-5] if filename.endswith(".json") else filename
            if not _NAME_RE.match(name):
                raise ValueError("filename must match [a-z0-9_-]{1,64}")
            path = (data_paths.find_definition_file(f"{name}.json")
                    or data_paths.find_definition_file(f"{AI_PREFIX}{name}.json"))
            if path is None:
                raise ValueError(f"No saved definition '{name}.json' or '{AI_PREFIX}{name}.json'")
            definition = load_definition_from_file(str(path))
        try:
            result = ds.apply_definition(definition, db, user, "mcp", actor_label=token_name)
        except ds.DefinitionRejected as exc:
            raise _rejected(exc)
        result["next_step"] = ("The unit/structure roster changed: ask the creator to click Launch "
                               "in the admin panel to start a universe with it. " + _WORKERS_NOTE
                               if result["roster_changed"] else
                               "Live on this server process. " + _WORKERS_NOTE_SHORT)
        return result


@mcp.tool()
async def activate_definition(ctx: Context, filename: str | None = None, definition: dict | None = None) -> dict:
    """Make a ruleset live (same safety gate as the admin Import). Give exactly one of
    filename or definition. filename may include or omit .json; the exact name is tried
    first, then the ai_-prefixed draft name save_definition uses (so the name you saved
    under works). Only on the creator's go-ahead."""
    if (filename is None) == (definition is None):
        raise ValueError("Give exactly one of filename or definition")
    return await _off_loop(_activate, _caller(ctx), filename, definition)


def _list_mods(caller):
    with _session(caller) as (db, _u, _t):
        return ds.list_mods(db)


@mcp.tool()
async def list_mods(ctx: Context) -> dict:
    """Mods on this server, with kind, validity, and whether each is enabled."""
    return await _off_loop(_list_mods, _caller(ctx))


def _apply_mod(caller, mod_id, enabled):
    from auth import log_event
    with _session(caller) as (db, user, token_name):
        try:
            result = ds.set_mod_enabled_and_apply(db, mod_id, enabled, strict=True)
        except ds.DefinitionRejected as exc:
            raise _rejected(exc)
        log_event(db, user.id, "mod_apply_mcp",
                  f"Mod {mod_id} {'enabled' if enabled else 'disabled'} via AI token '{token_name}'")
        db.commit()
        return result


@mcp.tool()
async def apply_mod(ctx: Context, mod_id: str, enabled: bool = True) -> dict:
    """Enable or disable a content mod and hot-swap the ruleset. Only on the creator's go-ahead -
    call preview_mod first and show them what changes. Same safety gate as activate_definition:
    a mod that would change a setup-only engine flag on a running universe is refused (and
    nothing changes); explain the blocked list to the creator."""
    return await _off_loop(_apply_mod, _caller(ctx), mod_id, enabled)


def _preview_mod(caller, mod_id, enabled):
    import mod_planner
    with _session(caller) as (db, _u, _t):
        change = {"enable": [mod_id]} if enabled else {"disable": [mod_id]}
        plan = mod_planner.plan(db, strict=True, **change)
        plan.pop("safety", None)
        return plan


@mcp.tool()
async def preview_mod(ctx: Context, mod_id: str, enabled: bool = True) -> dict:
    """What enabling (or disabling) a content mod would change, without changing anything:
    roster entries added/removed, engine settings that change, errors and blocked changes.
    Show this to the creator before calling apply_mod."""
    return await _off_loop(_preview_mod, _caller(ctx), mod_id, enabled)


# ---------------------------------------------------------------- mounting

class _Guard:
    """Reject requests without a valid admin API token before they reach MCP.

    The token is verified once, off the event loop; the verified actor is left in the
    request state for the tools (see _caller)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            actor = await run_in_threadpool(_verify_actor, _bearer(headers))
            if actor is None:
                await JSONResponse({"error": "Valid admin API token required (Authorization: Bearer awe_...)"},
                                   status_code=401)(scope, receive, send)
                return
            scope.setdefault("state", {})["awe_actor"] = actor
        await self.inner(scope, receive, send)


def mount_mcp(app) -> None:
    """Serve MCP at exactly /mcp on `app` and run its session manager with the app."""
    inner = mcp.streamable_http_app()
    app.router.routes.insert(0, Route("/mcp", _Guard(inner), methods=["GET", "POST", "DELETE"]))
    stack = contextlib.AsyncExitStack()

    @app.on_event("startup")
    async def _start_mcp():
        await stack.enter_async_context(mcp.session_manager.run())

    @app.on_event("shutdown")
    async def _stop_mcp():
        await stack.aclose()
