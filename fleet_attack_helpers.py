import json

from fastapi import HTTPException

from models import Colony, Fleet, Planet
from auth import get_config, get_effective_defense_spec, get_effective_ship_spec
from game_logic import calc_player_level, resolve_battle, _fleet_total_ships, _fleet_value, get_building_level, _fleet_is_empty
from specs import ALL_SHIP_TYPES, DEFENSE_SPECS

def _get_attack_location(fleet, db):
    colony = db.query(Colony).filter(Colony.id == fleet.base_id).first() if fleet.base_id else None
    planet = None
    if colony and colony.planet:
        planet = colony.planet
    elif fleet.location_planet_id:
        planet = db.query(Planet).filter(Planet.id == fleet.location_planet_id).first()
    if not colony and not planet:
        raise HTTPException(400, "Fleet has no current location")
    location_name = colony.name if colony else (planet.name if planet else "Open Space")
    coords = planet.name if planet else ""
    return colony, planet, location_name, coords


def _build_attack_targets(fleet, user, db, game_speed, colony, planet, location_name, coords):
    from models import GuildMember

    my_gm = db.query(GuildMember).filter(GuildMember.user_id == user.id).first()
    my_guild_id = my_gm.guild_id if my_gm else None

    targets = []
    attacker_level = calc_player_level(user, db, game_speed)
    newbie_hours = int(get_config(db, "newbie_protection_hours", "168") or 168)
    base_owner_meta = None
    base_owner_fleet_value = 0

    if colony and colony.user_id != user.id:
        defender = colony.user
        defender_level = calc_player_level(defender, db, game_speed)
        defender_fleets = db.query(Fleet).filter(
            Fleet.base_id == colony.id,
            Fleet.user_id == defender.id,
            Fleet.is_moving == False,
        ).all()
        base_owner_fleet_value = sum(_fleet_value(df, db) for df in defender_fleets if _fleet_total_ships(df) > 0)
        warnings = []
        if defender.created_at and (datetime.utcnow() - defender.created_at).total_seconds() < newbie_hours * 3600:
            warnings.append("Defender is under newbie protection.")
        if user.created_at and (datetime.utcnow() - user.created_at).total_seconds() < newbie_hours * 3600:
            if defender_level > attacker_level * 1.5:
                warnings.append("Attacking this target will break your newbie protection for 48 hours.")
        atk_total_cc = sum(get_building_level(c, "command_centers") for c in user.colonies)
        atk_current_occ = db.query(Colony).filter(Colony.occupied_by == user.id).count()
        if atk_current_occ >= atk_total_cc:
            warnings.append(f"No Command Center capacity ({atk_current_occ}/{atk_total_cc}).")

        can_attack = True
        reason = ""
        def_gm = db.query(GuildMember).filter(GuildMember.user_id == defender.id).first()
        if my_guild_id and def_gm and def_gm.guild_id == my_guild_id:
            can_attack = False
            reason = "Cannot attack a member of your own guild."

        base_owner_meta = {
            "player": defender.username,
            "player_id": defender.id,
            "level": round(defender_level, 2),
            "defense_pct": round((colony.defense_effectiveness if colony.defense_effectiveness is not None else 1.0) * 100, 2),
            "can_attack": can_attack,
            "reason": reason,
            "warnings": warnings,
        }

    if colony:
        location_fleets = db.query(Fleet).filter(
            Fleet.base_id == colony.id,
            Fleet.is_moving == False,
        ).all()
    else:
        location_fleets = db.query(Fleet).filter(
            Fleet.location_planet_id == fleet.location_planet_id,
            Fleet.base_id == None,
            Fleet.is_moving == False,
        ).all()

    for enemy_fleet in location_fleets:
        if enemy_fleet.user_id == user.id:
            continue
        if _fleet_total_ships(enemy_fleet) == 0:
            continue
        defender = enemy_fleet.user
        can_attack = True
        reason = ""
        warnings = []
        defense_pct = None
        uses_defenses = False
        def_gm = db.query(GuildMember).filter(GuildMember.user_id == defender.id).first()
        if my_guild_id and def_gm and def_gm.guild_id == my_guild_id:
            can_attack = False
            reason = "Cannot attack a member of your own guild."
        if base_owner_meta and colony and defender.id == colony.user_id:
            can_attack = base_owner_meta["can_attack"]
            reason = base_owner_meta["reason"]
            warnings = list(base_owner_meta["warnings"])
            defense_pct = base_owner_meta["defense_pct"]
            uses_defenses = True
        attack_mode = "base" if uses_defenses else "fleet"
        attack_label = "Attack Base Defenses & Fleet" if uses_defenses else "Attack Fleet"
        targets.append({
            "target_type": "fleet",
            "list_section": "row",
            "fleet_name": enemy_fleet.name,
            "player": defender.username,
            "player_id": defender.id,
            "fleet_id": enemy_fleet.id,
            "level": round(calc_player_level(defender, db, game_speed), 2),
            "size": round(_fleet_value(enemy_fleet, db)),
            "attack_label": attack_label,
            "attack_mode": attack_mode,
            "defense_pct": defense_pct,
            "uses_defenses": uses_defenses,
            "can_attack": can_attack,
            "reason": reason,
            "warnings": warnings,
        })

    if base_owner_meta:
        targets.append({
            "target_type": "base",
            "list_section": "action",
            "fleet_name": colony.name,
            "player": base_owner_meta["player"],
            "player_id": base_owner_meta["player_id"],
            "fleet_id": None,
            "level": base_owner_meta["level"],
            "size": round(base_owner_fleet_value),
            "attack_label": "Attack Base Defenses & Fleet",
            "attack_mode": "base",
            "defense_pct": base_owner_meta["defense_pct"],
            "uses_defenses": True,
            "can_attack": base_owner_meta["can_attack"],
            "reason": base_owner_meta["reason"],
            "warnings": list(base_owner_meta["warnings"]),
        })
        targets.append({
            "target_type": "base",
            "list_section": "action",
            "fleet_name": colony.name,
            "player": base_owner_meta["player"],
            "player_id": base_owner_meta["player_id"],
            "fleet_id": None,
            "level": base_owner_meta["level"],
            "size": round(base_owner_fleet_value),
            "attack_label": "Attack Base Defenses & Fleet & Conquer Base in case of a Successful Attack",
            "attack_mode": "conquer",
            "defense_pct": base_owner_meta["defense_pct"],
            "uses_defenses": True,
            "can_attack": base_owner_meta["can_attack"],
            "reason": base_owner_meta["reason"],
            "warnings": list(base_owner_meta["warnings"]),
        })

        # Moon "destroy" mission: offered only when the target is a moon,
        # the engine enables moon destruction, and the fleet has a capable ship.
        from game_definition import get_game_definition
        from auth import ships_with_capability
        _eng = (get_game_definition() or {}).get("engine", {}) or {}
        if (_eng.get("moon_destruction") and planet is not None
                and (planet.orbit_row or 0) > 0
                and any(fleet.get_ship_count(k) for k in ships_with_capability(db, "can_destroy_moons"))):
            targets.append({
                "target_type": "base",
                "list_section": "action",
                "fleet_name": colony.name,
                "player": base_owner_meta["player"],
                "player_id": base_owner_meta["player_id"],
                "fleet_id": None,
                "level": base_owner_meta["level"],
                "size": round(base_owner_fleet_value),
                "attack_label": "Attack & Attempt Moon Destruction in case of a Successful Attack",
                "attack_mode": "destroy_moon",
                "defense_pct": base_owner_meta["defense_pct"],
                "uses_defenses": True,
                "can_attack": base_owner_meta["can_attack"],
                "reason": base_owner_meta["reason"],
                "warnings": list(base_owner_meta["warnings"]),
            })

    targets.sort(key=lambda t: (
        0 if t.get("list_section") == "row" else 1,
        0 if t.get("uses_defenses") else 1,
        0 if t["target_type"] == "fleet" else 1,
        0 if t.get("attack_mode") != "conquer" else 1,
        -t["size"],
        t["player"].lower(),
        t["fleet_name"].lower(),
    ))
    return {
        "location": location_name,
        "coords": coords,
        "fleet_name": fleet.name,
        "attacker_level": round(attacker_level, 2),
        "targets": targets,
    }


