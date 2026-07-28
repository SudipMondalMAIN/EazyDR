"""
Simple in-memory WebSocket fan-out per chat session. Works fine on a single
Render instance (current deployment). If this ever runs on multiple
instances, this needs to move to Redis pub/sub (redis_client.py already
exists in app/core for that) — not needed today.
"""
import uuid
from collections import defaultdict

from fastapi import WebSocket


class ChatConnectionManager:
    def __init__(self):
        self._connections: dict[uuid.UUID, list[WebSocket]] = defaultdict(list)

    async def connect(self, session_id: uuid.UUID, websocket: WebSocket):
        await websocket.accept()
        self._connections[session_id].append(websocket)

    def disconnect(self, session_id: uuid.UUID, websocket: WebSocket):
        if websocket in self._connections.get(session_id, []):
            self._connections[session_id].remove(websocket)
        if not self._connections.get(session_id):
            self._connections.pop(session_id, None)

    async def broadcast(self, session_id: uuid.UUID, message: dict):
        dead = []
        for ws in self._connections.get(session_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(session_id, ws)


chat_manager = ChatConnectionManager()
