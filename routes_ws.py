"""WebSocket route — real-time event streaming to authenticated clients."""
from fastapi import WebSocket, WebSocketDisconnect
from jose import jwt, JWTError
from database import SessionLocal, SECRET_KEY, ALGORITHM
from models import User
from ws_manager import ws_manager


def register_ws_routes(app):

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        # Authenticate via query param: /ws?token=xxx
        # (browser WebSocket API doesn't support custom headers)
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=4001, reason="Missing token")
            return

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload["sub"])
        except (JWTError, KeyError, ValueError):
            await ws.close(code=4001, reason="Invalid token")
            return

        # Verify user exists
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                await ws.close(code=4001, reason="User not found")
                return
        finally:
            db.close()

        await ws_manager.connect(user_id, ws)
        try:
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            ws_manager.disconnect(user_id, ws)
