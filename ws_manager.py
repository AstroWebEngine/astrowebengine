"""WebSocket connection manager — real-time event push to connected clients."""
import asyncio
import logging
from fastapi import WebSocket

logger = logging.getLogger("ae.ws")


class ConnectionManager:
    def __init__(self):
        # user_id -> set of WebSocket connections (supports multiple tabs)
        self._connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(ws)
        logger.info("WS connected: user %d (%d conns)", user_id,
                     len(self._connections[user_id]))

    def disconnect(self, user_id: int, ws: WebSocket):
        if user_id in self._connections:
            self._connections[user_id].discard(ws)
            if not self._connections[user_id]:
                del self._connections[user_id]

    async def send_to_user(self, user_id: int, data: dict):
        conns = self._connections.get(user_id, set())
        dead = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    def queue_event(self, user_id: int, data: dict):
        """Schedule a send from synchronous code (game tick runs in asyncio)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.send_to_user(user_id, data))
        except RuntimeError:
            pass  # No event loop available

    @property
    def active_user_ids(self) -> list[int]:
        return list(self._connections.keys())

    @property
    def active_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


ws_manager = ConnectionManager()
