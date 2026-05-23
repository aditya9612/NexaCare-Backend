from typing import Optional

from fastapi import WebSocket, status

from app.core.security import decode_token
from app.core.database import AsyncSessionLocal
from app.repositories.auth_repository import AuthRepository


async def authenticate_websocket(websocket: WebSocket) -> Optional[dict]:
    """Authenticate WebSocket via query param ?token= or Authorization header."""
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        user_id = int(payload["sub"])
    except (ValueError, KeyError, TypeError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    async with AsyncSessionLocal() as db:
        user = await AuthRepository(db).get_by_id(user_id)
        if not user or not user.is_active:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        return {
            "user_id": user.id,
            "email": user.email,
            "role": user.role.name if user.role else None,
        }
