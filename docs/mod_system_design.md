# AstroWebEngine Mod System — Design

Status: **draft / design** (no code yet). This doc proposes how AstroWebEngine
(AWE) turns its existing data-driven composition into a first-class **mod /
add-on system**, so operators extend their game by *installing mods* rather
than editing engine source.

---

## 1. Goals & principles

1. **The core is immutable.** A regular operator never edits engine `.py`. They
   install mods. This is the contract that "saves a lot of broken code" — there
   is one canonical engine, and bugs in a mod can't be bugs in the core.
2. **Mods are add-ons, composed — not forks.** A mod layers onto a base game
   definition; it never replaces the engine.
3. **Stable surface, hidden internals.** Mods bind to a versioned *mod API*
   (data schema + hook points), not to engine internals that move between
   releases.
4. **Mods are products.** A mod has an author, a version, and a license. Free
   or paid. Distribution and discovery run through the AWE registry/marketplace.
5. **Safe by default.** Content mods are pure data (zero code execution).
   Behavioral mods run code and require explicit trust + sandboxing.

---

## 2. What already exists (the foundation)

AWE is already data-driven. The pieces a mod system builds on:

- **Game definitions** (`game_definitions/*.json`) — the complete ruleset
  (units, buildings, research, defenses, terrain, engine flags, display names).
- **Rule fragments** (`game_definitions/fragments/<component_type>/*.json`) —
  small, named, composable pieces. Each carries `meta` (`name`, `version`,
  `description`, `component_type`) plus the data it contributes.
- **Composition** — `game_definition.py`:
  - `extends` (string or list) references fragments; `_deep_merge` merges them
    recursively with **child-wins** semantics; circular `extends` is rejected.
  - `load_definition_from_file(..., compile_extends=True)` resolves a definition
    + its fragments into one compiled ruleset.
  - `validate_definition()` checks the result.
- **Admin "Build Game" UI** — composes fragments and hot-swaps the active
  definition at runtime.
- **Client catalog** (`/api/catalog/*`, `core.js`) — display names/specs resolve
  through a normalized catalog, so renaming/adding content is already a
  data-only operation on the client too.

**Implication:** *content* modding already works without touching code. A mod
system mostly (a) **packages** this, (b) adds a **lifecycle** (install/enable/
disable), and (c) adds a **hook API** for the one thing data can't express today
— new *behavior*.

---

## 3. Mod taxonomy

| Type | Contains | Code? | Examples |
|------|----------|-------|----------|
| **Content mod** | game-definition fragments | No | new ship line, rebalance, a "hardcore" ruleset, new terrain table |
| **Skin / asset mod** | CSS vars, images, i18n strings | No | a theme, a localization, reskinned UI |
| **Behavioral mod** | content + hook handlers | **Yes** | "plague" event each tick, a building with a novel effect, a custom victory condition |

Content and skin mods are pure data and always safe. Behavioral mods are where
the new engineering (and the trust/security model) lives.

---

## 3.5 Rulesets ARE mods (the "million options" model)

The engine ships with **no ruleset of its own** — it's a configurable machine
("a million options"). What makes it *a game* is a mod. This is the natural
endpoint of the data-driven design, and it has two big payoffs:

- **A game is `base + ruleset mod (+ rule mods + skins)`.**
  - A neutral **Base Game** mod ships first-party so the engine is playable out
    of the box (and dogfoods the format).
  - A **"Classic Space" ruleset mod** configures the engine to play like the
    faithful reference game. **It can stay private** — the operator installs it
    on their server; it is never in the public engine repo.
  - Other ruleset mods (sci-fi, fantasy, minimal) are just different content
    packages over the same engine.

- **It cleanly resolves the legal strategy.** Instead of "neutral engine + a
  private game definition," the model becomes "neutral engine + a *private
  ruleset mod*." The reference-game flavor is isolated as a removable add-on the
  engine never ships. The public engine is provably generic; the faithful mod is
  the operator's private install. (Supersedes the older framing in
  [[opensource-defingerprint]].)

