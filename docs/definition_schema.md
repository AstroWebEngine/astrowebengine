# Game Definition Schema Reference

This reference is split into sections. Each `## name` heading below is a top-level key of a game definition (plus `overview`). It is written for people and for AI assistants that build definitions section by section. Statements here were checked against the engine code; where the code does not make a field's effect clear, the doc says so instead of guessing.

## overview

A game definition is a single JSON object that holds every rule of a game: resources, combat, units, buildings, research, defenses. The engine has no hardcoded ruleset beyond lean built-in defaults; whatever the active definition says is what the game does. Definitions are loaded at startup and can be hot-swapped from the admin panel.

**Required top-level keys** (checked by validation after `extends` is resolved): `meta`, `engine`, `ships`, `buildings`, `research`, `defenses`, `weapon_types`.
**Optional top-level keys:** `extends`, `ui`, `economy`, `combat`, `fleet`, `tutorial`, `terrains`. Omitted optional blocks fall back to engine defaults.

| Key | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `meta` | object | yes | Name, version, author, description | `{"name": "My Game"}` |
| `extends` | string or list | no | Fragment files merged underneath this definition | `["fragments/combat/six_rounds.json"]` |
| `engine` | object | yes | Mode switches and tuning flags | `{"resource_model": "single"}` |
| `ui` | object | no | Theme, shell and label overrides | `{"theme": "awe"}` |
| `economy` | object | no | Build-speed and bonus constants | `{"min_build_time_seconds": 5}` |
| `combat` | object | no | Damage allocation, loot, debris | `{"loot_percent": 0.2}` |
| `fleet` | object | no | Fleet-size constant | `{"size_limit_multiplier": 2500}` |
| `weapon_types` | object | yes | Weapon classes and shield passthrough | `{"laser": {"shield_passthrough": 0.01}}` |
| `ships` | object | yes | Ship roster keyed by internal id | `{"scout": {}}` |
| `buildings` | object | yes | Structures keyed by internal id | `{"mine": {}}` |
| `research` | object | yes | Technologies keyed by internal id | `{"energy": {}}` |
| `defenses` | object | yes | Defensive structures keyed by internal id | `{"turret": {}}` |
| `tutorial` | string or list | no | Guided tutorial steps | `"classic"` |
| `terrains` | object | no | Planet terrain table | `{"rocky": {}}` |

