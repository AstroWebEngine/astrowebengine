@echo off
title AstroWebEngine Server
rd /s /q __pycache__ 2>nul
echo Starting AstroWebEngine server on http://localhost:8000
echo.
echo Default launch: SQLite dev mode
echo For 50-player fights use something like:
echo   start.bat --postgres USER:PASS@HOST/DBNAME --workers 4
echo Press Ctrl+C to stop
python run.py %*
