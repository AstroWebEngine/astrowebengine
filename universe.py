import math
import random
import logging
from sqlalchemy import text as import_text
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import engine, ModelBase, SessionLocal, _is_sqlite
from models import Cluster, Galaxy, Region, StarSystem, Planet, Colony, Building, Defense, Research, Fleet, User, GalaxyLink, Wormhole
from specs import PLANET_TYPE_STATS, ORBIT_MODIFIERS, get_astro_category, BUILDING_SPECS, RESEARCH_SPECS, SERVER_NAMES, DEFENSE_SPECS, GALAXY_PRESETS
from galaxy_templates import GALAXY_TEMPLATES
from galaxy_layout_templates import GALAXY_SYSTEM_LAYOUTS

from auth import get_config, get_config_int, get_config_float, set_config, init_default_configs, log_event, get_effective_astro_spec, is_astro_disabled, get_all_astro_specs
from game_logic import _record_region_snapshot

logger = logging.getLogger("awe")

# ======================== UNIVERSE GENERATION ========================

# ── Star Types & Weights (derived from reference data analysis) ──
# 10 star types with observed frequency weights
AWE_STAR_TYPES = {
    "orange":      20.8,
    "red":         14.5,
    "yellow":      14.4,
    "white":       13.3,
    "blue":        13.3,
    "white-dwarf": 10.6,
    "red-giant":    4.6,
    "blue-giant":   3.9,
    "super-giant":  2.7,
    "neutron":      2.0,
}

# Average astros per system by star type (from reference data)
AWE_ASTROS_PER_STAR = {
    "orange": 4.29, "red": 4.08, "yellow": 4.38, "white": 3.98, "blue": 3.95,
    "white-dwarf": 4.23, "red-giant": 4.32, "blue-giant": 4.31, "super-giant": 3.40, "neutron": 5.20,
}

# ── Orbit Distribution ──
# How often each orbit slot (1-5) appears
AWE_ORBIT_WEIGHTS = {1: 33.3, 2: 26.8, 3: 19.4, 4: 13.3, 5: 7.1}

# ── Moon/Satellite Count Distribution (by primary type) ──
# From reference dataset analysis
AWE_MOON_COUNT_WEIGHTS = {0: 42.0, 1: 40.0, 2: 14.0, 3: 5.0}  # fallback
AWE_SAT_COUNT_BY_PRIMARY = {
    "planet":        {0: 44.9, 1: 35.1, 2: 14.6, 3: 5.4},
    "gas_giant":     {0: 40.0, 1: 48.0, 2: 11.6, 3: 0.4},
    "asteroid_belt": {0: 36.3, 1: 36.0, 2: 14.6, 3: 13.1},
}

# ── Primary Body Types (Row 0) ──
# Some internal terrain keys represent non-colonizable body types; the rest are planet terrain types.
AWE_PRIMARY_WEIGHTS = {
    "gas_giant":     33.9,
    "asteroid_belt": 19.2,
    "craters":        6.9,
    "earthly":        6.5,
    "toxic":          5.8,
    "arid":           5.8,
    "rocky":          4.4,
    "radioactive":    4.3,
    "metallic":       3.5,
    "volcanic":       2.6,
    "magma":          1.6,
    "gaia":           1.6,
    "glacial":        1.3,
    "tundra":         1.3,
    "crystalline":    0.7,
    "oceanic":        0.6,
}

# ── Moon/Asteroid Types (Row 1-3) ──
# Moon terrain varies significantly by parent type (from reference data analysis, n=3176 moons)
AWE_MOON_WEIGHTS_GAS_GIANT = {
    "craters":      17.6,
    "arid":         16.8,
    "glacial":      15.2,
    "toxic":        14.4,
    "radioactive":   7.7,
    "metallic":      6.5,
    "volcanic":      6.0,
    "tundra":        4.4,
    "rocky":         4.0,
    "earthly":       3.4,
    "magma":         1.9,
    "crystalline":   1.8,
    "oceanic":       0.3,
    "gaia":          0.0,
}
AWE_MOON_WEIGHTS_PLANET = {
    "toxic":        17.6,
    "rocky":        14.8,
    "craters":      14.2,
    "radioactive":   9.2,
    "arid":          6.9,
    "metallic":      6.2,
    "oceanic":       5.5,
    "volcanic":      5.2,
    "tundra":        4.7,
    "crystalline":   3.9,
    "earthly":       3.4,
    "glacial":       3.3,
    "magma":         2.6,
    "gaia":          2.3,
}
# Aggregate weights (used for enabled_set filtering)
AWE_MOON_WEIGHTS = {
    "toxic":        16.4,
    "craters":      15.5,
    "rocky":        10.8,
    "arid":         10.6,
    "radioactive":   8.7,
    "glacial":       7.8,
    "metallic":      6.4,
    "volcanic":      5.5,
    "tundra":        4.6,
    "earthly":       3.4,
    "oceanic":       3.6,
    "crystalline":   3.1,
    "magma":         2.4,
    "gaia":          1.4,
}

def _weighted_choice(weights_dict, enabled_set=None):
    """Pick a key from a {key: weight} dict using weighted random selection.
    If enabled_set provided, only pick from enabled keys."""
    if enabled_set:
        items = [(k, v) for k, v in weights_dict.items() if k in enabled_set]
    else:
        items = list(weights_dict.items())
    if not items:
        return list(weights_dict.keys())[0]  # fallback
    keys, weights = zip(*items)
    return random.choices(keys, weights=weights, k=1)[0]

def _pick_star_type():
    """Pick a star type using reference frequency weights."""
    return _weighted_choice(AWE_STAR_TYPES)

def _pick_num_orbits(star_type):
    """Pick how many orbits (1-5) a system has, influenced by star type.
    Reference data: 2307 primary bodies across 745 systems = 3.10 avg orbits/system.
    With 1.83 astros/orbit average, this gives ~5.65 astros/system."""
    avg = AWE_ASTROS_PER_STAR.get(star_type, 4.2)
    # Center at 3.1 orbits (from reference data), shift by star type
    # Global avg astros = ~4.2, so star-specific offset adjusts from there
    avg_orbits = 3.1 + (avg - 4.2) * 0.5
    avg_orbits = max(1.8, min(4.5, avg_orbits))
    # Use wide gaussian — systems range from 1-5 orbits
    weights = []
    for n in range(1, 6):
        w = math.exp(-0.4 * (n - avg_orbits) ** 2)
        weights.append(w)
    return random.choices(range(1, 6), weights=weights, k=1)[0]

def _pick_which_orbits(num_orbits):
    """Pick which orbit slots (from 1-5) are populated, using reference orbit weights."""
    orbit_slots = [1, 2, 3, 4, 5]
    weights = [AWE_ORBIT_WEIGHTS[o] for o in orbit_slots]
    # Sample without replacement, weighted
    chosen = []
    available = list(zip(orbit_slots, weights))
    for _ in range(min(num_orbits, 5)):
        if not available:
            break
        slots, wts = zip(*available)
        pick = random.choices(slots, weights=wts, k=1)[0]
        chosen.append(pick)
        available = [(s, w) for s, w in available if s != pick]
    return sorted(chosen)

def _pick_moon_count(primary_type="planet"):
    """Pick how many satellites (0-3) an orbit has, varying by primary type.
    Large non-colonizable bodies favor 1 moon; belt bodies have more satellites overall."""
    weights = AWE_SAT_COUNT_BY_PRIMARY.get(primary_type, AWE_MOON_COUNT_WEIGHTS)
    return _weighted_choice(weights)

def _pick_primary_type(enabled_types):
    """Pick a primary body type (Row 0) using reference frequency weights.
    Returns (terrain_type, body_type) tuple.
    - gas_giant -> terrain="gas_giant", body="Gas Giant"
    - asteroid_belt -> terrain="asteroid_belt", body="Asteroid"
    - everything else -> terrain=name, body="Planet"
    """
    primary = _weighted_choice(AWE_PRIMARY_WEIGHTS, enabled_types if enabled_types else None)
    if primary == "gas_giant":
        return ("gas_giant", "Gas Giant")
    elif primary == "asteroid_belt":
        return ("asteroid_belt", "Asteroid")
    else:
        return (primary, "Planet")

