"""In-process WebSocket connection registry for broadcasting training events.

`WebSocketManager` keeps active connections in a plain instance-level list and
broadcasts payloads to all of them. State is held in memory within a single
process.

Single-worker limitation
-------------------------
This manager is process-local. Broadcasts only reach sockets connected to the
*same* Uvicorn worker. With multiple workers (``--workers > 1``) a training
event received by one worker will not reach sockets held by another worker.
This is acceptable for single-worker dev, but for a multi-worker deployment use
a shared pub/sub layer (e.g. Redis pub/sub) so events fan out across workers.

The connection-list mutations rely on asyncio's single-threaded execution model
within a worker; ``disconnect`` is additionally guarded so removing a socket
that is no longer present does not raise.
"""

from fastapi import WebSocket
from typing import List


class WebSocketManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        # Guard against removing a socket that isn't tracked (idempotent):
        # broadcast() may have already dropped a dead socket.
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, payload: dict):
        dead = []

        for ws in self.connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)


manager = WebSocketManager()
