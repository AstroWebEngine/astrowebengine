"""
Centralized game configuration defaults.
All gameplay-affecting constants should be defined here with their default values.
These can be overridden at runtime via the game_config table using get_config_float/get_config_int.

When this becomes a game engine, server operators modify these via admin panel
without touching code.
"""

# ── Queue Limits ──
CONSTRUCTION_QUEUE_MAX = 6          # Max items per base construction queue (1 active + 5 queued)
RESEARCH_QUEUE_MAX = 6              # Max items in global research queue (1 active + 5 queued)
PRODUCTION_QUEUE_MAX = 12           # Max items per base ship production queue (1 active + 11 queued)
FLEET_SPLIT_MIN = 2                 # Minimum fleets to split into
FLEET_SPLIT_MAX = 10                # Maximum fleets to split into

# ── Fleet & Movement ──
# Travel time formula:
#   travel_time_hours = distance / speed_units_per_hour
#   speed_units_per_hour = base_speed * (1 + drive_tech / 20)
# Convert hours to seconds with 3600, then divide by game_speed.
FLEET_TRAVEL_DIVISOR = 3600         # travel_time = distance * this / (speed * mult * game_speed)
BASE_FLEET_COUNT = 5                # Starting fleet command slots (+ computer tech)
FLEET_SIZE_LIMIT_MULTIPLIER = 2500  # Fleet size limit = total_production * this
DEFAULT_MIN_SPEED = 1               # Fallback speed for fleets with no speed data

# ── Autoscout ──
AUTOSCOUT_DWELL_SECONDS = 120       # Real-time seconds scout sits at region (not speed-adjusted)
AUTOSCOUT_PER_COMPUTER_LEVELS = 5   # 1 autoscout per this many Computer tech levels

# ── Detection ──
DETECTION_HOURS_CAP = 24            # Max detection time in hours
DETECTION_SENSOR_BASE = 200000      # Sensor formula base constant
DETECTION_FLEET_SIZE_MULT = 1.6     # Fleet size multiplier in detection formula
DETECTION_STEALTH_BASE = 0.9        # Stealth decay base (0.9 ^ stealth_level)
DETECTION_MIN_HOURS = 1 / 60        # Minimum detection time (~1 minute)
DETECTION_MAX_HOURS = 24            # Maximum detection time

# ── Combat ──
DAMAGE_ALLOCATION_EXPONENT = 0.85   # Proportional damage allocation exponent
COMBAT_LOOT_PERCENT = 0.20          # Each side gets this % of destroyed value as loot
DEBRIS_PERCENT = 0.40               # This % of destroyed value becomes debris
ION_SHIELD_PASSTHROUGH = 0.50       # Ion weapons vs shields: 50% passthrough
NORMAL_SHIELD_PASSTHROUGH = 0.01    # Normal weapons vs shields: 1% passthrough
WEAPON_TECH_DIVISOR = 20            # power = base * (1 + wpn_tech / this)
ARMOUR_TECH_DIVISOR = 20            # armour = base * (1 + arm_tech / this)
SHIELDING_TECH_DIVISOR = 20         # shield = base * (1 + shd_tech / this)
COMMAND_CENTER_DIVISOR = 20         # CC bonus: 1 + cc_lv / this
TACTICAL_COMMANDER_DIVISOR = 100    # TC bonus: tc_lv / this
DEFENSE_COMMANDER_DIVISOR = 100     # DC bonus: 1 + dc_lv / this
CAPITAL_SHIP_1_BONUS_MULT = 1.05    # Primary flagship fleet bonus to power+armour
CAPITAL_SHIP_2_BONUS_MULT = 1.10    # Secondary flagship bonus (overrides primary)
COMBAT_SCORE_DIVISOR = 100          # Score gained = destroyed_value / this
EXPERIENCE_PERCENT = 0.05           # XP = this % of total destroyed value

# ── Economy & Production ──
CONSTRUCTION_BONUS_BASE = 20        # Flat construction bonus for all bases
CONSTRUCTION_BONUS_HOMEWORLD = 20   # Additional construction bonus for homeworld
CYBERNETICS_BONUS_PER_LEVEL = 0.05  # +5% construction/production per cybernetics level
AI_TECH_BONUS_PER_LEVEL = 0.05      # +5% research per AI tech level
RESEARCH_LAB_RATE = 8               # Research output per lab level
LAB_CAPACITY_PER_LEVEL = 6          # Lab capacity units per research_labs level
SHIPYARD_PRODUCTION_MULT = 2        # Production per shipyard level
ORBITAL_SHIPYARD_PRODUCTION_MULT = 8  # Production per orbital shipyard level
ORBITAL_SHIPYARD_EFFECTIVE_MULT = 2 # Effective shipyard = orbital_sy * this
BASE_ENERGY_BONUS = 2               # Flat energy bonus per colony

