#!/usr/bin/env python3
"""
Standalone combat formula tester.
Tests the core formulas from resolve_battle() without needing a DB.
Run: python3 test_combat.py
"""

import math
from decimal import Decimal, ROUND_HALF_UP
from specs import SHIP_SPECS, ALL_SHIP_TYPES, DEFENSE_SPECS

# These legacy combat fixtures use the generic small_ship_* roster.
from game_definition import set_game_definition, load_definition_from_file
set_game_definition(load_definition_from_file("mods/classic_empire/definition.json"))

# ──────────────────────────────────────────────────────────────
# Core formulas extracted from game_logic.py resolve_battle()
# ──────────────────────────────────────────────────────────────

SHIP_ORDER = list(SHIP_SPECS.keys())
DEF_ORDER = list(DEFENSE_SPECS.keys())
ION_WEAPONS = {"ion"}

def get_rounding_type(unit_key, is_defense=False):
    if is_defense:
        return 2
    try:
        idx = SHIP_ORDER.index(unit_key)
    except ValueError:
        return 0
    if idx <= 10:
        return 0
    elif idx <= 13:
        return 1
    else:
        return 2

def round_quantity(rounding_type, qty):
    if qty <= 0:
        return 0.0
    def half_up(value, digits):
        quant = "1" if digits == 0 else "1." + ("0" * digits)
        return float(Decimal(str(value)).quantize(Decimal(quant), rounding=ROUND_HALF_UP))
    if rounding_type == 0:
        return math.ceil(qty)
    elif rounding_type == 1:
        return half_up(qty, 1)
    else:
        return half_up(qty, 3)

def single_attack_damage(attacker_power, attacker_weapon, defender_shield):
    is_ion = attacker_weapon in ION_WEAPONS
    if defender_shield == 0:
        return attacker_power
    elif defender_shield < attacker_power:
        if is_ion:
            return attacker_power - defender_shield * 0.5
        else:
            return attacker_power - defender_shield * 0.99
    else:
        if is_ion:
            return attacker_power * 0.5
        else:
            return attacker_power * 0.01

def make_ship_stats(spec, wpn_tech, arm_tech, shd_tech, cc_lv=0, tc_lv=0, fleet_bonus=1.0):
    power = spec["attack"] * (1 + wpn_tech / 20.0) * (1 + cc_lv / 20.0 + tc_lv / 100.0) * fleet_bonus
    armour = spec["armour"] * (1 + arm_tech / 20.0) * fleet_bonus
    shield = spec.get("shield", 0) * (1 + shd_tech / 20.0)
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"]}

def make_def_stats(spec, wpn_tech, arm_tech, shd_tech, dc_lv=0):
    dc_mult = 1 + dc_lv / 100.0
    power = spec["attack"] * (1 + wpn_tech / 20.0) * dc_mult
    armour = spec["armour"] * (1 + arm_tech / 20.0) * dc_mult
    shield = spec.get("shield", 0) * (1 + shd_tech / 20.0) * dc_mult
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"]}

