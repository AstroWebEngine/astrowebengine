# Code Examples - Key Game Mechanics

## Resource Production Calculation

From `calc_production_rate()` (line 348):

```python
def calc_production_rate(base: Base, user: User, game_speed: float) -> float:
    """Credits per hour"""
    metal_level = sum(b.level for b in base.buildings if b.building_type == "metal_factory")
    crystal_level = sum(b.level for b in base.buildings if b.building_type == "crystal_mine")
    
    mining_tech = next((r.level for r in user.research if r.tech_type == "mining"), 0)
    
    rate = (metal_level * 10 + crystal_level * 8) * (1 + mining_tech * 0.1) * game_speed
    return rate
```

**Formula**: `(metal_level * 10 + crystal_level * 8) * (1 + mining_tech * 0.1) * game_speed`

Example: Base with 5 metal factories, 3 crystal mines, mining tech level 2, game_speed 1.0
- Rate = (5 * 10 + 3 * 8) * (1 + 2 * 0.1) * 1.0 = (50 + 24) * 1.2 = 88.8 credits/hour

## Building Cost & Time Calculation

From `calc_building_cost()` (line 334):

```python
def calc_building_cost(building_type: str, current_level: int, game_speed: float) -> tuple:
    """Returns (cost, build_time_seconds)"""
    spec = BUILDING_SPECS[building_type]
    cost = spec["cost"] * (spec["cost_mult"] ** current_level)
    build_time = spec["time"] * (1.5 ** current_level) / game_speed
    return cost, build_time
```

Example: Upgrading metal factory from level 2 to level 3, game_speed 1.0

Metal factory specs: `base_cost=100, cost_mult=1.8, time=60s`

- Cost = 100 * (1.8 ** 2) = 100 * 3.24 = 324 credits
- Time = 60 * (1.5 ** 2) / 1.0 = 60 * 2.25 = 135 seconds (2.25 minutes)

With game_speed 2.0:
- Time = 60 * 2.25 / 2.0 = 67.5 seconds (1.125 minutes) - 2x faster!

## Research System

From `calc_research_cost()` (line 341):

```python
def calc_research_cost(tech_type: str, current_level: int, lab_count: int, game_speed: float) -> tuple:
    """Returns (cost, research_time_seconds)"""
    spec = RESEARCH_SPECS[tech_type]
    cost = spec["cost"] * (spec["cost_mult"] ** current_level)
    research_time = spec["time"] * (2.0 ** current_level) / (1 + lab_count * 0.1) / game_speed
    return cost, research_time
```

Example: Researching weapons tech from level 1 to level 2, with 2 research labs, game_speed 1.0

Weapons specs: `cost=300, cost_mult=2.0, time=240s`

- Cost = 300 * (2.0 ** 1) = 600 credits
- Time = 240 * (2.0 ** 1) / (1 + 2 * 0.1) / 1.0 = 240 * 2 / 1.2 = 400 seconds (6.67 minutes)

With 3 labs instead:
- Time = 480 / (1 + 0.3) = 480 / 1.3 = 369 seconds (6.15 minutes) - faster due to more labs!

## Combat Simulation

From `resolve_battle()` (line 432):

```python
def resolve_battle(attacker_fleet, attacker_user, defender_base, defender_user, game_speed, db):
    """Simulate combat and return results"""
    attacker_stats = get_fleet_stats(attacker_fleet, attacker_user, game_speed)
    defender_stats = get_fleet_stats(Fleet(...), defender_user, game_speed)
    
    attacker_health = attacker_stats["hull"]
    defender_health = defender_stats["hull"]
    
    rounds = 0
    max_rounds = 100
    
    while attacker_health > 0 and defender_health > 0 and rounds < max_rounds:
        if attacker_stats["attack"] > 0:
            damage_to_defender = attacker_stats["attack"] * (
                attacker_stats["attack"] / (attacker_stats["attack"] + defender_stats["defense"] + 1)
            )
            defender_health -= damage_to_defender
        
        if defender_stats["attack"] > 0:
            damage_to_attacker = defender_stats["attack"] * (
                defender_stats["attack"] / (defender_stats["attack"] + attacker_stats["defense"] + 1)
            )
            attacker_health -= damage_to_attacker
        
        rounds += 1
    
    attacker_won = attacker_health > 0
    plunder = int(defender_user.credits * 0.3) if attacker_won else 0
```

**Damage Formula**: `damage = attacker_attack * (attacker_attack / (attacker_attack + defender_defense + 1))`

