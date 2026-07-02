# ======================== GAME CONSTANTS — CLASSIC SPACE STRATEGY SPECS ========================

# ── Ships (lean engine-default archetypes; full roster lives in a definition) ──
SHIP_SPECS = {
    # Lean engine-default roster: ONE archetype per tier/role. A game definition
    # (e.g. game_definitions/classic_space.json) supplies the full tuned roster;
    # the count per tier is the definition's call. `tier` groups combat hulls
    # (light/medium/heavy/capital); functional ships are tier "support".
    # rounding: 0=binary (ceil), 1=partial (round 0.1), 2=capital precision.
    "light_warship":   {"name": "Light Warship",   "desc": "Cheap early combat unit.", "cost": 20, "attack": 8, "armour": 6, "shield": 0, "speed": 10, "hangar": 0, "weapon": "laser", "drive": "stellar", "shipyard": 2, "req": {"laser": 1}, "rounding": 0, "tier": "light"},
    "medium_warship":  {"name": "Medium Warship", "desc": "Versatile mid-tier combat unit.", "cost": 150, "attack": 20, "armour": 18, "shield": 1, "speed": 6, "hangar": 4, "weapon": "ion", "drive": "warp", "shipyard": 8, "req": {"ion": 4, "warp_drive": 1, "armour": 6, "shielding": 2}, "rounding": 1, "tier": "medium"},
    "heavy_warship":   {"name": "Heavy Warship", "desc": "Strong heavy-class combat unit.", "cost": 2000, "attack": 160, "armour": 128, "shield": 12, "speed": 4, "hangar": 20, "weapon": "photon", "drive": "warp", "shipyard": 16, "req": {"photon": 6, "warp_drive": 8, "armour": 16, "shielding": 8}, "rounding": 2, "tier": "heavy"},
    "capital_warship": {"name": "Capital Warship", "desc": "Flagship-class capital unit; grants +5% fleet bonus.", "cost": 200000, "attack": 10000, "armour": 6600, "shield": 40, "speed": 3, "hangar": 4000, "weapon": "disruptor", "drive": "warp", "shipyard": 24, "req": {"disruptor": 10, "warp_drive": 18, "armour": 24, "shielding": 16}, "rounding": 2, "tier": "capital", "fleet_bonus": 0.05},
    "colony_ship":     {"name": "Colony Ship", "desc": "Founds a new base.", "cost": 100, "attack": 2, "armour": 4, "shield": 0, "speed": 4, "hangar": 0, "weapon": "laser", "drive": "warp", "shipyard": 8, "req": {"warp_drive": 1}, "rounding": 0, "tier": "support", "can_colonize": True},
    "scout_ship":      {"name": "Scout Ship", "desc": "Fast unit for exploration and scouting.", "cost": 40, "attack": 1, "armour": 2, "shield": 0, "speed": 12, "hangar": 0, "weapon": "laser", "drive": "warp", "shipyard": 4, "req": {"warp_drive": 1}, "rounding": 0, "tier": "support", "can_autoscout": True},
    "utility_ship":    {"name": "Utility Ship", "desc": "Collects debris and converts it to credits.", "cost": 30, "attack": 2, "armour": 2, "shield": 0, "speed": 8, "hangar": 0, "weapon": "laser", "drive": "stellar", "shipyard": 5, "req": {"laser": 1, "stellar_drive": 1}, "rounding": 0, "tier": "support", "can_recycle": True},
    "carrier":         {"name": "Carrier", "desc": "Support hauler with large hangar capacity.", "cost": 2500, "attack": 64, "armour": 96, "shield": 10, "speed": 4, "hangar": 500, "weapon": "ion", "drive": "warp", "shipyard": 16, "req": {"ion": 4, "warp_drive": 8, "armour": 14, "shielding": 6}, "rounding": 2, "tier": "support"},
}
ALL_SHIP_TYPES = list(SHIP_SPECS.keys())

# ── Weapon Types (defines shield interaction behavior per weapon) ──
WEAPON_TYPES = {
    "laser":     {"name": "Laser",     "shield_passthrough": 0.01},
    "missiles":  {"name": "Missiles",  "shield_passthrough": 0.01},
    "plasma":    {"name": "Plasma",    "shield_passthrough": 0.01},
    "ion":       {"name": "Ion",       "shield_passthrough": 0.50},
    "photon":    {"name": "Photon",    "shield_passthrough": 0.01},
    "disruptor": {"name": "Disruptor", "shield_passthrough": 0.01},
}

# Goods: special production item, not a ship. Uses base production rate (industrial), no shipyard needed.
GOODS_SPEC = {"name": "Goods", "cost": 20, "sell_price": 21, "shipyard": 0, "req": {}, "is_goods": True, "attack": 0, "armour": 0, "shield": 0, "speed": 0, "hangar": 0}

