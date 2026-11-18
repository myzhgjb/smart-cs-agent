"""对话引擎：意图路由 → 工具调用 → 检索 → 生成。

一次 turn 的流程与上游 LangGraph 图一致，只是把图编排换成显式流程，
便于在单机环境下调试与观测：
    intent_router ─┬─> query_order     ─┐
                   ├─> query_logistics ─┤
                   ├─> query_invoice   ─┼─> generate
                   ├─> refund_flow     ─┤
                   └─> retrieve(KB)    ─┘
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator, Dict, List, Optional

from sqlmodel import select

from app.agent import tools
from app.agent.llm import LLMError, chat, stream_chat
from app.agent.prompts import ANSWER_PROMPT, ROUTER_PROMPT
from app.core.config import settings
from app.core.db import async_session_maker
from app.models import ConversationLog, RefundStatus, User
from app.rag.bm25 import index
from app.services import refund as refund_svc
from app.services.notify import hub

ORDER_SN_RE = re.compile(r"SN\d{6,}", re.IGNORECASE)

INTENT_LABEL = {
    "ORDER": "订单查询",
    "LOGISTICS": "物流跟踪",
    "REFUND": "售后办理",
    "REFUND_STATUS": "退款进度",
    "INVOICE": "发票服务",
    "POLICY": "政策咨询",
    "PRODUCT": "商品咨询",
    "HUMAN": "转人工",
    "OTHER": "综合咨询",
}

SUGGESTIONS = {
    "ORDER": ["这笔订单什么时候发货？", "帮我开发票", "我要退货"],
    "LOGISTICS": ["我要退货", "订单能开发票吗？"],
    "REFUND": ["退款进度到哪了？", "退货运费谁承担？"],
    "REFUND_STATUS": ["退货运费谁承担？", "我要修改收货地址"],
    "INVOICE": ["发票多久能开好？", "查一下我的订单"],
    "POLICY": ["我要退货", "查一下我的订单", "物流到哪了"],
    "PRODUCT": ["这款有现货吗？", "支持七天无理由退货吗？", "帮我查一下物流"],
    "OTHER": ["查一下我的订单", "退换货政策是什么？", "怎么开发票？"],
}

_REFUND_KW = ("退货", "退款", "换货", "退掉", "不要了")
_REFUND_STATUS_KW = ("退款进度", "申请进度", "审核进度", "退款到哪", "退款状态", "审核结果")
_HUMAN_KW = ("转人工", "人工客服", "找客服", "真人客服", "投诉", "转接")
_PRODUCT_KW = ("库存", "有货", "还有吗", "这款", "多少钱", "什么价", "适合", "参数", "规格", "尺码怎么选", "买哪个")
_INVOICE_KW = ("发票", "开票", "抬头", "税号")
_LOGISTICS_KW = ("物流", "快递", "到哪", "什么时候发", "发货了吗", "签收", "配送", "运单")
_ORDER_KW = ("订单", "我买的", "单号", "查单", "买了什么", "订单号")
_EXPLICIT_REQ = ("我要", "我想", "帮我", "申请", "办理", "直接退")
_POLICY_TONE = ("可以", "能不能", "是否", "吗", "怎么", "多久", "几天", "规则", "政策", "运费")


async def classify(question: str, history: List[dict]) -> Dict[str, Optional[str]]:
    """规则优先，规则不确定时再问大模型，兼顾准确率与响应速度。"""
    text = question.strip()
    order_sn = (ORDER_SN_RE.search(text).group(0).upper() if ORDER_SN_RE.search(text) else None)

    if any(k in text for k in _HUMAN_KW) and not any(k in text for k in _REFUND_KW):
        return {"intent": "HUMAN", "order_sn": order_sn, "reason": None}

    if any(k in text for k in _REFUND_STATUS_KW):
        return {"intent": "REFUND_STATUS", "order_sn": order_sn, "reason": None}

    if any(k in text for k in _REFUND_KW):
        explicit = any(k in text for k in _EXPLICIT_REQ)
        policy_tone = any(k in text for k in _POLICY_TONE)
        if order_sn or (explicit and not policy_tone):
            return {"intent": "REFUND", "order_sn": order_sn, "reason": text}
        if explicit:
            return {"intent": "REFUND", "order_sn": order_sn, "reason": text}
        return {"intent": "POLICY", "order_sn": order_sn, "reason": None}

    if any(k in text for k in _INVOICE_KW):
        return {"intent": "INVOICE", "order_sn": order_sn, "reason": None}
    if any(k in text for k in _LOGISTICS_KW):
        return {"intent": "LOGISTICS", "order_sn": order_sn, "reason": None}
    if any(k in text for k in _ORDER_KW):
        return {"intent": "ORDER", "order_sn": order_sn, "reason": None}

    if any(k in text for k in _PRODUCT_KW):
        return {"intent": "PRODUCT", "order_sn": order_sn, "reason": None}

    # 交给模型兜底
    try:
        raw = await chat(
            [
                {"role": "system", "content": ROUTER_PROMPT},
                *history[-4:],
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        intent = str(data.get("intent", "POLICY")).upper()
        if intent not in INTENT_LABEL:
            intent = "POLICY"
        return {
            "intent": intent,
            "order_sn": order_sn or data.get("order_sn"),
            "reason": data.get("reason"),
        }
    except Exception:
        return {"intent": "POLICY", "order_sn": order_sn, "reason": None}


def _retrieve(question: str, top_k: int = settings.TOP_K):
    return index.search(question, top_k=top_k, min_coverage=settings.MIN_COVERAGE)


def _sources_payload(hits) -> List[dict]:
    return [
        {
            "index": i + 1,
            "title": h.chunk.title,
            "category": h.chunk.category,
            "content": h.chunk.content.replace("\n", " ")[:180],
            "score": round(h.score, 3),
            "coverage": round(h.coverage, 3),
        }
        for i, h in enumerate(hits)
    ]


async def _history_messages(user_id: int, thread_id: str, limit: int = 6) -> List[dict]:
    async with async_session_maker() as session:
        rows = (
            await session.exec(
                select(ConversationLog)
                .where(
                    ConversationLog.thread_id == thread_id,
                    ConversationLog.user_id == user_id,
                    ConversationLog.role.in_(["user", "assistant"]),  # type: ignore[attr-defined]
                )
                .order_by(ConversationLog.created_at.desc())
                .limit(limit)
            )
        ).all()
    rows = list(reversed(rows))
    out = []
    for r in rows:
        content = (r.content or "").strip()
        if not content:
            continue
        out.append({"role": r.role, "content": content[:600]})
    return out


async def _last_pending_flow(user_id: int, thread_id: str) -> Optional[str]:
    async with async_session_maker() as session:
        row = (
            await session.exec(
                select(ConversationLog)
                .where(
                    ConversationLog.thread_id == thread_id,
                    ConversationLog.user_id == user_id,
                    ConversationLog.role == "assistant",
                )
                .order_by(ConversationLog.created_at.desc())
                .limit(1)
            )
        ).first()
    if row and row.extra:
        return row.extra.get("awaiting")
    return None


async def _log(
    thread_id: str,
    user_id: int,
    role: str,
    content: str,
    intent: Optional[str] = None,
    sources: Optional[list] = None,
    extra: Optional[dict] = None,
) -> None:
    async with async_session_maker() as session:
        session.add(
            ConversationLog(
                thread_id=thread_id,
                user_id=user_id,
                role=role,
                content=content,
                intent=intent,
                sources=sources or [],
                extra=extra or {},
            )
        )
        await session.commit()


async def _refund_flow(
    user_id: int, thread_id: str, question: str, order_sn: Optional[str]
) -> tools.ToolResult:
    async with async_session_maker() as session:
        order = await refund_svc.get_user_order(session, user_id, order_sn)

        if not order:
            latest = await refund_svc.get_user_order(session, user_id, None)
            if latest:
                return tools.ToolResult(
                    context=(
                        f"用户要办理退货，但未提供订单号。其最近一笔订单是 {latest.order_sn}"
                        f"（{refund_svc.order_card(latest)['badge']}，¥{float(latest.total_amount):,.2f}）。"
                        f"请让用户确认要退哪一笔。"
                    ),
                    card=refund_svc.order_card(latest),
                    ok=False,
                    extra={"need_order_sn": True},
                )
            return tools.ToolResult(
                context="用户名下没有可查询的订单，无法发起退货。",
                ok=False,
                extra={"need_order_sn": True},
            )

        reason_detail = question
        category = refund_svc.guess_reason_category(question)
        ok, message = await refund_svc.check_eligibility(session, order, category)
        if not ok:
            return tools.ToolResult(
                context=f"订单 {order.order_sn} 不符合退货条件：{message}",
                card=refund_svc.order_card(order),
                ok=False,
            )

        refund = await refund_svc.create_refund(
            session, order, user_id, reason_detail, category
        )
        level = refund_svc.risk_of(float(refund.refund_amount))

        if level is None:
            await refund_svc.auto_approve(session, refund)
            return tools.ToolResult(
                context=(
                    f"已为订单 {order.order_sn} 创建退款申请 #{refund.id}，"
                    f"金额 ¥{float(refund.refund_amount):,.2f}，系统自动审核通过，"
                    f"资金将在 3-5 个工作日内原路退回。"
                ),
                card=refund_svc.refund_card(refund, order.order_sn),
                extra={"refund_id": refund.id, "order_sn": order.order_sn},
            )

        audit = await refund_svc.create_audit(
            session,
            thread_id=thread_id,
            user_id=user_id,
            order_id=order.id,
            refund_id=refund.id,
            level=level,
            amount=float(refund.refund_amount),
            snapshot={
                "question": question,
                "order_sn": order.order_sn,
                "order_status": str(order.status),
                "refund_amount": float(refund.refund_amount),
                "reason": reason_detail,
            },
        )
        await hub.send_admins(
            {
                "type": "audit:new",
                "audit_id": audit.id,
                "order_sn": order.order_sn,
                "amount": float(refund.refund_amount),
                "risk": level,
            }
        )
        return tools.ToolResult(
            context=(
                f"已为订单 {order.order_sn} 创建退款申请 #{refund.id}，"
                f"金额 ¥{float(refund.refund_amount):,.2f}。因触发风控规则"
                f"「{audit.trigger_reason}」，已转人工审核（审核单 AU{audit.id:04d}），"
                f"承诺 24 小时内给出结果，无需重复提交。"
            ),
            card=refund_svc.refund_card(refund, order.order_sn, audit.id),
            extra={"refund_id": refund.id, "audit_id": audit.id, "order_sn": order.order_sn},
        )


async def stream_turn(user_id: int, thread_id: str, question: str) -> AsyncIterator[dict]:
    """产出一轮流式事件。"""
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "message": "请输入问题"}
        return

    history = await _history_messages(user_id, thread_id)
    pending = await _last_pending_flow(user_id, thread_id)
    await _log(thread_id, user_id, "user", question)

    result = await classify(question, history)
    intent = result["intent"] or "OTHER"
    order_sn = result.get("order_sn")

    # 上一轮在等订单号，且这一轮只给了单号 → 延续退货流程
    if pending == "refund" and order_sn and intent in ("ORDER", "OTHER", "POLICY"):
        intent = "REFUND"

    # 用户只发了一个订单号，而上下文是查询
    if order_sn and not ORDER_SN_RE.sub("", question).strip(" ，。,.号订单"):
        if intent not in ("REFUND", "REFUND_STATUS", "INVOICE", "LOGISTICS"):
            intent = "ORDER" if pending != "refund" else "REFUND"

    yield {"type": "intent", "intent": intent, "label": INTENT_LABEL.get(intent, "综合咨询")}

    context_parts: List[str] = []
    persisted_sources: List[dict] = []
    card: Optional[dict] = None
    awaiting: Optional[str] = None
    extra_log: dict = {}

    if intent == "POLICY":
        hits = _retrieve(question)
        if hits:
            persisted_sources = _sources_payload(hits)
            yield {"type": "sources", "sources": persisted_sources}
            for i, h in enumerate(hits):
                context_parts.append(f"[{i + 1}] {h.chunk.content}")
        else:
            answer = (
                "这条我暂时没在知识库里查到准确说法，不敢凭空回答你。\n"
                "你可以换个说法再问一次，或者提供订单号，我帮你转人工客服跟进。"
            )
            for ch in answer:
                yield {"type": "token", "text": ch}
            await _log(thread_id, user_id, "assistant", answer, intent)
            yield {"type": "done", "intent": intent, "suggestions": SUGGESTIONS.get(intent, [])}
            return

    elif intent == "ORDER":
        async with async_session_maker() as session:
            res = await tools.query_order(session, user_id, order_sn)
        context_parts.append(res.context)
        card = res.card
        if not res.ok:
            awaiting = "order_sn"

    elif intent == "LOGISTICS":
        async with async_session_maker() as session:
            res = await tools.query_logistics(session, user_id, order_sn)
        context_parts.append(res.context)
        card = res.card
        if not res.ok:
            awaiting = "order_sn"

    elif intent == "INVOICE":
        async with async_session_maker() as session:
            res = await tools.query_invoice(session, user_id, order_sn)
        context_parts.append(res.context)
        card = res.card
        if not res.ok:
            awaiting = "order_sn"
        # 同时补充开票政策
        hits = _retrieve("发票 开具 电子发票 抬头 多久")
        if hits:
            persisted_sources = _sources_payload(hits)
            yield {"type": "sources", "sources": persisted_sources}
            context_parts.extend(f"[开票政策{i + 1}] {h.chunk.content}" for i, h in enumerate(hits))

    elif intent == "REFUND_STATUS":
        async with async_session_maker() as session:
            res = await tools.query_refund_status(session, user_id, order_sn)
        context_parts.append(res.context)
        card = res.card
        hits = _retrieve("退款到账 时效 几个工作日 原路退回")
        if hits:
            persisted_sources = _sources_payload(hits)
            yield {"type": "sources", "sources": persisted_sources}
            context_parts.extend(f"[退款政策{i + 1}] {h.chunk.content}" for i, h in enumerate(hits))

    elif intent == "REFUND":
        res = await _refund_flow(user_id, thread_id, question, order_sn)
        context_parts.append(res.context)
        card = res.card
        extra_log = {k: v for k, v in res.extra.items() if isinstance(v, (int, str))}
        if not res.ok:
            awaiting = "refund" if res.extra.get("need_order_sn") else None
        # 售后处理同样需要引用政策条款（运费、期限、质量问题凭证）
        hits = _retrieve(f"退货退款 {question} 运费 期限 质量问题")
        if hits:
            persisted_sources = _sources_payload(hits)
            yield {"type": "sources", "sources": persisted_sources}
            context_parts.extend(f"[售后政策{i + 1}] {h.chunk.content}" for i, h in enumerate(hits))

    elif intent == "PRODUCT":
        async with async_session_maker() as session:
            res = await tools.query_product(session, question)
        context_parts.append(res.context)
        card = res.card
        hits = _retrieve(f"商品 选购 {question} 尺码 材质 适用")
        if hits:
            persisted_sources = _sources_payload(hits)
            yield {"type": "sources", "sources": persisted_sources}
            context_parts.extend(f"[选购参考{i + 1}] {h.chunk.content}" for i, h in enumerate(hits))

    elif intent == "HUMAN":
        answer = (
            "好的，已为你登记转接人工客服。\n"
            "人工在线时间为每天 09:00-22:00，平均等待 30 秒左右；如果当前是非服务时段，"
            "客服会在次日 09:30 前主动联系你。\n"
            "你也可以先把问题留在这里，我继续帮你查订单、物流或退款进度。"
        )
        for ch in answer:
            yield {"type": "token", "text": ch}
        await _log(thread_id, user_id, "assistant", answer, intent)
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
        await hub.send_admins(
            {
                "type": "handoff",
                "user_id": user_id,
                "user_name": user.full_name if user else "用户",
                "question": question,
                "thread_id": thread_id,
            }
        )
        yield {"type": "done", "intent": intent, "suggestions": SUGGESTIONS.get("OTHER", [])}
        return

    if card:
        yield {"type": "card", "card": card}
    # ---------------- 生成回答 ----------------
    context_text = "\n".join(p for p in context_parts if p) or "（本轮无业务数据）"
    user_payload = f"【业务数据】\n{context_text}\n\n【用户问题】\n{question}"

    answer_parts: List[str] = []
    try:
        messages = [{"role": "system", "content": ANSWER_PROMPT}, *history, {"role": "user", "content": user_payload}]
        async for token in stream_chat(messages, temperature=0.4):
            answer_parts.append(token)
            yield {"type": "token", "text": token}
    except LLMError as exc:
        fallback = context_text + f"\n\n（模型服务暂时不可用：{exc}）"
        answer_parts.append(fallback)
        yield {"type": "token", "text": fallback}

    answer = "".join(answer_parts).strip()
    log_extra = dict(extra_log)
    if awaiting:
        log_extra["awaiting"] = awaiting
    if card:
        log_extra["card"] = card

    await _log(
        thread_id,
        user_id,
        "assistant",
        answer,
        intent,
        sources=persisted_sources,
        extra=log_extra,
    )
    yield {
        "type": "done",
        "intent": intent,
        "suggestions": SUGGESTIONS.get(intent, []),
        "awaiting": awaiting,
    }
