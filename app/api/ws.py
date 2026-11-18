"""WebSocket：用户接收审核结果，管理员接收新工单提醒。"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.services.notify import hub

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    payload = decode_token(token)
    if not payload:
        await ws.close(code=4401)
        return

    user_id = int(payload["sub"])
    is_admin = bool(payload.get("is_admin"))
    if is_admin:
        await hub.connect_admin(ws)
    else:
        await hub.connect_user(user_id, ws)

    try:
        while True:
            # 心跳（前端每 25s 发送 ping）
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(ws)
    except Exception:
        await hub.disconnect(ws)
