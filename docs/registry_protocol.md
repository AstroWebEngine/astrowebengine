# AstroWebEngine Registry — Protocol

How an AstroWebEngine (AWE) deployment talks to a public **registry**: the shared
directory of AWE-powered games (and, later, mods). The registry **server** is a
separate project you host; this doc is the contract its `/api/register` endpoint
must honor so the in-engine client (`awe_registry.py`) can list a game.

The client is **opt-in** (`AWE_REGISTRY_ENABLED`, default off) and **fail-soft**
— registry downtime never affects a running game.

---

## Client → registry: `POST {AWE_REGISTRY_URL}/api/register`

Sent on startup and on an hourly heartbeat while enabled. JSON body:

```json
{
  "engine": "AstroWebEngine",
  "engine_url": "https://astrowebengine.com",
  "engine_version": "0.97.0",
  "game_name": "My Space Game",
  "public_url": "https://mygame.example.com",
  "description": "A 24x-speed hardcore galaxy.",
  "status": "active",
  "players": 142,
  "max_players": "500"
}
```

| Field | Meaning |
|-------|---------|
| `engine` / `engine_url` | constant AWE identity |
| `engine_version` | the engine build running the game |
| `game_name` | operator's game title (`game_name` config) |
| `public_url` | the game's public base URL — **the verification anchor** |
| `description` | operator blurb (`AWE_REGISTRY_DESCRIPTION`) |
| `status` | `setup` / `active` / … (`game_status`) |
| `players` | current non-bot player count |
| `max_players` | configured cap |

### Expected response (200)

```json
{ "ok": true, "id": "mygame", "listing_url": "https://registry.astrowebengine.com/g/mygame" }
```

The client logs `listing_url` and otherwise ignores the body. Any `4xx/5xx` is
logged and dropped; the heartbeat retries next hour.

---

## Verification (anti-spoof) — registry's responsibility

Anyone can POST arbitrary JSON, so the registry **must not trust the payload on
its face**. To confirm a listing is a genuine AWE deployment, the registry
should call back the submitted `public_url`:

1. `GET {public_url}/api/engine` (or `/.well-known/astrowebengine`).
2. Confirm the response is JSON with `engine == "AstroWebEngine"` and a
   plausible `version`.
3. Optionally confirm the `X-Powered-By: AstroWebEngine` header is present.

Only then publish the listing. Re-verify periodically; drop listings whose
`public_url` stops responding or stops identifying as AWE. This is what makes
the directory trustworthy and ties it to the attribution layer (`/api/engine`,
the header, the footer) shipped in Phase 3a.

---

## Notes for the registry server (out of scope for this repo)

- **Dedup** on `public_url` (canonicalized), not `game_name`.
- **Rate-limit** registrations per source.
- **Mods (future):** the same service can host a `/api/mods` catalog — browse,
  version, ratings, "AWE-verified" signing, free/paid. See
  `docs/mod_system_design.md` §8; registration reuses the same identity/verify
  flow.
- **Privacy:** only operator-provided, already-public fields are sent; no user
  PII. Registration stays opt-in per the AstroWebEngine License §4.
