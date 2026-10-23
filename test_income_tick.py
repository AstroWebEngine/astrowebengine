"""The income tick must reach the conquest capture sweep.

It called datetime.utcnow() without importing datetime (app.py only imports it
inside other functions), so the sweep raised NameError on every tick and was
skipped - occupied bases were never captured in conquest games.
"""
import app


def test_income_tick_runs_the_capture_sweep(monkeypatch):
    import conquest
    calls = []
    monkeypatch.setattr(conquest, "process_occupation_capture",
                        lambda db, now: calls.append(now) or [])
    app._income_tick_sync()
    assert len(calls) == 1 and calls[0] is not None
