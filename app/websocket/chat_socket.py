import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import AsyncSessionLocal
from app.core.websocket_deps import authenticate_websocket
from app.schemas.chat_schema import SendMessageRequest
from app.services.chat_service import ChatService

router = APIRouter()
chat_manager_connections: dict[str, list[WebSocket]] = {}


class ChatManager:
    def __init__(self):
        self.rooms: dict[str, list[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms.setdefault(room_id, []).append(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.rooms and websocket in self.rooms[room_id]:
            self.rooms[room_id].remove(websocket)

    async def send_to_room(self, room_id: str, message: dict, exclude: WebSocket | None = None):
        for ws in self.rooms.get(room_id, []):
            if ws != exclude:
                await ws.send_json(message)

    async def send_typing(self, room_id: str, sender: str, is_typing: bool = True):
        await self.send_to_room(room_id, {"type": "typing", "sender": sender, "is_typing": is_typing})


chat_manager = ChatManager()


@router.websocket("/ws/chat/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    user = await authenticate_websocket(websocket)
    if not user:
        return

    await chat_manager.connect(session_id, websocket)
    await chat_manager.send_to_room(
        session_id,
        {"type": "connected", "session_id": session_id, "user_id": user["user_id"]},
    )

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type", "message")

            if msg_type == "typing":
                await chat_manager.send_typing(session_id, data.get("sender", "user"), data.get("is_typing", True))
                continue

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            message_text = data.get("message", "")
            if not message_text:
                continue

            await chat_manager.send_typing(session_id, "bot", True)

            async with AsyncSessionLocal() as db:
                try:
                    service = ChatService(db)
                    result = await service.send_message(
                        SendMessageRequest(session_id=session_id, message=message_text)
                    )
                    await db.commit()
                    payload = {
                        "type": "message",
                        "user_message": result.user_message.model_dump(mode="json"),
                        "bot_message": result.bot_message.model_dump(mode="json"),
                        "intent": result.intent.model_dump(mode="json") if result.intent else None,
                    }
                except Exception as exc:
                    await db.rollback()
                    payload = {"type": "error", "message": str(exc)}

            await chat_manager.send_typing(session_id, "bot", False)
            await chat_manager.send_to_room(session_id, payload)
    except WebSocketDisconnect:
        chat_manager.disconnect(session_id, websocket)