# ── Commander Name Pools ──
import random

COMMANDER_FIRST_NAMES = [
    "Jay", "Victor", "Vince", "Doug", "Damon", "Joseph", "Tristan", "Drew",
    "Harry", "Marcus", "Elena", "Kai", "Zara", "Niko", "Aria", "Raven",
    "Cael", "Luna", "Orion", "Atlas", "Nova", "Sage", "Rex", "Juno",
    "Mira", "Axel", "Lyra", "Phoenix", "Soren", "Thane", "Kira", "Dante",
    "Qi-chen", "Yuki", "Rho", "Vesper", "Talia", "Cade", "Ember", "Zane",
]
COMMANDER_LAST_NAMES = [
    "Luso", "Vogel", "Thor", "Suknoi", "Leo", "Polarm", "Zeen", "Maxim",
    "Nessus", "Voss", "Kaine", "Stark", "Reyes", "Orin", "Vega", "Hale",
    "Cross", "Prime", "Solari", "Thorn", "Ash", "Drake", "Vale", "Storm",
    "Rune", "Crest", "Nova", "Flint", "Sable", "Onyx", "Steel", "Wren",
    "Corvus", "Zenith", "Blade", "Quasar", "Helix", "Drift", "Forge", "Ember",
]

COMMANDER_SKILL_TYPES = ["construction", "research", "production", "defense", "tactical", "logistics"]

# Commander skill specs — data-driven so admin can edit bonus amounts and add new types.
# bonus_category: how the code applies the bonus
#   "reduce_build"   — multiplies cost/time by (1 - level * bonus_per_level)
#   "boost_combat"   — multiplies combat stats by (1 + level * bonus_per_level)
#   "reduce_travel"  — multiplies travel time by (1 - level * bonus_per_level)
# scope: "colony" = only at assigned base, "global" = best level across all bases
# targets: what the bonus affects (informational, the category determines code path)
COMMANDER_SKILL_SPECS = {
    "construction": {"name": "Construction", "bonus_per_level": 0.01, "bonus_category": "reduce_build",
                     "scope": "colony", "targets": "construction cost",
                     "desc": "Decreases construction cost by 1% per level (time reduces because cost is lower)."},
    "research":     {"name": "Research",     "bonus_per_level": 0.01, "bonus_category": "reduce_build",
                     "scope": "colony", "targets": "research cost",
                     "desc": "Decreases research cost by 1% per level at this base (time reduces because cost is lower)."},
    "production":   {"name": "Production",   "bonus_per_level": 0.01, "bonus_category": "reduce_build",
                     "scope": "colony", "targets": "ship build time",
                     "desc": "Decreases production time by 1% per commander level."},
    "defense":      {"name": "Defense",      "bonus_per_level": 0.01, "bonus_category": "boost_combat",
                     "scope": "colony", "targets": "defense power, armour & shield",
                     "desc": "Increases defenses' attack, armour and shield by 1% per commander level."},
    "tactical":     {"name": "Tactical",     "bonus_per_level": 0.01, "bonus_category": "boost_combat",
                     "scope": "colony", "targets": "fleet attack power",
                     "desc": "Increases fleet attack power at base location by 1% per commander level."},
    "logistics":    {"name": "Logistics",    "bonus_per_level": 0.01, "bonus_category": "reduce_travel",
                     "scope": "colony+guild", "targets": "fleet travel time",
                     "desc": "Decreases fleet travel time by 1% per level for owner and guild members departing from this base."},
}

# Backwards-compatible alias
COMMANDER_SKILL_INFO = COMMANDER_SKILL_SPECS

def generate_commander_name():
    return f"{random.choice(COMMANDER_FIRST_NAMES)} {random.choice(COMMANDER_LAST_NAMES)}"

