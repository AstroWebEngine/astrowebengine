# AstroWebEngine — Notes for AI agents

AstroWebEngine (AWE) is a data-driven engine for multiplayer browser space-strategy games.
FastAPI + SQLAlchemy backend, vanilla-JS frontend. All game rules live in a JSON **game
definition**; the engine code holds no ruleset.

## Designing a game (most people)

Use the server's MCP endpoint instead of editing code:

1. In the admin panel, open **AI Assistant** and generate a token.
2. `claude mcp add --transport http awe https://<your-server>/mcp --header "Authorization: Bearer <token>"`
3. Optional: download the game-designer skill from the same tab.

Schema reference: `docs/definition_schema.md`.

## Working on the engine code

See `README.md` and `CONTRIBUTING.md`. Key modules: `game_definition.py` (load/compose/
validate), `definition_service.py` (apply rulesets), `combat.py`, `game_logic.py`,
`routes_*.py`, `mcp_server.py`. Frontend modules load from `static/game.html`;
`static/game.js` is not loaded. Run tests with `python -m pytest`.
