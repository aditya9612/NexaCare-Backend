from fastapi import WebSocket


class QueueManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, department: str, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(department, []).append(websocket)

    async def update_queue(self, department: str, queue_data: dict):
        for ws in self.connections.get(department, []):
            await ws.send_json(queue_data)


queue_manager = QueueManager()
