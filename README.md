# AstroWebEngine

A data-driven web engine for browser-based, multiplayer space-strategy games.
The engine ships as a FastAPI backend with a vanilla-JavaScript single-page
frontend, and is designed for self-hosting.

Gameplay is **fully data-driven**: units, structures, research, defenses,
combat behavior, the resource model, and the map layout are all defined in a
**game definition** (JSON or Python dict). Operators compose or author their own
definitions to build different game styles — the engine code itself contains no
hardcoded ruleset.

## Features

- **Configurable game definitions** — units, buildings, research, defenses,
  terrain, weapon types, and economy, all loaded at startup and hot-swappable.
- **Composable rule fragments** — build a game by combining fragments (e.g. combat
  model, defense destructibility) via the admin Build Game UI.
- **Combat engine** — proportional damage allocation, shields, weapon types with
  configurable shield passthrough, per-unit rounding classes, debris/loot.
- **Economy & construction** — energy, population, industry, research, and
  production formulas driven by building contributions and tech bonuses.
- **Procedural galaxy generation** — multi-cluster, spiral-density universe with
  configurable presets.
- **Admin panel** — runtime configuration of game speed, balance constants,
  spec overrides, and galaxy presets without a restart.
- **Skins** — themeable UI via CSS variables with client-side persistence.
- **NPC factions** — configurable non-player empires with stability/lifecycle rules.

## Stack

- **Backend:** FastAPI + SQLAlchemy (SQLite with WAL by default; Postgres/MySQL supported)
- **Auth:** JWT (HS256) + bcrypt
- **Frontend:** vanilla-JS SPA (no build step)

## Quick start

```bash
pip install -r requirements.txt
python run.py            # serves on http://localhost:8000
```

The first registered account is the admin/observer. Configure game rules from the
admin panel, or point the engine at a custom game definition.

## License

See [LICENSE](LICENSE).