# ── Buildings (all 23 types) ──
# Credits = base_cost, energy/pop/area = per-level resource requirements
# "advanced" flag = appears under Advanced Structures
BUILDING_SPECS = {
    # contributions: data-driven stat formulas. Types:
    #   "flat"       — adds per_level × building_level to stat
    #   "planet_stat"— adds per_level × building_level × planet.<stat> to stat
    # Special stats: "fertility_modifier" adjusts effective fertility before population calc,
    #   "industrial" feeds into both construction and production.
    "urban_structures":     {"name": "Urban Structures",     "base_cost": 1,      "cost_mult": 1.5, "time": 60,   "desc": "+Pop based on Fertility",           "energy_req": 0,  "pop_req": 0, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False, "start_level": 1,
        "contributions": {"population": {"type": "planet_stat", "stat": "fertility", "per_level": 1}}},
    "solar_plants":         {"name": "Solar Plants",         "base_cost": 1,      "cost_mult": 1.5, "time": 60,   "desc": "+Energy based on Solar",             "energy_req": 0,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"energy": {"type": "planet_stat", "stat": "solar", "per_level": 1}}},
    "gas_plants":           {"name": "Gas Plants",           "base_cost": 1,      "cost_mult": 1.5, "time": 60,   "desc": "+Energy based on Gas",               "energy_req": 0,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"energy": {"type": "planet_stat", "stat": "gas", "per_level": 1}}},
    "fusion_plants":        {"name": "Fusion Plants",        "base_cost": 20,     "cost_mult": 1.5, "time": 120,  "desc": "+4 Energy (flat)",                   "energy_req": 0,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"energy": 6},                               "advanced": False,
        "contributions": {"energy": {"type": "flat", "per_level": 4}}},
    "antimatter_plants":    {"name": "Antimatter Plants",    "base_cost": 2000,   "cost_mult": 1.5, "time": 480,  "desc": "+10 Energy (flat)",                  "energy_req": 0,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"energy": 20},                              "advanced": True,
        "contributions": {"energy": {"type": "flat", "per_level": 10}}},
    "orbital_plants":       {"name": "Orbital Plants",       "base_cost": 40000,  "cost_mult": 1.5, "time": 1200, "desc": "+12 Energy (no area)",               "energy_req": 0,  "pop_req": 1, "area_req": 0, "max_level": 0, "tech_req": {"energy": 25},                              "advanced": True,
        "contributions": {"energy": {"type": "flat", "per_level": 12}}},
    "research_labs":        {"name": "Research Labs",        "base_cost": 2,      "cost_mult": 1.5, "time": 80,   "desc": "+Research capacity",                 "energy_req": 1,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"research": {"type": "flat", "per_level": 8}, "research_lab_level": {"type": "flat", "per_level": 1}}},
    "metal_refineries":     {"name": "Metal Refineries",     "base_cost": 1,      "cost_mult": 1.5, "time": 60,   "desc": "+Construction/Prod, +1 econ",        "energy_req": 1,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"industrial": {"type": "planet_stat", "stat": "metal", "per_level": 1}, "economy": {"type": "flat", "per_level": 1}}},
    "crystal_mines":        {"name": "Crystal Mines",        "base_cost": 2,      "cost_mult": 1.5, "time": 80,   "desc": "+Economy based on Crystal",          "energy_req": 1,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"economy": {"type": "planet_stat", "stat": "crystal", "per_level": 1}}},
    "robotic_factories":    {"name": "Robotic Factories",    "base_cost": 5,      "cost_mult": 1.5, "time": 100,  "desc": "+2 Construction/Prod, +1 econ",      "energy_req": 1,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"computer": 2},                             "advanced": False,
        "contributions": {"industrial": {"type": "flat", "per_level": 2}, "economy": {"type": "flat", "per_level": 1}}},
    "shipyard":             {"name": "Shipyard",             "base_cost": 5,      "cost_mult": 1.5, "time": 100,  "desc": "+2 Production, +1 econ, unlocks ships","energy_req": 1,"pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"production": {"type": "flat", "per_level": 2}, "economy": {"type": "flat", "per_level": 1}, "ground_shipyard": {"type": "flat", "per_level": 1}, "shipyard_level": {"type": "flat", "per_level": 1}}},
    "orbital_shipyard":     {"name": "Orbital Shipyard",     "base_cost": 10000,  "cost_mult": 1.5, "time": 960,  "desc": "+Prod (no area), extends ship access","energy_req": 12, "pop_req": 1, "area_req": 0, "max_level": 0, "tech_req": {"cybernetics": 2},                          "advanced": True,
        "contributions": {"production": {"type": "flat", "per_level": 8}, "economy": {"type": "flat", "per_level": 2}, "orbital_shipyard": {"type": "flat", "per_level": 1}, "shipyard_level": {"type": "flat", "per_level": 2}}},
    "spaceports":           {"name": "Spaceports",           "base_cost": 5,      "cost_mult": 1.5, "time": 100,  "desc": "+2 econ/hr, trade routes",           "energy_req": 1,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {},                                          "advanced": False,
        "contributions": {"economy": {"type": "flat", "per_level": 2}}},
    "command_centers":      {"name": "Command Centers",      "base_cost": 20,     "cost_mult": 1.5, "time": 120,  "desc": "+5% fleet attack at base",           "energy_req": 1,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"computer": 6},                             "advanced": False,
        "contributions": {"command_level": {"type": "flat", "per_level": 1}}},
    "nanite_factories":     {"name": "Nanite Factories",     "base_cost": 80,     "cost_mult": 1.5, "time": 240,  "desc": "+4 Construction/Prod, +2 econ",      "energy_req": 2,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"computer": 10, "laser": 8},                "advanced": True,
        "contributions": {"industrial": {"type": "flat", "per_level": 4}, "economy": {"type": "flat", "per_level": 2}}},
    "android_factories":    {"name": "Android Factories",    "base_cost": 1000,   "cost_mult": 1.5, "time": 480,  "desc": "+Construction/Prod, +2 econ",        "energy_req": 4,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"artificial_intelligence": 4},              "advanced": True,
        "contributions": {"industrial": {"type": "flat", "per_level": 6}, "economy": {"type": "flat", "per_level": 2}}},
    "economic_centers":     {"name": "Economic Centers",     "base_cost": 80,     "cost_mult": 1.5, "time": 240,  "desc": "+3 econ (advanced)",                 "energy_req": 2,  "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"computer": 10},                            "advanced": True,
        "contributions": {"economy": {"type": "flat", "per_level": 3}}},
    "terraform":            {"name": "Terraform",            "base_cost": 80,     "cost_mult": 1.5, "time": 240,  "desc": "+5 Area per level",                  "energy_req": 0,  "pop_req": 0, "area_req": 0, "max_level": 0, "tech_req": {"computer": 10, "energy": 10},              "advanced": True,
        "contributions": {"area": {"type": "flat", "per_level": 5}}},
    "multi_level_platforms":{"name": "Multi-Level Platforms", "base_cost": 10000, "cost_mult": 1.5, "time": 960,  "desc": "+10 Area per level",                 "energy_req": 0,  "pop_req": 0, "area_req": 0, "max_level": 0, "tech_req": {"armour": 22},                              "advanced": True,
        "contributions": {"area": {"type": "flat", "per_level": 10}}},
    "orbital_base":         {"name": "Orbital Base",         "base_cost": 2000,   "cost_mult": 1.5, "time": 480,  "desc": "+10 Population (no area)",           "energy_req": 0,  "pop_req": 0, "area_req": 0, "max_level": 0, "tech_req": {"computer": 20},                            "advanced": True,
        "contributions": {"population": {"type": "flat", "per_level": 10}}},
    "biosphere_mod":        {"name": "Biosphere Modification","base_cost": 20000, "cost_mult": 1.5, "time": 1200, "desc": "+1 Fertility per level",             "energy_req": 24, "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"computer": 24, "energy": 24},              "advanced": True,
        "contributions": {"fertility_modifier": {"type": "flat", "per_level": 1}}},
    "capital":              {"name": "Capital",              "base_cost": 15000,  "cost_mult": 1.5, "time": 1440, "desc": "+10 econ, +1 econ all other bases, -15% income if occupied", "energy_req": 12, "pop_req": 1, "area_req": 1, "max_level": 0, "tech_req": {"tachyon_communications": 1}, "advanced": True, "unique": True,
        "contributions": {"economy": {"type": "flat", "per_level": 10}}},
    "jump_gate":            {"name": "Jump Gate",            "base_cost": 5000,   "cost_mult": 1.5, "time": 1200, "desc": "+fleet speed from base",              "energy_req": 12, "pop_req": 1, "area_req": 0, "max_level": 0, "tech_req": {"warp_drive": 12, "energy": 20},            "advanced": True,
        "contributions": {"jump_gate_level": {"type": "flat", "per_level": 1}}},
}

