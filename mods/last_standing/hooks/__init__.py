"""
Last Standing — reference behavioral mod for AstroWebEngine.

Implements the 'annihilation' win condition (last player with any base wins),
which the core engine intentionally leaves to a mod. This is the victory-logic
counterpart to `battle_logger`: instead of an observer hook, it registers the
`compute_victory` OVERRIDE hook.

It only owns victory when the active win condition is 'annihilation' — for any
other condition it returns None, so the engine's built-in domination/economic
checks still run. Expose `register_hooks(register)` and call
`register("compute_victory", fn)`; the handler receives a HookContext.
"""
import logging

logger = logging.getLogger("awe")


def _compute_victory(ctx):
    """Return {"winner": name} when annihilation is decided, else defer.

    "Last *team* standing": survivors are grouped into teams — your guild if you
    belong to one, otherwise you alone. The game is won when a single team is
    left holding any base. So it's "last guild standing" when guilds are in play
    and "last player standing" otherwise; a guild and a lone player both surviving
    is two teams, so no winner yet.

    Only a *contested* game can be won this way (>=2 players took part). Eliminated
    players keep their account but have no colonies — that's what makes them out.
    """
    if ctx.get("condition") != "annihilation":
        return None  # not our condition — let the engine decide
    db = ctx.get("db")
    if db is None:
        return None

    # The engine now implements 'annihilation' natively (guild-aware last team
    # standing); this mod is a thin example of overriding victory via the
    # compute_victory hook, reusing the same shared helper. Returns
    # {"winner": None} while undecided (it still owns the condition).
    import conquest
    winner = conquest.last_team_standing_winner(db)
    if winner:
        logger.info(f"[mod:last_standing] annihilation victory — {winner}")
    return {"winner": winner}


def register_hooks(register):
    """Entry point the engine calls to wire this mod's hooks."""
    register("compute_victory", _compute_victory)
