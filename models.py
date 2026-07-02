"""
SQLAlchemy models and Pydantic request/response models for AstroWebEngine
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import json

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey, Text, func, Index
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship


class JSONCost(TypeDecorator):
    """A queued-item cost that is either a scalar (single-resource economy) or a
    per-resource dict (multi-resource, e.g. metal/crystal/deuterium). Persists as
    JSON text and reads back the original type, so the charge-on-advance logic
    (can_afford/deduct_cost) gets the exact per-resource amounts. Tolerates legacy
    numeric values from the pre-multi-resource Float columns."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, (int, float)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
from pydantic import BaseModel, RootModel
try:
    from pydantic import EmailStr
except ImportError:
    EmailStr = str

from database import ModelBase

# ======================== SQLALCHEMY MODELS ========================

class User(ModelBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True)
    hashed_password = Column(String(200), nullable=False)
    is_admin = Column(Boolean, default=False)
    is_bot = Column(Boolean, default=False)  # NPC bot accounts
    bot_strategy = Column(String(20), nullable=True)  # 'builder', 'military', 'balanced'
    credits = Column(Float, default=500.0)
    resources_json = Column(Text, nullable=True)  # Multi-resource: {"metal": X, "crystal": Y, ...}
    score = Column(Integer, default=0)
    experience = Column(Float, default=0.0)  # combat XP
    base_reserve = Column(Float, default=0.0)  # discount credits from disbanding bases/structures (reduces next base cost)
    bases_founded_peak = Column(Integer, default=0)  # most bases ever held; rebuilding below this costs 25%
    action_points = Column(Float, default=0.0)  # action-point ("Turns") economy pool; inert unless enabled
    last_ap_accrual = Column(DateTime, nullable=True)  # last lazy action-point accrual timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
    newbie_protection_until = Column(DateTime, nullable=True)  # legacy, replaced by level-based protection
    protection_broken_until = Column(DateTime, nullable=True)  # 48h window when level protection is lost
    has_completed_tutorial = Column(Boolean, default=False)
    chosen_galaxy_id = Column(Integer, nullable=True)  # galaxy chosen at registration
    date_format = Column(String(10), default="MDY")  # MDY, DMY, or YMD
    show_bbcode_images = Column(Boolean, default=False)  # off by default to prevent IP tracking
    last_collected = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    last_changelog_seen = Column(Integer, default=0)  # ID of last changelog entry seen
    colonies = relationship("Colony", back_populates="user", foreign_keys="[Colony.user_id]")
    research = relationship("Research", back_populates="user")
    fleets = relationship("Fleet", back_populates="user")

class Cluster(ModelBase):
    """A cluster groups galaxies (e.g., x0-x9). Pumpkin map has 4 clusters."""
    __tablename__ = "clusters"
    id = Column(Integer, primary_key=True)
    name = Column(String(20), nullable=False)  # e.g. "Alpha", "Beta"
    cluster_index = Column(Integer, default=0)  # 0-based index for topology
    galaxies = relationship("Galaxy", back_populates="cluster")

class Galaxy(ModelBase):
    __tablename__ = "galaxies"
    id = Column(Integer, primary_key=True)
    name = Column(String(10), nullable=False)  # e.g. "A00", "A09", "B00"
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    galaxy_index = Column(Integer, default=0)  # 0-9 within cluster
    regions_grid_w = Column(Integer, default=10)  # grid width (e.g. 10 for 100 regions)
    regions_grid_h = Column(Integer, default=10)  # grid height
    cluster = relationship("Cluster", back_populates="galaxies")
    regions = relationship("Region", back_populates="galaxy")

class Region(ModelBase):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True)
    name = Column(String(20), nullable=False)
    galaxy_id = Column(Integer, ForeignKey("galaxies.id"))
    grid_x = Column(Integer, default=0)
    grid_y = Column(Integer, default=0)
    galaxy = relationship("Galaxy", back_populates="regions")
    systems = relationship("StarSystem", back_populates="region")

