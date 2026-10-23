"""Keep each server worker in step with changes made through the others.

uvicorn's --workers N runs N separate processes. Each holds its own copy of the
game_config cache (auth._config_cache) and of the active game definition, so an
admin change or a ruleset activation handled by one worker used to stay
invisible to the rest until a restart.

Every worker calls sync_once() every few seconds (app.py). It reloads the
config cache from the database, tells this worker's connected players about
changed spec settings, and — when the ruleset revision stamp has moved —
reloads the active definition the same way startup does.
"""
import os
import secrets

REVISION_KEY = "active_definition_rev"
SYNC_SECONDS = float(os.environ.get("AWE_SYNC_SECONDS", "5"))

_seen_revision = None
_baseline_taken = False


def new_revision() -> str:
    return secrets.token_hex(8)


def note_local_revision(revision: str):
    """This worker made the change itself: don't reload it on the next sync."""
    global _seen_revision
    _seen_revision = revision


def _reload_definition(db):
    """Same precedence as startup, but a runtime activation outranks the env
    override: persisted selection -> AWE_GAME_DEFINITION -> built-in default."""
    import game_definition as gd
    if gd.restore_persisted_definition(db):
        return
    env_path = os.environ.get("AWE_GAME_DEFINITION")
    if env_path and os.path.exists(env_path):
        gd.set_game_definition(gd.load_definition_from_file(env_path))
    else:
        gd.set_game_definition(gd.build_default_definition())


def sync_once(db) -> dict:
    """Catch up with other workers. Returns {"changed": set(keys), "reloaded": bool}."""
    global _seen_revision, _baseline_taken
    import auth

    before = dict(auth._config_cache)
    auth.refresh_config_cache(db)
    after = auth._config_cache
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if not _baseline_taken:
        changed = set()          # first pass only establishes what this worker has

    for key in changed - {REVISION_KEY}:
        auth._maybe_invalidate_catalog_for_config(key)

    revision = after.get(REVISION_KEY)
    reloaded = False
    if _baseline_taken and revision != _seen_revision:
        _reload_definition(db)
        try:
            from catalog_sync import invalidate_all_online
            invalidate_all_online(["specs"], "game_definition_change")
        except Exception:
            pass
        reloaded = True
    _seen_revision = revision
    _baseline_taken = True
    return {"changed": changed, "reloaded": reloaded}
