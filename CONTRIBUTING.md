# Contributing to AstroWebEngine

Help is genuinely wanted. This is a small project with a large surface, and the
areas below are ones where a second pair of eyes would make a real difference.

## Getting it running

```bash
git clone https://github.com/AstroWebEngine/astrowebengine.git
cd astrowebengine
python -m venv venv && . venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python run.py                                    # http://localhost:8000
```

The first account you register becomes the admin. From the admin panel you can
pick or compile a ruleset, then launch the game to generate a universe.

```bash
pytest -q          # 243 tests, a few seconds, no server or database needed
```

If `pytest` passes on a clean checkout, your environment is right.

## The one idea to hold on to

**The engine contains no ruleset.** Units, structures, research, defenses, the
resource model, combat behaviour and the map shape all come from a *game
definition* (`game_definitions/*.json`). Engine code reads flags and specs; it
never assumes a particular game.

The most common way to break this is an innocent-looking hardcoded default — a
ship key, a resource name, a rule that "obviously" holds. If you find yourself
writing one, that value probably belongs in the definition.

## The failure mode to watch for

The bug this codebase attracts is **configuration that does nothing**. A flag
gets declared, documented, set by shipped rulesets, and read by no code. Nothing
raises. The game just quietly ignores it, and there is no symptom to notice.

Real examples, all found in one afternoon:

- `combat_model` selected a battle model the resolver never consulted, so
  rulesets declaring "rounds" and "simultaneous" fought identically.
- Rapid-fire tables sat in a definition for months; `combat.py` never opened the
  key.
- A ruleset declared five resources whose costs were all plain numbers, so four
  of them were mined forever and never spent.
- Power plants generated energy that no building consumed.

`test_engine_flag_consumption.py` now fails on any engine flag a shipped ruleset
declares that no code reads. **If you add a flag, wire it up or the test will
say so.** If a flag is genuinely descriptive, add it to `DESCRIPTIVE` with a
reason. If the engine cannot honour a value yet, make `validate_definition`
reject it rather than accept and ignore it.

## Two traps that will cost you an hour

**Editing a definition file does not change a running game.**
`_active_definition.json` is a snapshot taken at activation, not a pointer.
After editing `game_definitions/x.json`, re-activate it (admin Build Game UI, or
`set_game_definition` + `persist_active_definition`) or the server keeps serving
the old content.

**A standalone script gets the default ruleset, not the live one.**
`get_game_definition()` falls back to the built-in default when the app's
startup path has not run, so a `python myscript.py` against a live database sees
the wrong game. Call `restore_persisted_definition(db)` first.

## Where the code lives

| Path | What it does |
|---|---|
| `app.py` | Route registration, startup, background ticks |
| `game_definition.py` | Definition load / compile / validate / hot-swap |
| `combat.py` | Battle resolution — the most correctness-sensitive file here |
| `game_logic.py` | Economy, base stats, queue processing |
| `universe.py` | Galaxy generation |
| `routes_*.py` | HTTP endpoints by area |
| `specs.py` | Default content, used when a definition omits a section |
| `static/*.js` | Vanilla-JS client, no build step |
| `game_definitions/` | Shipped rulesets and composable fragments |
| `mods/` | Content overlays and behavioural (Python hook) mods |

## Good first issues

- **`datetime.utcnow()` — 100 calls.** Deprecated in Python 3.12 and scheduled
  for removal; it also returns a naive datetime, which is a latent bug class of
  its own. Mechanical, well-scoped, and it clears ~195 warnings from every test
  run.
- **`buildings_destructible` and `ships_always_destroyed` are unimplemented.**
  `validate_definition` currently rejects the value the engine cannot honour.
  Implementing either lets that check be deleted.
- **Section gating (`ui.menus`).** A ruleset can rename UI labels but not hide
  surfaces it has no concept of, so Deep Frontier shows Economy and Population
  panels for mechanics it does not have. `report_categories` already gates the
  Reports sidebar; the rest needs the same treatment.
- **More rulesets.** The engine is only as interesting as the games it can
  express. A definition that breaks an assumption nobody noticed is a genuinely
  useful contribution.

## Pull requests

- Run `pytest -q` before opening. CI runs it on 3.11, 3.12 and 3.13.
- Add a test when you change behaviour. For combat and economy changes this
  matters more than usual — the existing tests are the only thing standing
  between a balance tweak and a silently broken battle.
- Explain *why* in the commit message. What changed is visible in the diff.
- Small and focused beats large and comprehensive.

## Licence

By contributing you agree your work is licensed under the
[AGPL-3.0](LICENSE), same as the rest of the engine.
