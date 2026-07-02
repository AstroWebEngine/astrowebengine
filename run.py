#!/usr/bin/env python3
"""
AstroWebEngine — Launcher
Run this file to start the game server.

Usage:
  python run.py                              # single universe, port 8000
  python run.py --admin-port 8001            # game + separate admin server
  python run.py --multi --admin-port 8001    # multi-universe mode (admin only)

Single universe mode:
  Players connect to: http://YOUR_IP:8000

Multi-universe mode:
  Admin panel: http://localhost:8001/admin
  Lobby page:  http://YOUR_IP:8001/lobby
  Game servers started/stopped from admin panel
"""
import sys
import os
import argparse

# Make sure we're running from the correct directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

parser = argparse.ArgumentParser(description='AstroWebEngine')
parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
parser.add_argument('--port', type=int, default=8000, help='Game server port (default: 8000)')
parser.add_argument('--admin-port', type=int, default=None,
                    help='Run admin panel on a separate port (e.g., 8001). '
                         'When set, admin routes are removed from the game server.')
parser.add_argument('--admin-host', default='127.0.0.1',
                    help='Admin server host (default: 127.0.0.1 — local only for security)')
parser.add_argument('--multi', action='store_true',
                    help='Multi-universe mode: admin portal only, game servers managed individually. '
                         'Requires --admin-port. Players use the lobby page to pick a server.')
parser.add_argument('--reload', action='store_true', help='Auto-reload for dev')
parser.add_argument('--workers', type=int, default=1,
                    help='Worker processes (use 2-4 for 50+ players, requires non-SQLite DB)')
parser.add_argument('--db', type=str, default=None, metavar='FILENAME',
                    help='SQLite database file (default: astroclone.db). Example: --db mss.db')
parser.add_argument('--mysql', type=str, default=None, metavar='USER:PASS@HOST/DBNAME',
                    help='Use MySQL. Example: root:secret@localhost/astroclone')
parser.add_argument('--postgres', type=str, default=None, metavar='USER:PASS@HOST/DBNAME',
                    help='Use PostgreSQL. Example: postgres:secret@localhost/astroclone')
args = parser.parse_args()

# Validate multi mode
if args.multi and not args.admin_port:
    print("  ERROR: --multi requires --admin-port (e.g., --multi --admin-port 8001)")
    sys.exit(1)

# Set DATABASE_URL from flags
if args.mysql:
    os.environ["DATABASE_URL"] = f"mysql+pymysql://{args.mysql}"
    db_label = f"MySQL ({args.mysql.split('@')[-1]})"
elif args.postgres:
    os.environ["DATABASE_URL"] = f"postgresql+psycopg://{args.postgres}"
    db_label = f"PostgreSQL ({args.postgres.split('@')[-1]})"
elif args.db:
    os.environ["DATABASE_URL"] = f"sqlite:///./{args.db}"
    db_label = f"SQLite ({args.db}) — WAL mode enabled"
else:
    db_label = "SQLite (astroclone.db) — WAL mode enabled"

# Tell the game app whether admin routes should be excluded
if args.admin_port:
    os.environ["AWE_ADMIN_SEPARATE"] = "1"

import uvicorn

if args.multi:
    # ── Multi-Universe Mode ──
    # Only the admin portal runs. Game servers are managed from the admin UI.
    print(f"""
  AstroWebEngine — Multi-Universe Mode
  ======================================
  Admin Panel:  http://{args.admin_host}:{args.admin_port}/admin
  Lobby Page:   http://{args.admin_host}:{args.admin_port}/lobby
  Database:     {db_label} (admin DB)

  Game servers are created and managed from the admin panel.
  Each universe runs on its own port with its own database.

  Login to the admin panel to create your first universe.
""")
    uvicorn.run(
        "admin_app:admin_app",
        host=args.admin_host,
        port=args.admin_port,
        log_level="info",
    )

elif args.admin_port:
    # ── Split Mode: game server + separate admin server ──
    import threading
    import time

    print(f"""
  AstroWebEngine
  ============================
  Game:      http://{args.host}:{args.port}
  Admin:     http://{args.admin_host}:{args.admin_port}/admin  (separate server)
  Database:  {db_label}
  Workers:   {args.workers}

  First user to register becomes the admin.
  Share your IP address with friends to play!
""")

    if args.workers > 1 and not (args.mysql or args.postgres):
        print("  WARNING: Multiple workers with SQLite may cause issues.")
        print("  Consider using --mysql or --postgres for 50+ players.\n")
    elif args.postgres and args.workers < 2:
        print("  NOTE: PostgreSQL is enabled. For 50-player fights, consider --workers 2 to 4.\n")

    def run_admin_server():
        time.sleep(0.5)
        uvicorn.run(
            "admin_app:admin_app",
            host=args.admin_host,
            port=args.admin_port,
            log_level="warning",
        )

    admin_thread = threading.Thread(target=run_admin_server, daemon=True)
    admin_thread.start()
    print(f"  [admin] Starting admin server on {args.admin_host}:{args.admin_port}")

    uvicorn.run(
        "app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
    )

else:
    # ── Single Mode: everything on one port ──
    print(f"""
  AstroWebEngine
  ============================
  Server:    http://{args.host}:{args.port}
  Admin:     http://localhost:{args.port}/admin
  Database:  {db_label}
  Workers:   {args.workers}

  First user to register becomes the admin.
  Share your IP address with friends to play!
""")

    if args.workers > 1 and not (args.mysql or args.postgres):
        print("  WARNING: Multiple workers with SQLite may cause issues.")
        print("  Consider using --mysql or --postgres for 50+ players.\n")
    elif args.postgres and args.workers < 2:
        print("  NOTE: PostgreSQL is enabled. For 50-player fights, consider --workers 2 to 4.\n")

    uvicorn.run(
        "app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
    )
