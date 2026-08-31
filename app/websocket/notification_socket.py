import asyncio
import json
import logging
import uuid
import redis.asyncio as aioredis

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.websocket_deps import authenticate_websocket

router = APIRouter()
logger = logging.getLogger(__name__)

CHANNEL_NAME = "notifications:websocket"

class NotificationManager:
    def __init__(self):
        self.user_connections: dict[int, list[WebSocket]] = {}
        self.instance_id = str(uuid.uuid4())
        self._pubsub_task = None
        self._redis_client = None

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.user_connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        conns = self.user_connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)

    async def _send_local(self, user_id: int, message: dict):
        for ws in self.user_connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def send_to_user(self, user_id: int, message: dict):
        await self._send_local(user_id, message)

        if not settings.REDIS_URL or not self._redis_client:
            return

        try:
            payload = json.dumps({
                "user_id": user_id,
                "message": message,
                "sender_instance": self.instance_id
            })
            await self._redis_client.publish(CHANNEL_NAME, payload)
        except Exception as e:
            logger.warning("Failed to publish notification to Redis Pub/Sub: %s", e)

    async def broadcast(self, message: dict):
        for conns in self.user_connections.values():
            for ws in conns:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

        if not settings.REDIS_URL or not self._redis_client:
            return

        try:
            payload = json.dumps({
                "user_id": None,
                "message": message,
                "sender_instance": self.instance_id
            })
            await self._redis_client.publish(CHANNEL_NAME, payload)
        except Exception as e:
            logger.warning("Failed to broadcast notification to Redis Pub/Sub: %s", e)

    async def start_listener(self):
        if not settings.REDIS_URL:
            return

        try:
            self._redis_client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
            self._pubsub_task = asyncio.create_task(self._listen_loop())
            logger.info("Redis Pub/Sub listener task started")
        except Exception as e:
            logger.error("Failed to start Redis Pub/Sub listener: %s", e)

    async def stop_listener(self):
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass

        if self._redis_client:
            await self._redis_client.close()

    async def _listen_loop(self):
        while True:
            try:
                if not self._redis_client:
                    self._redis_client = aioredis.from_url(
                        settings.REDIS_URL,
                        decode_responses=True
                    )

                async with self._redis_client.pubsub() as pubsub:
                    await pubsub.subscribe(CHANNEL_NAME)

                    async for msg in pubsub.listen():
                        if msg["type"] == "message":
                            try:
                                data = json.loads(msg["data"])
                                sender = data.get("sender_instance")
                                if sender == self.instance_id:
                                    continue

                                user_id = data.get("user_id")
                                message = data.get("message")

                                if user_id is None:
                                    for conns in self.user_connections.values():
                                        for ws in conns:
                                            try:
                                                await ws.send_json(message)
                                            except Exception:
                                                pass
                                else:
                                    await self._send_local(user_id, message)

                            except json.JSONDecodeError:
                                pass
                            except Exception as e:
                                logger.error("Error processing pub/sub message: %s", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Redis Pub/Sub disconnected: %s. Retrying in 5s...", e)
                if self._redis_client:
                    await self._redis_client.close()
                    self._redis_client = None
                await asyncio.sleep(5)


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

    # Security Fix: Reject non-Super-Admin roles
    if user.get("role") != "Super Admin":
        await websocket.close(code=1008)
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