### "A different combat engine" as a mod

This is the motivating case for the hook API (§6):

- **Tuning** the existing combat (rounds vs simultaneous, max rounds, repair %)
  is already pure **content** — engine flags in a fragment
  (`combat_model`, `combat_max_rounds`, …). A "6-round combat" mod is just
  `fragments/combat/six_rounds.json`. No code.
- A genuinely **different resolution algorithm** is a **behavioral** mod: it
  registers a `resolve_battle` hook (an *overriding* extension point) that
  replaces the default resolver via `ctx`. The engine calls the registered
  resolver instead of the built-in one. This is exactly why overriding hooks
  (§6, `ctx.stop()`) exist.

So: balance/format swaps = content mods (today, basically); a new combat *engine*
= a behavioral mod against a stable hook — without forking core.

---

## 4. Mod package format

A mod is a single directory (or zip) under `mods/<mod_id>/`:

```
mods/
  hardcore_combat/
    manifest.json          # required — identity, compat, contents, license
    definition/            # game-definition fragments (content)
      combat/no_repair.json
      units/elite_ships.json
    assets/                # optional — images, fonts
    skins/                 # optional — CSS var overrides
    i18n/                  # optional — string tables, per-locale
    hooks/                 # optional — behavioral code (Python), see §6
      __init__.py
    LICENSE                # optional — mod's own license (free/paid/custom)
```

### manifest.json (proposed schema)

```json
{
  "id": "hardcore_combat",
  "name": "Hardcore Combat",
  "version": "1.2.0",
  "author": "someone",
  "homepage": "https://...",
  "license": "free",                 // free | paid | custom | SPDX id
  "engine_api": "^1.0",              // mod API version this targets (semver)
  "requires": [],                    // other mod ids this depends on
  "conflicts": ["peaceful_mode"],    // mutually exclusive mods
  "provides": {
    "definition": ["combat/no_repair.json", "units/elite_ships.json"],
    "skins": ["dark_steel"],
    "i18n": ["en", "de"],
    "hooks": ["on_battle_resolved", "on_tick"]   // declared, see §6
  },
  "load_order": 100                   // lower loads first; ties broken by id
}
```

`engine_api` is the key compatibility contract: the engine advertises a mod-API
version (e.g. `1.0`); a mod that needs `^1.0` is rejected on a `2.x` engine with
a clear message instead of breaking at runtime.

---

## 5. Loader & lifecycle

New module, e.g. `mod_loader.py`:

- **Discover** — scan `mods/`, parse each `manifest.json`, validate schema.
- **Resolve** — check `engine_api` compat, `requires`, `conflicts`; topologically
  order by `requires` then `load_order` then `id`.
- **Enable/disable** — persisted in `game_config` (admin toggle, like spec
  overrides today). Disabled mods are inert.
- **Compose** — for enabled mods in order, fold their `definition/` fragments
  into the active game definition using the **existing** `_deep_merge`
  (child-wins). Mods are, in effect, dynamically-discovered `extends` sources.
- **Register hooks** — import enabled behavioral mods' `hooks/` and register
  their handlers (see §6).
- **Hot-swap** — reuse the Build Game hot-swap path so enabling a mod re-compiles
  the active definition without a restart (content); behavioral hooks register
  at load.

Admin UI: a "Mods" panel listing discovered mods with enable/disable, version,
license badge, compat status, and conflicts — parallel to today's Build Game UI.

---

## 6. Hook / extension API (behavioral mods)

The piece data can't express. The engine exposes **named extension points** it
calls at well-defined moments; mods register handlers. Handlers receive a
**typed context** and a constrained API object — never raw ORM/internal access.

Candidate hook surface (start small, grow deliberately):