def apply_fleet_attack(attackers, atk_stat_map, defenders, def_stat_map, exponent=1.0):
    total_damage_dealt = 0.0
    atk_types = [t for t in attackers if attackers[t] > 0]

    for a_type in atk_types:
        a_qty = attackers[a_type]
        if a_qty <= 0:
            continue
        a_stats = atk_stat_map[a_type]
        a_power = a_stats["power"]
        a_weapon = a_stats["weapon"]

        damage_vs = {}
        total_damage_sum = 0.0
        for d_type in defenders:
            if defenders[d_type] <= 0:
                continue
            d_stats = def_stat_map[d_type]
            dmg = single_attack_damage(a_power, a_weapon, d_stats["shield"])
            dmg_exp = dmg ** exponent if dmg > 0 else 0.0
            if dmg_exp > 0:
                damage_vs[d_type] = dmg_exp
                total_damage_sum += dmg_exp

        if total_damage_sum <= 0:
            continue

        overflow = 0.0
        for d_type, dmg_exp in damage_vs.items():
            d_stats = def_stat_map[d_type]
            d_armour = d_stats["armour"]
            if d_armour <= 0:
                continue
            proportion = dmg_exp / total_damage_sum
            allocation = proportion * a_qty + overflow
            overflow = 0.0
            single_dmg = single_attack_damage(a_power, a_weapon, d_stats["shield"])
            if single_dmg <= 0:
                continue
            units_killed = allocation * single_dmg / d_armour
            total_damage_dealt += allocation * single_dmg
            max_killable_qty = defenders[d_type]
            max_killable_alloc = max_killable_qty * d_armour / single_dmg
            if allocation > max_killable_alloc:
                defenders[d_type] = 0.0
                overflow += allocation - max_killable_alloc
            else:
                defenders[d_type] -= units_killed

        max_overflow_passes = 10
        while overflow > 1e-6 and max_overflow_passes > 0:
            max_overflow_passes -= 1
            remaining = {d: defenders[d] for d in defenders if defenders[d] > 0}
            if not remaining:
                break
            new_total = 0.0
            new_dmg_vs = {}
            for d_type in remaining:
                d_stats = def_stat_map[d_type]
                de = single_attack_damage(a_power, a_weapon, d_stats["shield"])
                de_exp = de ** exponent if de > 0 else 0.0
                if de_exp > 0:
                    new_dmg_vs[d_type] = de_exp
                    new_total += de_exp
            if new_total <= 0:
                break
            next_overflow = 0.0
            for d_type, de in new_dmg_vs.items():
                d_stats = def_stat_map[d_type]
                d_armour = d_stats["armour"]
                if d_armour <= 0:
                    continue
                prop = de / new_total
                alloc = prop * overflow
                sd = single_attack_damage(a_power, a_weapon, d_stats["shield"])
                if sd <= 0:
                    continue
                uk = alloc * sd / d_armour
                total_damage_dealt += alloc * sd
                max_k_qty = defenders[d_type]
                max_k_alloc = max_k_qty * d_armour / sd
                if alloc > max_k_alloc:
                    defenders[d_type] = 0.0
                    next_overflow += alloc - max_k_alloc
                else:
                    defenders[d_type] -= uk
            overflow = next_overflow

    return total_damage_dealt