class StarSystem(ModelBase):
    __tablename__ = "star_systems"
    id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"))
    star_type = Column(String(20), default="yellow")
    region = relationship("Region", back_populates="systems")
    planets = relationship("Planet", back_populates="system")

class Planet(ModelBase):
    __tablename__ = "planets"
    id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=False)
    system_id = Column(Integer, ForeignKey("star_systems.id"))
    planet_type = Column(String(20), default="rocky")
    orbit_position = Column(Integer, default=1)  # 1-5 orbit slot
    orbit_row = Column(Integer, default=1)  # row within orbit (1-3 for multiple astros at same orbit)
    is_colonized = Column(Boolean, default=False)
    # Astro stats
    solar = Column(Integer, default=2)
    gas = Column(Integer, default=0)
    fertility = Column(Integer, default=4)
    area = Column(Integer, default=65)
    metal = Column(Integer, default=2)
    crystal = Column(Integer, default=0)
    temperature = Column(Integer, nullable=True)  # °C, set by uniform world generation (position-based)
    debris = Column(Float, default=0.0)  # debris credits from destroyed ships
    system = relationship("StarSystem", back_populates="planets")
    colony = relationship("Colony", uselist=False, back_populates="planet")

class Colony(ModelBase):
    __tablename__ = "colonies"
    __table_args__ = (
        Index("ix_colonies_user_occupied", "user_id", "occupied_by"),
    )
    id = Column(Integer, primary_key=True)
    planet_id = Column(Integer, ForeignKey("planets.id"), unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String(50), default="New Colony")
    last_collected = Column(DateTime, default=datetime.utcnow)
    # Occupation system
    occupied_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    occupation_start = Column(DateTime, nullable=True)
    last_pillaged = Column(DateTime, nullable=True)
    unrest = Column(Float, default=0.0)  # 0.0 to 1.0 (100%)
    defense_effectiveness = Column(Float, default=1.0)  # 0.0 to 1.0 (100%)
    npc_stability = Column(Float, nullable=True)  # Settlers stability: 1.0 = 100%, disbands at 0
    npc_last_stability_tick = Column(DateTime, nullable=True)  # last server-midnight stability decay
    economy_penalty = Column(Integer, default=0)  # economy points lost from occupation, recovers 1 per 8h
    last_economy_recovery = Column(DateTime, nullable=True)  # last time 1 econ was recovered
    trade_listed_until = Column(DateTime, nullable=True)  # public trade finder listing expiry
    is_home_base = Column(Boolean, default=False)  # home base gets +20 construction bonus
    sort_order = Column(Integer, default=0)  # user-defined base ordering
    planet = relationship("Planet", back_populates="colony")
    user = relationship("User", back_populates="colonies", foreign_keys=[user_id])
    occupier = relationship("User", foreign_keys=[occupied_by])
    buildings = relationship("Building", back_populates="colony", cascade="all, delete-orphan")
    defenses = relationship("Defense", back_populates="colony", cascade="all, delete-orphan")

class Building(ModelBase):
    __tablename__ = "buildings"
    id = Column(Integer, primary_key=True)
    colony_id = Column(Integer, ForeignKey("colonies.id"), index=True)
    building_type = Column(String(30), nullable=False)
    level = Column(Integer, default=0)
    is_constructing = Column(Boolean, default=False)
    construction_end = Column(DateTime, nullable=True)
    colony = relationship("Colony", back_populates="buildings")

class Defense(ModelBase):
    __tablename__ = "defenses"
    id = Column(Integer, primary_key=True)
    colony_id = Column(Integer, ForeignKey("colonies.id"), index=True)
    defense_type = Column(String(30), nullable=False)
    level = Column(Integer, default=0)
    is_constructing = Column(Boolean, default=False)
    construction_end = Column(DateTime, nullable=True)
    colony = relationship("Colony", back_populates="defenses")

    @property
    def quantity(self):
        """Legacy: each level = 5 turrets (defense level model). Not used in combat calculations."""
        return self.level * 5

    @property
    def combat_units(self):
        """Number of combat units for battle. In both models, level IS the combat unit count.
        Level model: level=upgrade level, stats represent 5 turrets per level.
        Count model: level=unit count, stats represent 1 unit."""
        return self.level