def _pick_moon_type(enabled_types, parent_type="planet"):
    """Pick a moon/asteroid type (Row 1-3) using reference frequency weights.
    parent_type: 'planet' or 'gas_giant' — determines terrain distribution.
    Returns (terrain_type, body_type) tuple."""
    if parent_type == "gas_giant":
        weights = AWE_MOON_WEIGHTS_GAS_GIANT
    else:
        weights = AWE_MOON_WEIGHTS_PLANET
    moon = _weighted_choice(weights, enabled_types if enabled_types else None)
    return (moon, "Moon")


# ── Average Radial Density Profile ──
# From reference galaxy analysis, normalized 0-1, center at (4.5, 4.5)
# Used as base density; spiral arms are overlaid as perturbation
AWE_RADIAL_DENSITY = [
    [0.000, 0.008, 0.048, 0.133, 0.204, 0.183, 0.134, 0.036, 0.008, 0.000],
    [0.004, 0.062, 0.174, 0.201, 0.168, 0.191, 0.221, 0.204, 0.061, 0.003],
    [0.028, 0.185, 0.190, 0.250, 0.321, 0.348, 0.336, 0.244, 0.220, 0.014],
    [0.089, 0.248, 0.320, 0.304, 0.284, 0.428, 0.381, 0.266, 0.274, 0.073],
    [0.137, 0.284, 0.256, 0.290, 0.775, 1.000, 0.587, 0.305, 0.338, 0.143],
    [0.144, 0.302, 0.244, 0.401, 0.832, 0.984, 0.530, 0.184, 0.365, 0.098],
    [0.074, 0.298, 0.214, 0.409, 0.360, 0.367, 0.310, 0.352, 0.198, 0.064],
    [0.019, 0.167, 0.268, 0.232, 0.311, 0.323, 0.298, 0.160, 0.153, 0.015],
    [0.002, 0.070, 0.152, 0.218, 0.193, 0.166, 0.182, 0.197, 0.066, 0.000],
    [0.000, 0.007, 0.036, 0.104, 0.168, 0.184, 0.118, 0.037, 0.000, 0.000],
]

def _interpolate_density_table(table: list, gx_fine: float, gy_fine: float) -> float:
    """Bilinear interpolation of a 10x10 density table.
    gx_fine, gy_fine are in 0-9 space (mapping to the 10x10 density table)."""
    x0 = int(math.floor(gx_fine))
    y0 = int(math.floor(gy_fine))
    x1 = min(x0 + 1, 9)
    y1 = min(y0 + 1, 9)
    x0 = max(x0, 0)
    y0 = max(y0, 0)
    fx = gx_fine - math.floor(gx_fine)
    fy = gy_fine - math.floor(gy_fine)
    v00 = table[y0][x0]
    v10 = table[y0][x1]
    v01 = table[y1][x0]
    v11 = table[y1][x1]
    return v00 * (1 - fx) * (1 - fy) + v10 * fx * (1 - fy) + v01 * (1 - fx) * fy + v11 * fx * fy


def _interpolate_density(gx_fine: float, gy_fine: float) -> float:
    return _interpolate_density_table(AWE_RADIAL_DENSITY, gx_fine, gy_fine)


def _rotate_density_table(table: list, quarter_turns: int) -> list:
    out = [row[:] for row in table]
    for _ in range(quarter_turns % 4):
        out = [list(row) for row in zip(*out[::-1])]
    return out


def _pick_density_template(galaxy_seed: int) -> list:
    rng = random.Random(galaxy_seed)
    template = [row[:] for row in GALAXY_TEMPLATES[galaxy_seed % len(GALAXY_TEMPLATES)]]
    template = _rotate_density_table(template, rng.randrange(4))
    if rng.random() < 0.5:
        template = [row[::-1] for row in template]
    if rng.random() < 0.5:
        template = template[::-1]
    return template


def _pick_real_system_layout(galaxy_seed: int):
    """Pick one precomputed galaxy system layout as a template."""
    if not GALAXY_SYSTEM_LAYOUTS:
        return None, None
    rng = random.Random(galaxy_seed)
    name, points = GALAXY_SYSTEM_LAYOUTS[rng.randrange(len(GALAXY_SYSTEM_LAYOUTS))]
    return name, points


def _build_value_noise_100(rng: random.Random, control_size: int = 11) -> list:
    controls = [[rng.uniform(0.82, 1.18) for _ in range(control_size)] for _ in range(control_size)]
    size = 100
    scale = (control_size - 1) / (size - 1)
    noise = [[1.0] * size for _ in range(size)]
    for y in range(size):
        gy = y * scale
        y0 = int(math.floor(gy))
        y1 = min(y0 + 1, control_size - 1)
        fy = gy - y0
        for x in range(size):
            gx = x * scale
            x0 = int(math.floor(gx))
            x1 = min(x0 + 1, control_size - 1)
            fx = gx - x0
            v00 = controls[y0][x0]
            v10 = controls[y0][x1]
            v01 = controls[y1][x0]
            v11 = controls[y1][x1]
            noise[y][x] = (
                v00 * (1 - fx) * (1 - fy)
                + v10 * fx * (1 - fy)
                + v01 * (1 - fx) * fy
                + v11 * fx * fy
            )
    return noise


def _build_procedural_spiral_100(galaxy_seed: int, num_arms: int = 2) -> list:
    """Neutral, purely procedural galaxy silhouette: a 100x100 density mask from a
    parametric spiral, using NO bundled templates. This is the public
    `galaxy_shape` default; the reference-derived templates are an opt-in preset.
    Ported from the standalone spiral in test_spiral.py.
    """
    grid_w = grid_h = 100
    rng = random.Random(galaxy_seed)
    rotation_offset = rng.uniform(0, 2 * math.pi)
    tightness = rng.uniform(0.14, 0.22)
    if galaxy_seed % 2 == 1:
        tightness = -tightness
    arm_width = rng.uniform(0.18, 0.26)
    bulge_radius = rng.uniform(0.12, 0.18)
    bulge_strength = rng.uniform(0.8, 1.0)
    arm_strength = rng.uniform(0.8, 1.0)
    scatter_strength = rng.uniform(0.03, 0.07)
    galaxy_scale = rng.uniform(1.05, 1.2)
    cx, cy = 0.5, 0.5
    mask = [[0.0] * grid_w for _ in range(grid_h)]
    for y in range(grid_h):
        for x in range(grid_w):
            nx = (x + 0.5) / grid_w
            ny = (y + 0.5) / grid_h
            dx = (nx - cx) * galaxy_scale
            dy = (ny - cy) * galaxy_scale
            r = math.sqrt(dx * dx + dy * dy)
            theta = math.atan2(dy, dx)
            if r > 0.65:
                continue
            edge_fade = 1.0
            if r > 0.45:
                edge_fade = max(0.0, 1.0 - (r - 0.45) / 0.20)
            bulge = bulge_strength * math.exp(-0.5 * (r / bulge_radius) ** 2)
            arm_density = 0.0
            for arm in range(num_arms):
                arm_offset = arm * (2 * math.pi / num_arms)
                if r > 0.01:
                    spiral_theta = (1.0 / tightness) * math.log(max(r, 0.01) / 0.02)
                    spiral_theta += arm_offset + rotation_offset
                    delta = (theta - spiral_theta) % (2 * math.pi)
                    if delta > math.pi:
                        delta -= 2 * math.pi
                    linear_dist = abs(delta) * r
                    arm_density += arm_strength * math.exp(-0.5 * (linear_dist / arm_width) ** 2)
                    radial_falloff = math.exp(-0.6 * r)
                    arm_density *= (0.3 + 0.7 * radial_falloff)
            scatter = scatter_strength * math.exp(-4.0 * r)
            density = (bulge + arm_density + scatter) * edge_fade
            density *= rng.uniform(0.85, 1.15)
            mask[y][x] = max(0.0, density)
    max_val = max((max(row) for row in mask), default=0.0)
    if max_val > 0:
        mask = [[v / max_val for v in row] for row in mask]
    return mask