def _find_attack_target(targets, target_user_id=None, target_fleet_id=None, attack_mode=None):
    def _matches(target):
        if attack_mode is not None and target.get("attack_mode") != attack_mode:
            return False
        if target_user_id is not None and target.get("player_id") != target_user_id:
            return False
        return True

    if target_fleet_id is not None:
        for target in targets:
            if target.get("fleet_id") == target_fleet_id and _matches(target):
                return target
    if target_user_id is not None:
        matching_targets = [target for target in targets if _matches(target)]
        if attack_mode in ("base", "conquer"):
            for target in matching_targets:
                if target.get("list_section") == "action":
                    return target
        for target in matching_targets:
            if target.get("fleet_id") is None:
                return target
        if len(matching_targets) == 1:
            return matching_targets[0]
    elif attack_mode is not None:
        matching_targets = [target for target in targets if _matches(target)]
        if len(matching_targets) == 1:
            return matching_targets[0]
    return None


def _effective_ship_counts_for_preview(fleet):
    try:
        damage_state = json.loads(fleet.ship_damage or "{}")
    except Exception:
        damage_state = {}
    counts = {}
    for st in ALL_SHIP_TYPES:
        whole = float(fleet.get_ship_count(st) if hasattr(fleet, "get_ship_count") else (getattr(fleet, st, 0) or 0))
        if st in damage_state and whole > 0:
            whole = (whole - 1) + float(damage_state[st])
        counts[st] = whole
    return counts