# ── Research (all 17 technologies) ──
RESEARCH_SPECS = {
    "energy":                {"name": "Energy",                "base_cost": 2,      "cost_mult": 1.5, "base_time": 80,   "lab_req": 1,  "prereqs": {},                                           "icon": "⚡", "bonus": "+5% energy output per level",
                              "bonuses": [{"type": "stat_multiplier", "stat": "energy", "per_level": 0.05}]},
    "computer":              {"name": "Computer",              "base_cost": 2,      "cost_mult": 1.5, "base_time": 80,   "lab_req": 1,  "prereqs": {},                                           "icon": "💻", "bonus": "Allows one campaign fleet per level",
                              "bonuses": [{"type": "fleet_count", "per_level": 1}]},
    "armour":                {"name": "Armour",                "base_cost": 4,      "cost_mult": 1.5, "base_time": 120,  "lab_req": 2,  "prereqs": {},                                           "icon": "🛡️", "bonus": "+5% armour per level",
                              "bonuses": [{"type": "combat_stat", "stat": "armour", "per_level": 0.05}]},
    "laser":                 {"name": "Laser",                 "base_cost": 4,      "cost_mult": 1.5, "base_time": 120,  "lab_req": 2,  "prereqs": {"energy": 2},                                "icon": "🔴", "bonus": "+5% laser weapon power",
                              "bonuses": [{"type": "weapon_power", "weapon": "laser", "per_level": 0.05}]},
    "missiles":              {"name": "Missiles",              "base_cost": 8,      "cost_mult": 1.5, "base_time": 180,  "lab_req": 4,  "prereqs": {"computer": 4},                              "icon": "🚀", "bonus": "+5% missile power",
                              "bonuses": [{"type": "weapon_power", "weapon": "missiles", "per_level": 0.05}]},
    "stellar_drive":         {"name": "Stellar Drive",         "base_cost": 16,     "cost_mult": 1.5, "base_time": 240,  "lab_req": 5,  "prereqs": {"energy": 6},                                "icon": "🌟", "bonus": "+5% stellar ship speed",
                              "bonuses": [{"type": "speed_multiplier", "drive": "stellar", "per_level": 0.05}]},
    "plasma":                {"name": "Plasma",                "base_cost": 32,     "cost_mult": 1.5, "base_time": 360,  "lab_req": 6,  "prereqs": {"energy": 6, "laser": 4},                    "icon": "🟣", "bonus": "+5% plasma weapon power",
                              "bonuses": [{"type": "weapon_power", "weapon": "plasma", "per_level": 0.05}]},
    "warp_drive":            {"name": "Warp Drive",            "base_cost": 64,     "cost_mult": 1.5, "base_time": 400,  "lab_req": 8,  "prereqs": {"energy": 8, "stellar_drive": 4},            "icon": "🌀", "bonus": "Enables warp-drive ships",
                              "bonuses": [{"type": "unlock", "unlocks": "warp_ships"}]},
    "shielding":             {"name": "Shielding",             "base_cost": 128,    "cost_mult": 1.5, "base_time": 480,  "lab_req": 10, "prereqs": {"energy": 10},                               "icon": "🔵", "bonus": "+5% shield strength",
                              "bonuses": [{"type": "combat_stat", "stat": "shield", "per_level": 0.05}]},
    "ion":                   {"name": "Ion",                   "base_cost": 256,    "cost_mult": 1.5, "base_time": 720,  "lab_req": 12, "prereqs": {"energy": 12, "laser": 10},                  "icon": "⚛️", "bonus": "+5% ion weapon power",
                              "bonuses": [{"type": "weapon_power", "weapon": "ion", "per_level": 0.05}]},
    "stealth":               {"name": "Stealth",               "base_cost": 512,    "cost_mult": 1.5, "base_time": 800,  "lab_req": 14, "prereqs": {"energy": 14},                               "icon": "👻", "bonus": "Decreases the time your own fleets can be detected before they arrive",
                              "bonuses": [{"type": "stealth", "per_level": 0.10}]},
    "photon":                {"name": "Photon",                "base_cost": 1024,   "cost_mult": 1.5, "base_time": 1200, "lab_req": 16, "prereqs": {"energy": 16, "plasma": 8},                  "icon": "✨", "bonus": "+5% photon weapon power",
                              "bonuses": [{"type": "weapon_power", "weapon": "photon", "per_level": 0.05}]},
    "artificial_intelligence":{"name": "Artificial Intelligence","base_cost": 2048, "cost_mult": 1.5, "base_time": 1600, "lab_req": 18, "prereqs": {"computer": 20},                             "icon": "🤖", "bonus": "Increases all bases research output by 5%",
                              "bonuses": [{"type": "stat_multiplier", "stat": "research", "per_level": 0.05}]},
    "disruptor":             {"name": "Disruptor",             "base_cost": 4096,   "cost_mult": 1.5, "base_time": 2000, "lab_req": 20, "prereqs": {"energy": 20, "laser": 18},                  "icon": "💥", "bonus": "+5% disruptor weapon power",
                              "bonuses": [{"type": "weapon_power", "weapon": "disruptor", "per_level": 0.05}]},
    "cybernetics":           {"name": "Cybernetics",           "base_cost": 8192,   "cost_mult": 1.5, "base_time": 2400, "lab_req": 22, "prereqs": {"artificial_intelligence": 6},               "icon": "🦾", "bonus": "Increases all bases construction and production by 5%",
                              "bonuses": [{"type": "stat_multiplier", "stat": "construction", "per_level": 0.05}, {"type": "stat_multiplier", "stat": "production", "per_level": 0.05}]},
    "tachyon_communications":{"name": "Tachyon Communications","base_cost": 32768,  "cost_mult": 1.5, "base_time": 3200, "lab_req": 24, "prereqs": {"energy": 24, "computer": 24},              "icon": "📡", "bonus": "Allows 1 research link between 2 bases (min labs 20)",
                              "bonuses": [{"type": "research_link", "per_level": 1, "min_lab_level": 20}]},
    "anti_gravity":          {"name": "Anti-Gravity",          "base_cost": 100000, "cost_mult": 1.5, "base_time": 4800, "lab_req": 26, "prereqs": {"energy": 26, "computer": 26},              "icon": "🔮", "bonus": "Decreases orbital structures construction time by 5% and increases Capital Ship 2 speed by 5%",
                              "bonuses": [{"type": "orbital_build_time", "per_level": -0.05}, {"type": "speed_multiplier", "ship": "capital_ship_2", "per_level": 0.05}]},
}

