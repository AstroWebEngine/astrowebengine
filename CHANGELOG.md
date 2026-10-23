# Changelog

All notable changes to AstroWebEngine are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) from 1.0.0 onward.

## [0.99.0] - 2026-10-23

### Added

- **AWE look.** A new default theme (charcoal, warm ivory, copper, amber) for the game,
  admin and setup screens, a brand mark and favicon, and shared brand tokens with the
  website. Rulesets can opt out with `ui.theme`; a skin a player picked keeps its colours.
- **Artwork pipeline and planet art.** Specs may set their own `image`; `art/build_art.py`
  builds sized WebP files from masters; 17 original AWE planet types replace the old
  pictures. Creator artwork always wins.
- **Mod preview.** Mods change through one preview-then-apply planner: the admin panel and
  the AI assistant (new `preview_mod` tool) see what changes before anything is saved, and
  a failed or out-of-date change saves nothing.

### Changed

- **Runtime state lives in `AWE_DATA_DIR`** (`/data` in Docker): the active ruleset, the
  mod base and saved definitions survive image updates. Older files are moved once at startup.
- **Mod validation** checks version ranges, required mods (installed, enabled, in range),
  conflicts in both directions and dependency cycles; activation is all or nothing.
- **Faster pages:** the bases list and research page no longer repeat a lookup per row
  (45 -> 23 and 28 -> 12 queries for a one-base player).

### Fixed

- **Several server workers** now share settings and ruleset changes, and only one runs the
  background jobs (NPC bots used to act once per worker).
- **Logins survive restarts** when `AWE_SECRET_KEY` isn't set: the generated key is kept in
  the data folder.
- **Disabling a mod** really removes its rules; **admin export** no longer overwrites a
  bundled definition of the same name.
- **Conquest capture never ran:** the income tick raised a NameError before reaching the
  occupation-capture sweep, so occupied bases were never captured in conquest games.

## [0.98.0] - 2026-10-08

### Added

- **AI assistant endpoint.** `/mcp` lets a game creator's AI assistant read the definition
  schema, check and save drafts, activate rulesets (through the same safety gate as the admin Import) and toggle mods (via
  the admin mod-apply path). Protected by admin API tokens (admin panel → AI Assistant).
- **Game-designer skill** download and a written game definition schema reference
  (`docs/definition_schema.md`).

## [0.97.0] - 2026-09-04

First tagged release. The engine has been running a live public demo since July 2026;
this marks the point where operators can pin a known version instead of tracking the
development branch.

### Engine

- **Data-driven rulesets.** Units, structures, research, defenses, terrain, weapon
  types and economy all live in a game definition (JSON), loaded at startup and
  hot-swappable at runtime. No ruleset is hardcoded in engine code.
- **Composable rule fragments.** Combat, defense, resource and map fragments layer
  over a base definition and compile into a single ruleset from the admin panel.
- **Engine flags** that reshape gameplay rather than reskin it: `resource_model`
  (single or multi-resource), `defense_model` (upgrade levels or unit counts),
  `defenses_destructible`, `combat_model` (simultaneous or rounds), `map_depth`,
  `map_topology` (nested hierarchy or graph of lanes and wormholes),
  `galaxy_network`, `economy_actions` (free actions or an action-point budget),
  and `win_condition`.
- **Combat** with proportional damage allocation under sub-linear weighting,
  overflow redistribution to surviving targets, shields with per-weapon-type
  passthrough, per-unit rounding classes, and configurable debris and loot.
- **Procedural galaxy generation**: multi-cluster spiral-density universe with
  configurable presets. Colonized planets are preserved across regeneration.
- **Conquest mode** (opt-in): occupation can escalate to permanent base loss,
  making an `annihilation` win condition reachable. Guild-aware last-team-standing.
- **NPC factions** with configurable per-galaxy targets, stability decay and
  disband/respawn lifecycle, excluded from player rankings.
- **Mod system**: content overlays (pure data) and behavioral mods (Python hooks
  such as `on_battle` and `compute_victory`). Seven mods ship with the engine.

### Operations

- Docker Compose deployment with SQLite on a persistent volume; optional PostgreSQL
  profile. SQLite (WAL), PostgreSQL and MySQL supported.
- Admin panel for game speed, balance constants, per-spec overrides, NPC settings,
  galaxy presets and ruleset selection, applied at runtime.
- Admin-activated game definitions persist across restarts.
- New database columns auto-migrate on startup.
- Optional public registry listing, opt-in and disabled by default.

### Interface

- Single-page vanilla-JS client, no build step, themeable via CSS variables.
- Responsive layout covering desktop and phone.

### License

- Released under the GNU Affero General Public License v3.0.

[0.97.0]: https://github.com/AstroWebEngine/astrowebengine/releases/tag/v0.97.0
