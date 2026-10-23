# Running AstroWebEngine with Docker

A self-contained way to host the engine. The default stack is a single container
backed by SQLite on a persistent volume — no external database required.

## Run the published image

No clone needed. The image carries the engine and its default rulesets; the
database lives on the mounted volume.

```bash
docker run -d --name awe -p 8000:8000 \
  -v awe-data:/data \
  -e AWE_SECRET_KEY=$(openssl rand -hex 32) \
  astrowebengine/astrowebengine
```

Open <http://localhost:8000>. **The first account you register becomes the
admin.** Tags: `latest` and the release version (e.g. `0.97.0`).

Published for `linux/amd64` and `linux/arm64`, so it runs on a Raspberry Pi,
Apple Silicon or an ARM cloud instance as well as on x86.

Build from source instead if you are modifying the engine — that is what the
Compose file below does.

## Quick start

```bash
cp .env.example .env
# Edit .env and set AWE_SECRET_KEY to a long random string:
#   python -c "import secrets; print(secrets.token_hex(32))"

docker compose up -d
```

Open <http://localhost:8000>. **The first account you register becomes the admin.**

To share with players, point a domain or public IP at the host's port 8000 (a
reverse proxy or tunnel such as Cloudflare Tunnel is recommended for TLS).

## Common operations

```bash
docker compose logs -f app        # follow server logs
docker compose restart app        # restart (DB persists)
docker compose up -d --build app  # rebuild after updating this source checkout
docker compose down               # stop (named volumes are retained)
```

## Data & backups

For the default SQLite deployment, stop the app before copying its data so the
database and WAL cannot change during the backup. Use a new, empty folder for
each backup. Run from the project folder:

The container sets `AWE_DATA_DIR=/data`. This volume now contains the database,
active definition, recorded mod base and creator definitions/AI drafts. Back up
the whole directory. `DATABASE_URL` still controls database location separately.

```bash
mkdir awe-backup
docker compose stop app
docker compose cp app:/data/. ./awe-backup/
```

Check that the copy succeeded, then run `docker compose start app`. Keep all
copied files together, including any `astroclone.db-wal` and `astroclone.db-shm`.
Do not copy only the live `.db`: committed changes may still be in the WAL.
For an online database snapshot, use [SQLite's backup API](https://www.sqlite.org/backup.html);
that snapshot alone does not capture ruleset or artwork files.

On versions that store definition state under `/app`, also copy these while
the app is stopped, before replacing its container:

```bash
docker compose cp app:/app/_active_definition.json ./awe-backup/
docker compose cp app:/app/_mod_base_definition.json ./awe-backup/
docker compose cp app:/app/game_definitions ./awe-backup/game_definitions
```

Snapshot files may not exist if no custom definition has been activated. Also
retain custom mods/artwork, your `.env` securely, and the engine version/source
revision. Before upgrading an older container, copy its `/app` files as above:
replacing the container loses those files before migration can find them. Restore
the snapshots into `/data` and creator drafts into `/data/game_definitions` while
the new container is stopped, or re-activate the intended ruleset after upgrading.

Restore into a separate stopped instance using the matching engine version and
configuration. Restore the complete database file set and definition files to
their corresponding paths, ensure container-user read/write access, then start
and check the selected rules, bases and queues before directing players there.
Do not combine an old database with unrelated WAL files.

Removing the volume (`docker compose down -v`) wipes saved data. PostgreSQL needs
a database-native backup such as `pg_dump`, plus the game files; these SQLite
copy steps do not back up PostgreSQL.

## Scaling to PostgreSQL

SQLite is fine for small servers. For 50+ concurrent players, use Postgres:

```bash
# In .env, set:
#   DATABASE_URL=postgresql+psycopg://awe:changeme@db:5432/awe
docker compose --profile postgres up -d
```

## Configuration

All settings are environment variables in `.env` — see `.env.example` for the
full list (secret key, game definition, game speed, database, optional registry).

### AI assistant drafts

Creator definitions, including AI drafts named `ai_<name>.json`, are written to
`$AWE_DATA_DIR/game_definitions/` (`/data/game_definitions/` in Docker). Bundled
definitions and fragments stay under `/app/game_definitions/`. Creator definitions
are listed/loaded first and can extend bundled definitions by name. A creator
filename matching a bundled definition hides that bundled definition; admin
exports avoid overwriting bundled files by using an `_export` suffix when needed.

`AWE_DATA_DIR` defaults to the project directory outside Docker. On startup with
a different data directory, existing active/base snapshots and `ai_*.json` drafts
are migrated from the project directory without overwriting destination files.
Other custom files should be copied deliberately. Check the `[data]` startup logs
to confirm the directory and migrated files.

### Signing key

Set `AWE_SECRET_KEY` for an explicit, stable signing key. If unset, AWE generates
one and persists it in `$AWE_DATA_DIR/.secret_key`; the Docker data volume keeps
it across container replacements. Preserve this private file with your backup.
Changing the key invalidates existing logins.

### Worker coordination

Multiple workers now refresh settings and active-definition revisions from the
database every 5 seconds by default (`AWE_SYNC_SECONDS`). Background jobs use
a database lease so one worker owns the scheduler; another can take over after
the 30-second lease expires. Workers need the same database, durable data
directory and signing key. PostgreSQL is the appropriate option when scaling
concurrent database writes; extra SQLite workers do not remove its write limits.

Lease takeover does not guarantee exactly-once effects: a worker paused beyond
its lease can resume an in-flight tick after another takes over. Extensions that
grant resources or apply other non-repeatable effects still need transactional
event deduplication and protection against stale owners. See
[`scheduler_lease.py`](scheduler_lease.py) for the current contract.