# ── Building Stat Multipliers ──
ROBOTIC_FACTORY_INDUSTRIAL_MULT = 2
NANITE_FACTORY_INDUSTRIAL_MULT = 4
ANDROID_FACTORY_INDUSTRIAL_MULT = 6
FUSION_PLANT_ENERGY = 4
ANTIMATTER_PLANT_ENERGY = 10
ORBITAL_PLANT_ENERGY = 12
TERRAFORM_AREA_PER_LEVEL = 5
MLP_AREA_PER_LEVEL = 10
BIOSPHERE_FERTILITY_PER_LEVEL = 1
ORBITAL_BASE_POP_PER_LEVEL = 10

# ── Economy Formula Multipliers ──
ECON_METAL_REFINERIES = 1
ECON_ROBOTIC_FACTORIES = 1
ECON_NANITE_FACTORIES = 2
ECON_ANDROID_FACTORIES = 2
ECON_SHIPYARD = 1
ECON_ORBITAL_SHIPYARD = 2
ECON_SPACEPORTS = 2
ECON_ECONOMIC_CENTERS = 3
ECON_CAPITAL = 10
CAPITAL_EMPIRE_BONUS = 1                # +1 economy to all OTHER bases when player has a Capital
CAPITAL_OCCUPIED_PENALTY = 0.15         # -15% empire income when Capital base is occupied

# ── Jump Gates ──
JUMP_GATE_SPEED_BONUS_PER_LEVEL = 0.70  # +70% fleet speed per Jump Gate level (was 1.0 = 100%)

# ── Wormholes ──
WORMHOLE_SPEED_PER_JG_LEVEL = 0.50      # Speed factor bonus per avg top JG level
WORMHOLE_TOP_JG_COUNT = 5               # How many top Jump Gate levels to average
WORMHOLE_INNER_REGIONS = [44, 45, 54, 55]  # Center 2×2 of 10×10 galaxy grid

# ── Build & Research Times ──
OCCUPATION_TIME_PENALTY = 1.3       # +30% build time when occupied
MIN_BUILD_TIME_SECONDS = 5          # Minimum construction time
MIN_RESEARCH_TIME_SECONDS = 5       # Minimum research time

# ── Trade ──
TRADE_ROUTE_COST_MULTIPLIER = 2     # Trade route setup cost = this * distance
TRADE_DISTANCE_DIVISOR = 75         # In trade income formula
TRADE_PLAYERS_DIVISOR = 10          # In trade income formula
SELF_TRADE_BONUS_MULT = 2.0         # Self-trade income multiplier
TRADE_ROUTES_PER_SPACEPORT_LEVELS = 5  # +1 route per this many spaceport levels
TRADE_CLOSING_HOURS_SHORT = 12      # Closing time for distance < threshold
TRADE_CLOSING_HOURS_LONG = 24       # Closing time for distance >= threshold
TRADE_CLOSING_DISTANCE_THRESHOLD = 1000
TRADE_CLOSING_REFUND_PERCENT = 0.25  # 25% of total cost refunded to each player
PUBLIC_TRADE_LISTING_HOURS = 48     # How long a public trade listing stays visible

# ── Occupation & Unrest ──
OCCUPIER_INCOME_SHARE = 0.30        # Occupier gets this % of base income
UNREST_INCREASE_PER_DAY = 0.10      # +10% unrest per day while occupied
UNREST_DECAY_PER_DAY = 0.10         # -10% unrest per day after freed
UNREST_SLOW_DECAY = 0.001           # Slow passive unrest decay per tick
DEFENSE_REGEN_PER_HOUR = 0.01       # +1% defense effectiveness per hour when free
POST_REVOLT_UNREST = 0.40           # Unrest level after a revolt

# ── NPC Factions ──
NPC_SETTLERS_BASES_START = 5              # Starting Settlers bases per galaxy
NPC_SETTLERS_BASES_MIN = 2                # Minimum Settlers bases per galaxy
NPC_SETTLERS_BASES_REDUCTION_PER_YEAR = 1 # Settlers target drops by this many bases per year
NPC_SETTLERS_AUTO_MAINTAIN_ENABLED = True # Replace missing Settlers bases up to current target
NPC_SETTLERS_STABILITY_ENABLED = True      # Settlers stability decays daily at server midnight
NPC_SETTLERS_STABILITY_INITIAL = 1.0       # 100% starting stability
NPC_SETTLERS_STABILITY_DECAY_PER_DAY = 0.03  # -3% stability per day