Example: Attacker 100 attack vs Defender 40 defense
- Attacker damage per round = 100 * (100 / (100 + 40 + 1)) = 100 * 0.704 = 70.4 damage
- Defender damage per round = 40 * (40 / (40 + 100 + 1)) = 40 * 0.281 = 11.24 damage

Attacker wins much faster! Defense is always disadvantageous but reduces damage taken.

## Distance & Travel Time

From `calc_distance()` (line 368) and `calc_travel_time()` (line 396):

```python
def calc_distance(base1: Base, base2: Base) -> float:
    """Calculate distance between two bases"""
    s1 = base1.planet.system
    s2 = base2.planet.system
    r1 = s1.region
    r2 = s2.region
    g1 = r1.galaxy
    g2 = r2.galaxy
    
    # Galaxy separation (1000 units per galaxy)
    gal_dist = abs(g1.index - g2.index) * 1000
    
    # System position within regions (10x10 grid per region, 4x4 regions per galaxy)
    x1 = r1.row * 10 + s1.x_offset
    y1 = r1.col * 10 + s1.y_offset
    x2 = r2.row * 10 + s2.x_offset
    y2 = r2.col * 10 + s2.y_offset
    
    system_dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    
    total_dist = math.sqrt(gal_dist ** 2 + system_dist ** 2)
    return total_dist

def calc_fleet_speed(fleet: Fleet, user: User, game_speed: float) -> float:
    """Calculate travel speed (distance units per second)"""
    propulsion_level = next((r.level for r in user.research if r.tech_type == "propulsion"), 0)
    base_speed = 0.1
    speed = base_speed * (1 + propulsion_level * 0.1) * game_speed
    return speed

def calc_travel_time(distance: float, speed: float) -> float:
    """Returns travel time in seconds"""
    return distance / speed if speed > 0 else 999999
```

Example: Fleet traveling from Galaxy A, Region 0, System (0,0) to Galaxy B, Region 1, System (2,3)

- Galaxy distance: |1 - 0| * 1000 = 1000 units
- System positions in regions: (0*10+0, 0*10+0) = (0,0) vs (1*10+2, 1*10+3) = (12, 13)
- System distance: sqrt((12-0)^2 + (13-0)^2) = sqrt(144 + 169) = sqrt(313) = 17.69 units
- Total distance: sqrt(1000^2 + 17.69^2) = sqrt(1000313) = 1000.16 units

With propulsion level 3, game_speed 1.0:
- Speed = 0.1 * (1 + 0.3) * 1.0 = 0.13 units/second
- Travel time = 1000.16 / 0.13 = 7692 seconds = 2.14 hours

With propulsion level 3, game_speed 2.0:
- Speed = 0.1 * 1.3 * 2.0 = 0.26 units/second
- Travel time = 1000.16 / 0.26 = 3846 seconds = 1.07 hours (2x faster!)

## Win Condition Checking

From `check_win_condition()` (line 490):

```python
def check_win_condition(db: Session) -> Optional[User]:
    """Check if game should end, return winner if so"""
    game_status = get_config(db, "game_status")
    if game_status != "active":
        return None
    
    win_condition = get_config(db, "win_condition")
    
    if win_condition == "domination":
        threshold = get_config(db, "domination_threshold", 0.75)
        total_colonized = db.query(Planet).filter(Planet.is_colonized).count()
        if total_colonized == 0:
            return None
        
        for user in db.query(User).all():
            user_bases = db.query(Base).filter(Base.user_id == user.id).count()
            if user_bases / total_colonized >= threshold:
                return user
    
    elif win_condition == "annihilation":
        # Last player with bases
        player_count = len([u for u in db.query(User).all() 
                          if db.query(Base).filter(Base.user_id == u.id).first()])
        if player_count <= 1:
            for user in db.query(User).all():
                if db.query(Base).filter(Base.user_id == user.id).first():
                    return user
    
    elif win_condition == "economic":
        target = get_config(db, "economic_target", 1000000)
        for user in db.query(User).all():
            if user.credits >= target:
                return user
    
    elif win_condition == "time_limit":
        start_time = get_config(db, "game_start_time")
        limit_hours = get_config(db, "time_limit_hours", 72)
        if start_time:
            start_dt = datetime.fromisoformat(start_time)
            if datetime.utcnow() >= start_dt + timedelta(hours=limit_hours):
                return max(db.query(User).all(), key=lambda u: u.score)
    
    return None
```

Example scenarios:

**Domination (75% threshold)**:
- Total planets: 100
- Player A bases: 76
- Winner: Player A (76/100 = 76% >= 75%)