class Research(ModelBase):
    __tablename__ = "research"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    tech_type = Column(String(30), nullable=False)
    level = Column(Integer, default=0)
    is_researching = Column(Boolean, default=False)
    research_end = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="research")

class Fleet(ModelBase):
    __tablename__ = "fleets"
    __table_args__ = (
        Index("ix_fleets_base_user_stationary", "base_id", "user_id", "is_moving"),
        Index("ix_fleets_location_user_stationary", "location_planet_id", "user_id", "is_moving"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String(50), default="Fleet")
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    base_id = Column(Integer, ForeignKey("colonies.id"), nullable=True, index=True)
    # Ship types (all 20)
    small_ship_1 = Column(Integer, default=0)
    small_ship_2 = Column(Integer, default=0)
    small_ship_3 = Column(Integer, default=0)
    small_ship_4 = Column(Integer, default=0)
    small_ship_5 = Column(Integer, default=0)
    small_ship_6 = Column(Integer, default=0)
    small_ship_7 = Column(Integer, default=0)
    medium_ship_1 = Column(Integer, default=0)
    medium_ship_2 = Column(Integer, default=0)
    small_ship_8 = Column(Integer, default=0)
    medium_ship_3 = Column(Integer, default=0)
    medium_ship_4 = Column(Integer, default=0)
    medium_ship_6 = Column(Integer, default=0)
    large_ship_1 = Column(Integer, default=0)
    large_ship_2 = Column(Integer, default=0)
    medium_ship_5 = Column(Integer, default=0)
    large_ship_3 = Column(Integer, default=0)
    large_ship_4 = Column(Integer, default=0)
    capital_ship_1 = Column(Integer, default=0)
    capital_ship_2 = Column(Integer, default=0)
    # Movement
    is_moving = Column(Boolean, default=False, index=True)
    destination_base_id = Column(Integer, nullable=True)
    destination_planet_id = Column(Integer, nullable=True, index=True)  # for uncolonized planet destinations
    arrival_time = Column(DateTime, nullable=True)
    origin_base_id = Column(Integer, nullable=True)
    origin_planet_id = Column(Integer, nullable=True, index=True)
    # Location for fleets at uncolonized planets (no colony to reference)
    location_planet_id = Column(Integer, nullable=True, index=True)
    # Recycler auto-collection toggle (on by default)
    auto_recycle = Column(Boolean, default=True)
    # Partial damage for Medium Ship 4+ (JSON: {"medium_ship_4": 0.75} = one unit at 75% health)
    ship_damage = Column(Text, default="{}")
    # Guild fleet hiding — hide from guild shared data for 24h
    guild_hidden_until = Column(DateTime, nullable=True)
    # Autoscout fields
    is_autoscout = Column(Boolean, default=False)
    autoscout_galaxy_id = Column(Integer, ForeignKey("galaxies.id"), nullable=True)
    autoscout_region_index = Column(Integer, default=0)  # position in boustrophedon order
    autoscout_system_index = Column(Integer, default=0)  # which system within region
    autoscout_planet_index = Column(Integer, default=0)  # which planet within system
    autoscout_last_move = Column(DateTime, nullable=True)  # when scout last moved to current astro
    sort_order = Column(Integer, default=0)
    # JSON overflow for custom ship types beyond the 20 built-in columns
    ships_extra = Column(Text, default="{}")
    user = relationship("User", back_populates="fleets")

    # ── Ship count abstraction layer ──
    # These methods provide a uniform interface for accessing ship counts,
    # whether stored in built-in columns or JSON overflow (custom ship types).
    _BUILTIN_SHIP_COLUMNS = {
        "small_ship_1", "small_ship_2", "small_ship_3", "small_ship_4", "small_ship_5",
        "small_ship_6", "small_ship_7", "medium_ship_1", "medium_ship_2", "small_ship_8",
        "medium_ship_3", "medium_ship_4", "medium_ship_6", "large_ship_1",
        "large_ship_2", "medium_ship_5", "large_ship_3", "large_ship_4", "capital_ship_1",
        "capital_ship_2",
    }

    def get_ship_count(self, ship_type: str) -> int:
        """Get count for any ship type (built-in column or custom JSON)."""
        if ship_type in self._BUILTIN_SHIP_COLUMNS:
            return getattr(self, ship_type, 0) or 0
        extra = json.loads(self.ships_extra or "{}") if isinstance(self.ships_extra, str) else (self.ships_extra or {})
        return extra.get(ship_type, 0)

    def set_ship_count(self, ship_type: str, count: int):
        """Set count for any ship type (built-in column or custom JSON)."""
        if ship_type in self._BUILTIN_SHIP_COLUMNS:
            setattr(self, ship_type, count)
            return

        extra = json.loads(self.ships_extra or "{}") if isinstance(self.ships_extra, str) else (self.ships_extra or {})
        if count > 0:
            extra[ship_type] = count
        else:
            if ship_type in extra:
                del extra[ship_type]
        self.ships_extra = json.dumps(extra)

    def get_all_ship_counts(self) -> dict:
        """Get dict of all ship types with non-zero counts."""
        counts = {}
        for st in self._BUILTIN_SHIP_COLUMNS:
            c = getattr(self, st, 0) or 0
            if c > 0:
                counts[st] = counts.get(st, 0) + c
        extra = json.loads(self.ships_extra or "{}") if isinstance(self.ships_extra, str) else (self.ships_extra or {})
        for st, c in extra.items():
            if c > 0:
                counts[st] = counts.get(st, 0) + c
        return counts

    def get_total_ships(self) -> int:
        """Total ship count across all types."""
        return sum(self.get_all_ship_counts().values())

    def clear_all_ships(self):
        """Set all ship counts to zero."""
        for st in self._BUILTIN_SHIP_COLUMNS:
            setattr(self, st, 0)
        self.ships_extra = "{}"

class ShipQueue(ModelBase):
    """Ship production queue. Up to 5 items per base, position 0 is active."""
    __tablename__ = "ship_queue"
    id = Column(Integer, primary_key=True)
    colony_id = Column(Integer, ForeignKey("colonies.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ship_type = Column(String(30), nullable=False)
    count = Column(Integer, default=1)
    built = Column(Integer, default=0)  # how many have been completed so far
    position = Column(Integer, default=0)  # 0=active, 1-4=queued
    cost = Column(JSONCost, default=0)  # total cost (scalar or per-resource dict)
    started_at = Column(DateTime, default=datetime.utcnow)
    next_complete = Column(DateTime, nullable=True)  # when the batch finishes
    colony = relationship("Colony")


class ConstructionQueue(ModelBase):
    """Construction queue for buildings and defenses. Up to 5 items per base.
    position=0 is active (currently building), 1-4 are queued.
    item_category: 'building' or 'defense'
    item_type: the building_type or defense_type string
    """
    __tablename__ = "construction_queue"
    id = Column(Integer, primary_key=True)
    colony_id = Column(Integer, ForeignKey("colonies.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    position = Column(Integer, default=0)  # 0=active, 1-4=queued
    item_category = Column(String(20), nullable=False)  # 'building' or 'defense'
    item_type = Column(String(30), nullable=False)  # building_type or defense_type
    target_level = Column(Integer, default=1)  # what level we're building TO
    cost = Column(JSONCost, default=0)  # charged when queued (scalar or per-resource dict)
    build_time = Column(Float, default=0)  # seconds for this item
    started_at = Column(DateTime, nullable=True)
    finish_at = Column(DateTime, nullable=True)
    colony = relationship("Colony")


class ResearchQueue(ModelBase):
    """Research queue. Per-base: each base with labs has its own queue (max 6).
    position=0 is active (currently researching), 1-5 are queued.
    Only one base can be actively researching a given tech at a time.
    """
    __tablename__ = "research_queue"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    colony_id = Column(Integer, ForeignKey("colonies.id"), nullable=True)
    position = Column(Integer, default=0)  # 0=active, 1-5=queued
    tech_type = Column(String(30), nullable=False)
    target_level = Column(Integer, default=1)  # what level we're researching TO
    cost = Column(JSONCost, default=0)  # scalar or per-resource dict
    research_time = Column(Float, default=0)  # seconds
    started_at = Column(DateTime, nullable=True)
    finish_at = Column(DateTime, nullable=True)
    user = relationship("User")
    colony = relationship("Colony")


class ScoutedRegion(ModelBase):
    """Fog of war: tracks which regions each player has scouted and stores snapshot data."""
    __tablename__ = "scouted_regions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False)
    last_scouted = Column(DateTime, default=datetime.utcnow)
    snapshot_data = Column(Text, nullable=True)  # JSON snapshot of region state at scout time

class ScoutedBase(ModelBase):
    """Galaxy Report: Bases — records bases seen by a player's scouts."""
    __tablename__ = "scouted_bases"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # who scouted it
    planet_id = Column(Integer, ForeignKey("planets.id"), nullable=False)
    owner_name = Column(String(50), default="")  # player who owns the base
    owner_guild_tag = Column(String(5), default="")  # guild tag at time of scouting
    base_name = Column(String(50), default="")
    location = Column(String(30), default="")  # full coord e.g. "A12:03:79:30"
    last_seen = Column(DateTime, default=datetime.utcnow)

class ScoutedFleet(ModelBase):
    """Galaxy Report: Fleets — records fleet sightings by a player's scouts."""
    __tablename__ = "scouted_fleets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # who scouted it
    owner_name = Column(String(50), default="")  # player who owns the fleet
    owner_guild_tag = Column(String(5), default="")
    location = Column(String(30), default="")  # coord where fleet was seen
    planet_id = Column(Integer, ForeignKey("planets.id"), nullable=True)
    fleet_size = Column(Integer, default=0)  # total fleet value (cost)
    is_moving = Column(Boolean, default=False)
    destination = Column(String(30), default="")  # coord if moving
    arrival_time = Column(DateTime, nullable=True)
    last_seen = Column(DateTime, default=datetime.utcnow)

class GalaxyLink(ModelBase):
    """Connections between galaxies. Pumpkin: x0↔x0, x9↔x9 between clusters. Within cluster: sequential."""
    __tablename__ = "galaxy_links"
    id = Column(Integer, primary_key=True)
    galaxy_a_id = Column(Integer, ForeignKey("galaxies.id"), nullable=False)
    galaxy_b_id = Column(Integer, ForeignKey("galaxies.id"), nullable=False)
    distance = Column(Integer, default=200)  # 200 within cluster, 1000 between clusters

class Wormhole(ModelBase):
    """Physical transit points between galaxies. 2 per galaxy (1 inner, 1 outer)."""
    __tablename__ = "wormholes"
    id = Column(Integer, primary_key=True)
    planet_id = Column(Integer, ForeignKey("planets.id"), nullable=False, unique=True)
    galaxy_id = Column(Integer, ForeignKey("galaxies.id"), nullable=False)
    wormhole_type = Column(String(10), default="inner")  # "inner" or "outer"
    linked_wormhole_id = Column(Integer, ForeignKey("wormholes.id"), nullable=True)
    planet = relationship("Planet")
    galaxy = relationship("Galaxy")

class SystemLink(ModelBase):
    """An edge between two star systems for the graph map topology
    (engine.map_topology == "graph"). Empty/unused in hierarchy mode."""
    __tablename__ = "system_links"
    __table_args__ = (
        Index("ix_system_links_a", "system_a_id"),
        Index("ix_system_links_b", "system_b_id"),
    )
    id = Column(Integer, primary_key=True)
    system_a_id = Column(Integer, ForeignKey("star_systems.id"), nullable=False)
    system_b_id = Column(Integer, ForeignKey("star_systems.id"), nullable=False)
    weight = Column(Float, default=1.0)        # travel cost; 1.0 = one hop
    one_way = Column(Boolean, default=False)   # a->b only when true
    kind = Column(String(10), default="link")  # "link" | "wormhole"

class BattleReport(ModelBase):
    __tablename__ = "battle_reports"
    id = Column(Integer, primary_key=True)
    attacker_id = Column(Integer, ForeignKey("users.id"))
    defender_id = Column(Integer, ForeignKey("users.id"))
    base_id = Column(Integer)
    report = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class TradeRoute(ModelBase):
    __tablename__ = "trade_routes"
    id = Column(Integer, primary_key=True)
    base_a_id = Column(Integer, ForeignKey("colonies.id"), nullable=False)
    base_b_id = Column(Integer, ForeignKey("colonies.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # who initiated the route
    partner_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # other player (null = self-trade)
    cost = Column(Float, default=0)  # total setup cost = 2 × distance
    income = Column(Float, default=0)  # credits/hr from this route
    is_pending = Column(Boolean, default=False)  # waiting for partner to accept
    created_at = Column(DateTime, default=datetime.utcnow)
    is_closing = Column(Boolean, default=False)
    closing_at = Column(DateTime, nullable=True)
    is_public = Column(Boolean, default=False)  # listed on public trade finder (non-guild)
    public_until = Column(DateTime, nullable=True)  # when public listing expires (48h)

class Message(ModelBase):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject = Column(String(200), default="")
    body = Column(Text, default="")
    is_read = Column(Boolean, default=False)
    is_saved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])

class Contact(ModelBase):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    contact_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(String(100), default="")
    added_at = Column(DateTime, default=datetime.utcnow)
    contact_user = relationship("User", foreign_keys=[contact_user_id])

class Guild(ModelBase):
    __tablename__ = "guilds"
    id = Column(Integer, primary_key=True)
    name = Column(String(36), unique=True, nullable=False)
    tag = Column(String(5), unique=True, nullable=False)  # short guild tag e.g. [SHIP]
    description = Column(Text, default="")
    homepage = Column(String(64), default="")
    forum_url = Column(String(64), default="")
    info_title_1 = Column(String(30), default="Info 1")
    info_body_1 = Column(Text, default="")
    info_title_2 = Column(String(30), default="Info 2")
    info_body_2 = Column(Text, default="")
    info_title_3 = Column(String(30), default="Info 3")
    info_body_3 = Column(Text, default="")
    info_title_4 = Column(String(30), default="Info 4")
    info_body_4 = Column(Text, default="")
    board_name_3 = Column(String(20), default="")  # custom name for board folder 3 (default: Trade)
    board_name_4 = Column(String(20), default="")  # custom name for board folder 4 (default: Strategy)
    tag_changed_at = Column(DateTime, nullable=True)  # 7-day cooldown on tag changes
    name_changed_at = Column(DateTime, nullable=True)  # 7-day cooldown on name changes
    leader_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    leader = relationship("User", foreign_keys=[leader_id])

class GuildMember(ModelBase):
    __tablename__ = "guild_members"
    __table_args__ = (
        Index("ix_guild_members_guild_user", "guild_id", "user_id"),
    )
    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("guilds.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rank = Column(String(20), default="member")  # leader, vice_leader, member
    title = Column(String(30), default="")  # custom title set by T-permission holders
    # Permission flags: R=Recruit K=Kick M=Announcements I=Internal T=Titles F=Fleets +=Inactivity -=Scouted
    permissions = Column(String(20), default="")  # e.g. "RKMITF+" for all flags
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_announcement_seen = Column(DateTime, nullable=True)  # track unread announcements
    guild = relationship("Guild")
    user = relationship("User")

    def has_perm(self, flag: str) -> bool:
        """Check if member has a specific permission flag.
        Leader and Vice Leader always have all permissions.
        + implies - (inactivity+scouted is a superset of scouted-only)."""
        if self.rank in ("leader", "vice_leader"):
            return True
        perms = self.permissions or ""
        if flag == "-" and "+" in perms:
            return True  # + includes scouted data access
        return flag in perms

class GuildBoardPost(ModelBase):
    """Guild board — 5 folders: general, announcements, combat, trade, strategy."""
    __tablename__ = "guild_board"
    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("guilds.id"), nullable=False)
    folder = Column(String(20), default="general")  # general, announcements, combat, trade, strategy
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null for system posts
    body = Column(Text, default="")
    battle_report_id = Column(Integer, ForeignKey("battle_reports.id"), nullable=True)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    guild = relationship("Guild")
    author = relationship("User", foreign_keys=[author_id])

class GuildApplication(ModelBase):
    """Pending guild membership applications."""
    __tablename__ = "guild_applications"
    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("guilds.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    applied_at = Column(DateTime, default=datetime.utcnow)
    guild = relationship("Guild")
    user = relationship("User")

class GuildLog(ModelBase):
    """Guild activity log — tracks member joins, kicks, permission changes, etc."""
    __tablename__ = "guild_logs"
    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("guilds.id"), nullable=False)
    done_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(String(200), default="")
    member_name = Column(String(50), default="")  # affected member username
    created_at = Column(DateTime, default=datetime.utcnow)
    guild = relationship("Guild")
    done_by = relationship("User", foreign_keys=[done_by_id])

class GuildHistorySnapshot(ModelBase):
    """Periodic guild totals used by the historical graphs page."""
    __tablename__ = "guild_history_snapshots"
    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("guilds.id"), nullable=False, index=True)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    guild_level = Column(Float, default=1.0)
    member_count = Column(Integer, default=0)
    total_economy = Column(Float, default=0.0)
    total_fleet = Column(Float, default=0.0)
    total_technology = Column(Float, default=0.0)
    total_experience = Column(Float, default=0.0)
    guild = relationship("Guild")

class EventLog(ModelBase):
    __tablename__ = "event_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String(30), nullable=False)  # construction, research, fleet, attack, colonize, trade, guild
    message = Column(Text, default="")
    data = Column(Text, default="{}")  # JSON structured data for programmatic access
    created_at = Column(DateTime, default=datetime.utcnow)

class CreditLog(ModelBase):
    """Credit history ledger — every credit change is recorded with running balance."""
    __tablename__ = "credit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(String(200), default="")  # e.g. "Empire Income", "Construction of Solar Plants lvl 10 at IX"
    amount = Column(Float, default=0)  # positive = income, negative = expense
    balance = Column(Float, default=0)  # running balance after this transaction
    category = Column(String(20), default="other")  # income, construction, production, research, trade, combat, admin, other
    created_at = Column(DateTime, default=datetime.utcnow)

class FleetAuditLog(ModelBase):
    """Fleet composition audit trail — records every fleet change for admin recovery."""
    __tablename__ = "fleet_audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fleet_id = Column(Integer, nullable=False)  # not FK — fleet may be deleted
    fleet_name = Column(String(50), default="")
    action = Column(String(30), default="")  # build, battle_loss, merge, split, disband, move, admin_grant
    ships_before = Column(Text, default="{}")  # JSON {ship_type: count}
    ships_after = Column(Text, default="{}")   # JSON {ship_type: count}
    details = Column(Text, default="")  # human-readable context
    created_at = Column(DateTime, default=datetime.utcnow)

class BugReport(ModelBase):
    __tablename__ = "bug_reports"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(50), default="")
    category = Column(String(30), default="bug")  # bug, request, feedback
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    page = Column(String(50), default="")  # which tab/page the report was filed from
    status = Column(String(20), default="open")  # open, acknowledged, fixed, wontfix
    admin_notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", foreign_keys=[user_id])

class Changelog(ModelBase):
    """Server changelog entries shown to players on login."""
    __tablename__ = "changelogs"
    id = Column(Integer, primary_key=True)
    version = Column(String(20), default="")  # e.g. "0.95.1"
    title = Column(String(200), nullable=False)
    body = Column(Text, default="")  # markdown or plain text
    created_at = Column(DateTime, default=datetime.utcnow)

class Commander(ModelBase):
    """Player-recruited officers assigned to bases for skill bonuses."""
    __tablename__ = "commanders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(40), nullable=False)
    skill_type = Column(String(20), nullable=False)  # construction/research/production/defense/tactical/logistics
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)  # accumulated XP for training
    colony_id = Column(Integer, ForeignKey("colonies.id"), nullable=True)  # physical location (null=pool)
    is_assigned = Column(Boolean, default=False)  # True = active Base Commander at colony_id
    is_traveling = Column(Boolean, default=False)
    arrival_time = Column(DateTime, nullable=True)
    is_training = Column(Boolean, default=False)
    training_complete_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", foreign_keys=[user_id])
    colony = relationship("Colony", foreign_keys=[colony_id])

class GameConfig(ModelBase):
    __tablename__ = "game_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(String(200))

class Bookmark(ModelBase):
    __tablename__ = "bookmarks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(50), nullable=False)
    planet_id = Column(Integer, ForeignKey("planets.id"), nullable=False)
    user = relationship("User")
    planet = relationship("Planet")

class TutorialProgress(ModelBase):
    """Tracks each player's tutorial progress. One row per player."""
    __tablename__ = "tutorial_progress"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    current_step = Column(Integer, default=0)  # index into TUTORIAL_STEPS (0=introduction)
    completed_steps = Column(Text, default="[]")  # JSON array of completed step indices
    collected_steps = Column(Text, default="[]")  # JSON array of steps where reward was collected
    is_finished = Column(Boolean, default=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    # Galaxy the player chose during registration
    chosen_galaxy_id = Column(Integer, ForeignKey("galaxies.id"), nullable=True)
    user = relationship("User")


# ======================== PYDANTIC MODELS ========================

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class FleetSend(BaseModel):
    fleet_id: int
    destination_planet_id: int  # send to any planet/astro

class FleetAttack(BaseModel):
    fleet_id: int
    target_user_id: Optional[int] = None  # if None, attacks base owner
    target_fleet_id: Optional[int] = None
    attack_mode: Optional[str] = None

class ColonizeRequest(BaseModel):
    planet_id: int
    fleet_id: int  # fleet must have a colonizer ship at that planet

class BuildShipRequest(BaseModel):
    base_id: int
    ship_type: str
    count: int = 1

class UpgradeBuildingRequest(BaseModel):
    base_id: int
    building_type: str

class ResearchRequest(BaseModel):
    tech_type: str

class BuildDefenseRequest(BaseModel):
    base_id: int
    defense_type: str
    count: int = 1

class BaseRename(BaseModel):
    name: str

class BaseSetHome(BaseModel):
    base_id: int

class BaseReorder(BaseModel):
    base_ids: list  # ordered list of colony IDs

class TradeRouteCreate(BaseModel):
    base_a_id: int
    base_b_id: int

class TradeRoutePlunder(BaseModel):
    trade_route_id: int

class RevoltRequest(BaseModel):
    base_id: int

class FleetSplitRequest(BaseModel):
    fleet_id: int
    new_name: str = "New Fleet"
    ships: Dict[str, int]  # ship_type -> count to move to new fleet

class FleetMergeRequest(BaseModel):
    source_fleet_id: int
    target_fleet_id: int

class SendMessageRequest(BaseModel):
    recipient: str
    subject: str = ""
    body: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class CreateGuildRequest(BaseModel):
    name: str
    tag: str
    description: str = ""

class FleetRenameRequest(BaseModel):
    fleet_id: int
    name: str

class FleetRepairRequest(BaseModel):
    fleet_id: int

class GalaxySelectRequest(BaseModel):
    galaxy_id: int

class CommanderRecruit(BaseModel):
    skill_type: Optional[str] = None  # None = random
    use_credits: bool = False

class CommanderAssign(BaseModel):
    colony_id: Optional[int] = None  # None = unassign

class CommanderMove(BaseModel):
    colony_id: int