| Hook | Fired when | Context |
|------|-----------|---------|
| `on_tick(ctx)` | each background tick | game time, rng |
| `on_battle_resolved(ctx)` | after `combat.resolve_battle` | attacker/defender snapshots, losses, debris |
| `on_colony_founded(ctx)` | colony created | colony, owner |
| `on_research_completed(ctx)` | research finishes | user, tech |
| `on_economy_collect(ctx)` | resource collection | colony, amounts (mutable) |
| `resolve_battle(ctx)` *(overriding)* | a battle needs resolving | forces/specs → losses/result; replaces the default resolver if a mod provides one |
| `compute_victory(ctx)` | win-condition check | game state → optional winner |

Design rules:
- **One-way data + a narrow API.** `ctx` exposes read models and a small set of
  sanctioned mutations (`ctx.grant_resources`, `ctx.send_message`, …), not the
  `Session` or models directly. This keeps the engine free to refactor internals.
- **Deterministic rng.** Hooks get `ctx.rng` seeded by the engine so behavior is
  reproducible and testable.
- **Versioned.** The hook set + `ctx` shape are the `engine_api` contract.
- **Fail-soft.** A throwing hook is caught, logged, and disabled for the tick;
  one bad mod can't take down the server.

Implementation note: hooks are a thin registry (`mod_hooks.py`) the engine calls
at the listed points. Adding a hook point = one engine call site + a doc entry.

### The `resolve_battle` override facade ✅ built

`combat.resolve_battle` is a **facade**: it calls `fire_override("resolve_battle")`
first; if a mod returns a report, that report is used and the built-in
`_resolve_battle_default` is skipped — otherwise the default runs. `on_battle_resolved`
observers fire once afterward for both paths. Because every caller binds to
`combat.resolve_battle` (the player route and fleet helper via the `game_logic`
re-export, and `bot_logic` via its direct import), a single override covers all
combat — player, helper, and NPC — with no call-site changes.

**Override contract** — a mod resolver receives a ctx with the full battle args
(`attacker_fleet, attacker_user, defender_colony, defender_user, game_speed, db,
target_fleet_id, defender_planet_id`) and must:
- **own its persistence** (mutate fleets/defenses/credits/debris, write the
  `BattleReport`, commit) — the default commits internally;
- **return a report dict** with the keys downstream reads: `result`,
  `attacker/defender_forces`, `defender_turrets`, `*_losses`, `debris`,
  `combat_loot`, `attacker/defender_value_lost`, `attacker/defender_damage_dealt`,
  `attacker`, `defender`, `base_name` (see `_resolve_battle_default`). The player
  route then layers pillage/occupation/XP on top.

This is the "ringbounds-style / positional / module-based combat as a mod" path:
a full alternate resolver, no engine fork. A safe way to start is to *wrap* the
default (`combat._resolve_battle_default(...)`) and adjust its report, rather than
reimplement from scratch.

---

## 7. Composition & conflict resolution

- **Content** uses the existing child-wins `_deep_merge`. Later mods (higher
  `load_order`) override earlier ones; the base definition is the floor.
- **Declared conflicts** (`conflicts`) are refused at enable time with a clear
  message rather than silently merged.
- **Hooks** are additive: all registered handlers for a point run in load order.
  A hook may mark `ctx.stop()` to halt the chain (e.g. a victory override).
- **Determinism:** the compiled definition + ordered mod list is a pure function
  of the enabled set, so the same config always yields the same game.

---

## 8. Licensing, distribution & marketplace

This is where mods become a business and where it ties back to Phase 3 work.

- **Per-mod license.** `manifest.license` (free / paid / custom / SPDX). A mod
  may ship its own `LICENSE`.
- **The AWE registry is the marketplace.** The same registry that lists
  AWE-powered games (Phase 3b) lists and distributes **mods**: browse, version,
  ratings, "AWE-verified" badge, free + paid.