# ── Defenses (all 10 types) ──
DEFENSE_SPECS = {
    # Each level = +5 units. Cost scales 1.5x/level. Energy/area/pop per level.
    # Each level of defenses requires 1 Population.
    "barracks":           {"name": "Barracks",           "desc": "Help protect your bases, the cheapest defense.", "cost": 5,     "cost_mult": 1.5, "energy_req": 0,  "pop_req": 1, "area_req": 1, "attack": 4,    "armour": 4,    "shield": 0,  "weapon": "laser",     "max_level": 50, "req": {"laser": 1}},
    "laser_turrets":      {"name": "Laser Turrets",      "desc": "Small defenses, good against small units.", "cost": 10,    "cost_mult": 1.5, "energy_req": 1,  "pop_req": 1, "area_req": 1, "attack": 8,    "armour": 8,    "shield": 0,  "weapon": "laser",     "max_level": 50, "req": {"laser": 1}},
    "missile_turrets":    {"name": "Missile Turrets",    "desc": "Small defenses, good against small and medium units.", "cost": 20,    "cost_mult": 1.5, "energy_req": 1,  "pop_req": 1, "area_req": 1, "attack": 16,   "armour": 16,   "shield": 0,  "weapon": "missiles",  "max_level": 50, "req": {"missiles": 1}},
    "plasma_turrets":     {"name": "Plasma Turrets",     "desc": "Average defenses, good against medium units.", "cost": 100,   "cost_mult": 1.5, "energy_req": 2,  "pop_req": 1, "area_req": 1, "attack": 24,   "armour": 24,   "shield": 0,  "weapon": "plasma",    "max_level": 50, "req": {"plasma": 1, "armour": 6}},
    "ion_turrets":        {"name": "Ion Turrets",        "desc": "Average defenses, good against medium units.", "cost": 250,   "cost_mult": 1.5, "energy_req": 3,  "pop_req": 1, "area_req": 1, "attack": 40,   "armour": 40,   "shield": 2,  "weapon": "ion",       "max_level": 50, "req": {"ion": 1, "armour": 10, "shielding": 2}},
    "photon_turrets":     {"name": "Photon Turrets",     "desc": "Big defenses, good against large units.", "cost": 1000,  "cost_mult": 1.5, "energy_req": 4,  "pop_req": 1, "area_req": 1, "attack": 80,   "armour": 80,   "shield": 6,  "weapon": "photon",    "max_level": 50, "req": {"photon": 1, "armour": 14, "shielding": 6}},
    "disruptor_turrets":  {"name": "Disruptor Turrets",  "desc": "Biggest turrets, good against large units.", "cost": 4000,  "cost_mult": 1.5, "energy_req": 8,  "pop_req": 1, "area_req": 1, "attack": 320,  "armour": 320,  "shield": 8,  "weapon": "disruptor", "max_level": 50, "req": {"disruptor": 1, "armour": 18, "shielding": 8}},
    "deflection_shields": {"name": "Deflection Shields", "desc": "Strong shields that increase bases protection.", "cost": 4000,  "cost_mult": 1.5, "energy_req": 8,  "pop_req": 1, "area_req": 1, "attack": 2,    "armour": 640,  "shield": 16, "weapon": "ion",       "max_level": 50, "req": {"ion": 6, "shielding": 10}},
    "planetary_shield":   {"name": "Planetary Shield",   "desc": "Massive shield protecting the entire planet.", "cost": 25000, "cost_mult": 1.5, "energy_req": 16, "pop_req": 1, "area_req": 1, "attack": 4,    "armour": 2000, "shield": 20, "weapon": "ion",       "max_level": 50, "req": {"ion": 10, "shielding": 14}},
    "planetary_ring":     {"name": "Planetary Ring",     "desc": "Orbital ring of heavy weapons platforms.", "cost": 50000, "cost_mult": 1.5, "energy_req": 24, "pop_req": 1, "area_req": 0, "attack": 1600, "armour": 1000, "shield": 12, "weapon": "photon",    "max_level": 50, "req": {"photon": 10, "armour": 22, "shielding": 12}},
}