def _build_spiral_mask_100(galaxy_seed: int = 0, num_arms: int = 2) -> list:
    """Build a 100x100 density mask for the full galaxy grid.

    The coarse 10x10 galaxy silhouette comes from the bundled density templates,
    then gets upsampled to 100x100 and shaped by a corrected double-arm spiral
    overlay. This keeps the intended two-arm galaxy shape while avoiding the
    old over-smoothed ring look.
    """
    rng = random.Random(galaxy_seed)
    template = _pick_density_template(galaxy_seed)
    low_freq_noise = _build_value_noise_100(rng)
    rotation_offset = rng.uniform(0, 2 * math.pi)
    tightness = rng.uniform(0.18, 0.24)
    if rng.random() < 0.5:
        tightness = -tightness
    arm_width = rng.uniform(0.48, 0.64)
    inter_arm_floor = rng.uniform(0.12, 0.22)
    core_radius = rng.uniform(0.12, 0.16)
    size = 100
    mask = [[0.0] * size for _ in range(size)]
    cx, cy = 49.5, 49.5

    for y in range(size):
        for x in range(size):
            gx_fine = x / 10.0
            gy_fine = y / 10.0
            base_density = _interpolate_density_table(template, gx_fine, gy_fine)

            if base_density < 0.001:
                continue

            dx = (x - cx) / size
            dy = (y - cy) / size
            r = math.sqrt(dx * dx + dy * dy)
            theta = math.atan2(dy, dx)

            arm_proximity = 0.0
            if r > 0.01:
                for arm in range(num_arms):
                    arm_offset = arm * (2 * math.pi / num_arms)
                    spiral_theta = (1.0 / tightness) * math.log(max(r, 0.01) / 0.018)
                    spiral_theta += arm_offset + rotation_offset
                    delta = theta - spiral_theta
                    delta = delta % (2 * math.pi)
                    if delta > math.pi:
                        delta -= 2 * math.pi
                    scaled_delta = abs(delta) / max(0.18, r * arm_width)
                    arm_proximity = max(arm_proximity, math.exp(-0.5 * scaled_delta * scaled_delta))

            bulge_factor = 1.0 if r <= core_radius else max(0.0, 1.0 - (r - core_radius) / 0.08)
            spiral_multiplier = inter_arm_floor + (1.0 - inter_arm_floor) * arm_proximity

            # Preserve the reference silhouette, but emphasize the intended
            # two-arm structure everywhere outside the central bulge.
            density = base_density * (bulge_factor + (1.0 - bulge_factor) * spiral_multiplier)
            density *= low_freq_noise[y][x]
            density *= rng.uniform(0.96, 1.04)

            mask[y][x] = max(0.0, density)

    # Normalize to 0.0-1.0
    max_val = max(max(row) for row in mask)
    if max_val > 0:
        mask = [[v / max_val for v in row] for row in mask]

    # Keep different templates in the same overall density band so one seed
    # doesn't explode into an overfull ring while another ends up too sparse.
    target_total_density = 950.0
    current_total_density = sum(sum(row) for row in mask)
    if current_total_density > 0:
        scale = target_total_density / current_total_density
        mask = [[min(1.0, v * scale) for v in row] for row in mask]

    return mask