# ── Pillage ──
PILLAGE_COOLDOWN_HOURS = 24         # Can't pillage same base more than once per this
PILLAGE_MAX_HOURS = 100             # Cap on hours since last collection for pillage calc
PILLAGE_ECONOMY_MULT = 8            # Player pillage: economy * this * time_fraction
PILLAGE_NPC_MULT = 16               # NPC pillage: economy * this * time_fraction
PILLAGE_ADDITIONAL_BONUS_MULT = 5   # Additional bonus = (actual income - new income)^2 * this

# ── Post-Occupation Recovery ──
ECONOMY_RECOVERY_RATE = 1           # Economy points recovered per tick
ECONOMY_RECOVERY_HOURS = 8          # Hours between each economy recovery tick
DEFENSE_REPAIR_PCT_PER_HOUR = 0.01  # 1% defense repair per hour (not while occupied)

# ── Protection ──
PROTECTION_BROKEN_HOURS = 48        # Hours of protection removed when attacking
NEWBIE_PROTECTION_LEVEL = 10        # Below this level, newbie rules apply

# ── Colonization ──
COLONIZE_SCORE_BONUS = 20           # Score bonus for establishing a new colony

# ── Recycling ──
RECYCLER_RATE_PER_UNIT = 10         # Credits collected per recycler per tick

# ── Disband / Downgrade Refunds ──
FLEET_DISBAND_REFUND_HOME = 0.50    # Fleet disbanded while stationed at your own base → 50% of value
FLEET_DISBAND_REFUND_AWAY = 0.25    # Fleet disbanded while stationed away from your base → 25% of value
                                    # Fleet in transit → 0% (no refund)
STRUCTURE_DOWNGRADE_REFUND_PERCENT = 0.50  # 50% of structure cost → base reserve (discount on next base)
COLONY_REBUILD_DISCOUNT = 0.25      # New base costs 25% of normal while below your peak base count

# ── Distance Defaults ──
SAME_CLUSTER_GALAXY_DISTANCE = 200  # Distance between galaxies in same cluster
CROSS_CLUSTER_DISTANCE = 1000       # Distance between different clusters

# ── Player Level ──
PLAYER_LEVEL_ECONOMY_MULT = 100     # Economy weight in level formula
PLAYER_LEVEL_EXPONENT = 0.25        # Level = (economy*mult + fleet + tech) ^ this

# ── Guild ──
GUILD_HIDE_DURATION_HOURS = 24      # How long fleet stays hidden from guild view

# ── Background Ticks ──
QUEUE_TICK_INTERVAL = 10            # Seconds between queue processing ticks
FLEET_ARRIVAL_TICK_INTERVAL = 1     # Seconds between server-side fleet arrival processing ticks
AUTOSCOUT_TICK_INTERVAL = 1         # Seconds between autoscout processing ticks

# ── Repair ──
REPAIR_COST_FRACTION = 0.50         # Repair cost = ship_cost * damage * this

# ── Commanders ──
COMMANDER_RECRUIT_XP_COST = 20      # XP cost to recruit a new commander
COMMANDER_RECRUIT_CREDIT_COST = 40  # Credit cost to recruit a new commander
COMMANDER_TRAVEL_INITIAL_SECONDS = 600  # 10 min for fresh recruits to reach any base
COMMANDER_BONUS_PER_LEVEL = 0.01    # 1% bonus per commander level
COMMANDER_TRAIN_TIME_PER_LEVEL = 3600  # 1 hour per target level (capped at 8h)
COMMANDER_TRAIN_TIME_CAP = 28800    # 8 hour max training time
COMMANDER_TRAIN_XP_BASE = 20        # XP cost base: 20 * 1.5^level
COMMANDER_TRAIN_XP_MULT = 1.5       # Training XP cost multiplier per level
COMMANDER_TRAIN_CREDIT_MULT = 2     # Credit cost = XP cost * this
COMMANDER_MAX_LEVEL = 20            # Hard cap on commander level
COMMANDER_XP_ONLY_ABOVE = 8         # Above this level, can only use XP to train (not credits)
COMMANDER_PILLAGE_KILL_CHANCE = 0.10  # 10% chance per commander at pillaged base