# ── Planet terrain types (15 terrain types + non-colonizable primary bodies) ──
# Stats are base values before orbit position modifiers
# area_planet and area_moon are separate — asteroids have no planet area (None)
    # Terrain != body type. Any terrain except Asteroid can be a planet or moon.
    # During world generation, each astro gets a body_type and a terrain.
PLANET_TYPE_STATS = {
    # Planet terrain balance data used by generated systems
    # Solar is 0 base; orbit modifiers add the solar bonus per position
    #                  metal gas  crystals fertility area_planet area_moon
    "arid":           {"name": "Arid",          "solar": 0, "gas": 3, "fertility": 5, "area_planet": 95, "area_moon": 83, "metal": 3, "crystal": 0},
    "asteroid":       {"name": "Asteroid",      "solar": 0, "gas": 2, "fertility": 4, "area_planet": None, "area_moon": 65, "metal": 4, "crystal": 2},
    "asteroid_belt":  {"name": "Asteroid Belt", "solar": 0, "gas": 0, "fertility": 0, "area_planet": None, "area_moon": None,"metal": 0, "crystal": 0, "colonizable": False},
    "craters":        {"name": "Craters",       "solar": 0, "gas": 2, "fertility": 4, "area_planet": 85, "area_moon": 75, "metal": 4, "crystal": 2},
    "crystalline":    {"name": "Crystalline",   "solar": 0, "gas": 2, "fertility": 4, "area_planet": 80, "area_moon": 71, "metal": 3, "crystal": 3},
    "earthly":        {"name": "Earthly",       "solar": 0, "gas": 3, "fertility": 6, "area_planet": 85, "area_moon": 75, "metal": 3, "crystal": 0},
    "gaia":           {"name": "Gaia",          "solar": 0, "gas": 2, "fertility": 6, "area_planet": 90, "area_moon": 79, "metal": 3, "crystal": 0},
    "glacial":        {"name": "Glacial",       "solar": 0, "gas": 4, "fertility": 5, "area_planet": 95, "area_moon": 83, "metal": 2, "crystal": 0},
    "magma":          {"name": "Magma",         "solar": 0, "gas": 5, "fertility": 5, "area_planet": 80, "area_moon": 71, "metal": 3, "crystal": 0},
    "metallic":       {"name": "Metallic",      "solar": 0, "gas": 2, "fertility": 4, "area_planet": 85, "area_moon": 75, "metal": 4, "crystal": 2},
    "oceanic":        {"name": "Oceanic",       "solar": 0, "gas": 4, "fertility": 6, "area_planet": 80, "area_moon": 71, "metal": 2, "crystal": 0},
    "radioactive":    {"name": "Radioactive",   "solar": 0, "gas": 4, "fertility": 4, "area_planet": 90, "area_moon": 79, "metal": 3, "crystal": 0},
    "rocky":          {"name": "Rocky",         "solar": 0, "gas": 2, "fertility": 5, "area_planet": 85, "area_moon": 75, "metal": 4, "crystal": 0},
    "toxic":          {"name": "Toxic",         "solar": 0, "gas": 5, "fertility": 4, "area_planet": 90, "area_moon": 79, "metal": 3, "crystal": 0},
    "tundra":         {"name": "Tundra",        "solar": 0, "gas": 3, "fertility": 5, "area_planet": 95, "area_moon": 83, "metal": 3, "crystal": 0},
    "volcanic":       {"name": "Volcanic",      "solar": 0, "gas": 5, "fertility": 5, "area_planet": 80, "area_moon": 71, "metal": 3, "crystal": 0},
    "gas_giant":      {"name": "Gas Giant",     "solar": 0, "gas": 6, "fertility": 0, "area_planet": None,"area_moon": None,"metal": 0, "crystal": 0, "colonizable": False},
}