def _generate_galaxy_content(db, galaxy, regions_per, max_systems_per, pmin, pmax,
                              enabled_types=None, cached_specs=None, universe_seed=0,
                              active_cols=None, active_rows=None):
    """Fill a single galaxy with regions, systems, and planets using spiral density.
    Orbit-first generation model:
      1. Pick orbits for each system (1-5, weighted by reference distribution)
      2. For each orbit: pick a primary body (Row 0) - Planet, Gas Giant, or Asteroid Belt
      3. For each orbit: roll for 0-3 moons (Row 1-3)
      4. Pick moon types from reference moon distribution
    Uses batched inserts and cached specs for performance."""
    grid_w = galaxy.regions_grid_w
    grid_h = galaxy.regions_grid_h
    actual_regions = min(regions_per, grid_w * grid_h)
    gal_name = galaxy.name

    # Build enabled-type sets for primary and moon picking
    # enabled_types is a list of terrain keys from specs; we also need gas_giant and asteroid_belt
    enabled_primary_set = set()
    enabled_moon_set = set()
    if enabled_types:
        for t in enabled_types:
            # Map terrain types to primary weight keys
            if t in AWE_PRIMARY_WEIGHTS:
                enabled_primary_set.add(t)
            if t in AWE_MOON_WEIGHTS:
                enabled_moon_set.add(t)
        # Always allow gas_giant and asteroid_belt as primaries (they map to terrains)
        enabled_primary_set.add("gas_giant")
        enabled_primary_set.add("asteroid_belt")
    else:
        enabled_primary_set = None
        enabled_moon_set = None

    # Batch-insert all regions at once, then systems, then planets
    region_rows = []
    for ri in range(actual_regions):
        gx = ri % grid_w
        gy = ri // grid_w
        # Region naming: RC where R=row, C=column (e.g. "46" = row 4, col 6)
        region_rows.append({"name": f"{gy}{gx}", "galaxy_id": galaxy.id, "grid_x": gx, "grid_y": gy})

    if region_rows:
        db.execute(Region.__table__.insert(), region_rows)
        db.flush()

    # Fetch back all regions with their IDs
    regions = db.query(Region).filter(Region.galaxy_id == galaxy.id).order_by(Region.id).all()

    # Combine universe_seed + galaxy.id so each regeneration AND each galaxy is unique
    galaxy_seed = universe_seed * 100 + galaxy.id
    # Per-galaxy SHAPE is a setup-only engine option. Default is the neutral
    # procedural spiral (no bundled templates); "templates" opts into the
    # reference-derived layout/density presets.
    shape = (get_config(db, "galaxy_shape", "procedural_spiral") or "procedural_spiral").strip()
    if shape == "templates":
        layout_name, layout_points = _pick_real_system_layout(galaxy_seed)
        density_mask_100 = None if layout_points else _build_spiral_mask_100(galaxy_seed=galaxy_seed)
    else:
        layout_name, layout_points = None, None
        density_mask_100 = _build_procedural_spiral_100(galaxy_seed)

    # Seed the global random per-galaxy so fallback procedural placement remains deterministic
    rng_galaxy = random.Random(galaxy_seed)

    # Build region lookup by (gx, gy)
    region_by_grid = {}
    for ri, region in enumerate(regions):
        gx = ri % grid_w
        gy = ri // grid_w
        region_by_grid[(gx, gy)] = region

    # ── Sample systems from the 100x100 density grid ──
    # Each point (x, y) in the 100x100 grid maps to:
    #   region (x//10, y//10), system position (y%10 * 10 + x%10) formatted as "YX"
    # A point becomes a system with probability proportional to its density.
    # Calibrated threshold to produce ~784 systems per galaxy.
    DENSITY_THRESHOLD = 0.04  # minimum density to place a system
    PLACE_PROBABILITY = 1.10  # base probability multiplier (tuned for ~784 systems)

    system_rows = []
    region_system_info = []
    # Collect systems grouped by region
    region_systems_map = {}  # (gx, gy) -> [(sys_pos, star_type), ...]

    if layout_points:
        logger.info(f"[universe] Galaxy {gal_name} using layout template {layout_name}")
        for packed in layout_points:
            fy = packed // 100
            fx = packed % 100
            rgx, rgy = fx // 10, fy // 10

            if active_cols is not None and rgx not in active_cols:
                continue
            if active_rows is not None and rgy not in active_rows:
                continue

            local_x = fx % 10
            local_y = fy % 10
            sys_pos = local_y * 10 + local_x
            key = (rgx, rgy)
            st = _pick_star_type()
            region_systems_map.setdefault(key, []).append((sys_pos, st))
    else:
        for fy in range(100):
            for fx in range(100):
                rgx, rgy = fx // 10, fy // 10

                # Skip non-active regions (MSS: only generate content in center 4x4)
                if active_cols is not None and rgx not in active_cols:
                    continue
                if active_rows is not None and rgy not in active_rows:
                    continue

                density = density_mask_100[fy][fx]
                if density < DENSITY_THRESHOLD:
                    continue

                # Probability of placing a system at this point
                prob = density ** 1.2 * PLACE_PROBABILITY
                if rng_galaxy.random() > prob:
                    continue

                # System position within region: local_y * 10 + local_x -> "YX"
                local_x = fx % 10
                local_y = fy % 10
                sys_pos = local_y * 10 + local_x
                key = (rgx, rgy)

                # Avoid duplicate positions in the same region
                existing = region_systems_map.get(key, [])
                if any(p == sys_pos for p, _ in existing):
                    continue

                st = _pick_star_type()
                region_systems_map.setdefault(key, []).append((sys_pos, st))

    # Build system rows and region_system_info from the sampled points
    for (rgx, rgy), sys_list in sorted(region_systems_map.items()):
        region = region_by_grid.get((rgx, rgy))
        if not region:
            continue
        region_num = f"{rgy}{rgx}"
        sys_infos = []
        for sys_pos, st in sorted(sys_list):
            system_rows.append({"name": f"{sys_pos:02d}", "region_id": region.id, "star_type": st})
            sys_infos.append((sys_pos, st))
        region_system_info.append((region, region_num, sys_infos))

    if system_rows:
        db.execute(StarSystem.__table__.insert(), system_rows)
        db.flush()

    # Fetch systems per region in bulk
    all_systems = db.query(StarSystem).filter(
        StarSystem.region_id.in_([r.id for r in regions])
    ).order_by(StarSystem.id).all()
    systems_by_region = {}
    for s in all_systems:
        systems_by_region.setdefault(s.region_id, []).append(s)

    planet_rows = []
    for region, region_num, sys_infos in region_system_info:
        region_systems = systems_by_region.get(region.id, [])
        for sys_obj, (sys_num, star_type) in zip(region_systems, sys_infos):
            # ── Orbit-First Generation ──
            # 1. Pick how many orbits this system has (influenced by star type)
            num_orbits = _pick_num_orbits(star_type)
            # 2. Pick which orbit slots are populated (weighted: inner orbits more common)
            orbit_slots = _pick_which_orbits(num_orbits)

            for orbit in orbit_slots:
                orbit_idx = orbit - 1

                # 3. Pick primary body (Row 0) for this orbit
                terrain, body_type = _pick_primary_type(enabled_primary_set)

                # Spec key = terrain directly (gas_giant, asteroid_belt, or terrain name)
                spec_key = terrain
                if spec_key in cached_specs:
                    stats = cached_specs[spec_key]
                else:
                    # Fallback to first available
                    spec_key = list(cached_specs.keys())[0]
                    stats = cached_specs[spec_key]

                # Calculate stats with orbit modifiers
                p_solar = max(0, stats["solar"] + ORBIT_MODIFIERS["solar"][orbit_idx])
                p_gas = max(0, stats["gas"] + ORBIT_MODIFIERS["gas"][orbit_idx])
                p_fertility = max(0, stats["fertility"] + ORBIT_MODIFIERS["fertility"][orbit_idx])

                if body_type == "Asteroid":
                    base_area = stats["area_moon"]
                elif body_type == "Moon":
                    base_area = stats["area_moon"]
                else:
                    base_area = stats["area_planet"] if stats["area_planet"] is not None else stats["area_moon"]
                # Non-colonizable astros (gas giants, asteroid belts) have no area
                p_area = max(0, base_area) if base_area else 0

                # Row 0 = primary body
                row = 0
                astro_coord = orbit * 10 + row
                coord_name = f"{gal_name}:{region_num}:{sys_num:02d}:{astro_coord:02d}"

                # planet_type = terrain directly (gas_giant, asteroid_belt, earthly, etc.)
                display_type = terrain

                planet_rows.append({
                    "name": coord_name, "system_id": sys_obj.id,
                    "planet_type": display_type,
                    "orbit_position": orbit, "orbit_row": row,
                    "solar": p_solar, "gas": p_gas,
                    "fertility": p_fertility, "area": p_area,
                    "metal": stats["metal"], "crystal": stats["crystal"],
                    "is_colonized": False,
                })

                # 4. Roll for satellites (Rows 1-3)
                # Satellite count varies by primary type
                primary_cat = "gas_giant" if terrain == "gas_giant" else ("asteroid_belt" if terrain == "asteroid_belt" else "planet")
                num_moons = _pick_moon_count(primary_cat)
                for moon_row in range(1, num_moons + 1):
                    # Hard rule: belt children are always asteroids,
                    # planet/gas giant children are always moons (with parent-specific terrain)
                    if terrain == "asteroid_belt":
                        m_terrain, m_body = ("asteroid", "Asteroid")
                    elif terrain == "gas_giant":
                        m_terrain, m_body = _pick_moon_type(enabled_moon_set, "gas_giant")
                    else:
                        m_terrain, m_body = _pick_moon_type(enabled_moon_set, "planet")
                    m_spec_key = m_terrain if m_terrain in cached_specs else "asteroid"
                    if m_spec_key not in cached_specs:
                        m_spec_key = list(cached_specs.keys())[0]
                    m_stats = cached_specs[m_spec_key]

                    m_solar = max(0, m_stats["solar"] + ORBIT_MODIFIERS["solar"][orbit_idx])
                    m_gas = max(0, m_stats["gas"] + ORBIT_MODIFIERS["gas"][orbit_idx])
                    m_fertility = max(0, m_stats["fertility"] + ORBIT_MODIFIERS["fertility"][orbit_idx])
                    m_area = max(10, m_stats["area_moon"])

                    m_astro_coord = orbit * 10 + moon_row
                    m_coord_name = f"{gal_name}:{region_num}:{sys_num:02d}:{m_astro_coord:02d}"

                    planet_rows.append({
                        "name": m_coord_name, "system_id": sys_obj.id,
                        "planet_type": m_terrain,
                        "orbit_position": orbit, "orbit_row": moon_row,
                        "solar": m_solar, "gas": m_gas,
                        "fertility": m_fertility, "area": m_area,
                        "metal": m_stats["metal"], "crystal": m_stats["crystal"],
                        "is_colonized": False,
                    })

    if planet_rows:
        # Insert in batches of 5000 to avoid SQLite variable limits
        batch_size = 5000
        for i in range(0, len(planet_rows), batch_size):
            db.execute(Planet.__table__.insert(), planet_rows[i:i+batch_size])
        db.flush()


def _get_map_depth(db) -> int:
    """Active navigation depth: 4 = galaxy/region/system/orbit (default),
    3 = galaxy/system/position (flat coordinate addressing). Read from the engine flag
    (definition or admin override). Setup-only: locked once a universe exists."""
    try:
        return int(get_config(db, "map_depth", "4") or 4)
    except (TypeError, ValueError):
        return 4


# Uniform world model (flat coordinate galaxies): every planet is the same kind of object;
# the system POSITION sets the temperature band and a partially-random size.
# Per-position {area: [lo, hi], temperature: [lo, hi]} — overridable via the
# definition's engine.position_profiles (keys are position numbers as strings).
# Bands derived from the classic formulas (verified against the open-source
# open-source reference implementation): fields ~ gaussian(200 - 10|8-pos|, 60 - 5|8-pos|),
# temperature ~ 30 + 1.75*sign(8-pos)*(8-pos)^2 ± 10, clamped to [-60, 120].
# Position 8 is the sweet spot for size; slot 1 bakes, slot 15 freezes.
UNIFORM_POSITION_PROFILES = {
    1:  {"area": [105, 155], "temperature": [106, 120]},
    2:  {"area": [110, 170], "temperature": [83, 103]},
    3:  {"area": [115, 185], "temperature": [64, 84]},
    4:  {"area": [120, 200], "temperature": [48, 68]},
    5:  {"area": [125, 215], "temperature": [36, 56]},
    6:  {"area": [130, 230], "temperature": [27, 47]},
    7:  {"area": [135, 245], "temperature": [22, 42]},
    8:  {"area": [140, 260], "temperature": [20, 40]},
    9:  {"area": [135, 245], "temperature": [18, 38]},
    10: {"area": [130, 230], "temperature": [13, 33]},
    11: {"area": [125, 215], "temperature": [4, 24]},
    12: {"area": [120, 200], "temperature": [-8, 12]},
    13: {"area": [115, 185], "temperature": [-24, -4]},
    14: {"area": [110, 170], "temperature": [-43, -23]},
    15: {"area": [105, 155], "temperature": [-60, -46]},
}


