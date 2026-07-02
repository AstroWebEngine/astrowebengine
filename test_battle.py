"""
Simulate a fixed combat regression fixture.

Attacker: 1000 FT + 500 CR
  Techs: ARM 20, LAS 20, MIS 20, PLA 15, WD 2, SLD 10, ION 10, PHO 10, DIS 1

Defender: 1000 FT + 10 BS + defenses: IT 10 lvl, OT 10 lvl (photon), DT 10 lvl (disruptor)
  Techs: ARM 20, LAS 20, MIS 20, PLA 15, WD 8, SLD 10, ION 10, PHO 10, DIS 1
  Command Centers: 10
"""
import math, copy
from specs import SHIP_SPECS, ALL_SHIP_TYPES, DEFENSE_SPECS

# These legacy combat fixtures use the generic small_ship_* roster.
from game_definition import set_game_definition, load_definition_from_file
set_game_definition(load_definition_from_file("mods/classic_empire/definition.json"))


def get_weapon_tech(techs, weapon):
    return techs.get(weapon, 0)


def make_ship_stats(ship_type, techs, fleet_bonus, cc_lv=0):
    spec = dict(SHIP_SPECS[ship_type])
    wpn_tech = get_weapon_tech(techs, spec["weapon"])
    arm_tech = techs.get("armour", 0)
    shd_tech = techs.get("shielding", 0)
    power = spec["attack"] * (1 + wpn_tech / 20.0) * (1 + cc_lv / 20.0) * fleet_bonus
    armour = spec["armour"] * (1 + arm_tech / 20.0) * fleet_bonus
    shield = spec.get("shield", 0) * (1 + shd_tech / 20.0)
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"], "name": spec["name"]}


def make_def_stats(def_type, techs, dc_lv=0):
    spec = dict(DEFENSE_SPECS[def_type])
    wpn_tech = get_weapon_tech(techs, spec["weapon"])
    arm_tech = techs.get("armour", 0)
    shd_tech = techs.get("shielding", 0)
    dc_mult = 1 + dc_lv / 100.0
    power = spec["attack"] * (1 + wpn_tech / 20.0) * dc_mult
    armour = spec["armour"] * (1 + arm_tech / 20.0) * dc_mult
    shield = spec.get("shield", 0) * (1 + shd_tech / 20.0) * dc_mult
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"], "name": spec["name"]}


def single_damage(atk_power, atk_weapon, def_shield):
    if def_shield == 0:
        return atk_power
    is_ion = (atk_weapon == "ion")
    if is_ion:
        passthrough, pt_mult = 0.5, 0.5
    else:
        passthrough, pt_mult = 0.01, 0.99
    if def_shield < atk_power:
        return atk_power - def_shield * pt_mult
    else:
        return atk_power * passthrough


SHIP_ORDER = list(SHIP_SPECS.keys())


def get_rounding_type(key, is_defense=False):
    if is_defense:
        return 2
    try:
        idx = SHIP_ORDER.index(key)
    except ValueError:
        return 0
    if idx <= 10:
        return 0
    elif idx <= 13:
        return 1
    else:
        return 2


def round_qty(rt, qty):
    if qty <= 0:
        return 0.0
    if rt == 0:
        return math.ceil(qty)
    elif rt == 1:
        return round(qty, 2)
    else:
        return round(qty, 3)


def attack_fleet(attackers, atk_stat, defenders, def_stat):
    total_dmg = 0.0
    for a_type, a_qty in list(attackers.items()):
        if a_qty <= 0:
            continue
        a_s = atk_stat[a_type]

        dmg_vs = {}
        total_sum = 0.0
        for d_type, d_qty in defenders.items():
            if d_qty <= 0:
                continue
            d_s = def_stat[d_type]
            dmg = single_damage(a_s["power"], a_s["weapon"], d_s["shield"])
            if dmg > 0:
                dmg_vs[d_type] = dmg
                total_sum += dmg
        if total_sum <= 0:
            continue

        overflow = 0.0
        for d_type, dmg in dmg_vs.items():
            d_s = def_stat[d_type]
            if d_s["armour"] <= 0:
                continue
            proportion = dmg / total_sum
            allocation = proportion * a_qty + overflow
            overflow = 0.0
            sd = single_damage(a_s["power"], a_s["weapon"], d_s["shield"])
            if sd <= 0:
                continue
            units_killed = allocation * sd / d_s["armour"]
            total_dmg += allocation * sd
            max_k = defenders[d_type] * d_s["armour"] / sd
            if allocation > max_k:
                defenders[d_type] = 0.0
                overflow += allocation - max_k
            else:
                defenders[d_type] -= units_killed

        # Overflow redistribution
        passes = 10
        while overflow > 1e-6 and passes > 0:
            passes -= 1
            rem = {d: defenders[d] for d in defenders if defenders[d] > 0}
            if not rem:
                break
            nt = 0.0
            ndv = {}
            for d_type in rem:
                d_s = def_stat[d_type]
                d = single_damage(a_s["power"], a_s["weapon"], d_s["shield"])
                if d > 0:
                    ndv[d_type] = d
                    nt += d
            if nt <= 0:
                break
            no = 0.0
            for d_type, d in ndv.items():
                d_s = def_stat[d_type]
                if d_s["armour"] <= 0:
                    continue
                prop = d / nt
                alloc = prop * overflow
                sd = single_damage(a_s["power"], a_s["weapon"], d_s["shield"])
                if sd <= 0:
                    continue
                uk = alloc * sd / d_s["armour"]
                total_dmg += alloc * sd
                mk = defenders[d_type] * d_s["armour"] / sd
                if alloc > mk:
                    defenders[d_type] = 0.0
                    no += alloc - mk
                else:
                    defenders[d_type] -= uk
            overflow = no
    return total_dmg