def simulate_battle(atk_ships, def_ships, def_defs, atk_techs, def_techs, atk_cc=0, def_cc=0):
    """
    Run one round of combat simulation.

    atk_ships: dict of {ship_type: quantity}
    def_ships: dict of {ship_type: quantity}
    def_defs: dict of {defense_type: quantity}
    atk_techs: dict of {tech_name: level}
    def_techs: dict of {tech_name: level}
    atk_cc: attacker command center level
    def_cc: defender command center level

    Returns dict with results.
    """
    # Fill in missing ship types
    for st in ALL_SHIP_TYPES:
        atk_ships.setdefault(st, 0.0)
        def_ships.setdefault(st, 0.0)
    for dt in DEFENSE_SPECS:
        def_defs.setdefault(dt, 0.0)

    atk_initial = {st: float(atk_ships[st]) for st in ALL_SHIP_TYPES}
    def_initial = {st: float(def_ships[st]) for st in ALL_SHIP_TYPES}
    def_defs_initial = {dt: float(def_defs[dt]) for dt in DEFENSE_SPECS}

    # Fleet bonuses
    atk_has_cap_1 = atk_ships.get("capital_ship_1", 0) > 0
    atk_has_cap_2 = atk_ships.get("capital_ship_2", 0) > 0
    def_has_cap_1 = def_ships.get("capital_ship_1", 0) > 0
    def_has_cap_2 = def_ships.get("capital_ship_2", 0) > 0

    def get_fb(has_cap_1, has_cap_2):
        if has_cap_2: return 1.1
        elif has_cap_1: return 1.05
        return 1.0

    atk_fb = get_fb(atk_has_cap_1, atk_has_cap_2)
    def_fb = get_fb(def_has_cap_1, def_has_cap_2)

    # Build stats
    def get_wpn_tech(techs, weapon):
        tech_map = {"laser": "laser", "missiles": "missiles", "plasma": "plasma",
                    "ion": "ion", "photon": "photon", "disruptor": "disruptor"}
        t = tech_map.get(weapon, "")
        return techs.get(t, 0) if t else 0

    atk_arm_tech = atk_techs.get("armour", 0)
    atk_shd_tech = atk_techs.get("shielding", 0)
    def_arm_tech = def_techs.get("armour", 0)
    def_shd_tech = def_techs.get("shielding", 0)

    atk_stats = {}
    for st in ALL_SHIP_TYPES:
        spec = SHIP_SPECS[st]
        wt = get_wpn_tech(atk_techs, spec["weapon"])
        atk_stats[st] = make_ship_stats(spec, wt, atk_arm_tech, atk_shd_tech, atk_cc, 0, atk_fb)

    def_stats = {}
    for st in ALL_SHIP_TYPES:
        spec = SHIP_SPECS[st]
        wt = get_wpn_tech(def_techs, spec["weapon"])
        def_stats[st] = make_ship_stats(spec, wt, def_arm_tech, def_shd_tech, def_cc, 0, def_fb)

    turret_stats = {}
    for dt, dspec in DEFENSE_SPECS.items():
        wt = get_wpn_tech(def_techs, dspec["weapon"])
        turret_stats[dt] = make_def_stats(dspec, wt, def_arm_tech, def_shd_tech, 0)

    # Merge defender forces
    combined_def = {}
    combined_def_stats = {}
    for st in ALL_SHIP_TYPES:
        combined_def[st] = float(def_ships[st])
        combined_def_stats[st] = def_stats[st]
    for dt in DEFENSE_SPECS:
        combined_def[dt] = float(def_defs.get(dt, 0))
        combined_def_stats[dt] = turret_stats[dt]

    # Defender attackers (ships + turrets)
    def_atk_counts = {}
    def_atk_stats = {}
    for st in ALL_SHIP_TYPES:
        if def_ships[st] > 0:
            def_atk_counts[st] = float(def_ships[st])
            def_atk_stats[st] = def_stats[st]
    for dt in DEFENSE_SPECS:
        if def_defs.get(dt, 0) > 0:
            def_atk_counts[dt] = float(def_defs[dt])
            def_atk_stats[dt] = turret_stats[dt]

    # Attacker counts (working copy)
    atk_counts = {st: float(atk_ships[st]) for st in ALL_SHIP_TYPES}

    # Snapshot for simultaneous fire
    atk_before = dict(atk_counts)
    def_before = dict(combined_def)

    # Attacker fires
    atk_dmg = apply_fleet_attack(atk_before, atk_stats, combined_def, combined_def_stats)

    # Defender fires
    def_dmg = apply_fleet_attack(def_atk_counts, def_atk_stats, atk_counts, atk_stats)

    # Apply rounding
    for st in ALL_SHIP_TYPES:
        rt = get_rounding_type(st, False)
        atk_counts[st] = round_quantity(rt, atk_counts[st])
        combined_def[st] = round_quantity(rt, combined_def[st])
    for dt in DEFENSE_SPECS:
        combined_def[dt] = round_quantity(2, combined_def[dt])

    # Defense rebalancing
    orig_def_cost = sum(def_defs_initial.get(dt, 0) * DEFENSE_SPECS[dt]["cost"] for dt in DEFENSE_SPECS)
    surv_def_cost = sum(combined_def.get(dt, 0) * DEFENSE_SPECS[dt]["cost"] for dt in DEFENSE_SPECS)
    if orig_def_cost > 0:
        ratio = surv_def_cost / orig_def_cost
        for dt in DEFENSE_SPECS:
            combined_def[dt] = round_quantity(2, def_defs_initial.get(dt, 0) * ratio)

    # Extract results
    atk_final = {st: atk_counts[st] for st in ALL_SHIP_TYPES}
    def_final = {st: combined_def[st] for st in ALL_SHIP_TYPES}
    def_defs_final = {dt: combined_def.get(dt, 0) for dt in DEFENSE_SPECS}

    # Losses
    atk_losses = {st: max(0, atk_initial[st] - atk_final[st]) for st in ALL_SHIP_TYPES}
    def_losses = {st: max(0, def_initial[st] - def_final[st]) for st in ALL_SHIP_TYPES}
    def_def_losses = {dt: max(0, def_defs_initial[dt] - def_defs_final[dt]) for dt in DEFENSE_SPECS}

    # Debris/loot are based on fully destroyed ships only.
    def full_destroyed_count(initial_qty, final_qty, ship_type):
        if initial_qty <= 0:
            return 0
        if ship_type in {"medium_ship_4", "medium_ship_5", "medium_ship_6", "large_ship_1",
                         "large_ship_2", "large_ship_3", "large_ship_4", "capital_ship_1", "capital_ship_2"}:
            surviving_full = math.ceil(final_qty) if final_qty > 0 else 0
        else:
            surviving_full = int(final_qty)
        return max(0, int(initial_qty) - int(surviving_full))

    atk_val_lost = sum(full_destroyed_count(atk_initial[st], atk_final[st], st) * SHIP_SPECS[st]["cost"]
                       for st in ALL_SHIP_TYPES)
    def_val_lost = sum(full_destroyed_count(def_initial[st], def_final[st], st) * SHIP_SPECS[st]["cost"]
                       for st in ALL_SHIP_TYPES)
    def_turret_val_lost = sum(def_def_losses[dt] * DEFENSE_SPECS[dt]["cost"] for dt in DEFENSE_SPECS)
    total_destroyed = atk_val_lost + def_val_lost

    debris = total_destroyed * 0.4
    loot = total_destroyed * 0.2

    return {
        "atk_initial": {k: v for k, v in atk_initial.items() if v > 0},
        "def_initial": {k: v for k, v in def_initial.items() if v > 0},
        "def_defs_initial": {k: v for k, v in def_defs_initial.items() if v > 0},
        "atk_final": {k: v for k, v in atk_final.items() if v > 0},
        "def_final": {k: v for k, v in def_final.items() if v > 0},
        "def_defs_final": {k: v for k, v in def_defs_final.items() if v > 0},
        "atk_losses": {k: v for k, v in atk_losses.items() if v > 0},
        "def_losses": {k: v for k, v in def_losses.items() if v > 0},
        "def_def_losses": {k: v for k, v in def_def_losses.items() if v > 0},
        "atk_value_lost": atk_val_lost,
        "def_value_lost": def_val_lost + def_turret_val_lost,
        "total_destroyed": total_destroyed,
        "debris": debris,
        "loot": loot,
        "atk_damage_dealt": atk_dmg,
        "def_damage_dealt": def_dmg,
    }


