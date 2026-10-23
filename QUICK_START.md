# Start your first AstroWebEngine game

Run AWE on your computer, create an administrator account and launch a game
through the browser. Docker supplies Python and the database; no coding or API
commands are needed.

## 1. Install Docker and get AWE

Install and start [Docker Desktop](https://docs.docker.com/get-started/get-docker/).
On Linux, Docker Engine with the Compose plugin also works.

On [AWE's GitHub page](https://github.com/AstroWebEngine/astrowebengine), choose
**Code → Download ZIP** and extract it. Open a terminal in the extracted folder
containing `docker-compose.yml`. On Windows, open that folder in File Explorer,
type `powershell` in its address bar and press Enter.

If you use Git instead:

```bash
git clone https://github.com/AstroWebEngine/astrowebengine.git
cd astrowebengine
```

## 2. Set your server key

Copy `.env.example` to `.env` in that folder using your file manager. Make sure
the new name is `.env`, not `.env.txt`. Build the container, then generate a
random key with its bundled Python:

```bash
docker compose build app
docker compose run --rm --no-deps app python -c "import secrets; print(secrets.token_hex(32))"
```

Open `.env` in a text editor. Replace the example value after `AWE_SECRET_KEY=`
with the generated 64-character value and save. Keep the key private and retain
it across restarts so player logins remain valid. Leave other settings at their
defaults for your first trial.

If `AWE_SECRET_KEY` is unset, AWE generates a key once and stores it in
`AWE_DATA_DIR/.secret_key`. It survives restarts when that directory is retained.
An explicit key is still recommended for hosted servers. Replacing an existing
key signs players out; keep it with your private server configuration.

## 3. Start the server

```bash
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000). Startup may take a moment.
Docker keeps the server running after you close the terminal.

## 4. Register and launch

Choose **Register** and create your account. The first account becomes the
administrator, so register before making your server public.

Open [the admin panel](http://localhost:8000/admin) while logged in. In **Game
Definitions**, choose a packaged ruleset or use **Build Game**, then apply your
selection. Rulesets supply the buildings, units, resources and rules.

Review **Universe & Game Configuration**, including speed and universe size.
Keep the first trial small. Click **Launch Game & Generate Universe**, confirm
and wait for generation to finish.

The administrator manages the game. To play, return to the login page and create
a separate player account. Follow its homeworld setup screen to establish a base.
Buildings, research and units depend on your selected game.

Setup-only rules such as universe size need a fresh universe to change fully.
Use another trial instance for experimenting; the admin reset removes game progress.

## Optional: design with AI

Open **AI Assistant** in admin, generate a token and follow the displayed MCP
connection instructions. Copy the command or configuration into your MCP client.
The same tab offers a downloadable game-designer skill.

Your assistant can inspect the schema, draft/check rulesets and apply permitted
changes. You still launch or reset the universe yourself. Treat the token like
a password and revoke it when finished.

## Stop, restart and share

From the same source folder:

```bash
docker compose stop app
docker compose start app
docker compose logs --tail 100 app
```

Stopping retains saved data. Read [Docker hosting and backups](DOCKER.md) before
updating or moving your server. Removing the data volume deletes the saved game.
`localhost` works only on your computer; friends need a reachable server address.
For public hosting, set up HTTPS as described in that guide.

## Troubleshooting

| Problem | Action |
| --- | --- |
| `docker` is not recognized | Install Docker, reopen your terminal and start Docker Desktop. |
| Cannot connect to Docker | Wait for Docker Desktop to finish starting. |
| Compose cannot find its configuration | Open your terminal in the folder containing `docker-compose.yml`. |
| Port 8000 is already used | Change the mapping to `"8002:8000"` in `docker-compose.yml`, run `docker compose up -d` and open `http://localhost:8002`. |
| Browser cannot connect | Check `docker compose ps` and `docker compose logs --tail 100 app`. |
| Game is waiting for launch | Log in as the first account, open `/admin` and launch the universe. |

## Alternative: Python

Use Python 3.11–3.13, the versions covered by CI. In the source folder:

```bash
python -m venv .venv
```

Generate a private key with `python -c "import secrets; print(secrets.token_hex(32))"`.
Save it privately and reuse it each time. On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:AWE_SECRET_KEY = Read-Host "Paste your private server key"
.\.venv\Scripts\python.exe run.py --host 127.0.0.1
```

On macOS or Linux:

```bash
.venv/bin/python -m pip install -r requirements.txt
export AWE_SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python run.py --host 127.0.0.1
```

The direct launcher reads environment variables; copying `.env` alone does not
load them. The default worker count is sufficient for a first trial; see
[worker coordination](DOCKER.md#worker-coordination) before scaling. Open
`http://localhost:8000` and follow
the registration/launch steps above. Ctrl+C stops the server. SQLite is created
automatically. Developers can open `/docs` for the interactive API reference.