def _uniform_world_config():
    """Read the uniform world model settings off the active definition's engine
    section. Returns None when the definition uses the (default) terrain model."""
    from game_definition import get_game_definition
    engine = (get_game_definition() or {}).get("engine", {}) or {}
    if engine.get("world_model") != "uniform":
        return None
    profiles = dict(UNIFORM_POSITION_PROFILES)
    for pos, band in (engine.get("position_profiles") or {}).items():
        try:
            profiles[int(pos)] = band
        except (ValueError, TypeError):
            continue
    return {
        "terrain": engine.get("uniform_terrain"),
        "positions": int(engine.get("uniform_positions", 15)),
        "profiles": profiles,
    }


def _generate_galaxy_content_flat(db, galaxy, systems_per_galaxy, cached_specs,
                                  enabled_types=None, universe_seed=0):
    """Fill a galaxy with a flat galaxy:system:position layout (map_depth=3).

    Galaxies hold systems directly, numbered 1..N; a single synthetic Region per
    galaxy is kept only to satisfy the schema FK chain (system -> region ->
    galaxy) so the 4-level traversals elsewhere keep working unchanged. The
    region is invisible to navigation — coordinates are galaxy:system:position.
    No spiral density: systems are uniform, like a flat coordinate galaxy. Reuses the same
    orbit-first per-system body generation as the 4-level path."""
    gal_name = galaxy.name
    enabled_primary_set = set()
    enabled_moon_set = set()
    if enabled_types:
        for t in enabled_types:
            if t in AWE_PRIMARY_WEIGHTS:
                enabled_primary_set.add(t)
            if t in AWE_MOON_WEIGHTS:
                enabled_moon_set.add(t)
    else:
        enabled_primary_set = None
        enabled_moon_set = None

    # One synthetic region (hidden from navigation) so system->region->galaxy holds.
    db.execute(Region.__table__.insert(),
               [{"name": "00", "galaxy_id": galaxy.id, "grid_x": 0, "grid_y": 0}])
    db.flush()
    region = db.query(Region).filter(Region.galaxy_id == galaxy.id).first()

    # Systems numbered 1..N directly in the galaxy.
    system_rows = [{"name": f"{i:03d}", "region_id": region.id, "star_type": _pick_star_type()}
                   for i in range(1, systems_per_galaxy + 1)]
    db.execute(StarSystem.__table__.insert(), system_rows)
    db.flush()
    systems = (db.query(StarSystem).filter(StarSystem.region_id == region.id)
               .order_by(StarSystem.id).all())

    uniform = _uniform_world_config()
    if uniform:
        # Uniform worlds: one identical planet per position 1..N; the position sets
        # the temperature band and a partially-random size. No moons at
        # generation — moons form from combat debris (engine.moon_formation).
        terrain = uniform["terrain"]
        if terrain not in cached_specs:
            terrain = list(cached_specs.keys())[0]
        stats = cached_specs[terrain]
        planet_rows = []
        for sys_num, sys_obj in enumerate(systems, start=1):
            for pos in range(1, uniform["positions"] + 1):
                band = uniform["profiles"].get(pos) or {"area": [60, 130], "temperature": [0, 40]}
                a_lo, a_hi = band.get("area", [60, 130])
                t_lo, t_hi = band.get("temperature", [0, 40])
                planet_rows.append({
                    "name": f"{gal_name}:{sys_num:03d}:{pos * 10:02d}", "system_id": sys_obj.id,
                    "planet_type": terrain, "orbit_position": pos, "orbit_row": 0,
                    "solar": stats["solar"], "gas": stats["gas"], "fertility": stats["fertility"],
                    "area": random.randint(int(a_lo), int(a_hi)),
                    "temperature": random.randint(int(t_lo), int(t_hi)),
                    "metal": stats["metal"], "crystal": stats["crystal"], "is_colonized": False,
                })
        for i in range(0, len(planet_rows), 5000):
            db.execute(Planet.__table__.insert(), planet_rows[i:i+5000])
        db.flush()
        logger.info(f"[universe] Galaxy {gal_name} (flat/uniform) — {len(systems)} systems, {len(planet_rows)} astros")
        return

    planet_rows = []
    for sys_num, sys_obj in enumerate(systems, start=1):
        star_type = sys_obj.star_type
        orbit_slots = _pick_which_orbits(_pick_num_orbits(star_type))
        for orbit in orbit_slots:
            orbit_idx = orbit - 1
            terrain, body_type = _pick_primary_type(enabled_primary_set)
            spec_key = terrain if terrain in cached_specs else list(cached_specs.keys())[0]
            stats = cached_specs[spec_key]
            p_solar = max(0, stats["solar"] + ORBIT_MODIFIERS["solar"][orbit_idx])
            p_gas = max(0, stats["gas"] + ORBIT_MODIFIERS["gas"][orbit_idx])
            p_fertility = max(0, stats["fertility"] + ORBIT_MODIFIERS["fertility"][orbit_idx])
            if body_type in ("Asteroid", "Moon"):
                base_area = stats["area_moon"]
            else:
                base_area = stats["area_planet"] if stats["area_planet"] is not None else stats["area_moon"]
            p_area = max(0, base_area) if base_area else 0
            astro_coord = orbit * 10  # row 0 = primary body
            planet_rows.append({
                "name": f"{gal_name}:{sys_num:03d}:{astro_coord:02d}", "system_id": sys_obj.id,
                "planet_type": terrain, "orbit_position": orbit, "orbit_row": 0,
                "solar": p_solar, "gas": p_gas, "fertility": p_fertility, "area": p_area,
                "metal": stats["metal"], "crystal": stats["crystal"], "is_colonized": False,
            })
            primary_cat = ("gas_giant" if terrain == "gas_giant"
                           else "asteroid_belt" if terrain == "asteroid_belt" else "planet")
            for moon_row in range(1, _pick_moon_count(primary_cat) + 1):
                if terrain == "asteroid_belt":
                    m_terrain = "asteroid"
                elif terrain == "gas_giant":
                    m_terrain, _m = _pick_moon_type(enabled_moon_set, "gas_giant")
                else:
                    m_terrain, _m = _pick_moon_type(enabled_moon_set, "planet")
                m_spec_key = m_terrain if m_terrain in cached_specs else "asteroid"
                if m_spec_key not in cached_specs:
                    m_spec_key = list(cached_specs.keys())[0]
                m_stats = cached_specs[m_spec_key]
                m_astro_coord = orbit * 10 + moon_row
                planet_rows.append({
                    "name": f"{gal_name}:{sys_num:03d}:{m_astro_coord:02d}", "system_id": sys_obj.id,
                    "planet_type": m_terrain, "orbit_position": orbit, "orbit_row": moon_row,
                    "solar": max(0, m_stats["solar"] + ORBIT_MODIFIERS["solar"][orbit_idx]),
                    "gas": max(0, m_stats["gas"] + ORBIT_MODIFIERS["gas"][orbit_idx]),
                    "fertility": max(0, m_stats["fertility"] + ORBIT_MODIFIERS["fertility"][orbit_idx]),
                    "area": max(10, m_stats["area_moon"]),
                    "metal": m_stats["metal"], "crystal": m_stats["crystal"], "is_colonized": False,
                })

    for i in range(0, len(planet_rows), 5000):
        db.execute(Planet.__table__.insert(), planet_rows[i:i+5000])
    db.flush()
    logger.info(f"[universe] Galaxy {gal_name} (flat) — {len(systems)} systems, {len(planet_rows)} astros")


