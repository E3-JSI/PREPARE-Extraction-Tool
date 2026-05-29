from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.websocket_manager import manager

router = APIRouter()


@router.websocket("/ws/training")
async def websocket_training(ws: WebSocket):
    await manager.connect(ws)

    try:
        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(ws)