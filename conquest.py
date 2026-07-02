"""Conquest mode — occupation can escalate to permanent base loss (data-driven).

Opt-in via engine flags in a game definition's ``engine`` section (or an admin
``game_config`` override). The default rulesets leave these off, so bases stay
permanent (AE/OGame-style: you can be occupied, never eliminated).

    occupation_zero_production : bool  — an occupied base produces nothing for its owner
    occupation_capture         : bool  — occupation can escalate to permanent capture
    occupation_capture_hours   : num   — continuous-occupation hours before capture (default 6)
    occupation_capture_mode    : str   — "disband" (owner refunded) | "transfer" (occupier gains it)

This is the mechanic that makes the annihilation / last-standing win condition
reachable (see mods/last_standing): with capture on, a player can lose their last
base and be eliminated.
"""
from datetime import datetime

from auth import get_config, get_config_float


def _flag_true(db, key: str) -> bool:
    return str(get_config(db, key, "false")).strip().lower() in ("1", "true", "yes", "on")


def occupation_zero_production(db) -> bool:
    return _flag_true(db, "occupation_zero_production")


def capture_enabled(db) -> bool:
    return _flag_true(db, "occupation_capture")


def capture_hours(db) -> float:
    return max(0.0, get_config_float(db, "occupation_capture_hours", 6.0))


def capture_mode(db) -> str:
    mode = str(get_config(db, "occupation_capture_mode", "disband")).strip().lower()
    return mode if mode in ("disband", "transfer") else "disband"


def last_team_standing_winner(db):
    """Winner when a single team holds every remaining base, else None.

    A *team* is your guild if you belong to one, otherwise you alone. So this is
    "last guild standing" when guilds are in play and "last player standing"
    otherwise. Needs a contested game (>=2 human players took part). Shared by the
    core 'annihilation' win check and the last_standing behavioral mod.
    """
    from models import User, Colony, GuildMember, Guild

    humans = db.query(User).filter(User.is_admin == False, User.is_bot == False).all()
    survivors = [
        u for u in humans
        if db.query(Colony).filter(Colony.user_id == u.id).first() is not None
    ]
    if len(humans) < 2 or not survivors:
        return None

    def _team(user):
        gm = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
        return ("guild", gm.guild_id) if gm else ("solo", user.id)

    teams = {_team(u) for u in survivors}
    if len(teams) != 1:
        return None
    kind, key = next(iter(teams))
    if kind == "guild":
        guild = db.query(Guild).filter(Guild.id == key).first()
        return guild.name if guild else "Guild"
    return next(u.username for u in survivors if u.id == key)


def disband_captured_colony(db, colony) -> float:
    """Remove a captured base and refund its ORIGINAL owner the structure discount
    (mirrors a voluntary abandon). Returns the credit added to the owner's reserve."""
    from models import Building, Defense, ConstructionQueue, ResearchQueue, ShipQueue, Fleet, Commander
    from game_logic import structure_refund_value

    owner = colony.user
    planet = colony.planet
    reserve_gain = 0.0
    for b in db.query(Building).filter(Building.colony_id == colony.id).all():
        if b.level > 0:
            reserve_gain += structure_refund_value(db, "building", b.building_type, b.level, 0)
    for d in db.query(Defense).filter(Defense.colony_id == colony.id).all():
        if d.level > 0:
            reserve_gain += structure_refund_value(db, "defense", d.defense_type, d.level, 0)
    if owner and reserve_gain > 0:
        owner.bases_founded_peak = max(getattr(owner, "bases_founded_peak", 0) or 0, len(owner.colonies))
        owner.base_reserve = (owner.base_reserve or 0.0) + reserve_gain

    db.query(Defense).filter(Defense.colony_id == colony.id).delete()
    db.query(Building).filter(Building.colony_id == colony.id).delete()
    db.query(ConstructionQueue).filter(ConstructionQueue.colony_id == colony.id).delete()
    db.query(ResearchQueue).filter(ResearchQueue.colony_id == colony.id).delete()
    db.query(ShipQueue).filter(ShipQueue.colony_id == colony.id).delete()
    for cmdr in db.query(Commander).filter(Commander.colony_id == colony.id).all():
        cmdr.colony_id = None
        cmdr.is_assigned = False
    for f in db.query(Fleet).filter(Fleet.base_id == colony.id).all():
        f.base_id = None
        f.location_planet_id = planet.id if planet else None
    db.delete(colony)
    return reserve_gain


def transfer_colony(db, colony, new_owner_id: int):
    """Hand a captured base to the occupier — they inherit its buildings/defenses."""
    colony.user_id = new_owner_id
    colony.occupied_by = None
    colony.occupation_start = None
    colony.is_home_base = False
    colony.unrest = 0.0


def process_occupation_capture(db, now: datetime = None) -> list:
    """Escalate occupations held past the threshold into permanent capture.

    Returns a list of event dicts (one per captured base). No-op unless the
    ``occupation_capture`` flag is on, so it's safe to call every income tick.
    """
    if not capture_enabled(db):
        return []
    from models import Colony

    now = now or datetime.utcnow()
    threshold_s = capture_hours(db) * 3600.0
    mode = capture_mode(db)
    events = []

    occupied = db.query(Colony).filter(Colony.occupied_by != None).all()  # noqa: E711
    for colony in occupied:
        start = colony.occupation_start
        if start is None or (now - start).total_seconds() < threshold_s:
            continue
        occupier_id = colony.occupied_by
        owner_id = colony.user_id
        base_name = colony.name

        if mode == "transfer":
            transfer_colony(db, colony, occupier_id)
            event = {"mode": "transfer", "base": base_name, "from_user": owner_id, "to_user": occupier_id}
        else:
            refund = disband_captured_colony(db, colony)
            event = {"mode": "disband", "base": base_name, "owner": owner_id, "refund": round(refund)}
        events.append(event)

        try:
            from auth import log_event
            if mode == "transfer":
                log_event(db, owner_id, "base_captured", f"Lost base '{base_name}' — captured by an occupier")
                log_event(db, occupier_id, "base_captured", f"Captured base '{base_name}'")
            else:
                log_event(db, owner_id, "base_captured",
                          f"Lost base '{base_name}' to prolonged occupation (+{event['refund']} reserve)")
                log_event(db, occupier_id, "base_captured", f"Razed occupied base '{base_name}'")
        except Exception:
            pass

    if events:
        db.flush()
    return events