def generate_universe(db: Session):
    """Generate server universe.

    Server = one letter (e.g. Alpha = A).
    Clusters = groups of 10 galaxies each (x0-x9).
      4 clusters → A00-A09, A10-A19, A20-A29, A30-A39
    Within a cluster: galaxies linked sequentially (200 dist).
    Between clusters: pumpkin (x0↔x0, x9↔x9, 1000 dist) or classic (x9→x0, 1000 dist).
    Coordinates: A13:41:05:03 = Galaxy A13, Region 41, System 05, Astro 03.
    """
    server_letter = get_config(db, "server_letter", "A")
    server_name = SERVER_NAMES.get(server_letter, f"Server-{server_letter}")
    topology = get_config(db, "map_topology", "pumpkin")

    # ── Load galaxy preset (Standard, MSS, etc.) ──
    preset_key = get_config(db, "galaxy_preset", "standard")
    preset = GALAXY_PRESETS.get(preset_key, GALAXY_PRESETS["standard"])
    logger.info(f"[universe] Using galaxy preset: {preset['name']} ({preset_key})")

    # Config values override preset defaults; preset provides sensible fallbacks
    num_clusters = get_config_int(db, "num_clusters", preset.get("num_clusters", 4))
    galaxies_per_cluster = preset.get("galaxies_per_cluster", 10)
    regions_per = get_config_int(db, "regions_per_galaxy", preset.get("regions_per_galaxy", 100))
    max_systems_per = get_config_int(db, "systems_per_region", preset.get("systems_per_region", 44))
    pmin = get_config_int(db, "planets_per_system_min", 1)
    pmax = get_config_int(db, "planets_per_system_max", 11)

    # ── Cache all astro specs ONCE to avoid per-planet DB queries ──
    all_specs = get_all_astro_specs(db)
    disabled_raw = get_config(db, "disabled_astros") or ""
    disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
    enabled_types = [k for k in all_specs if k not in disabled_set]
    cached_specs = {k: all_specs[k] for k in enabled_types}
    logger.info(f"[universe] Cached {len(enabled_types)} astro types, generating {num_clusters} clusters...")

    grid_w = preset.get("regions_grid_w", int(math.ceil(math.sqrt(regions_per))))
    grid_h = preset.get("regions_grid_h", int(math.ceil(regions_per / grid_w)))

    # Universe seed — changes each regeneration so galaxies look different every time
    import time
    universe_seed = int(time.time()) % 1000000
    set_config(db, "universe_seed", str(universe_seed))
    logger.info(f"[universe] Universe seed: {universe_seed}")

    clusters = []           # list of Cluster objects
    cluster_galaxies = {}   # cluster.id → [Galaxy, ...]

    total_galaxies = num_clusters * galaxies_per_cluster
    galaxies_done = 0

    for ci in range(num_clusters):
        cluster = Cluster(name=f"{server_name} Cluster {ci}", cluster_index=ci)
        db.add(cluster)
        db.flush()
        clusters.append(cluster)
        cluster_galaxies[cluster.id] = []

        # Each cluster has galaxies_per_cluster galaxies
        # Cluster 0 → A00-A09, Cluster 1 → A10-A19, etc.
        base_index = ci * galaxies_per_cluster
        for gi in range(galaxies_per_cluster):
            gal_num = base_index + gi
            gal_name = f"{server_letter}{gal_num:02d}"  # A00, A01, ... A09, A10, A11, ...
            gal = Galaxy(
                name=gal_name,
                cluster_id=cluster.id,
                galaxy_index=gi,  # 0-9 within this cluster
                regions_grid_w=grid_w,
                regions_grid_h=grid_h,
            )
            db.add(gal)
            db.flush()
            cluster_galaxies[cluster.id].append(gal)
            # MSS: compute active region range from configurable size (centered in grid)
            active_size = get_config_int(db, "active_region_size", preset.get("active_region_size", 0))
            if active_size > 0 and active_size < grid_w:
                offset = (grid_w - active_size) // 2
                active_cols = list(range(offset, offset + active_size))
                active_rows = list(range(offset, offset + active_size))
            else:
                active_cols = None
                active_rows = None

            if _get_map_depth(db) == 3:
                systems_per_galaxy = get_config_int(db, "systems_per_galaxy", 120)
                _generate_galaxy_content_flat(db, gal, systems_per_galaxy, cached_specs,
                                              enabled_types=enabled_types,
                                              universe_seed=universe_seed)
            else:
                _generate_galaxy_content(db, gal, regions_per, max_systems_per, pmin, pmax,
                                         enabled_types=enabled_types, cached_specs=cached_specs,
                                         universe_seed=universe_seed,
                                         active_cols=active_cols,
                                         active_rows=active_rows)

            # Commit after EACH galaxy to release the write lock frequently.
            # This prevents "database is locked" errors from concurrent read requests.
            db.commit()
            galaxies_done += 1
            logger.info(f"[universe] Galaxy {gal_name} done ({galaxies_done}/{total_galaxies})")

            # Update progress in game config so frontend can show it
            set_config(db, "gen_progress", f"{galaxies_done}/{total_galaxies}")
            db.commit()

    # Create galaxy links
    import galaxy_network as _gnet
    _gn_topo = (get_config(db, "galaxy_network", "") or "").strip()
    if _gn_topo in _gnet.GRAPH_TOPOLOGIES:
        # Graph topologies (lane_network/tree/small_world/k_random): the links ARE
        # the travel graph — fleet distance is shortest-path over them.
        gid_order = [g.id for gals in cluster_galaxies.values()
                     for g in sorted(gals, key=lambda g: g.galaxy_index)]
        for a, b, w in _gnet.build_links(gid_order, _gn_topo, seed=len(gid_order)):
            db.add(GalaxyLink(galaxy_a_id=a, galaxy_b_id=b, distance=w))
        _gnet.invalidate_galaxy_graph_cache()
    else:
        # Static geometric topologies: links are for display / wormhole routing.
        # Within each cluster: sequential x0↔x1↔...↔x9 (200 distance)
        for cid, gals in cluster_galaxies.items():
            gals_sorted = sorted(gals, key=lambda g: g.galaxy_index)
            for i in range(len(gals_sorted) - 1):
                db.add(GalaxyLink(galaxy_a_id=gals_sorted[i].id, galaxy_b_id=gals_sorted[i+1].id, distance=200))

        # Between clusters: depends on topology
        if topology == "classic":
            # Classic: x9 of cluster i → x0 of cluster j (mesh pattern)
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    ci_gals = sorted(cluster_galaxies[clusters[i].id], key=lambda g: g.galaxy_index)
                    cj_gals = sorted(cluster_galaxies[clusters[j].id], key=lambda g: g.galaxy_index)
                    db.add(GalaxyLink(galaxy_a_id=ci_gals[-1].id, galaxy_b_id=cj_gals[0].id, distance=1000))
                    db.add(GalaxyLink(galaxy_a_id=cj_gals[-1].id, galaxy_b_id=ci_gals[0].id, distance=1000))
        else:
            # Pumpkin: x0↔x0 and x9↔x9 between all cluster pairs
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    ci_gals = sorted(cluster_galaxies[clusters[i].id], key=lambda g: g.galaxy_index)
                    cj_gals = sorted(cluster_galaxies[clusters[j].id], key=lambda g: g.galaxy_index)
                    db.add(GalaxyLink(galaxy_a_id=ci_gals[0].id, galaxy_b_id=cj_gals[0].id, distance=1000))
                    db.add(GalaxyLink(galaxy_a_id=ci_gals[-1].id, galaxy_b_id=cj_gals[-1].id, distance=1000))

    db.commit()

    # Place wormholes in all galaxies (presets like MSS opt out)
    if _wormholes_enabled(db):
        _place_wormholes(db, cluster_galaxies)
        db.commit()
    else:
        logger.info("[universe] Wormholes disabled for this universe — skipping placement")

    # Graph map topology: build the SystemLink network over all systems (no-op
    # in hierarchy mode). Runs after every galaxy's systems exist so links can
    # span the whole universe and the connectivity guarantee is global.
    try:
        import graph_map
        if graph_map.is_graph_map(db):
            rep = graph_map.generate_graph_links(db, graph_map.graph_config(db))
            logger.info(f"[universe] graph map links: {rep}")
    except Exception as e:
        logger.error(f"[universe] graph link generation failed: {e}")

    logger.info(f"[universe] All {total_galaxies} galaxies + links + wormholes created successfully.")