**Economic (1,000,000 credits target)**:
- Player A: 950,000 credits
- Player B: 1,050,000 credits
- Winner: Player B (first to reach target)

**Time Limit (72 hour limit)**:
- Start time: 2026-03-01 12:00 UTC
- Timeout: 2026-03-04 12:00 UTC
- Scores at timeout: A=2000, B=3500, C=1500
- Winner: Player B (highest score)

## Building Auto-Completion (Lazy Evaluation)

From `GET /api/bases` (line 918):

```python
@app.get("/api/bases")
def get_bases(token: str, db: Session = Depends(get_db)):
    current_user = get_current_user(token, db)
    
    bases = db.query(Base).filter(Base.user_id == current_user.id).all()
    
    result = []
    for base in bases:
        collect_resources(base, current_user, game_speed)
        
        buildings = db.query(Building).filter(Building.base_id == base.id).all()
        buildings_data = []
        for building in buildings:
            # AUTO-COMPLETION: Check if construction finished
            if building.construction_end and building.construction_end <= datetime.utcnow():
                building.level += 1
                building.construction_end = None
                db.commit()
            
            buildings_data.append({
                "building_type": building.building_type,
                "level": building.level,
                "construction_end": building.construction_end.isoformat() if building.construction_end else None,
            })
```

Example timeline:
- 10:00 AM: Start upgrading metal factory (level 2 → 3), construction_end = 10:02:15 AM
- 10:01 AM: Query `/api/bases` → Still building, level=2, construction_end="10:02:15"
- 10:02:30 AM: Query `/api/bases` → Auto-completes! level=3, construction_end=None
- Building is instantly ready when queried after completion time

This pattern used for all time-based completions in the system.

## Fleet Movement & Auto-Resolution

From `GET /api/fleets` (line 1083):

```python
if fleet.is_moving and fleet.arrival_time and fleet.arrival_time <= datetime.utcnow():
    if fleet.mission == "attack":
        defender_base = db.query(Base).filter(Base.id == fleet.destination_base_id).first()
        defender_user = defender_base.user
        
        resolve_battle(fleet, current_user, defender_base, defender_user, game_speed, db)
        
        fleet.is_moving = False
        fleet.arrival_time = None
        fleet.destination_base_id = None
    
    elif fleet.mission == "colonize":
        planet = db.query(Planet).filter(Planet.id == fleet.destination_base_id).first()
        if not planet.is_colonized:
            planet.is_colonized = True
            new_base = Base(planet_id=planet.id, user_id=current_user.id, name=f"{planet.name} Base")
            # ... initialize buildings
```

Example timeline:
- 5:00 PM: Send fleet to attack, arrival_time = 5:30 PM
- 5:15 PM: Query `/api/fleets` → Still moving, is_moving=true
- 5:30:30 PM: Query `/api/fleets` → Auto-resolves battle! Combat happens, fleet stops

## Configuration Management

From lines 291-308:

```python
def get_config(db: Session, key: str, default=None):
    config = db.query(GameConfig).filter(GameConfig.key == key).first()
    if config:
        try:
            return json.loads(config.value)
        except:
            return config.value
    return default

def set_config(db: Session, key: str, value):
    config = db.query(GameConfig).filter(GameConfig.key == key).first()
    if config:
        config.value = json.dumps(value) if not isinstance(value, str) else value
    else:
        config = GameConfig(key=key, value=json.dumps(value) if not isinstance(value, str) else value)
        db.add(config)
    db.commit()
```

Usage examples:

```python
# Get a config
game_speed = get_config(db, "game_speed", 1.0)
win_condition = get_config(db, "win_condition", "domination")

# Set a config
set_config(db, "game_speed", 2.0)
set_config(db, "domination_threshold", 0.6)
```

All game parameters stored and retrieved this way!

## Complete Game Loop Example

1. Admin starts server → auto-creates database with default configs
2. First user registers → becomes admin
3. Admin configures game via `/api/admin/config`
4. Admin launches game → generates universe, sets status to active
5. Other players register → gates registration_open
6. Player builds metal factory → credits deducted, construction_end set
7. Player queries `/api/bases` → auto-completes if time passed
8. Player researches weapons → requires lab, affects battle damage
9. Player builds fleet → requires shipyard
10. Player sends fleet → arrival_time calculated
11. Query `/api/fleets` → fleet auto-resolves when arrival_time passes
12. Winner determined → checks win condition, sets winner config

All mechanics work together in this flow!
