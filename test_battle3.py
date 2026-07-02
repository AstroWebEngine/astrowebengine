"""Validate combat engine against a fixed battle report fixture.

Fixture timestamp: 2 Mar 2026, 15:29:51
Attacker: level 27.86 - 377 FT + 200 CR
Defender: level 23.19 - defenses only at 32.72%
  IT=1.64, PT=3.28, DT=1.64, DS=1.64, CC=1

Expected result: ATK wins, 263 FT + 190.9 CR remaining, all defenses destroyed.
Total destroyed: 2370 (9 CR + 114 FT)
"""
import math, copy
from specs import SHIP_SPECS, DEFENSE_SPECS

# These legacy combat fixtures use the generic small_ship_* roster.
from game_definition import set_game_definition, load_definition_from_file
set_game_definition(load_definition_from_file("mods/classic_empire/definition.json"))

DAMAGE_EXPONENT = 0.85


def make_ship_stats(ship_type, techs, fleet_bonus=1.0, cc_lv=0):
    spec = SHIP_SPECS[ship_type]
    wpn_tech = techs.get(spec["weapon"], 0)
    arm_tech = techs.get("armour", 0)
    shd_tech = techs.get("shielding", 0)
    power = spec["attack"] * (1 + wpn_tech / 20.0) * (1 + cc_lv / 20.0) * fleet_bonus
    armour = spec["armour"] * (1 + arm_tech / 20.0) * fleet_bonus
    shield = spec.get("shield", 0) * (1 + shd_tech / 20.0)
    return {"power": power, "armour": armour, "shield": shield,
            "cost": spec["cost"], "weapon": spec["weapon"], "name": spec["name"]}


def make_def_stats(def_type, techs, dc_lv=0):
    spec = DEFENSE_SPECS[def_type]
    wpn_tech = techs.get(spec["weapon"], 0)
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
        return round(qty, 1)
    else:
        return round(qty, 3)


