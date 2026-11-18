"""会话接口：SSE 流式对话 + 会话列表 + 历史消息。"""
import json
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.engine import stream_turn
from app.core.db import get_session
from app.core.security import get_current_user_id
from app.models import ConversationLog

router = APIRouter()

# 公网演示限流：每人 10 分钟 30 条，防止有人刷接口消耗模型额度
_RATE_LIMIT = 30
_RATE_WINDOW = 600
_buckets: dict[int, deque] = defaultdict(deque)


def _check_rate(user_id: int) -> None:
    now = time.time()
    q = _buckets[user_id]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="演示环境已限流：每人 10 分钟最多 30 条消息，请稍后再试。",
        )
    q.append(now)


class ChatRequest(BaseModel):
    question: str
    thread_id: str = "default"


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, user_id: int = Depends(get_current_user_id)):
    _check_rate(user_id)

    async def event_generator():
        try:
            async for event in stream_turn(user_id, body.thread_id, body.question):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # 兜底，保证前端能收到明确错误
            payload = json.dumps({"type": "error", "message": f"服务异常：{exc}"}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/threads")
async def list_threads(
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.exec(
            select(ConversationLog)
            .where(ConversationLog.user_id == user_id)
            .order_by(ConversationLog.created_at.desc())
            .limit(400)
        )
    ).all()

    threads: dict[str, dict] = {}
    for row in rows:
        item = threads.setdefault(
            row.thread_id,
            {
                "thread_id": row.thread_id,
                "title": "新会话",
                "preview": "",
                "updated_at": row.created_at,
                "count": 0,
            },
        )
        item["count"] += 1
        if item["preview"] == "" and row.role == "assistant" and row.content:
            item["preview"] = row.content.replace("\n", " ")[:46]
        if item["title"] == "新会话" and row.role == "user" and row.content:
            item["title"] = row.content.replace("\n", " ")[:22]
    result = sorted(threads.values(), key=lambda x: x["updated_at"], reverse=True)
    for item in result:
        item["updated_at"] = item["updated_at"].strftime("%Y-%m-%d %H:%M")
    return result


@router.get("/chat/threads/{thread_id}/messages")
async def thread_messages(
    thread_id: str,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.exec(
            select(ConversationLog)
            .where(
                ConversationLog.user_id == user_id,
                ConversationLog.thread_id == thread_id,
            )
            .order_by(ConversationLog.created_at)
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="会话不存在")
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "intent": r.intent,
            "sources": r.sources,
            "extra": r.extra,
            "created_at": r.created_at.strftime("%H:%M"),
        }
        for r in rows
    ]
