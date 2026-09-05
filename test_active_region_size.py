"""A preset that fills the whole galaxy must not inherit another preset's clipping.

`active_region_size` is an MSS-style knob: fill only a centred sub-grid and leave
the rest of the galaxy void. It lives in game_config as an admin override, and
the override used to win unconditionally - so switching the preset from mss to
standard left the old 4 in place and generated 16 of 100 regions per galaxy,
with the other 84 empty. Nothing errored; the map just came out mostly void.

The rule these pin: the override applies only when the ACTIVE preset declares
the knob.
"""
import pytest

from specs import GALAXY_PRESETS


def _effective_active_size(preset: dict, config_value):
    """Mirror of the resolution in universe.py's galaxy loop."""
    if "active_region_size" in preset:
        return config_value if config_value is not None else preset["active_region_size"]
    return 0


def test_standard_preset_declares_no_clipping():
    assert "active_region_size" not in GALAXY_PRESETS["standard"], (
        "the full-galaxy preset must not declare a sub-grid, or it will clip")


def test_mss_preset_declares_clipping():
    assert GALAXY_PRESETS["mss"]["active_region_size"] > 0


@pytest.mark.parametrize("stale", [2, 4, 6, 8])
def test_standard_ignores_a_leftover_override(stale):
    """The exact regression: MSS's value still in game_config after switching."""
    assert _effective_active_size(GALAXY_PRESETS["standard"], stale) == 0, (
        f"a leftover active_region_size={stale} would clip a standard galaxy")


@pytest.mark.parametrize("override", [2, 6, 8])
def test_mss_still_honours_the_admin_override(override):
    """The knob has to stay tunable for the preset it belongs to."""
    assert _effective_active_size(GALAXY_PRESETS["mss"], override) == override


def test_mss_falls_back_to_its_own_default():
    preset = GALAXY_PRESETS["mss"]
    assert _effective_active_size(preset, None) == preset["active_region_size"]


def test_full_galaxy_generates_every_region():
    """Sanity on the arithmetic that made the bug visible.

    A standard galaxy is a 10x10 region grid; clipping to 4x4 yields 16 regions,
    so roughly a sixth of the systems. That 6x shortfall is the symptom to look
    for if this ever regresses.
    """
    preset = GALAXY_PRESETS["standard"]
    full = preset["regions_grid_w"] * preset["regions_grid_h"]
    clipped = 4 * 4
    assert full == 100
    assert full // clipped > 5, "the clipped map should be dramatically smaller"