# ── Galaxy Presets ──
# Each preset defines generation parameters.
# Add new presets here and they auto-appear in the admin dropdown.
GALAXY_PRESETS = {
    "standard": {
        "name": "Standard",
        "desc": "Standard galaxy — 10×10 regions, spiral density, ~745 systems, ~4200 astros",
        "regions_per_galaxy": 100,
        "systems_per_region": 44,
        "regions_grid_w": 10,
        "regions_grid_h": 10,
    },
    "mss": {
        "name": "MSS",
        "desc": "Mini Speed Server — single galaxy, configurable active region size, no wormholes",
        "num_clusters": 1,
        "galaxies_per_cluster": 1,
        "regions_per_galaxy": 100,
        "systems_per_region": 44,
        "regions_grid_w": 10,
        "regions_grid_h": 10,
        "active_region_size": 4,  # default 4×4 center, configurable via admin (2/4/6/8)
        "wormholes": False,
    },
}

# ── Astro body categories ──
# Body type (Planet/Moon/Asteroid/Gas Giant) is separate from terrain type.
# Any terrain except "asteroid" can be either a Planet or a Moon.
# Only "asteroid" is always an Asteroid.
# The body type is assigned during world generation and stored on the Planet model.
# This function is a FALLBACK for legacy code — new code should use planet.body_type directly.
ASTRO_CATEGORY = {
    "asteroid": "Asteroid",
    "asteroid_belt": "Asteroid",
    "gas_giant": "Gas Giant",
    # All other terrains can be Planet or Moon — determined at generation time
}