# ======================== WORMHOLE PLACEMENT ========================

def _wormholes_enabled(db):
    """Whether this universe has wormholes. Admin config wins; the galaxy
    preset provides the default (MSS = no wormholes)."""
    preset_key = get_config(db, "galaxy_preset", "standard")
    preset = GALAXY_PRESETS.get(preset_key, GALAXY_PRESETS["standard"])
    default = "true" if preset.get("wormholes", True) else "false"
    return get_config(db, "wormholes_enabled", default).strip().lower() in ("true", "1", "yes")


def _pick_wormhole_planet(db, galaxy_id, region_filter_fn, weight_fn=None):
    """Pick a random existing astro in a region matching the filter.
    The astro keeps its original terrain/stats — wormhole is just a flag.
    If weight_fn is provided, regions are weighted by weight_fn(grid_x, grid_y)."""
    regions = db.query(Region).filter(Region.galaxy_id == galaxy_id).all()
    matching = [r for r in regions if region_filter_fn(r.grid_x, r.grid_y)]
    if not matching:
        return None
    if weight_fn:
        weights = [weight_fn(r.grid_x, r.grid_y) for r in matching]
        total = sum(weights)
        if total > 0:
            # Weighted shuffle: pick regions with probability proportional to weight
            ordered = []
            remaining = list(zip(matching, weights))
            while remaining:
                r_val = random.random() * sum(w for _, w in remaining)
                cumulative = 0
                for i, (reg, w) in enumerate(remaining):
                    cumulative += w
                    if cumulative >= r_val:
                        ordered.append(reg)
                        remaining.pop(i)
                        break
            matching = ordered
        else:
            random.shuffle(matching)
    else:
        random.shuffle(matching)
    for region in matching:
        systems = db.query(StarSystem).filter(StarSystem.region_id == region.id).all()
        if not systems:
            continue
        system = random.choice(systems)
        # Pick any planet that isn't a non-colonizable type (gas giant, asteroid belt)
        planets = db.query(Planet).filter(
            Planet.system_id == system.id,
            ~Planet.planet_type.in_(["gas_giant", "asteroid_belt"]),
        ).all()
        if planets:
            return random.choice(planets)
    return None


def _place_wormholes(db, cluster_galaxies):
    """Place 2 wormholes per galaxy (1 inner, 1 outer) and link them along GalaxyLink topology.
    Inner = center 2×2 (regions where grid_x in [4,5] and grid_y in [4,5]).
    Outer = everything else."""
    from config_defaults import WORMHOLE_INNER_REGIONS

    # Inner region check: both grid coords in [4,5] (center of 10×10)
    def is_inner(gx, gy):
        return (gy * 10 + gx) in WORMHOLE_INNER_REGIONS

    def is_outer(gx, gy):
        return not is_inner(gx, gy)

    def outer_weight(gx, gy):
        """Weight outer regions by distance from center — further out = much more likely."""
        dist = ((gx - 4.5) ** 2 + (gy - 4.5) ** 2) ** 0.5
        return dist ** 3  # cubic weighting: edges heavily favored

    wh_count = 0

    for cid, gals in cluster_galaxies.items():
        for gal in gals:
            inner_planet = _pick_wormhole_planet(db, gal.id, is_inner)
            outer_planet = _pick_wormhole_planet(db, gal.id, is_outer, weight_fn=outer_weight)

            if inner_planet:
                db.add(Wormhole(planet_id=inner_planet.id, galaxy_id=gal.id, wormhole_type="inner"))
                wh_count += 1
            if outer_planet:
                db.add(Wormhole(planet_id=outer_planet.id, galaxy_id=gal.id, wormhole_type="outer"))
                wh_count += 1

    db.flush()
    logger.info(f"[universe] Placed {wh_count} wormholes")


def ensure_wormholes(db):
    """For existing databases: place wormholes if none exist but galaxies do.
    Also deduplicates if multiple wormholes of the same type exist per galaxy.
    If wormholes are disabled (e.g. MSS preset), removes any that exist instead."""
    if not _wormholes_enabled(db):
        stale = db.query(Wormhole).delete()
        if stale:
            db.commit()
            logger.info(f"[universe] Wormholes disabled — removed {stale} existing wormholes")
        return
    # Deduplicate: keep only one inner and one outer per galaxy
    from sqlalchemy import func
    dupes = db.query(Wormhole.galaxy_id, Wormhole.wormhole_type, func.count().label('cnt')) \
        .group_by(Wormhole.galaxy_id, Wormhole.wormhole_type) \
        .having(func.count() > 1).all()
    if dupes:
        removed = 0
        for galaxy_id, wh_type, cnt in dupes:
            extras = db.query(Wormhole).filter(
                Wormhole.galaxy_id == galaxy_id,
                Wormhole.wormhole_type == wh_type
            ).order_by(Wormhole.id).all()
            # Keep the first, delete the rest
            for wh in extras[1:]:
                db.delete(wh)
                removed += 1
        db.commit()
        logger.info(f"[universe] Removed {removed} duplicate wormholes")

    existing = db.query(Wormhole).first()
    if existing:
        return
    galaxies = db.query(Galaxy).all()
    if not galaxies:
        return
    # Rebuild cluster_galaxies dict
    clusters = db.query(Cluster).all()
    cluster_galaxies = {}
    for c in clusters:
        cluster_galaxies[c.id] = [g for g in galaxies if g.cluster_id == c.id]
    _place_wormholes(db, cluster_galaxies)
    db.commit()
    logger.info("[universe] Wormholes placed in existing galaxies.")


# ======================== HOMEWORLD ASSIGNMENT ========================

def _find_homeworld_planet(db):
    """Find an available 3rd-orbit Earthly planet for a new player's home base.
    All starting bases use 3rd-position Earthly planets.
    Returns a Planet or None if none available.
    """
    # Exclude planets with wormholes
    wormhole_planet_ids = {w.planet_id for w in db.query(Wormhole).all()}
    candidates = (
        db.query(Planet)
        .filter(
            Planet.is_colonized == False,
            Planet.planet_type == "earthly",
            Planet.orbit_position == 3,
        )
        .all()
    )
    candidates = [p for p in candidates if p.id not in wormhole_planet_ids]
    if not candidates:
        return None
    return random.choice(candidates)


