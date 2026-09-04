"""Rapid fire and shield bouncing.

These two mechanics are what make fleet composition a puzzle rather than a sum:
rapid fire creates hard counters, and bouncing means a cheap hull can be simply
unable to hurt a big one no matter how many you bring. Both are opt-in, so the
first thing each test group pins is that leaving them out changes nothing.

Both were declared in a ruleset once and never implemented - combat.py read
neither key - so these tests assert on damage actually dealt, not on the flags
being present.
"""
import pytest

import combat


def _stats(power=0, armour=100.0, shield=0.0, weapon="laser", rapid_fire=None):
    return {"power": power, "armour": armour, "shield": shield,
            "cost": 10, "weapon": weapon, "rapid_fire": rapid_fire or {}}


# ---------------------------------------------------------------- shield bounce

def test_no_bounce_by_default():
    """A weak shot still chips a shielded target when bouncing is off."""
    dmg = combat._single_attack_damage(1, "laser", 500)
    assert dmg > 0


def test_weak_shot_bounces_off_heavy_shields():
    """Under threshold the shot is absorbed completely, not merely reduced."""
    assert combat._single_attack_damage(1, "laser", 500, bounce_threshold=0.01) == 0.0


def test_shot_at_the_threshold_still_lands():
    """The boundary is exclusive: exactly 1% of shields is not a bounce."""
    assert combat._single_attack_damage(5, "laser", 500, bounce_threshold=0.01) > 0


def test_bounce_ignores_unshielded_targets():
    """No shields means nothing to bounce off, however weak the shot."""
    assert combat._single_attack_damage(1, "laser", 0, bounce_threshold=0.5) > 0


def test_swarm_cannot_grind_down_a_shielded_capital():
    """The point of the mechanic: numbers alone stop being an answer."""
    attackers = {"swarm": 100000.0}
    atk_stats = {"swarm": _stats(power=1)}
    defenders = {"capital": 1.0}
    def_stats = {"capital": _stats(armour=10000.0, shield=500.0)}

    without = combat._apply_fleet_attack(
        dict(attackers), atk_stats, dict(defenders), def_stats, 1.0)
    survivors = dict(defenders)
    with_bounce = combat._apply_fleet_attack(
        dict(attackers), atk_stats, survivors, def_stats, 1.0, bounce_threshold=0.01)

    assert without > 0, "sanity: the swarm hurts it when bouncing is off"
    assert with_bounce == 0.0
    assert survivors["capital"] == pytest.approx(1.0), "capital took no losses"


# ------------------------------------------------------------------ rapid fire

def test_no_rapid_fire_by_default():
    """An empty rapid_fire map must not perturb the baseline."""
    attackers = {"hunter": 10.0}
    defenders_a, defenders_b = {"prey": 100.0}, {"prey": 100.0}
    plain = {"hunter": _stats(power=10)}
    empty_rf = {"hunter": _stats(power=10, rapid_fire={})}
    prey = {"prey": _stats(armour=10.0)}

    a = combat._apply_fleet_attack(dict(attackers), plain, defenders_a, prey, 1.0)
    b = combat._apply_fleet_attack(dict(attackers), empty_rf, defenders_b, prey, 1.0)
    assert a == pytest.approx(b)
    assert defenders_a["prey"] == pytest.approx(defenders_b["prey"])


def test_rapid_fire_kills_more_of_its_prey():
    attackers = {"hunter": 10.0}
    prey_stats = {"prey": _stats(armour=10.0)}

    plain_prey = {"prey": 1000.0}
    combat._apply_fleet_attack(
        dict(attackers), {"hunter": _stats(power=10)}, plain_prey, prey_stats, 1.0)

    rf_prey = {"prey": 1000.0}
    combat._apply_fleet_attack(
        dict(attackers), {"hunter": _stats(power=10, rapid_fire={"prey": 5})},
        rf_prey, prey_stats, 1.0)

    plain_killed = 1000.0 - plain_prey["prey"]
    rf_killed = 1000.0 - rf_prey["prey"]
    assert rf_killed > plain_killed, "rapid fire did nothing"
    assert rf_killed == pytest.approx(plain_killed * 5, rel=0.05)


def test_rapid_fire_only_applies_to_the_named_target():
    """A counter is only a counter against what it counters."""
    attackers = {"hunter": 10.0}
    stats = {"hunter": _stats(power=10, rapid_fire={"prey": 10})}
    unit = _stats(armour=10.0)

    targets = {"other": 1000.0}
    combat._apply_fleet_attack(dict(attackers), stats, targets, {"other": unit}, 1.0)
    baseline = {"other": 1000.0}
    combat._apply_fleet_attack(
        dict(attackers), {"hunter": _stats(power=10)}, baseline, {"other": unit}, 1.0)

    assert targets["other"] == pytest.approx(baseline["other"])


def test_rapid_fire_survives_the_stat_builder():
    """The table has to reach combat from the spec, which is where it broke before."""
    spec = {"attack": 10, "armour": 10, "shield": 0, "cost": 5,
            "weapon": "laser", "rapid_fire": {"prey": 7}}
    built = combat._make_ship_stats(
        spec, wpn_tech=0, arm_tech=0, shd_tech=0, cc_lv=0, tc_lv=0, fleet_bonus=1.0)
    assert built["rapid_fire"] == {"prey": 7}


def test_stat_builder_defaults_rapid_fire_to_empty():
    spec = {"attack": 10, "armour": 10, "shield": 0, "cost": 5, "weapon": "laser"}
    built = combat._make_ship_stats(
        spec, wpn_tech=0, arm_tech=0, shd_tech=0, cc_lv=0, tc_lv=0, fleet_bonus=1.0)
    assert built["rapid_fire"] == {}
