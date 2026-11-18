"""进程内 WebSocket 连接管理：用户侧退款进度推送 + 管理台新工单提醒。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._users: Dict[int, Set[WebSocket]] = {}
        self._admins: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_user(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._users.setdefault(user_id, set()).add(ws)

    async def connect_admin(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._admins.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._admins.discard(ws)
            for conns in self._users.values():
                conns.discard(ws)

    async def _safe_send(self, ws: WebSocket, payload: Dict[str, Any]) -> bool:
        try:
            await ws.send_json(payload)
            return True
        except Exception:
            return False

    async def send_user(self, user_id: int, payload: Dict[str, Any]) -> None:
        for ws in list(self._users.get(user_id, set())):
            if not await self._safe_send(ws, payload):
                await self.disconnect(ws)

    async def send_admins(self, payload: Dict[str, Any]) -> None:
        for ws in list(self._admins):
            if not await self._safe_send(ws, payload):
                await self.disconnect(ws)


hub = Hub()
