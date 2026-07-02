# Running AstroWebEngine with Docker

A self-contained way to host the engine. The default stack is a single container
backed by SQLite on a persistent volume — no external database required.

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
docker compose pull && docker compose up -d   # update to a newer image
docker compose down               # stop (named volumes are retained)
```

## Data & backups

All game state lives in the `awe-data` volume (`/data/astroclone.db` plus its WAL
sidecars). Back it up by copying that file out of the container:

```bash
docker compose cp app:/data/astroclone.db ./backup-astroclone.db
```

Removing the volume (`docker compose down -v`) wipes the game.

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