def _add_cluster(db):
    """Dynamically add a new cluster to the universe.
    Called when existing clusters run out of 3rd-position Earthly planets for home bases.
    Also callable by admins.
    Returns the new Cluster object.
    """
    server_letter = get_config(db, "server_letter", "A")
    server_name = SERVER_NAMES.get(server_letter, f"Server-{server_letter}")
    topology = get_config(db, "map_topology", "pumpkin")
    regions_per = get_config_int(db, "regions_per_galaxy", 100)
    max_systems_per = get_config_int(db, "systems_per_region", 5)
    pmin = get_config_int(db, "planets_per_system_min", 3)
    pmax = get_config_int(db, "planets_per_system_max", 6)

    # Cache astro specs once
    all_specs = get_all_astro_specs(db)
    disabled_raw = get_config(db, "disabled_astros") or ""
    disabled_set = set(s.strip() for s in disabled_raw.split(",") if s.strip())
    enabled_types = [k for k in all_specs if k not in disabled_set]
    cached_specs = {k: all_specs[k] for k in enabled_types}

    grid_w = int(math.ceil(math.sqrt(regions_per)))
    grid_h = int(math.ceil(regions_per / grid_w))

    # Determine next cluster index
    max_ci_val = db.query(func.max(Cluster.cluster_index)).scalar()
    max_ci = max_ci_val if max_ci_val is not None else -1
    new_ci = max_ci + 1

    cluster = Cluster(name=f"{server_name} Cluster {new_ci}", cluster_index=new_ci)
    db.add(cluster)
    db.flush()

    # Generate 10 galaxies for the new cluster
    base_index = new_ci * 10
    new_galaxies = []
    for gi in range(10):
        gal_num = base_index + gi
        gal_name = f"{server_letter}{gal_num:02d}"
        gal = Galaxy(
            name=gal_name,
            cluster_id=cluster.id,
            galaxy_index=gi,
            regions_grid_w=grid_w,
            regions_grid_h=grid_h,
        )
        db.add(gal)
        db.flush()
        new_galaxies.append(gal)
        if _get_map_depth(db) == 3:
            _generate_galaxy_content_flat(db, gal, get_config_int(db, "systems_per_galaxy", 120),
                                          cached_specs, enabled_types=enabled_types)
        else:
            _generate_galaxy_content(db, gal, regions_per, max_systems_per, pmin, pmax,
                                     enabled_types=enabled_types, cached_specs=cached_specs)

    db.flush()

    # Within-cluster links: sequential x0↔x1↔...↔x9 (200 distance)
    for i in range(len(new_galaxies) - 1):
        db.add(GalaxyLink(galaxy_a_id=new_galaxies[i].id, galaxy_b_id=new_galaxies[i + 1].id, distance=200))

    # Between-cluster links: connect new cluster to all existing clusters
    existing_clusters = db.query(Cluster).filter(Cluster.id != cluster.id).all()
    for ec in existing_clusters:
        ec_gals = (
            db.query(Galaxy)
            .filter(Galaxy.cluster_id == ec.id)
            .order_by(Galaxy.galaxy_index)
            .all()
        )
        if not ec_gals:
            continue
        if topology == "classic":
            # x9 of each → x0 of other
            db.add(GalaxyLink(galaxy_a_id=ec_gals[-1].id, galaxy_b_id=new_galaxies[0].id, distance=1000))
            db.add(GalaxyLink(galaxy_a_id=new_galaxies[-1].id, galaxy_b_id=ec_gals[0].id, distance=1000))
        else:
            # Pumpkin: x0↔x0 and x9↔x9
            db.add(GalaxyLink(galaxy_a_id=ec_gals[0].id, galaxy_b_id=new_galaxies[0].id, distance=1000))
            db.add(GalaxyLink(galaxy_a_id=ec_gals[-1].id, galaxy_b_id=new_galaxies[-1].id, distance=1000))

    db.commit()
    logger.info(f"[cluster] Added cluster {new_ci}: {server_letter}{base_index:02d}-{server_letter}{base_index+9:02d}")
    return cluster


def _find_homeworld_planet_in_galaxy(db, galaxy_id):
    """Find an available 3rd-orbit Earthly planet in a specific galaxy."""
    candidates = (
        db.query(Planet)
        .join(StarSystem, Planet.system_id == StarSystem.id)
        .join(Region, StarSystem.region_id == Region.id)
        .filter(
            Region.galaxy_id == galaxy_id,
            Planet.is_colonized == False,
            Planet.planet_type == "earthly",
            Planet.orbit_position == 3,
        )
        .all()
    )
    if not candidates:
        # Fallback: any uncolonized planet in that galaxy
        candidates = (
            db.query(Planet)
            .join(StarSystem, Planet.system_id == StarSystem.id)
            .join(Region, StarSystem.region_id == Region.id)
            .filter(Region.galaxy_id == galaxy_id, Planet.is_colonized == False)
            .all()
        )
    return random.choice(candidates) if candidates else None


def _assign_homeworld_in_galaxy(user, galaxy_id, db):
    """Assign a homeworld in a specific galaxy (player chose during registration)."""
    planet = _find_homeworld_planet_in_galaxy(db, galaxy_id)
    if not planet:
        # Fallback to any galaxy
        planet = _find_homeworld_planet(db)
    if not planet:
        _add_cluster(db)
        planet = _find_homeworld_planet(db)
    if not planet:
        planets = db.query(Planet).filter(Planet.is_colonized == False).all()
        if not planets:
            return
        planet = random.choice(planets)
    planet.is_colonized = True
    base = Colony(planet_id=planet.id, user_id=user.id, name=f"{user.username}'s Homeworld")
    db.add(base)
    db.flush()
    # Homeworld establishes the peak base count (=1) for the rebuild-discount invariant.
    user.bases_founded_peak = max(getattr(user, "bases_founded_peak", 0) or 0, 1)
    # Starter buildings — homeworld starts with Urban Structures Lv1 only
    # (the +2 free energy and +20 construction are base bonuses in calc_base_stats)
    for bt, bspec in BUILDING_SPECS.items():
        db.add(Building(colony_id=base.id, building_type=bt, level=bspec.get("start_level", 0)))
    # Initialize defenses
    for dt in DEFENSE_SPECS.keys():
        db.add(Defense(colony_id=base.id, defense_type=dt, level=0))
    # Initialize research
    for tt in RESEARCH_SPECS.keys():
        existing = db.query(Research).filter(Research.user_id == user.id, Research.tech_type == tt).first()
        if not existing:
            db.add(Research(user_id=user.id, tech_type=tt, level=0))
    # Starter fleet
    db.add(Fleet(name="Home Fleet", user_id=user.id, base_id=base.id))
    user.score += 10
    _record_region_snapshot(user.id, planet.system.region_id, db)
    db.commit()


def _assign_homeworld(user, db):
    planet = _find_homeworld_planet(db)
    # If no 3rd-position Earthly planets are available, expand the universe.
    if not planet:
        logger.info("[homeworld] No available home slots — adding new cluster...")
        _add_cluster(db)
        planet = _find_homeworld_planet(db)
    # Last resort fallback (should never happen after cluster expansion)
    if not planet:
        planets = db.query(Planet).filter(Planet.is_colonized == False).all()
        if not planets:
            return
        planet = random.choice(planets)
    planet.is_colonized = True
    base = Colony(planet_id=planet.id, user_id=user.id, name=f"{user.username}'s Homeworld")
    db.add(base)
    db.flush()
    # Homeworld establishes the peak base count (=1) for the rebuild-discount invariant.
    user.bases_founded_peak = max(getattr(user, "bases_founded_peak", 0) or 0, 1)
    # Starter buildings — homeworld starts with Urban Structures Lv1 only
    # (the +2 free energy and +20 construction are base bonuses in calc_base_stats)
    for bt, bspec in BUILDING_SPECS.items():
        db.add(Building(colony_id=base.id, building_type=bt, level=bspec.get("start_level", 0)))
    # Initialize defenses
    for dt in DEFENSE_SPECS.keys():
        db.add(Defense(colony_id=base.id, defense_type=dt, level=0))
    # Initialize research
    for tt in RESEARCH_SPECS.keys():
        existing = db.query(Research).filter(Research.user_id == user.id, Research.tech_type == tt).first()
        if not existing:
            db.add(Research(user_id=user.id, tech_type=tt, level=0))
    # Starter fleet
    db.add(Fleet(name="Home Fleet", user_id=user.id, base_id=base.id))
    user.score += 10
    # Record fog-of-war snapshot for homeworld region
    _record_region_snapshot(user.id, planet.system.region_id, db)
    db.commit()

# ======================== STARTUP ========================

def _auto_migrate_sqlite():
    """Auto-add any missing columns to existing SQLite tables."""
    if not _is_sqlite:
        return
    import sqlite3 as _sqlite3
    # Use a completely separate sqlite3 connection to avoid corrupting SQLAlchemy's pool
    db_url = str(engine.url)
    db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
    if not db_path or db_path == ":memory:":
        return
    raw = _sqlite3.connect(db_path)
    cursor = raw.cursor()
    try:
        for table in ModelBase.metadata.sorted_tables:
            cursor.execute(f"PRAGMA table_info({table.name})")
            existing_cols = {row[1] for row in cursor.fetchall()}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(dialect=engine.dialect)
                    default_clause = ""
                    if col.default is not None:
                        if callable(col.default.arg):
                            default_clause = ""
                        elif isinstance(col.default.arg, str):
                            safe = col.default.arg.replace("'", "''")
                            default_clause = f" DEFAULT '{safe}'"
                        else:
                            default_clause = f" DEFAULT {col.default.arg}"
                    elif col.nullable:
                        default_clause = " DEFAULT NULL"
                    sql = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{default_clause}"
                    logger.info(f"[migrate] {sql}")
                    cursor.execute(sql)
        raw.commit()
    finally:
        raw.close()
