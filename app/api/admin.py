"""管理台接口：审核工单、会话回放、知识库管理、概览统计。"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import get_admin_user_id
from app.models import (
    AuditAction,
    AuditLog,
    ConversationLog,
    KnowledgeChunk,
    KnowledgeDoc,
    Order,
    RefundApplication,
    User,
)
from app.rag.ingest import SUPPORTED, delete_doc, ingest_file, refresh_index
from app.services import refund as refund_svc
from app.services.notify import hub

router = APIRouter()


# ============================================================
# 概览
# ============================================================
@router.get("/admin/stats")
async def stats(
    _: int = Depends(get_admin_user_id), session: AsyncSession = Depends(get_session)
):
    pending = (
        await session.exec(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == AuditAction.PENDING)
        )
    ).one()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_msgs = (
        await session.exec(
            select(func.count())
            .select_from(ConversationLog)
            .where(ConversationLog.role == "user", ConversationLog.created_at >= today)
        )
    ).one()
    chunks = (
        await session.exec(select(func.count()).select_from(KnowledgeChunk))
    ).one()
    refunds = (
        await session.exec(select(func.count()).select_from(RefundApplication))
    ).one()
    refund_amount = (
        await session.exec(select(func.coalesce(func.sum(RefundApplication.refund_amount), 0)))
    ).one()
    return {
        "pending_audits": int(pending),
        "today_conversations": int(today_msgs),
        "kb_chunks": int(chunks),
        "refund_count": int(refunds),
        "refund_amount": float(refund_amount or 0),
    }


# ============================================================
# 审核工单
# ============================================================
@router.get("/admin/audits")
async def list_audits(
    status: str = "pending",
    _: int = Depends(get_admin_user_id),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)
    if status == "pending":
        stmt = stmt.where(AuditLog.action == AuditAction.PENDING)
    logs = (await session.exec(stmt)).all()

    result = []
    for log in logs:
        refund = await session.get(RefundApplication, log.refund_application_id) if log.refund_application_id else None
        order = await session.get(Order, log.order_id) if log.order_id else None
        user = await session.get(User, log.user_id)
        result.append(
            {
                "id": log.id,
                "code": f"AU{log.id:04d}",
                "thread_id": log.thread_id,
                "trigger_reason": log.trigger_reason,
                "risk_level": log.risk_level,
                "action": log.action,
                "created_at": log.created_at.strftime("%m-%d %H:%M"),
                "admin_note": log.admin_note,
                "handled_at": log.handled_at.strftime("%m-%d %H:%M") if log.handled_at else None,
                "snapshot": log.context_snapshot,
                "user": {"id": user.id, "name": user.full_name, "username": user.username} if user else None,
                "order": {
                    "order_sn": order.order_sn,
                    "amount": float(order.total_amount),
                    "status": order.status,
                } if order else None,
                "refund": {
                    "id": refund.id,
                    "amount": float(refund.refund_amount),
                    "reason": refund.reason_detail,
                    "category": refund.reason_category,
                    "status": refund.status,
                } if refund else None,
            }
        )
    return result


class DecideRequest(BaseModel):
    approve: bool
    note: str = ""


@router.post("/admin/audits/{audit_id}/decide")
async def decide(
    audit_id: int,
    body: DecideRequest,
    admin_id: int = Depends(get_admin_user_id),
    session: AsyncSession = Depends(get_session),
):
    try:
        log = await refund_svc.decide_audit(session, audit_id, body.approve, admin_id, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    verdict = "通过" if body.approve else "驳回"
    notice = (
        f"您的退款申请（审核单 AU{log.id:04d}）人工审核已{verdict}。"
        + (f"备注：{body.note}" if body.note else "")
    )
    # 把人工结论写回会话，方便用户回看
    session.add(
        ConversationLog(
            thread_id=log.thread_id,
            user_id=log.user_id,
            role="system",
            content=notice,
            intent="REFUND_STATUS",
            extra={"audit_id": log.id, "approved": body.approve},
        )
    )
    await session.commit()

    await hub.send_user(
        log.user_id,
        {
            "type": "audit:decided",
            "audit_id": log.id,
            "approved": body.approve,
            "note": body.note,
            "message": notice,
        },
    )
    return {"ok": True, "action": log.action, "message": notice}


# ============================================================
# 会话回放
# ============================================================
@router.get("/admin/threads")
async def admin_threads(
    _: int = Depends(get_admin_user_id), session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.exec(
            select(ConversationLog).order_by(ConversationLog.created_at.desc()).limit(600)
        )
    ).all()
    users = {u.id: u for u in (await session.exec(select(User))).all()}

    threads: dict[str, dict] = {}
    for row in rows:
        item = threads.setdefault(
            row.thread_id,
            {
                "thread_id": row.thread_id,
                "user_id": row.user_id,
                "user_name": users[row.user_id].full_name if row.user_id in users else "未知用户",
                "title": "新会话",
                "preview": "",
                "updated_at": row.created_at,
                "count": 0,
                "intents": [],
            },
        )
        item["count"] += 1
        if item["title"] == "新会话" and row.role == "user" and row.content:
            item["title"] = row.content.replace("\n", " ")[:24]
        if item["preview"] == "" and row.role == "assistant" and row.content:
            item["preview"] = row.content.replace("\n", " ")[:50]
        if row.intent and row.intent not in item["intents"]:
            item["intents"].append(row.intent)

    result = sorted(threads.values(), key=lambda x: x["updated_at"], reverse=True)
    for item in result:
        item["updated_at"] = item["updated_at"].strftime("%m-%d %H:%M")
    return result


@router.get("/admin/threads/{thread_id}")
async def admin_thread_detail(
    thread_id: str,
    _: int = Depends(get_admin_user_id),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.exec(
            select(ConversationLog)
            .where(ConversationLog.thread_id == thread_id)
            .order_by(ConversationLog.created_at)
        )
    ).all()
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "intent": r.intent,
            "sources": r.sources,
            "extra": r.extra,
            "created_at": r.created_at.strftime("%H:%M:%S"),
        }
        for r in rows
    ]


# ============================================================
# 知识库
# ============================================================
@router.get("/admin/kb/docs")
async def list_docs(
    _: int = Depends(get_admin_user_id), session: AsyncSession = Depends(get_session)
):
    docs = (
        await session.exec(select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc()))
    ).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "filename": d.filename,
            "category": d.category,
            "source": d.source,
            "chunk_count": d.chunk_count,
            "char_count": d.char_count,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for d in docs
    ]


@router.post("/admin/kb/upload")
async def upload_doc(
    file: UploadFile = File(...),
    category: str = Form("上传知识"),
    _: int = Depends(get_admin_user_id),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"仅支持 {', '.join(sorted(SUPPORTED))} 格式")

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = settings.UPLOAD_DIR / (file.filename or f"upload{suffix}")
    with target.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    try:
        doc = await ingest_file(target, category=category or "上传知识", source="上传")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析失败：{exc}")
    return {"ok": True, "doc_id": doc.id, "chunks": doc.chunk_count, "title": doc.title}


@router.delete("/admin/kb/docs/{doc_id}")
async def remove_doc(doc_id: int, _: int = Depends(get_admin_user_id)):
    await delete_doc(doc_id)
    return {"ok": True}


@router.post("/admin/kb/reindex")
async def reindex(_: int = Depends(get_admin_user_id)):
    count = await refresh_index()
    return {"ok": True, "chunks": count}


@router.get("/admin/kb/search")
async def kb_search(q: str, _: int = Depends(get_admin_user_id)):
    from app.rag.bm25 import index

    hits = index.search(q, top_k=6, min_coverage=0.05)
    return [h.to_dict() for h in hits]