def print_result(name, result):
    print(f"\n{'='*60}")
    print(f" {name}")
    print(f"{'='*60}")

    print(f"\n  Attacker initial: {result['atk_initial']}")
    print(f"  Defender initial: {result['def_initial']}")
    if result['def_defs_initial']:
        print(f"  Defender defenses: {result['def_defs_initial']}")

    print(f"\n  Attacker remaining: {result['atk_final']}")
    print(f"  Defender remaining: {result['def_final']}")
    if result['def_defs_final']:
        print(f"  Defender defenses remaining: {result['def_defs_final']}")

    print(f"\n  Attacker losses: {result['atk_losses']}")
    print(f"  Defender losses: {result['def_losses']}")
    if result['def_def_losses']:
        print(f"  Defense losses: {result['def_def_losses']}")

    print(f"\n  Atk value lost:  {result['atk_value_lost']:,.0f}")
    print(f"  Def value lost:  {result['def_value_lost']:,.0f}")
    print(f"  Total destroyed: {result['total_destroyed']:,.0f}")
    print(f"  Debris (40%):    {result['debris']:,.0f}")
    print(f"  Loot (20%):      {result['loot']:,.0f}")
    print(f"  Atk dmg dealt:   {result['atk_damage_dealt']:,.1f}")
    print(f"  Def dmg dealt:   {result['def_damage_dealt']:,.1f}")