def _format_preview_value(value):
    try:
        number = float(value)
    except Exception:
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _build_preview_ship_rows(ship_counts, ship_stats, eff_ship_specs):
    rows = []
    for st in ALL_SHIP_TYPES:
        count = ship_counts.get(st, 0.0)
        if count <= 0:
            continue
        stats = ship_stats[st]
        rows.append({
            "unit": eff_ship_specs[st].get("name", st.replace("_", " ").title()),
            "count": _format_preview_value(count),
            "attack": _format_preview_value(stats["power"]),
            "armour": _format_preview_value(stats["armour"]),
            "shield": _format_preview_value(stats["shield"]),
        })
    return rows


def _build_preview_defense_rows(defense_counts, turret_stats, eff_def_specs):
    rows = []
    for dt in DEFENSE_SPECS:
        count = defense_counts.get(dt, 0.0)
        if count <= 0:
            continue
        stats = turret_stats[dt]
        rows.append({
            "unit": eff_def_specs[dt].get("name", dt.replace("_", " ").title()),
            "count": _format_preview_value(count),
            "attack": _format_preview_value(stats["power"]),
            "armour": _format_preview_value(stats["armour"]),
            "shield": _format_preview_value(stats["shield"]),
        })
    return rows


def _build_attack_confirm_preview(fleet, attacker_user, defender_user, colony, planet, location_name, coords, game_speed, db, selected_target):
    from combat import _get_fleet_bonus, _make_def_stats, _make_ship_stats
    from game_logic import evaluate_tech_bonuses, get_commander_bonus, get_commander_level_at_base

    eff_ship_specs = {st: get_effective_ship_spec(db, st) for st in ALL_SHIP_TYPES}
    eff_def_specs = {dt: get_effective_defense_spec(db, dt) for dt in DEFENSE_SPECS}

    atk_counts = _effective_ship_counts_for_preview(fleet)
    atk_tech = evaluate_tech_bonuses(attacker_user, db)
    atk_weapon_mults = atk_tech["weapon_power"]
    atk_combat_mults = atk_tech["combat_stats"]
    atk_cc_lv = 0
    if fleet.base_id:
        atk_home = db.query(Colony).filter(Colony.id == fleet.base_id).first()
        if atk_home:
            atk_cc_lv = get_building_level(atk_home, "command_centers")
    atk_tc_lv = get_commander_level_at_base(db, fleet.base_id, "tactical") if fleet.base_id else 0
    tc_bonus = get_commander_bonus(db, "tactical")
    atk_fleet_bonus = _get_fleet_bonus(atk_counts, eff_ship_specs)
    atk_stats = {
        st: _make_ship_stats(
            eff_ship_specs[st], 0, 0, 0,
            atk_cc_lv, atk_tc_lv, atk_fleet_bonus, tc_bonus,
            weapon_power_mults=atk_weapon_mults,
            combat_stat_mults=atk_combat_mults,
        )
        for st in ALL_SHIP_TYPES
    }

    def_counts = {st: 0.0 for st in ALL_SHIP_TYPES}
    def_defenses = {dt: 0.0 for dt in DEFENSE_SPECS}
    def_fleet_name = selected_target.get("fleet_name") or "Defensive Force"
    def_cc_lv = 0
    def_tc_lv = 0
    def_dc_lv = 0
    def_start_defenses = None
    def_command_centers = None
    def_base_name = None
    selected_attack_mode = selected_target.get("attack_mode") or (
        "base" if selected_target.get("target_type") == "base" else "fleet"
    )
    includes_defenses = bool(colony and defender_user.id == colony.user_id and selected_attack_mode in ("base", "conquer"))

    if selected_attack_mode in ("base", "conquer"):
        defender_fleets = db.query(Fleet).filter(
            Fleet.base_id == colony.id,
            Fleet.user_id == defender_user.id,
            Fleet.is_moving == False,
        ).all()
        for defender_fleet in defender_fleets:
            fleet_counts = _effective_ship_counts_for_preview(defender_fleet)
            for st in ALL_SHIP_TYPES:
                def_counts[st] += fleet_counts[st]
        def_eff = getattr(colony, "defense_effectiveness", 1.0) or 1.0
        for defense in colony.defenses:
            def_defenses[defense.defense_type] = float(defense.level) * def_eff
        if selected_target.get("target_type") == "fleet":
            def_fleet_name = selected_target.get("fleet_name") or "Base Defenses & Fleet"
        else:
            def_fleet_name = "Base Defenses & Fleet"
        def_cc_lv = get_building_level(colony, "command_centers")
        def_tc_lv = get_commander_level_at_base(db, colony.id, "tactical")
        def_dc_lv = get_commander_level_at_base(db, colony.id, "defense")
        def_start_defenses = _format_preview_value(def_eff * 100)
        def_command_centers = def_cc_lv
        def_base_name = colony.name
    else:
        if colony:
            defender_fleet = db.query(Fleet).filter(
                Fleet.id == selected_target.get("fleet_id"),
                Fleet.user_id == defender_user.id,
                Fleet.base_id == colony.id,
                Fleet.is_moving == False,
            ).first()
        else:
            defender_fleet = db.query(Fleet).filter(
                Fleet.id == selected_target.get("fleet_id"),
                Fleet.user_id == defender_user.id,
                Fleet.location_planet_id == fleet.location_planet_id,
                Fleet.base_id == None,
                Fleet.is_moving == False,
            ).first()
        if not defender_fleet:
            raise HTTPException(404, "Target fleet not found")
        def_counts = _effective_ship_counts_for_preview(defender_fleet)
        def_fleet_name = defender_fleet.name
        if includes_defenses:
            def_eff = getattr(colony, "defense_effectiveness", 1.0) or 1.0
            for defense in colony.defenses:
                def_defenses[defense.defense_type] = float(defense.level) * def_eff
            def_cc_lv = get_building_level(colony, "command_centers")
            def_tc_lv = get_commander_level_at_base(db, colony.id, "tactical")
            def_dc_lv = get_commander_level_at_base(db, colony.id, "defense")
            def_start_defenses = _format_preview_value(def_eff * 100)
            def_command_centers = def_cc_lv
            def_base_name = colony.name

    def_tech = evaluate_tech_bonuses(defender_user, db)
    def_weapon_mults = def_tech["weapon_power"]
    def_combat_mults = def_tech["combat_stats"]
    def_fleet_bonus = _get_fleet_bonus(def_counts, eff_ship_specs)
    def_stats = {
        st: _make_ship_stats(
            eff_ship_specs[st], 0, 0, 0,
            def_cc_lv, def_tc_lv, def_fleet_bonus, tc_bonus,
            weapon_power_mults=def_weapon_mults,
            combat_stat_mults=def_combat_mults,
        )
        for st in ALL_SHIP_TYPES
    }
    dc_bonus = get_commander_bonus(db, "defense")
    turret_stats = {
        dt: _make_def_stats(
            eff_def_specs[dt], 0, 0, 0, def_dc_lv, dc_bonus,
            weapon_power_mults=def_weapon_mults,
            combat_stat_mults=def_combat_mults,
        )
        for dt in DEFENSE_SPECS
    }

    return {
        "location": location_name,
        "coords": coords,
        "server": get_config(db, "game_name", "AstroWebEngine"),
        "target_type": selected_target.get("target_type"),
        "attack_mode": selected_attack_mode,
        "warnings": selected_target.get("warnings", []),
        "attacker": {
            "name": attacker_user.username,
            "level": _format_preview_value(round(calc_player_level(attacker_user, db, game_speed), 2)),
            "fleet_name": fleet.name,
        },
        "defender": {
            "name": defender_user.username,
            "level": _format_preview_value(round(calc_player_level(defender_user, db, game_speed), 2)),
            "fleet_name": def_fleet_name,
            "base_name": def_base_name,
            "defense_pct": def_start_defenses,
            "command_centers": def_command_centers,
        },
        "attacker_forces": _build_preview_ship_rows(atk_counts, atk_stats, eff_ship_specs),
        "defender_forces": _build_preview_ship_rows(def_counts, def_stats, eff_ship_specs),
        "defender_defenses": _build_preview_defense_rows(def_defenses, turret_stats, eff_def_specs),
    }


