# Quick Start Guide - AstroWebEngine Backend

## Installation

```bash
# Install dependencies
pip install fastapi uvicorn sqlalchemy pydantic[email] passlib[bcrypt] python-jose[cryptography]

# Navigate to project directory
cd /sessions/busy-keen-sagan/mnt/outputs/astroclone

# Run the server
python main.py
```

Server will start on `http://localhost:8000`

## First Time Setup

### 1. Create Admin Account
```bash
curl -X POST "http://localhost:8000/api/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@game.local",
    "password": "adminpass123"
  }'
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "username": "admin",
  "is_admin": true
}
```

Save the `access_token` value.

### 2. View Game Configuration
```bash
curl -X GET "http://localhost:8000/api/admin/config" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

### 3. Customize Game Settings (Optional)
```bash
curl -X POST "http://localhost:8000/api/admin/config" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "game_name": "My Private Server",
    "game_speed": 2.0,
    "win_condition": "domination",
    "domination_threshold": 0.5,
    "num_galaxies": 2,
    "starting_credits": 5000
  }'
```

### 4. Launch the Game
```bash
curl -X POST "http://localhost:8000/api/admin/launch" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

This will:
- Generate the universe (galaxies, regions, systems, planets)
- Set game status to "active"
- Close the registration window

### 5. Players Can Now Register
Other players can register once the game is launched.

## Key Endpoints

### For Players

**Register/Login**
- `POST /api/register` - Create account
- `POST /api/login` - Get access token

**Game Status**
- `GET /api/game/status` - Current game state
- `GET /api/leaderboard` - Top 20 players by score

**Bases**
- `GET /api/bases` - Your bases and production
- `POST /api/bases/upgrade` - Upgrade a building
- `POST /api/bases/collect` - Manually collect resources

**Fleets**
- `GET /api/fleets` - Your fleets
- `POST /api/fleets/build` - Build ships
- `POST /api/fleets/send` - Send fleet to target (attack/colonize)
- `POST /api/fleets/recall` - Recall a moving fleet

**Research**
- `GET /api/research` - Tech levels
- `POST /api/research/start` - Begin researching a tech

**Colonization**
- `POST /api/colonize` - Colonize an unoccupied planet

**Battles**
- `GET /api/battles` - Battle reports involving you

**Exploration**
- `GET /api/universe` - All galaxies
- `GET /api/galaxy/{id}` - Regions in a galaxy
- `GET /api/region/{id}` - Systems and planets in a region

### For Admins

**Admin Controls**
- `GET /api/admin/config` - View all settings
- `POST /api/admin/config` - Update settings
- `POST /api/admin/launch` - Start the game
- `POST /api/admin/reset` - Wipe all game data
- `GET /api/admin/players` - List all players
- `DELETE /api/admin/players/{id}` - Remove a player

## Game Flow Example

### For Admin
1. Start server
2. Register as first user (becomes admin automatically)
3. Configure game settings as desired
4. Launch game (POST /api/admin/launch)
5. Send join links to friends

### For Player
1. Register account (POST /api/register)
2. Check game status (GET /api/game/status)
3. View starting base (GET /api/bases)
4. Build metal factories and crystal mines
5. Research technologies (POST /api/research/start)
6. Build fleets (POST /api/fleets/build)
7. Explore universe (GET /api/universe, /api/galaxy/{id}, /api/region/{id})
8. Attack other players or colonize planets
9. Check progress (GET /api/player/stats, GET /api/leaderboard)

## Important Constants

### Building Types
```
orbital_base, metal_factory, crystal_mine, power_plant, research_lab, shipyard
```

### Research Types
```
propulsion, weapons, shielding, energy, mining, armor
```

### Ship Types
```
small_ship_1, small_ship_2, small_ship_7, medium_ship_4, battlecruisers, large_ship_3
```

### Win Conditions
```
domination - Control X% of colonized planets
annihilation - Last player with bases
economic - First to reach X credits
time_limit - Highest score after X hours
```

## Example Workflow with cURL

```bash
# 1. Register
TOKEN=$(curl -s -X POST "http://localhost:8000/api/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"player1","email":"p1@game.local","password":"pass123"}' \
  | jq -r '.access_token')

# 2. Get bases
curl -s "http://localhost:8000/api/bases?token=$TOKEN" | jq .

# 3. Upgrade metal factory
curl -s -X POST "http://localhost:8000/api/bases/upgrade?token=$TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_id":1,"building_type":"metal_factory"}' | jq .

# 4. Check research
curl -s "http://localhost:8000/api/research?token=$TOKEN" | jq .

# 5. Start weapons research
curl -s -X POST "http://localhost:8000/api/research/start?token=$TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tech_type":"weapons"}' | jq .

# 6. Build ships
curl -s -X POST "http://localhost:8000/api/fleets/build?token=$TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"base_id":1,"ship_type":"small_ship_1","count":10}' | jq .

# 7. Get fleets
curl -s "http://localhost:8000/api/fleets?token=$TOKEN" | jq .

# 8. View leaderboard
curl -s "http://localhost:8000/api/leaderboard" | jq .
```

## Configuration Options

All values in `/api/admin/config`:

```json
{
  "game_name": "Private Server",
  "game_status": "setup|active|finished",
  "game_speed": 1.0,
  "num_galaxies": 4,
  "regions_per_galaxy": 16,
  "systems_per_region": 6,
  "planets_per_system_min": 2,
  "planets_per_system_max": 6,
  "starting_credits": 2000,
  "colonize_cost": 5000,
  "win_condition": "domination|annihilation|economic|time_limit",
  "domination_threshold": 0.75,
  "economic_target": 1000000,
  "time_limit_hours": 72,
  "max_players": 20,
  "registration_open": true,
  "winner": null
}
```

## Troubleshooting

**"Database locked" error**
- SQLite doesn't support concurrent writes well
- For multiple players, consider migrating to PostgreSQL
- Edit `DATABASE_URL` in main.py to: `"postgresql://user:pass@localhost/astroclone"`

**Changes not appearing**
- Most endpoints use lazy evaluation (check timestamps)
- Building/research complete when you query, not in background
- Always collect resources first: `POST /api/bases/collect`

**Fleet stuck in transit**
- Check `arrival_time` in fleet data
- Can recall with `POST /api/fleets/recall`
- Will return to origin base

**Can't build ships**
- Check shipyard level: `GET /api/bases`
- Ship requires: `shipyard_level >= ship.requires_shipyard`
- Small Ship 1 require shipyard level 1, large_ship_3 require level 8

## Database

Database file: `astroclone.db` (created automatically)

Reset entire game:
```bash
curl -X POST "http://localhost:8000/api/admin/reset" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

Or manually:
```bash
rm astroclone.db
# Restart the server - will recreate with defaults
```

## API Documentation

After starting server, visit:
- `http://localhost:8000/docs` - Interactive Swagger UI
- `http://localhost:8000/redoc` - ReDoc documentation

All endpoints documented with request/response schemas.