- **Trust tie-in.** The engine-identity/attribution infra (`/api/engine`,
  `X-Powered-By`, LICENSE) is the trust backbone: verified engines, signed mods.
- **Paid-mod enforcement (future).** Paid behavioral mods can be gated by a
  license key checked against the registry at install — the realistic lever,
  since pure data mods are inherently copyable.

---

## 9. Security model

- **Content/skin mods**: pure JSON/CSS/images. No code path. Always safe; the
  only risk is bad data, which `validate_definition` catches.
- **Behavioral mods**: arbitrary Python = arbitrary trust. Options, in order of
  effort:
  1. **Trusted-only** (v1): behavioral mods load only if explicitly enabled by
     the operator, with a clear "this runs code" warning. Same trust level as
     installing any server software.
  2. **Capability-narrowed**: hooks see only the sanctioned `ctx` API (no
     filesystem/network/Session). Limits accidental damage, not malice.
  3. **Sandboxed/out-of-process** (future): run mod hooks in a restricted
     subprocess/RPC. Real isolation; significant work.
- **Registry signing**: "AWE-verified" mods are signed; the loader can warn on
  unsigned behavioral mods.

Recommendation: ship content/skin mods first (zero new risk), gate behavioral
mods behind explicit operator trust (option 1 + 2), defer true sandboxing.

---

## 10. Phased roadmap

1. **M1 — Content mod packaging.** ✅ **Built** — `mod_loader.py`: `manifest.json`
   schema + validation (kind/engine_api/requires/conflicts), `mods/` discovery,
   ruleset+content composition via existing `_deep_merge` (base display identity
   preserved, applied mods recorded in `meta.active_mods`), enable/active-ruleset
   state in `game_config`, admin endpoints (`/api/admin/mods[/enable|/ruleset|/apply]`),
   `test_mod_loader.py`. Solar Empire shipped as the first ruleset mod
   (`mods/solar_empire/`); `hardcore_rules` as a content-overlay example.
   *No code execution.*
2. **M2 — Skin & i18n mods.** Extend the loader to register skin CSS-var sets and
   i18n string tables from mods. Pure data.
3. **M3 — Hook API (read-only).** ✅ **Built** — `mod_hooks.py` (registry,
   `HookContext`, observer + override dispatch, fail-soft, `fire`/`fire_override`
   one-liners, gated mod-code loading). Observers wired at audited choke points:
   `on_battle_resolved` (single point in `combat.py` covering player/helper/bot),
   `on_tick` (typed, all 8 background tick syncs), `on_research_completed` and
   `on_economy_collect` (`game_logic.py`), `on_colony_founded` (colonize route),
   and the `compute_victory` **override** (`check_win`, can supply
   annihilation/time_limit). `mods/battle_logger/` is the reference behavioral
   mod. Tests: `test_mod_hooks.py`. *Deferred:* bot/NPC `on_colony_founded`, and
   the overriding `resolve_battle` facade (its own phase, for module combat).
4. **M4 — Hook API (mutating).** Sanctioned `ctx` mutations (grant resources,
   spawn events, victory override). Behavioral mods become real.
5. **M5 — Marketplace.** Registry hosts mods; install-from-registry, versions,
   paid-mod license keys, verified signing.

Each milestone is independently shippable and leaves the core immutable.

---

## 11. Open questions

- Mod API versioning cadence — how often can hook signatures change?
- Do we allow mods to add **new DB columns** (behavioral mods may want state)?
  Likely a per-mod JSON state blob keyed by mod id, not real columns, to keep
  the core schema stable.
- Paid-mod enforcement: license-key check vs honor system for v1.
- ~~Should the base ruleset ship as a mod?~~ **Decided (§3.5): yes — rulesets
  are mods.** A neutral Base Game mod ships first-party; the faithful "Classic
  Space" ruleset is a separate, private mod.
- Migration: fold the current private game definition into a "Classic Space"
  mod package so the legal isolation and the mod format are the same mechanism.