def attack_fleet(attackers, atk_stat, defenders, def_stat):
    total_dmg = 0.0
    for a_type, a_qty in list(attackers.items()):
        if a_qty <= 0:
            continue
        a_s = atk_stat[a_type]

        # Calculate damage vs each defender type, raised to exponent for allocation
        dmg_vs = {}
        total_sum = 0.0
        for d_type, d_qty in defenders.items():
            if d_qty <= 0:
                continue
            d_s = def_stat[d_type]
            dmg = single_damage(a_s["power"], a_s["weapon"], d_s["shield"])
            if dmg > 0:
                weighted = dmg ** DAMAGE_EXPONENT
                dmg_vs[d_type] = (dmg, weighted)
                total_sum += weighted
        if total_sum <= 0:
            continue

        overflow = 0.0
        for d_type, (raw_dmg, weighted) in dmg_vs.items():
            d_s = def_stat[d_type]
            if d_s["armour"] <= 0:
                continue
            proportion = weighted / total_sum
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
                    w = d ** DAMAGE_EXPONENT
                    ndv[d_type] = (d, w)
                    nt += w
            if nt <= 0:
                break
            no = 0.0
            for d_type, (raw_d, w) in ndv.items():
                d_s = def_stat[d_type]
                if d_s["armour"] <= 0:
                    continue
                prop = w / nt
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
    # Attacker techs (derived from battle report stats)
    atk_techs = {"laser": 18, "plasma": 14, "armour": 21, "shielding": 12}

    # Defender techs (derived from defense stats, CC=1 only affects ships not defenses)
    def_techs = {"ion": 9, "photon": 1, "disruptor": 1, "armour": 18, "shielding": 11}

    # Attacker forces
    atk_ships = {"small_ship_1": 377.0, "medium_ship_4": 200.0}
    atk_stats = {st: make_ship_stats(st, atk_techs) for st in atk_ships}

    # Defender forces (defenses only, at 32.72% of original)
    # Original: IT=5, PT=10, DT=5, DS=5 -> 32.72% gives these quantities
    def_defenses = {
        "ion_turrets": 1.64,
        "photon_turrets": 3.28,
        "disruptor_turrets": 1.64,
        "deflection_shields": 1.64,
    }
    def_def_stats = {dt: make_def_stats(dt, def_techs) for dt in def_defenses}

    # Verify stats match battle report
    print("STAT VERIFICATION (should match battle report):")
    print(f"  FT: atk={atk_stats['small_ship_1']['power']:.1f} arm={atk_stats['small_ship_1']['armour']:.1f} shd={atk_stats['small_ship_1']['shield']:.1f}")
    print(f"  CR: atk={atk_stats['medium_ship_4']['power']:.1f} arm={atk_stats['medium_ship_4']['armour']:.1f} shd={atk_stats['medium_ship_4']['shield']:.1f}")
    for dt in def_defenses:
        s = def_def_stats[dt]
        print(f"  {s['name']:20s}: atk={s['power']:.1f} arm={s['armour']:.1f} shd={s['shield']:.1f}")

    print(f"\n  Expected: FT(3.8/4.1/0) CR(40.8/49.2/3.2)")
    print(f"  Expected: IT(58/76/3.1) PT(84/152/9.3) DT(336/608/12.4) DS(2.9/1216/24.8)")

    # Combine defender forces
    all_def = dict(def_defenses)
    all_def_stats = dict(def_def_stats)

    # Snapshot
    atk_before = dict(atk_ships)
    def_before = dict(all_def)

    # Simultaneous fire
    def_target = copy.deepcopy(all_def)
    atk_target = copy.deepcopy(atk_ships)

    # Defender attacks attacker (defenses fire at ships)
    def_atk_counts = {dt: qty for dt, qty in def_defenses.items() if qty > 0}
    def_atk_stats_map = {dt: def_def_stats[dt] for dt in def_atk_counts}

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
    if orig_cost > 0 and surv_cost > 0:
        ratio = surv_cost / orig_cost
        for dt in def_defenses:
            def_target[dt] = round_qty(2, def_before.get(dt, 0) * ratio)

    # Results
    print("\n" + "=" * 70)
    print("SIMULATION RESULTS vs BATTLE REPORT")
    print("=" * 70)

    print("\nATTACKER:")
    expected_atk = {"small_ship_1": 263, "medium_ship_4": 190.9}
    for st in atk_ships:
        start = atk_ships[st]
        end = atk_target[st]
        exp = expected_atk[st]
        match = "OK" if abs(end - exp) < 0.5 else f"DIFF={end - exp:+.2f}"
        print(f"  {atk_stats[st]['name']:12s}  Start:{start:>6.0f}  Got:{end:>8.2f}  Expected:{exp:>8.1f}  [{match}]")

    print("\nDEFENDER DEFENSES:")
    for dt in def_defenses:
        start = def_before[dt]
        end = def_target.get(dt, 0)
        print(f"  {def_def_stats[dt]['name']:20s}  Start:{start:>6.2f}  End:{end:>8.3f}  (expected: 0)")

    # Cost calculation
    ft_lost = atk_ships["small_ship_1"] - atk_target["small_ship_1"]
    cr_full_lost = int(atk_ships["medium_ship_4"]) - math.ceil(atk_target["medium_ship_4"])
    # Only fully destroyed ships count toward "cost destroyed".
    # 190.9 means 190 full + 1 damaged -> 200 - 191 = 9 destroyed
    cr_destroyed = int(atk_ships["medium_ship_4"]) - math.ceil(atk_target["medium_ship_4"])
    total_destroyed = ft_lost * 5 + cr_destroyed * 200
    print(f"\n  FT lost: {ft_lost:.0f} (expected: 114)")
    print(f"  CR destroyed: {cr_destroyed} (expected: 9)")
    print(f"  Total cost destroyed: {total_destroyed:.0f} (expected: 2370)")

    debris = total_destroyed * 0.4
    loot_each = total_destroyed * 0.2
    print(f"  Debris: {debris:.0f} (expected: 948)")
    print(f"  Loot each: {loot_each:.0f} (expected: 474)")
