"""Helpers for client catalog WebSocket invalidation."""
from ws_manager import ws_manager


def invalidate_all_online(kinds: list[str], reason: str):
    event = {
        "type": "catalog.invalidate",
        "kinds": kinds,
        "reason": reason,
    }
    for user_id in ws_manager.active_user_ids:
        ws_manager.queue_event(user_id, event)