# ──────────────────────────────────────────────────────────────
# TESTS
# ──────────────────────────────────────────────────────────────

print("\n" + "="*60)
print(" UNIT FORMULA TESTS")
print("="*60)

# Test 1: Basic damage formula — no shield
dmg = single_attack_damage(10.0, "laser", 0.0)
assert dmg == 10.0, f"No shield: expected 10.0, got {dmg}"
print("OK No shield: damage = power")

# Test 2: Shield < power (non-ion)  →  damage = power - shield*0.99
dmg = single_attack_damage(10.0, "laser", 4.0)
assert dmg == 6.04, f"Shield<Power (laser): expected 6.04, got {dmg}"
print("OK Shield < Power (non-ion): damage = power - shield*0.99")

# Test 2b: Shield < power (ion)  →  damage = power - shield*0.5
dmg = single_attack_damage(10.0, "ion", 4.0)
assert dmg == 8.0, f"Shield<Power (ion): expected 8.0, got {dmg}"
print("OK Shield < Power (ion): damage = power - shield*0.5")

# Test 3: Shield >= power (non-ion)  →  damage = power * 0.01
dmg = single_attack_damage(10.0, "laser", 20.0)
assert dmg == 0.1, f"Shield>=Power (laser): expected 0.1, got {dmg}"
print("OK Shield >= Power (non-ion): damage = power * 0.01")

# Test 4: Shield >= power (ion)  →  damage = power * 0.5
dmg = single_attack_damage(10.0, "ion", 20.0)
assert dmg == 5.0, f"Shield>=Power (ion): expected 5.0, got {dmg}"
print("OK Shield >= Power (ion): damage = power * 0.5 (cross-shield)")

# Test 5: Shield == power (non-ion)
dmg = single_attack_damage(10.0, "plasma", 10.0)
assert dmg == 0.1, f"Shield==Power (plasma): expected 0.1, got {dmg}"
print("OK Shield == Power (non-ion): damage = power * 0.01")

# Test 6: Shield == power (ion)
dmg = single_attack_damage(10.0, "ion", 10.0)
assert dmg == 5.0, f"Shield==Power (ion): expected 5.0, got {dmg}"
print("OK Shield == Power (ion): damage = power * 0.5 (cross-shield)")

# Test 7: Tech scaling
spec = {"attack": 100, "armour": 50, "shield": 10, "cost": 1000, "weapon": "laser"}
stats = make_ship_stats(spec, wpn_tech=10, arm_tech=10, shd_tech=10, cc_lv=0)
assert stats["power"] == 150.0, f"Power with tech 10: expected 150.0, got {stats['power']}"
assert stats["armour"] == 75.0, f"Armour with tech 10: expected 75.0, got {stats['armour']}"
assert stats["shield"] == 15.0, f"Shield with tech 10: expected 15.0, got {stats['shield']}"
print("OK Tech scaling: stat * (1 + tech/20)")

# Test 8: Command center bonus
stats = make_ship_stats(spec, wpn_tech=0, arm_tech=0, shd_tech=0, cc_lv=10)
assert stats["power"] == 150.0, f"CC10 power: expected 150.0, got {stats['power']}"
assert stats["armour"] == 50.0, f"CC10 armour: expected 50.0 (no CC armour bonus), got {stats['armour']}"
print("OK Command center: power * (1 + CC/20)")