**Conventions**
- Keys inside `ships`, `buildings`, `research`, `defenses`, `weapon_types` and `terrains` are stable internal ids. Other data refers to them by id (a ship's `weapon`, a `req` map, a rapid-fire target). The `name` field is display text only and can change freely; renaming an id breaks every reference to it.
- Use lowercase ids with underscores.
- Costs are a plain number in a single-resource game and a per-resource object in a multi-resource game (see `engine`).

**Workflow:** check, then save, then activate. First run the definition through validation (it reports errors, warnings and blocked changes without changing anything). Fix every error. Then save/activate it; activation validates again, syncs the unit roster into the running game, and persists the choice across restarts. If a universe already exists, changes to setup-only engine flags are blocked until the game is reset.

**Formulas the numbers feed** (all inputs come from the definition):
```
cost(level)        = base_cost * cost_mult ^ current_level
build_time_s       = (cost / construction_rate) * 3600     ; times economy.occupation_time_penalty at an occupied base
research_time_s    = (cost / research_rate) * 3600
construction_rate  = industrial + economy.construction_bonus_base (+ homeworld bonus) ; times tech multiplier
```
Durations have a floor (`economy.min_build_time_seconds`, `economy.min_research_time_seconds`).

## meta

Identity of the game. Shown in the UI and returned by the public engine-config endpoint.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | yes | Game name. Validation fails if empty. | `"Deep Frontier"` |
| `version` | string | no | Free-form version label | `"1.0"` |
| `author` | string | no | Free-form author label | `"AstroWebEngine"` |
| `description` | string | no | Short description shown to players | `"Multi-resource industry..."` |
| `component_type` | string | no | Used by bundled fragment files to label what they are (for example `"map"`); not read by the engine at runtime | `"map"` |

```json
"meta": {"name": "Classic Space", "version": "1.0", "author": "Community Project",
         "description": "Classic single-resource space strategy gameplay."}
```

Gotchas
- Only `name` is validated. The other fields are informational.

## extends

Lets a definition build on reusable fragment files. `extends` is a string or a list of strings; each is a path to a JSON file. Fragment files are ordinary partial definitions (usually just a few `engine` flags).

Semantics (from the compiler):
- Fragments are merged left to right, then the current definition is applied last, so the current definition wins.
- Objects merge recursively (deep merge). Lists and scalars are replaced wholesale, not concatenated.
- A fragment may itself use `extends`. Circular references are an error.
- References resolve relative to the file containing them, then relative to the `game_definitions/` folder. Paths that escape that folder are rejected. Files must end in `.json`.
- The `extends` key itself is removed from the compiled result.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `extends` | string or list of strings | no | Fragment paths to merge underneath this definition | `["fragments/map/depth_3.json", "fragments/combat/six_rounds.json"]` |

Bundled fragments live in `game_definitions/fragments/`: `combat/` (`single_round.json`, `six_rounds.json`), `defenses/` (`permanent_losses.json`, `regenerating_defenses.json`), `map/` (`depth_3.json`, `depth_4.json`), `resources/` (`single_credits.json`, `multi_mcd.json`).

```json
{"extends": ["fragments/map/depth_3.json"],
 "meta": {"name": "Flat Map Game"}}
```

Gotchas
- A list replaces, it does not append: if a fragment sets `engine.report_categories` and you set it too, yours replaces it entirely.
- A definition submitted over the API (not from a file) can only reference fragments that exist on the server under `game_definitions/`.
- Validation runs on the compiled result, so required keys may come from fragments.

## engine

Mode switches and tuning flags. Every flag below is read from `engine`. Safety class: `setup_only` flags are blocked from changing once a universe has been generated (reset the game first); `live` flags can change at any time (a few only take effect when the thing they govern next happens, noted below).

Required: `resource_model`, `defense_model`, `combat_model` (each must be one of the listed values). Everything else is optional.

| Field | Type | Required | Safety | Meaning | Example |
|---|---|---|---|---|---|
| `resource_model` | `"single"` or `"multi"` | yes | `setup_only` | Single currency or several resources. In multi mode costs must be per-resource objects. | `"multi"` |
| `resource_types` | list of strings | no | `setup_only` | Resource ids; the first is the primary resource. Default `["credits"]`. Set it for `multi`. | `["metal","crystal","deuterium"]` |
| `defense_model` | `"level"` or `"count"` | yes | `setup_only` | `level`: each defense is upgraded one level at a time with cost growing by `cost_mult`. `count`: you build N units at flat unit cost. | `"count"` |
| `combat_model` | `"simultaneous"` or `"rounds"` | yes | `setup_only` | `simultaneous` forces a single exchange regardless of `combat_max_rounds`. `rounds` fights up to `combat_max_rounds`. | `"rounds"` |
| `combat_max_rounds` | integer | no | `live` | Max combat rounds. Must be a positive integer when `combat_model` is `rounds`. Default 1. | `6` |
| `defenses_destructible` | boolean | no | `live` | `true`: destroyed defenses are lost (subject to repair). `false`: damage is stored instead of units being removed. Engine default when absent: false. | `true` |
| `defense_repair_percent` | number 0-1 | no | `live` | Fraction of destroyed defenses restored after a battle. Engine default when absent: 1.0. | `0.7` |
| `buildings_destructible` | boolean | no | `live` | Not implemented: combat never destroys buildings. Only `false` is valid; `true` is rejected by validation. | `false` |
| `ships_always_destroyed` | boolean | no | `live` | Not implemented: destroyed ships are always lost. Only `true` is valid; `false` is rejected by validation. | `true` |
| `construction_queue_max` | integer | no | `live` | Max items in a base's construction queue. | `6` |
| `research_queue_max` | integer | no | `live` | Max items in the research queue. | `6` |
| `production_queue_max` | integer | no | `live` | Max items in a base's ship production queue. | `12` |
| `map_depth` | `3` or `4` | no | `setup_only` | `4` = galaxy / region / system / orbit. `3` = galaxy / system / slot (flat). | `4` |
| `map_levels` | list of strings | no | `setup_only` | Names of the map levels. Descriptive only: not yet consumed by the engine; follow `map_depth`. | `["galaxy","region","system","orbit"]` |
| `map_topology` | string | no | `setup_only` | `"hierarchy"` (default) or `"graph"` (systems joined by explicit links; see `graph`). The legacy values `"pumpkin"` and `"classic"` are still read as a `galaxy_network` fallback. | `"hierarchy"` |
| `galaxy_network` | string | no | `setup_only` | How galaxies and clusters are arranged and how far apart they are. Geometric: `ring` (default), `equal_distance`, `line`, `pumpkin`, `wormhole_only`. Link-based: `lane_network`, `tree`, `small_world`, `k_random`, `dynamic_wormholes`. | `"ring"` |
| `galaxy_shape` | string | no | `setup_only` | Placement of systems inside a galaxy: `procedural_spiral` (default) or `templates`. | `"procedural_spiral"` |

Optional flags that are not in the safety sets (so they never block a switch; treat them as `live`, but note when they bite):

| Field | Type | Required | Safety | Meaning | Example |
|---|---|---|---|---|---|
| `report_categories` | list of strings | no | `live` | Which Reports sidebar entries the client shows (ids: scanners, player, guild, galaxy, top_scouters, top_jump_gates, trade, wormholes, astros). Read by the client. | `["scanners","player"]` |
| `starting_resources` | object or number | no | `live` | Starting stash for new players in multi-resource games, as `{resource: amount}` or one number applied to each. Default: 2000 of the first resource, 1000 of the others. Ignored in single mode. | `{"metal":5000}` |
| `moon_formation` | boolean | no | `live` | Battle debris may create a moon at the slot. | `true` |
| `moon_chance_per_100k_debris` | number | no | `live` | Moon chance per 100,000 debris (default 0.01). | `0.01` |
| `moon_max_chance` | number | no | `live` | Cap on the moon chance (default 0.20). | `0.2` |
| `moon_min_chance` | number | no | `live` | Below this chance no moon forms (default 0.01). | `0.01` |
| `moon_terrain` | string | no | `live` | Terrain id given to a new moon (default `craters`). | `"craters"` |
| `moon_destruction` | boolean | no | `live` | Ships flagged `can_destroy_moons` can destroy moons. | `true` |
| `rebuild_model` | `"fixed"` or `"binomial"` | no | `live` | How repaired/rebuilt units are counted: deterministic fraction (default) or a random binomial draw. | `"binomial"` |
| `fleet_rebuild_factor` | number 0-1 | no | `live` | Fraction of lost ships rebuilt after battle (default 0). | `0.0` |
| `plunder_model` | string | no | `live` | `"cargo"` makes a winning attacker steal resources up to its ships' `cargo` capacity. Other values do nothing. | `"cargo"` |
| `plunder_percent` | number 0-1 | no | `live` | Share of the defender's stock that can be plundered (default 0.5). | `0.5` |
| `shield_bounce_threshold` | number | no | `live` | Shots weaker than this fraction of the target's shield are bounced (default 0 = off). | `0.01` |
| `world_model` | string | no | `live` (applies when worlds are generated) | `"uniform"` generates one terrain everywhere with per-position size/temperature bands; anything else uses the terrain model. | `"uniform"` |
| `uniform_terrain` | string | no | `live` (generation time) | Terrain id used when `world_model` is `uniform`. | `"rocky"` |
| `uniform_positions` | integer | no | `live` (generation time) | Orbit positions per system in uniform mode (default 15). | `15` |
| `position_profiles` | object | no | `live` (generation time) | Per-position overrides in uniform mode: position number to `{"area": [min,max], "temperature": [min,max]}`. | `{"1":{"area":[105,155],"temperature":[106,120]}}` |
| `economy_actions` | string | no | `live` | `"action_points"` switches to a regenerating action-point pool that actions spend. Absent means the normal time-based economy. | `"action_points"` |
| `action_points` | object | no | `live` | Used with `economy_actions`: `start`, `regen_per_hour`, `max`, `apply_to_bots`, and `costs` (a map of action key to cost, for example `fleet_send`, `fleet_attack`, `colonize`). | `{"start":40,"regen_per_hour":10,"max":250}` |
| `graph` | object | no | `live` (link generation time) | Tuning when `map_topology` is `graph`: `links_per_system` `[min,max]`, `allow_one_way`, `wormhole_ratio`, `link_cost_model` (`hops` or `weighted`), `hop_distance`. | `{"links_per_system":[2,6]}` |
| `wormhole_model` | string | no | `live` | `jumpgate` (default, speed bonus on a normal trip), `natural` (flat travel time, optional damage), `none`. | `"natural"` |
| `wormhole_flat_travel_hours` | number | no | `live` | Flat hop time for `natural` wormholes (default 12). | `12` |
| `wormhole_damage_percent` | number 0-1 | no | `live` | Fraction of each ship type lost crossing a natural wormhole (default 0). | `0` |
| `occupation_zero_production` | boolean | no | `live` | An occupied base produces nothing for its owner. | `true` |
| `occupation_capture` | boolean | no | `live` | Long occupation escalates to permanent loss of the base. | `true` |
| `occupation_capture_hours` | number | no | `live` | Continuous occupation hours before capture (default 6). | `6` |
| `occupation_capture_mode` | `"disband"` or `"transfer"` | no | `live` | `disband`: owner is refunded. `transfer`: the occupier gains the base. | `"disband"` |

```json
"engine": {"resource_model": "multi", "resource_types": ["metal", "crystal", "deuterium"],
           "defense_model": "count", "defenses_destructible": true, "defense_repair_percent": 0.7,
           "buildings_destructible": false, "ships_always_destroyed": true,
           "combat_model": "rounds", "combat_max_rounds": 6, "map_depth": 4,
           "construction_queue_max": 6, "research_queue_max": 6, "production_queue_max": 12,
           "moon_formation": true, "rebuild_model": "binomial", "plunder_model": "cargo"}
```

Gotchas
- Setup-only flags (`combat_model`, `resource_model`, `defense_model`, `map_depth`, `map_levels`, `map_topology`, `galaxy_network`, `galaxy_shape`, `resource_types`) are blocked from changing once a universe exists. Reset the game first.
- Multi-resource games: a `multi` definition with two or more resources where every cost is a plain number is rejected, because every cost would silently fall on the first resource. Give costs as `{"metal": n, "crystal": n}`.
- `buildings_destructible: true` and `ships_always_destroyed: false` are rejected by validation; leave them at `false` and `true`.
- Flags the engine reads through its config layer (map, wormhole, queue and conquest flags among them) can also be overridden at runtime by an admin setting of the same name, which wins over the definition.
- The whole `engine` block is public: the engine-config endpoint returns it.
- An absent optional flag is not an error; the engine uses the default noted in the table.

## ui

Optional presentation hints returned to the client with the engine config. The client applies them on load unless the player picked their own theme.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `theme` | string | no | Visual theme. Omitted means `awe`, the AstroWebEngine default (charcoal, ivory, copper, amber). Bundled alternatives: `neutral` (slate and blue) and `classic` (the original blue-and-gold look, no theme attribute). | `"awe"` |
| `shell` | string | no | Layout shell. Omitted means `neutral` (flat single app bar) under the `awe` theme, and the classic layout otherwise. The bundled stylesheet defines `neutral`. | `"neutral"` |
| `labels` | object | no | Overrides for navigation text by translation key. Keys the client knows: `nav.bases`, `nav.galaxy`, `nav.fleets`, `nav.empire`, `nav.commanders`, `nav.guild`, `nav.messages`, `nav.ranks`, `nav.report`, `nav.tables`, `nav.help`, `nav.account`, `nav.more`. | `{"nav.bases": "Planets"}` |
| `art` | string | no | Default artwork. Omitted means `awe` (the engine's AWE art set, for keys it covers); `none` turns the default set off. A spec's own `image` always wins. | `"none"` |

```json
"ui": {"theme": "awe", "shell": "neutral",
       "labels": {"nav.bases": "Planets", "nav.fleets": "Fleet"}}
```

Gotchas
- Unknown theme or shell ids are applied as attributes but have no styling.
- Only translation keys the client uses have any effect; others are ignored. Label overrides apply to interface text, not to unit, building or research names (those come from each spec's `name`).

## economy

Constants that tune construction, research and base output. Every field is optional; an absent field falls back to the engine default.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `construction_bonus_base` | number | no | Flat construction rate added to every base on top of factory output. | `2500` |
| `construction_bonus_homeworld` | number | no | Extra construction rate at the first (home) base. | `0` |
| `base_energy_bonus` | number | no | Flat energy added to every base before the energy-tech multiplier. | `2` |
| `capital_empire_bonus` | number | no | Economy points a base gets when the player has a Capital building at another base. | `1` |
| `occupation_time_penalty` | number | no | Multiplier on build and research time at an occupied base (1.3 = 30 percent slower). | `1.3` |
| `min_build_time_seconds` | integer | no | Floor for any construction duration. | `5` |
| `min_research_time_seconds` | integer | no | Floor for any research duration. | `5` |

```json
"economy": {"construction_bonus_base": 20, "construction_bonus_homeworld": 20,
            "base_energy_bonus": 2, "capital_empire_bonus": 1,
            "occupation_time_penalty": 1.3, "min_build_time_seconds": 5,
            "min_research_time_seconds": 5}
```

Gotchas
- Construction duration is `cost / construction_rate` hours, so `construction_bonus_base` must be on the same scale as your costs. A game with costs in the thousands needs a large bonus (the bundled multi-resource game uses 2500); a bonus of 20 against costs of 60,000 makes every build take days.
- `capital_empire_bonus` only matters if some building is keyed exactly `capital`.

## combat

Constants for damage resolution and aftermath. Optional; absent fields use engine defaults.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `damage_allocation_exponent` | number | no | Damage is spread over target types in proportion to a sub-linear weight (value raised to this exponent). Lower values spread damage more evenly. | `0.85` |
| `loot_percent` | number 0-1 | no | Fraction of value looted by the winner. | `0.2` |
| `debris_percent` | number 0-1 | no | Fraction of destroyed value that becomes debris at the planet. | `0.4` |

```json
"combat": {"damage_allocation_exponent": 0.85, "loot_percent": 0.2, "debris_percent": 0.4}
```

Gotchas
- Model, round count, defense destruction and repair are `engine` flags, not fields here.
- Weapon strength and shields interact through `weapon_types` (`shield_passthrough`). Per-unit rounding is the ship/defense `rounding` field.

## fleet

Fleet constants. Optional. Only `size_limit_multiplier` is read from this block by the engine.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `size_limit_multiplier` | number | no | Max total fleet value = the player's total production rate times this. | `2500` |
| `travel_divisor` | number | no | Present in bundled definitions but not read from here: travel time uses the admin setting `FLEET_TRAVEL_DIVISOR` (engine default 3600). Larger means slower travel. | `200` |
| `base_fleet_count` | integer | no | Present in bundled definitions but not read from here: the engine takes it from the admin setting `BASE_FLEET_COUNT`. | `5` |

```json
"fleet": {"travel_divisor": 200, "base_fleet_count": 5, "size_limit_multiplier": 2500}
```

Gotchas
- Setting `travel_divisor` or `base_fleet_count` in a definition has no effect on its own. To tune travel speed or fleet slots, use the admin settings.

## weapon_types

Weapon classes. A ship or defense names one in its `weapon` field. The only mechanic a weapon type carries is how much damage ignores shields.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | no | Display name | `"Laser"` |
| `shield_passthrough` | number 0-1 | yes | Fraction of damage that bypasses shields. Low values (about 0.01) mean shields stop almost everything; high values (0.5) mean shields are mostly ignored. | `0.01` |

Keys are weapon ids. Research `weapon_power` bonuses refer to these ids.

```json
"weapon_types": {"ballistic": {"name": "Mass Driver", "shield_passthrough": 0.02},
                 "ion": {"name": "Ion", "shield_passthrough": 0.5}}
```

Gotchas
- Every weapon type needs `shield_passthrough`; validation fails without it.
- Every `weapon` used by a ship must exist here (validated). Defense `weapon` references are not validated, so check them yourself.

## ships

The ship roster, keyed by internal id. Validation requires `name`, `cost`, `attack`, `armour`, `shield`, `weapon` on every ship; the engine fills defaults for the other basic fields (`desc` empty, `speed` 0, `hangar` 0, `drive` `"inter"`, `shipyard` 0, `req` empty, `rounding` 0).

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | yes | Display name | `"Cruiser"` |
| `cost` | number or object | yes | Build cost: number (single) or `{resource: n}` (multi) | `{"metal":20000,"crystal":7000}` |
| `attack` | number | yes | Attack power per unit | `400` |
| `armour` | number | yes | Hull points per unit | `270` |
| `shield` | number | yes | Shield strength per unit | `50` |
| `weapon` | string | yes | Id from `weapon_types` | `"ion"` |
| `desc` | string | no | Description text | `"Fast mid-line warship."` |
| `speed` | number | no | Base speed. Ships with speed 0 are ignored when working out fleet speed. | `6` |
| `drive` | string | no | Drive class. Speed is boosted 5 percent per level of the `warp_drive` tech if the drive is `"warp"`, otherwise per level of the `stellar_drive` tech (those two tech ids are hardcoded; if absent the level is 0). `speed_multiplier` research bonuses can match a drive id or a ship id. | `"impulse"` |
| `hangar` | integer | no | Positive: carrier capacity. Negative: the ship uses that much carrier space per unit when moved. 0: neither. | `-1` |
| `shipyard` | integer | no | Shipyard level a base needs to build it | `5` |
| `req` | object | no | Tech prerequisites `{tech_id: level}` | `{"impulse_drive": 4}` |
| `rounding` | 0, 1 or 2 | no | Combat survivor rounding class: 0 whole units, 1 tenths, 2 thousandths (capital-style precision). If `rounding` is absent it may be derived from a `class`/`ship_class`/`hull_class` text (small/light/utility = 0, medium = 1, large/capital/heavy/supercapital = 2). | `1` |
| `cargo` | number | no | Cargo capacity, used by `plunder_model: "cargo"` | `800` |
| `rapid_fire` | object | no | `{target_id: shots}`: extra shots against that unit id | `{"interceptor": 6}` |
| `fleet_bonus` | number | no | Power and armour bonus for the whole fleet while this ship is present (the highest one in the fleet applies); for example 0.05 = +5 percent | `0.05` |
| `can_colonize` | boolean | no | Capability flag: founds a new base | `true` |
| `can_recycle` | boolean | no | Capability flag: collects debris | `true` |
| `can_autoscout` | boolean | no | Capability flag: usable for automatic scouting | `true` |
| `can_destroy_moons` | boolean | no | Capability flag: can destroy moons (also needs engine `moon_destruction`) | `true` |

```json
"cruiser": {"name": "Cruiser", "desc": "Fast mid-line warship, strong vs fighters.",
            "cost": {"metal": 20000, "crystal": 7000, "deuterium": 2000},
            "attack": 400, "armour": 270, "shield": 50, "speed": 6, "hangar": 10,
            "weapon": "ion", "drive": "impulse", "shipyard": 5,
            "req": {"impulse_drive": 4, "ion_tech": 2}, "rounding": 1, "cargo": 800,
            "rapid_fire": {"interceptor": 6}}
```

Gotchas
- `weapon` must exist in `weapon_types` (validated).
- In a multi-resource game, per-resource objects (ids from `engine.resource_types`) are how costs are expressed. A scalar cost falls entirely on the primary resource, and a definition with no per-resource costs at all is rejected.
- Capability flags are looked up by truthiness of the field on the spec, so any ship with the flag set gets the ability.
- `req` keys must be real research ids. They are not validated, and an unknown tech id makes the ship unbuildable.
- `tier` appears in the built-in default roster but no engine code reads it; it is informational.
- Total fleet value is capped by production (`fleet.size_limit_multiplier`).


### Artwork (`image`)

Any ship, building, defense, research or terrain spec may set `image` to its own
artwork. It wins over the AWE default set and the classic planet pictures.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `image` | string | no | An `https://` URL, a site path (`/static/...`) or a path under `/static` (`art/mygame/cruiser.webp`). Quotes, spaces, `..` and other schemes are rejected. Square images work best; units are shown at 48 px, planets up to 240 px. | `"art/mygame/cruiser.webp"` |
## buildings

Structures built per base, keyed by internal id. Required: `name`, `base_cost`, `cost_mult`. Everything a building does comes from its `contributions`.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | yes | Display name | `"Metal Extractor"` |
| `base_cost` | number or object | yes | Cost of level 1; the cost of level N+1 is `base_cost * cost_mult ^ N` | `{"metal":60,"crystal":15}` |
| `cost_mult` | number | yes | Per-level cost growth | `1.5` |
| `desc` | string | no | Description text | `"Strip-mines metal."` |
| `energy_req` | number | no | Energy used per level | `10` |
| `pop_req` | number | no | Population used per level | `0` |
| `area_req` | number | no | Area used per level. `0` marks an orbital building (eligible for orbital build-time tech). | `1` |
| `max_level` | integer | no | Level cap; 0 means unlimited | `0` |
| `tech_req` | object | no | Research prerequisites `{tech_id: level}` | `{"tachyon_communications": 1}` |
| `start_level` | integer | no | Level every new base starts with (default 0) | `2` |
| `unique` | boolean | no | Only enforced for the building keyed `capital`: one per empire | `true` |
| `contributions` | object | no | What the building adds per level; see below | `{"metal":{"type":"flat","per_level":30}}` |
| `time` | number | no | Stored but not used to compute duration (duration comes from cost and construction rate) | `60` |
| `advanced` | boolean | no | Stored; no engine code reads it | `false` |

**contributions** is a map `{stat: rule}`. A rule is `{"type": "flat", "per_level": n}` (adds `n * level`) or `{"type": "planet_stat", "stat": "<planet attribute>", "per_level": n}` (adds `n * level * planet_stat`; `fertility` uses the effective fertility). The special stat `fertility_modifier` adds to a planet's fertility before other contributions are evaluated. Stats the engine reads: `energy`, `population`, `area`, `economy`, `industrial` (feeds both construction and production), `production`, `research`, `research_lab_level`, `shipyard_level`, `ground_shipyard`, `orbital_shipyard`, `command_level`, `jump_gate_level`, and `fertility_modifier`. In a multi-resource game, a stat named after a resource id (for example `metal`) is that resource's hourly income.

```json
"metal_extractor": {"name": "Metal Extractor", "desc": "Strip-mines metal from the planet crust.",
                    "base_cost": {"metal": 60, "crystal": 15}, "cost_mult": 1.5,
                    "energy_req": 10, "pop_req": 0, "area_req": 1, "max_level": 0,
                    "tech_req": {}, "start_level": 2,
                    "contributions": {"metal": {"type": "flat", "per_level": 30}}}
```

Gotchas
- Validation requires `name`, `base_cost`, `cost_mult` only; a building with no `contributions` does nothing.
- Resource-named contributions only produce income when the resource id is in `engine.resource_types`; in a single-resource game income flows through the `economy` stat.
- Some engine rules refer to fixed building ids: `capital` (economy bonus and uniqueness) and `jump_gate` (fleet speed bonus). The bundled tutorial also names specific building ids. If your ruleset uses other ids, those features do nothing.
- Energy, population and area requirements are checked against what will be free after queued items complete.

## research

Technologies, keyed by internal id. Researched globally per player and gated by research lab level at a base.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | yes (by convention) | Display name | `"Energy Theory"` |
| `base_cost` | number or object | yes (by convention) | Cost of level 1; later levels cost `base_cost * cost_mult ^ level` | `{"crystal":800,"deuterium":400}` |
| `cost_mult` | number | yes (by convention) | Per-level cost growth | `2.0` |
| `lab_req` | integer | no | Research lab level needed at the base (default 1) | `1` |
| `prereqs` | object | no | Other techs needed `{tech_id: level}` | `{"energy": 2}` |
| `stat_req` | object | no | Base-scale requirement, for example `{"energy": 300000}`: the base needs that much free energy (a raw value for stats without a used counterpart) | `{"energy": 300000}` |
| `bonuses` | list of objects | no | Numeric effects, see below | `[{"type":"stat_multiplier","stat":"energy","per_level":0.05}]` |
| `bonus` | string | no | Human-readable summary of the effect (display only) | `"+5% energy per level"` |
| `icon` | string | no | Icon shown in the UI | `"E"` |
| `base_time` | number | no | Stored but not used to compute duration (duration comes from cost and research rate) | `80` |

Validation does not check research fields. The engine reads `base_cost`, `cost_mult` and `lab_req` directly, so omitting `base_cost` or `cost_mult` breaks research.

**bonuses** entries (`per_level` is applied per research level):
- `stat_multiplier`: `stat` is one of `energy`, `construction`, `production`, `research`. Multiplier = 1 + `per_level` * level, summed across techs.
- `weapon_power`: `weapon` is a `weapon_types` id. Multiplies attack of that weapon.
- `combat_stat`: `stat` is `armour` or `shield`. Multiplies that stat for all units.
- `fleet_count`: extra fleet slots.
- `speed_multiplier`: `drive` (a drive id) or `ship` (a ship id); multiplies speed.
- `stealth`: adds to the player's stealth factor (reduces detection); how scouting uses the value is not documented here.
- `research_link`: adds research links.
- `orbital_build_time`: scales build time of orbital buildings (those with `area_req` 0); use a negative `per_level`, for example -0.05.
- `unlock`: no numeric effect; unlocks are enforced through other items' `req` and `tech_req`.

```json
"energy_theory": {"name": "Energy Theory", "base_cost": {"crystal": 800, "deuterium": 400},
                  "cost_mult": 2.0, "base_time": 1, "lab_req": 1, "prereqs": {},
                  "bonus": "+5% energy output per level",
                  "bonuses": [{"type": "stat_multiplier", "stat": "energy", "per_level": 0.05}]}
```

Gotchas
- Tech ids used in `req`, `tech_req` and `prereqs` must match research ids exactly.
- Fixed tech ids: `stellar_drive` and `warp_drive` control ship speed bonuses (see `ships`).
- A bonus `type` outside the list above is silently ignored.

## defenses

Planetary defenses, keyed by internal id. Behavior depends on `engine.defense_model`: in `level` mode each purchase raises one level and the cost grows by `cost_mult`; in `count` mode each purchase builds N units at flat unit `cost`.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | yes (by convention) | Display name | `"Rocket Turret"` |
| `cost` | number or object | yes (by convention) | Unit cost (count mode) or level-1 cost (level mode) | `{"metal":2000}` |
| `attack` | number | yes (by convention) | Attack per unit | `80` |
| `armour` | number | yes (by convention) | Hull per unit | `40` |
| `shield` | number | yes (by convention) | Shield per unit | `0` |
| `weapon` | string | yes (by convention) | Id from `weapon_types` | `"ballistic"` |
| `desc` | string | no | Description text | `"Cheap kinetic launcher."` |
| `cost_mult` | number | no | Level mode: per-level cost growth (default 1.5) | `1.5` |
| `energy_req` | number | no | Energy used per level or unit | `0` |
| `pop_req` | number | no | Population used per level or unit | `1` |
| `area_req` | number | no | Area used per level or unit | `0` |
| `max_level` | integer | no | Level cap (default 50) | `50` |
| `req` | object | no | Tech prerequisites `{tech_id: level}` | `{"laser": 1}` |
| `rounding` | 0, 1 or 2 | no | Not read for defenses: combat always uses rounding class 2 (thousandths) for defenses, so this field has no effect | `0` |

The validator checks no defense fields. The engine reads the fields above directly, so leaving out `cost`, `attack`, `armour` or `weapon` fails at build or combat time.

```json
"rocket_turret": {"name": "Rocket Turret", "desc": "Cheap kinetic launcher.",
                  "cost": {"metal": 2000}, "cost_mult": 1.0,
                  "energy_req": 0, "pop_req": 0, "area_req": 0,
                  "attack": 80, "armour": 40, "shield": 0, "weapon": "ballistic",
                  "max_level": 1000000, "req": {}}
```

Gotchas
- Not validated: make sure `weapon` is defined in `weapon_types`.
- In count mode set `max_level` high (the bundled count-mode game uses 1,000,000); the default cap of 50 applies when the field is absent.
- `defenses_destructible`, `defense_repair_percent` and `defense_model` in `engine` decide how losses and repairs work.

## tutorial

Optional guided-tutorial content. The value of `tutorial` selects the source:
- the string `"classic"`: the engine-bundled tutorial;
- a list of step objects: your own tutorial;
- absent, `false` or empty: no tutorial.

Each step object (as consumed by the tutorial routes):

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `id` | string | yes | Unique step id | `"base_structures"` |
| `title` | string | yes | Step title | `"Base Structures"` |
| `description` | string | yes | Instruction text | `"Build a mine."` |
| `reward` | number | yes | Amount paid when the step is collected (0 for none) | `500` |
| `mission` | object or null | no | Objective whose completion is auto-detected; null = a plain "continue" step | see below |
| `optional_mission` | object | no | Bonus objective shown alongside the main mission | see below |
| `requirements` | list of mission objects | no | Prerequisite objectives shown as met or unmet | `[]` |

Mission objects have a `text` label and a `type`, plus type-specific fields:

| `type` | Extra fields | Done when |
|---|---|---|
| `building` | `building_type`, `target_level` | any base has that building at that level |
| `building_any_energy` | none | any of the building ids `solar_plants`, `gas_plants`, `fusion_plants`, `antimatter_plants`, `orbital_plants` is level 1 or more |
| `research` | `tech_type`, `target_level` | that tech reaches the level |
| `ship` | `ship_type`, `target_count` | player owns that many of the ship |
| `defense_any` | `target_level` | any defense reaches the level |
| `colony_count` | `target_count` | player owns that many bases |
| `trade_route` | `target_count` | player owns that many trade routes |
| `move_fleet` | `ship_type` | a fleet containing that ship has been sent out |
| `move_combat_fleet` | `required_ships` (`{ship_id: count}`) | a sent fleet holds all those ships |

```json
"tutorial": "classic"
```

A custom step:
```json
"tutorial": [{"id": "welcome", "title": "Welcome", "description": "Build your first mine.", "reward": 0,
              "mission": {"text": "Build a Metal Extractor", "type": "building",
                          "building_type": "metal_extractor", "target_level": 1}}]
```

Gotchas
- A mission `type` not in the table never completes.
- Rewards are paid in the primary resource only.
- The `"classic"` tutorial refers to the classic roster's ids (for example `metal_refineries`); use it only with a matching roster. For any other roster, write your own steps or omit the key.
- Some tutorial behavior depends on step position rather than data (the second-to-last step triggers end-of-tutorial handling when collected). In a custom list keep the steps linear and put a closing step last.

## terrains

Planet terrain table, keyed by terrain id. Optional: when absent, the engine's built-in table is used (rocky, arid, earthly, gaia, glacial, magma, oceanic, toxic, tundra, volcanic, radioactive, crystalline, metallic, craters, asteroid, asteroid_belt, gas_giant). When you supply `terrains`, it replaces the whole built-in table, so list every terrain you want to exist.

| Field | Type | Required | Meaning | Example |
|---|---|---|---|---|
| `name` | string | yes (by convention) | Display name | `"Rocky"` |
| `solar` | number | no | Base solar energy before orbit modifiers | `0` |
| `gas` | number | no | Gas yield (feeds gas-based energy contributions) | `2` |
| `fertility` | number | no | Fertility; drives population from `planet_stat` fertility contributions | `5` |
| `metal` | number | no | Metal richness stat; used by contributions with `"stat": "metal"` | `4` |
| `crystal` | number | no | Crystal richness stat; used by contributions with `"stat": "crystal"` | `0` |
| `area_planet` | integer or null | no | Base build area when the body is a planet; null = cannot be a planet | `85` |
| `area_moon` | integer or null | no | Base build area when the body is a moon; null = cannot be a moon | `75` |
| `colonizable` | boolean | no | `false` blocks colonizing this terrain (default true) | `false` |

```json
"terrains": {"rocky": {"name": "Rocky", "solar": 0, "gas": 2, "fertility": 5,
                       "area_planet": 85, "area_moon": 75, "metal": 4, "crystal": 0},
             "gas_giant": {"name": "Gas Giant", "solar": 0, "gas": 6, "fertility": 0,
                           "area_planet": null, "area_moon": null, "metal": 0, "crystal": 0,
                           "colonizable": false}}
```

Gotchas
- Neither bundled definition sets `terrains`; both use the built-in table.
- World generation weights are tied to the built-in terrain ids. The code does not show how a custom terrain id is weighted into generation, so test a generated galaxy before relying on custom terrains. The `moon_terrain` and `uniform_terrain` flags and the `world_model: "uniform"` option are the supported ways to steer terrain.
- Changing terrains affects only worlds generated afterwards; existing planets keep their stats.