def _resolve_fleet_battle(attacker_fleet, attacker_user, defender_user, location_colony, game_speed, db, target_fleet_id=None):
    """Fleet-vs-fleet combat WITHOUT base defenses.
    Used when attacking a player's fleets that are not at their own base."""
    from combat import _fleet_ship_counts

    # Find defender fleets at this location
    if location_colony:
        q = db.query(Fleet).filter(
            Fleet.base_id == location_colony.id,
            Fleet.is_moving == False,
            Fleet.user_id == defender_user.id
        )
        defender_planet_id = None
    else:
        # At uncolonized planet
        defender_planet_id = attacker_fleet.location_planet_id
        q = db.query(Fleet).filter(
            Fleet.location_planet_id == attacker_fleet.location_planet_id,
            Fleet.base_id == None,
            Fleet.is_moving == False,
            Fleet.user_id == defender_user.id
        )

    if target_fleet_id:
        q = q.filter(Fleet.id == target_fleet_id)

    def_fleets = q.all()

    if not def_fleets:
        return {"result": "no_defenders", "report": "No defending fleets found."}

    # Sum defender ships
    def_total = {}
    for st in ALL_SHIP_TYPES:
        def_total[st] = sum(f.get_ship_count(st) for f in def_fleets)
    if sum(def_total.values()) == 0:
        return {"result": "no_defenders", "report": "No defending ships."}

    # Use the full combat engine but with a dummy colony that has no defenses
    # We create a temporary object that looks like a colony but has empty defenses
    # Use a dummy colony with no defenses so combat engine skips turrets
    # but still finds defender fleets at this location
    class _DummyColony:
        def __init__(self):
            self.id = location_colony.id if location_colony else None
            self.defenses = []
            self.defense_effectiveness = 0.0
            self.name = location_colony.name if location_colony else "Open Space"
            self.user = defender_user
            self.occupied_by = None
            self.unrest = 0
            # Planet for debris â€” use actual planet if available
            if location_colony:
                self.planet = location_colony.planet
            elif attacker_fleet.location_planet_id:
                self.planet = db.query(Planet).filter(Planet.id == attacker_fleet.location_planet_id).first()
            else:
                self.planet = None

    report = resolve_battle(
        attacker_fleet,
        attacker_user,
        _DummyColony(),
        defender_user,
        game_speed,
        db,
        target_fleet_id=target_fleet_id,
        defender_planet_id=defender_planet_id,
    )

    # Combat engine already distributes losses to defender fleets and cleans up
    for f in def_fleets:
        if _fleet_is_empty(f):
            db.delete(f)

    return report


