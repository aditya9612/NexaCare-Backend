from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket_deps import authenticate_websocket

router = APIRouter()


class NotificationManager:
    def __init__(self):
        self.user_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.user_connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        conns = self.user_connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)

    async def send_to_user(self, user_id: int, message: dict):
        for ws in self.user_connections.get(user_id, []):
            await ws.send_json(message)

    async def broadcast(self, message: dict):
        for conns in self.user_connections.values():
            for ws in conns:
                await ws.send_json(message)


notification_manager = NotificationManager()


@router.websocket("/ws/notifications")
async def notification_websocket(websocket: WebSocket):
    user = await authenticate_websocket(websocket)
    if not user:
        return

    user_id = user["user_id"]
    await notification_manager.connect(user_id, websocket)
    await websocket.send_json({"type": "connected", "channel": "notifications"})

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        notification_manager.disconnect(user_id, websocket)


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    user = await authenticate_websocket(websocket)
    if not user:
        return

    await websocket.accept()
    await websocket.send_json({"type": "connected", "channel": "dashboard"})

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                from app.core.database import AsyncSessionLocal
                from app.services.analytics_service import AnalyticsService

                async with AsyncSessionLocal() as db:
                    summary = await AnalyticsService(db).get_dashboard()
                    await db.commit()
                await websocket.send_json({
                    "type": "dashboard_update",
                    "data": summary.model_dump(mode="json"),
                })
    except WebSocketDisconnect:
        pass