def get_astro_category(planet_type, body_type=None):
    """Return the astro body category (Planet, Moon, Asteroid, or Gas Giant).
    If body_type is provided (from DB), use it directly.
    Otherwise fall back to terrain-based guess (only reliable for asteroids).
    """
    if body_type:
        return body_type
    return ASTRO_CATEGORY.get(planet_type, "Planet")

# ── Orbit position modifiers (positions 1-5) ──
# V3 values from original game data:
#   Solar Energy: 5, 4, 3, 2, 2
#   Fertility: -1, 0, +1, +1, 0
#   Gas: 0, 0, 0, +1, +2
ORBIT_MODIFIERS = {
    # Orbit:         1    2    3    4    5
    "solar":      [  5,   4,   3,   2,   2],
    "fertility":  [ -1,   0,   1,   1,   0],
    "gas":        [  0,   0,   0,   1,   2],
}

# Server naming: one server = one letter. A=Alpha, B=Beta, etc.
SERVER_NAMES = {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta", "E": "Epsilon",
                "F": "Zeta", "G": "Eta", "H": "Theta", "I": "Iota", "J": "Kappa"}


# ======================== DEFINITION → RUNTIME SPEC SYNC ========================
#
# The engine resolves specs (build, combat, catalog, admin) through these module
# dicts/list. To make a ruleset mod actually swap the unit roster, the active
# game definition's content is synced INTO these structures IN PLACE on
# set_game_definition — so every consumer (including the ~70 ALL_SHIP_TYPES call
# sites and combat loops) uses the active ruleset's content with no call-site
# changes. Categories the definition omits fall back to the pristine engine
# defaults captured here at import (before any sync).

import copy as _copy

# Deep-copied so nested req/bonuses/contributions can't be mutated through the
# live dicts (a ruleset swap or override editing a nested value must not corrupt
# the pristine defaults).
_PRISTINE_SPECS = {
    "ships": _copy.deepcopy(SHIP_SPECS),
    "buildings": _copy.deepcopy(BUILDING_SPECS),
    "research": _copy.deepcopy(RESEARCH_SPECS),
    "defenses": _copy.deepcopy(DEFENSE_SPECS),
    "weapon_types": _copy.deepcopy(WEAPON_TYPES),
    "terrains": _copy.deepcopy(PLANET_TYPE_STATS),
}

# category -> (live dict, definition key)
_SYNC_TARGETS = (
    (SHIP_SPECS, "ships"),
    (BUILDING_SPECS, "buildings"),
    (RESEARCH_SPECS, "research"),
    (DEFENSE_SPECS, "defenses"),
    (WEAPON_TYPES, "weapon_types"),
    (PLANET_TYPE_STATS, "terrains"),
)

# Engine-expected optional ship fields. A ruleset mod only has to provide the
# validator-required fields (name/cost/attack/armour/shield/weapon); these
# defaults are merged so consumers that read optional fields directly (shipyard
# requirement, drive, hangar, …) don't crash on a minimal mod ship.
_SHIP_FIELD_DEFAULTS = {
    "desc": "", "speed": 0, "hangar": 0, "drive": "inter",
    "shipyard": 0, "req": {}, "rounding": 0,
}


def pristine_specs(category: str) -> dict:
    """The engine-default content for a category (independent of any active mod)."""
    return _copy.deepcopy(_PRISTINE_SPECS.get(category, {}))


def apply_definition_specs(definition: dict):
    """Sync a (compiled) game definition's content into the live spec structures
    in place. Categories the definition doesn't provide revert to pristine
    defaults, so this is also how the engine swaps back to the default ruleset."""
    definition = definition or {}
    for target, key in _SYNC_TARGETS:
        src = definition.get(key) or _PRISTINE_SPECS[key]
        target.clear()
        if key == "ships":
            # Backfill engine-expected optional fields so minimal mod ships work.
            target.update({k: {**_SHIP_FIELD_DEFAULTS, **_copy.deepcopy(v)} for k, v in src.items()})
        else:
            target.update({k: _copy.deepcopy(v) for k, v in src.items()})
    # Keep the canonical ship-type list in sync (mutated in place so existing
    # `from specs import ALL_SHIP_TYPES` references see the new roster).
    ALL_SHIP_TYPES[:] = list(SHIP_SPECS.keys())