# Test 9: Rounding types
assert get_rounding_type("small_ship_1") == 0, "Small Ship 1 should be type 0"
assert get_rounding_type("medium_ship_4") == 1, "Medium Ship 4 should be type 1"
assert get_rounding_type("large_ship_1") == 2, "Large Ship 1 should be type 2"
assert get_rounding_type("barracks", True) == 2, "Defenses should be type 2"
print("OK Rounding types: 0(small), 1(medium), 2(capital/defense)")

# Test 10: Rounding quantities
assert round_quantity(0, 4.1) == 5, f"Type 0 ceil: expected 5, got {round_quantity(0, 4.1)}"
assert round_quantity(1, 4.126) == 4.1, f"Type 1 round .1: expected 4.1, got {round_quantity(1, 4.126)}"
assert round_quantity(2, 4.1264) == 4.126, f"Type 2 round .001: expected 4.126, got {round_quantity(2, 4.1264)}"
print("OK Rounding: ceil/0.1/0.001")


# ──────────────────────────────────────────────────────────────
# SCENARIO TESTS
# ──────────────────────────────────────────────────────────────

print("\n" + "="*60)
print(" SCENARIO TESTS")
print("="*60)

# Scenario 1: Simple small_ship_1 vs small_ship_1, no tech
result = simulate_battle(
    atk_ships={"small_ship_1": 100},
    def_ships={"small_ship_1": 100},
    def_defs={},
    atk_techs={},
    def_techs={},
)
print_result("100 Small Ship 1 vs 100 Small Ship 1 (no tech)", result)
# Symmetric: each side does 100 * 2 = 200 damage, 200/2 = 100 kills each → all dead
assert result["atk_final"].get("small_ship_1", 0) == 0, "All atk small_ship_1 should die"
assert result["def_final"].get("small_ship_1", 0) == 0, "All def small_ship_1 should die"
print("OK Symmetric fighter battle: mutual destruction")

# Scenario 2: Small Ship 1 vs shielded medium_ship_4 (test shield absorption)
result = simulate_battle(
    atk_ships={"small_ship_1": 1000},
    def_ships={"medium_ship_4": 10},
    def_defs={},
    atk_techs={},
    def_techs={},
)
print_result("1000 Small Ship 1 vs 10 Medium Ship 4 (no tech)", result)
# Small Ship 1 power=2, Medium Ship 4 shield=2 → shield >= power → 2*0.01 = 0.02 per fighter
# 1000 small_ship_1 * 0.02 = 20 total damage. Medium Ship 4 armour = 24. 20/24 = 0.83 killed → 10-9.17 remaining
# Medium Ship 4 fires: 10 * 24 power vs small_ship_1 (no shield) = 240 dmg. 240/2 armour = 120 small_ship_1 killed.
print(f"  (Small Ship 1 should struggle vs shielded medium_ship_4 - 0.02 dmg each)")

# Scenario 3: Medium Ship 2 vs Medium Ship 4 (test ion cross-shield)
result = simulate_battle(
    atk_ships={"medium_ship_2": 100},
    def_ships={"medium_ship_4": 100},
    def_defs={},
    atk_techs={},
    def_techs={},
)
print_result("100 Medium Ship 2 vs 100 Medium Ship 4 (ion cross-shield)", result)
# IF power=14, cruiser shield=2: shield < power and ion → 14 - 2*0.5 = 13 per IF
# 100 * 13 = 1300 damage vs cruiser armour 24 = 54.17 killed
print(f"  (Medium Ship 2 should deal good damage despite cruiser shields)")