if __name__ == "__main__":
    # Tech levels
    atk_techs = {"armour": 20, "laser": 20, "missiles": 20, "plasma": 15,
                 "shielding": 10, "ion": 10, "photon": 10, "disruptor": 1}
    def_techs = {"armour": 20, "laser": 20, "missiles": 20, "plasma": 15,
                 "shielding": 10, "ion": 10, "photon": 10, "disruptor": 1}

    # Fleet bonuses (no levi/ds)
    atk_fleet_bonus = 1.0
    def_fleet_bonus = 1.0
    atk_cc = 0
    def_cc = 10  # command centers

    # Attacker units
    atk_ships = {"small_ship_1": 1000.0, "medium_ship_4": 500.0}
    atk_stats = {st: make_ship_stats(st, atk_techs, atk_fleet_bonus, atk_cc)
                 for st in atk_ships}

    # Defender ships
    def_ships = {"small_ship_1": 1000.0, "large_ship_1": 10.0}
    def_ship_stats = {st: make_ship_stats(st, def_techs, def_fleet_bonus, def_cc)
                      for st in def_ships}

    # Defender defenses (level * 5 = units)
    def_defenses = {
        "ion_turrets": 10.0 * 5,
        "photon_turrets": 10.0 * 5,
        "disruptor_turrets": 10.0 * 5,
    }
    def_def_stats = {dt: make_def_stats(dt, def_techs) for dt in def_defenses}

    # Print initial stats
    print("=" * 70)
    print("ATTACKER FORCES")
    print("=" * 70)
    for st, qty in atk_ships.items():
        s = atk_stats[st]
        print(f"  {s['name']:20s}  x{int(qty):>6d}  Pwr:{s['power']:>8.1f}  Arm:{s['armour']:>8.1f}  Shd:{s['shield']:>6.1f}  Wpn:{s['weapon']}")

    print()
    print("=" * 70)
    print("DEFENDER FORCES")
    print("=" * 70)
    for st, qty in def_ships.items():
        s = def_ship_stats[st]
        print(f"  {s['name']:20s}  x{int(qty):>6d}  Pwr:{s['power']:>8.1f}  Arm:{s['armour']:>8.1f}  Shd:{s['shield']:>6.1f}  Wpn:{s['weapon']}")
    for dt, qty in def_defenses.items():
        s = def_def_stats[dt]
        print(f"  {s['name']:20s}  x{int(qty):>6d}  Pwr:{s['power']:>8.1f}  Arm:{s['armour']:>8.1f}  Shd:{s['shield']:>6.1f}  Wpn:{s['weapon']}")

    # Combine defender forces
    all_def = {}
    all_def_stats = {}
    for st, qty in def_ships.items():
        all_def[st] = qty
        all_def_stats[st] = def_ship_stats[st]
    for dt, qty in def_defenses.items():
        all_def[dt] = qty
        all_def_stats[dt] = def_def_stats[dt]

    # Snapshot before
    atk_before = dict(atk_ships)
    def_before = dict(all_def)

    # Simultaneous fire using copies
    def_target = copy.deepcopy(all_def)
    atk_target = copy.deepcopy(atk_ships)

    def_atk_counts = {}
    def_atk_stats_map = {}
    for st, qty in def_ships.items():
        if qty > 0:
            def_atk_counts[st] = qty
            def_atk_stats_map[st] = def_ship_stats[st]
    for dt, qty in def_defenses.items():
        if qty > 0:
            def_atk_counts[dt] = qty
            def_atk_stats_map[dt] = def_def_stats[dt]

    atk_dmg = attack_fleet(atk_before, atk_stats, def_target, all_def_stats)
    def_dmg = attack_fleet(def_atk_counts, def_atk_stats_map, atk_target, atk_stats)

    # Apply rounding
    for st in atk_target:
        rt = get_rounding_type(st)
        atk_target[st] = round_qty(rt, atk_target[st])
    for dt in def_target:
        is_def = dt in DEFENSE_SPECS
        rt = get_rounding_type(dt, is_def)
        def_target[dt] = round_qty(rt, def_target[dt])

    # Defense rebalancing
    orig_cost = sum(def_before.get(dt, 0) * def_def_stats[dt]["cost"]
                    for dt in def_defenses)
    surv_cost = sum(def_target.get(dt, 0) * def_def_stats[dt]["cost"]
                    for dt in def_defenses)
    if orig_cost > 0:
        ratio = surv_cost / orig_cost
        for dt in def_defenses:
            def_target[dt] = round_qty(2, def_before.get(dt, 0) * ratio)

    # Print results
    print()
    print("=" * 70)
    print("RESULTS (single round, simultaneous)")
    print("=" * 70)

    print("\nATTACKER:")
    atk_lost_val = 0
    for st in atk_ships:
        start = atk_before[st]
        end = atk_target[st]
        lost = start - end
        cost = atk_stats[st]["cost"]
        atk_lost_val += lost * cost
        print(f"  {atk_stats[st]['name']:20s}  Start: {start:>8.0f}  End: {end:>8.2f}  Lost: {lost:>8.2f}")

    print("\nDEFENDER SHIPS:")
    def_lost_val = 0
    for st in def_ships:
        start = def_before[st]
        end = def_target.get(st, 0)
        lost = start - end
        cost = def_ship_stats[st]["cost"]
        def_lost_val += lost * cost
        print(f"  {def_ship_stats[st]['name']:20s}  Start: {start:>8.0f}  End: {end:>8.2f}  Lost: {lost:>8.2f}")

    print("\nDEFENDER DEFENSES:")
    def_def_lost_val = 0
    for dt in def_defenses:
        start = def_before[dt]
        end = def_target.get(dt, 0)
        lost = start - end
        cost = def_def_stats[dt]["cost"]
        def_def_lost_val += lost * cost
        print(f"  {def_def_stats[dt]['name']:20s}  Start: {start:>8.0f}  End: {end:>8.3f}  Lost: {lost:>8.3f}")

    total_destroyed = atk_lost_val + def_lost_val + def_def_lost_val
    debris = total_destroyed * 0.4
    loot_each = total_destroyed * 0.2

    # Repair costs
    atk_repair = 0
    for st in atk_ships:
        rt = get_rounding_type(st)
        if rt >= 1:
            qty = atk_target[st]
            frac = qty - math.floor(qty)
            if frac > 1e-6:
                atk_repair += (math.ceil(qty) - qty) * atk_stats[st]["cost"] * 0.5

    def_repair = 0
    for st in def_ships:
        rt = get_rounding_type(st)
        if rt >= 1:
            qty = def_target.get(st, 0)
            frac = qty - math.floor(qty)
            if frac > 1e-6:
                def_repair += (math.ceil(qty) - qty) * def_ship_stats[st]["cost"] * 0.5

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Attacker value lost:   {atk_lost_val:>12.1f}")
    print(f"  Defender value lost:   {def_lost_val + def_def_lost_val:>12.1f}")
    print(f"  Total destroyed:       {total_destroyed:>12.1f}")
    print(f"  Debris:                {debris:>12.1f}")
    print(f"  Combat loot (each):    {loot_each:>12.1f}")
    print(f"  Attacker repair cost:  {atk_repair:>12.1f}")
    print(f"  Defender repair cost:  {def_repair:>12.1f}")
    print(f"  Attacker damage dealt: {atk_dmg:>12.1f}")
    print(f"  Defender damage dealt: {def_dmg:>12.1f}")

    atk_remaining = sum(atk_target.values())
    def_remaining = sum(def_target.values())
    if atk_remaining > def_remaining:
        print(f"\n  >>> ATTACKER WINS (remaining: {atk_remaining:.1f} vs {def_remaining:.1f})")
    elif def_remaining > atk_remaining:
        print(f"\n  >>> DEFENDER WINS (remaining: {def_remaining:.1f} vs {atk_remaining:.1f})")
    else:
        print(f"\n  >>> DRAW")