# Scenario 4: Small Ship 1 vs Large Ship 1 (ion cross-shield on defense)
result = simulate_battle(
    atk_ships={"small_ship_1": 10000},
    def_ships={"large_ship_1": 1},
    def_defs={},
    atk_techs={},
    def_techs={},
)
print_result("10000 Small Ship 1 vs 1 Large Ship 1", result)
# Small Ship 1 power=2, BS shield=12 → shield >= power → 2*0.01 = 0.02 per fighter
# 10000 * 0.02 = 200 damage. BS armour = 128. 200/128 = 1.56 killed → BS destroyed
# BS fires: 1 * 160 (ion weapon) vs small_ship_1 (no shield) = 160 damage. 160/2 = 80 small_ship_1 killed
print(f"  (10k small_ship_1 overwhelm 1 BS despite shields)")

# Scenario 5: Large Ship 1 vs Large Ship 1 (ion vs ion shielded)
result = simulate_battle(
    atk_ships={"large_ship_1": 10},
    def_ships={"large_ship_1": 10},
    def_defs={},
    atk_techs={"ion": 10, "armour": 10, "shielding": 10},
    def_techs={"ion": 10, "armour": 10, "shielding": 10},
)
print_result("10 BS vs 10 BS (tech 10 ion/arm/shd)", result)
# BS power = 160 * (1 + 10/20) = 240. BS armour = 128 * 1.5 = 192. BS shield = 12 * 1.5 = 18
# Shield(18) < Power(240) and ion → 240 - 18*0.5 = 231 damage per BS
# 10 * 231 = 2310 total. 2310 / 192 = 12.03 → all 10 killed
print(f"  (Symmetric with tech: should be mutual destruction)")

# Scenario 6: With defenses
result = simulate_battle(
    atk_ships={"medium_ship_4": 50},
    def_ships={},
    def_defs={"laser_turrets": 100, "missile_turrets": 50},
    atk_techs={"plasma": 5, "armour": 5, "shielding": 5},
    def_techs={"laser": 5, "missiles": 5, "armour": 5, "shielding": 5},
)
print_result("50 Medium Ship 4 vs 100 LT + 50 MT (tech 5)", result)

# Scenario 7: With capital flagship bonus
result = simulate_battle(
    atk_ships={"capital_ship_1": 1, "large_ship_1": 10},
    def_ships={"large_ship_1": 15},
    def_defs={},
    atk_techs={"ion": 10, "photon": 10, "armour": 10, "shielding": 10},
    def_techs={"ion": 10, "armour": 10, "shielding": 10},
)
print_result("1 flagship + 10 BS vs 15 BS (flagship bonus test)", result)

# Scenario 8: Debris validation — ensure 40%
result = simulate_battle(
    atk_ships={"small_ship_1": 500},
    def_ships={"small_ship_1": 500},
    def_defs={},
    atk_techs={},
    def_techs={},
)
total_val = result["total_destroyed"]
debris = result["debris"]
if total_val > 0:
    ratio = debris / total_val
    assert abs(ratio - 0.4) < 0.001, f"Debris ratio: expected 0.4, got {ratio}"
    print(f"\nOK Debris ratio confirmed: {ratio:.4f} (expected 0.4)")

# Scenario 9: Command center test
result_no_cc = simulate_battle(
    atk_ships={"medium_ship_4": 10},
    def_ships={"medium_ship_4": 10},
    def_defs={},
    atk_techs={}, def_techs={},
    atk_cc=0, def_cc=0,
)
result_cc = simulate_battle(
    atk_ships={"medium_ship_4": 10},
    def_ships={"medium_ship_4": 10},
    def_defs={},
    atk_techs={}, def_techs={},
    atk_cc=10, def_cc=0,
)
print(f"\n  CC test: atk dmg without CC = {result_no_cc['atk_damage_dealt']:.1f}")
print(f"  CC test: atk dmg with CC10  = {result_cc['atk_damage_dealt']:.1f}")
assert result_cc['atk_damage_dealt'] > result_no_cc['atk_damage_dealt'], "CC should increase damage"
print("OK Command center increases attacker damage")

print("\n" + "="*60)
print(" ALL TESTS PASSED!")
print("="*60)
