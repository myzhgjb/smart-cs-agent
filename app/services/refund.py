"""退款业务：资格校验、申请创建、风险分级、人工审核决策。

这部分是「确定性业务逻辑」，不交给大模型判断，避免金额/时效被编造。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import (
    AuditAction,
    AuditLog,
    Order,
    OrderStatus,
    RefundApplication,
    RefundReason,
    RefundStatus,
    RiskLevel,
    utcnow,
)

# 拆封后不支持无理由退货的品类
NON_RETURNABLE_KEYWORDS = ("内衣", "内裤", "袜子", "生鲜", "定制", "已激活", "贴身")
RETURNABLE_STATUS = {OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED}
NO_REASON_DAYS = 7


def guess_reason_category(text: str) -> RefundReason:
    if any(k in text for k in ("质量", "破损", "坏了", "瑕疵", "色差", "少件", "故障", "异响", "问题", "划痕", "掉漆")):
        return RefundReason.QUALITY_ISSUE
    if any(k in text for k in ("尺码", "大小", "不合身", "穿不下", "偏大", "偏小")):
        return RefundReason.SIZE_NOT_FIT
    if any(k in text for k in ("不符", "描述", "不一样", "货不对板")):
        return RefundReason.NOT_AS_DESCRIBED
    if any(k in text for k in ("不想要", "买错", "后悔", "取消")):
        return RefundReason.CHANGED_MIND
    return RefundReason.OTHER


async def get_user_order(
    session: AsyncSession, user_id: int, order_sn: Optional[str] = None
) -> Optional[Order]:
    stmt = select(Order).where(Order.user_id == user_id)
    if order_sn:
        stmt = stmt.where(Order.order_sn == order_sn.strip().upper())
    else:
        stmt = stmt.order_by(Order.created_at.desc()).limit(1)
    return (await session.exec(stmt)).first()


async def check_eligibility(
    session: AsyncSession, order: Order, reason: RefundReason
) -> Tuple[bool, str]:
    if order.status not in RETURNABLE_STATUS:
        return False, f"订单当前状态为「{_status_text(order.status)}」，暂不支持发起退货。"

    # 已有进行中的申请
    existing = (
        await session.exec(
            select(RefundApplication).where(
                RefundApplication.order_id == order.id,
                RefundApplication.status.in_(  # type: ignore[attr-defined]
                    [RefundStatus.PENDING, RefundStatus.APPROVED]
                ),
            )
        )
    ).first()
    if existing:
        return False, f"该订单已有一笔退款申请（#{existing.id}，状态：{_refund_status_text(existing.status)}），请勿重复提交。"

    # 品类限制
    blocked = [
        item.get("name", "")
        for item in order.items
        if any(k in str(item.get("name", "")) for k in NON_RETURNABLE_KEYWORDS)
    ]
    if blocked and reason != RefundReason.QUALITY_ISSUE:
        return False, f"订单包含「{'、'.join(blocked)}」等贴身/定制类商品，拆封后不支持无理由退货；如为质量问题请提供凭证。"

    # 7 天无理由
    if order.status == OrderStatus.DELIVERED and order.delivered_at:
        if utcnow() - order.delivered_at > timedelta(days=NO_REASON_DAYS) and reason != RefundReason.QUALITY_ISSUE:
            return False, f"订单签收已超过 {NO_REASON_DAYS} 天，仅支持质量问题退货，请提供商品问题凭证。"

    return True, "符合退货条件"


async def create_refund(
    session: AsyncSession,
    order: Order,
    user_id: int,
    reason_detail: str,
    reason_category: Optional[RefundReason] = None,
) -> RefundApplication:
    refund = RefundApplication(
        order_id=order.id,
        user_id=user_id,
        status=RefundStatus.PENDING,
        reason_category=reason_category or guess_reason_category(reason_detail),
        reason_detail=reason_detail,
        refund_amount=float(order.total_amount),
    )
    session.add(refund)
    await session.commit()
    await session.refresh(refund)
    return refund


def risk_of(amount: float) -> Optional[RiskLevel]:
    if amount >= settings.HIGH_RISK_REFUND_AMOUNT:
        return RiskLevel.HIGH
    if amount >= settings.MEDIUM_RISK_REFUND_AMOUNT:
        return RiskLevel.MEDIUM
    return None


def risk_reason(level: RiskLevel, amount: float) -> str:
    if level == RiskLevel.HIGH:
        return f"高额退款 ¥{amount:,.2f}（阈值 ¥{settings.HIGH_RISK_REFUND_AMOUNT:,.0f}）"
    return f"中额退款 ¥{amount:,.2f}（阈值 ¥{settings.MEDIUM_RISK_REFUND_AMOUNT:,.0f}）"


async def create_audit(
    session: AsyncSession,
    thread_id: str,
    user_id: int,
    order_id: int,
    refund_id: int,
    level: RiskLevel,
    amount: float,
    snapshot: dict,
) -> AuditLog:
    log = AuditLog(
        thread_id=thread_id,
        user_id=user_id,
        order_id=order_id,
        refund_application_id=refund_id,
        trigger_reason=risk_reason(level, amount),
        risk_level=level,
        action=AuditAction.PENDING,
        context_snapshot=snapshot,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def auto_approve(session: AsyncSession, refund: RefundApplication) -> None:
    refund.status = RefundStatus.APPROVED
    refund.reviewed_at = utcnow()
    refund.admin_note = "低风险，系统自动审核通过"
    session.add(refund)
    await session.commit()


async def decide_audit(
    session: AsyncSession,
    audit_id: int,
    approve: bool,
    admin_id: int,
    note: str = "",
) -> AuditLog:
    log = await session.get(AuditLog, audit_id)
    if not log:
        raise ValueError("审核单不存在")
    if log.action != AuditAction.PENDING:
        raise ValueError("该审核单已处理")

    log.action = AuditAction.APPROVED if approve else AuditAction.REJECTED
    log.admin_note = note
    log.handled_by = admin_id
    log.handled_at = utcnow()
    session.add(log)

    if log.refund_application_id:
        refund = await session.get(RefundApplication, log.refund_application_id)
        if refund:
            refund.status = RefundStatus.APPROVED if approve else RefundStatus.REJECTED
            refund.reviewed_at = utcnow()
            refund.admin_note = note
            session.add(refund)

    await session.commit()
    await session.refresh(log)
    return log


# ============================================================
# 文案
# ============================================================
_STATUS_MAP = {
    OrderStatus.PENDING: "待付款",
    OrderStatus.PAID: "已付款",
    OrderStatus.SHIPPED: "已发货",
    OrderStatus.DELIVERED: "已签收",
    OrderStatus.CANCELLED: "已取消",
}

_REFUND_STATUS_MAP = {
    RefundStatus.PENDING: "待审核",
    RefundStatus.APPROVED: "审核通过",
    RefundStatus.REJECTED: "已驳回",
    RefundStatus.COMPLETED: "已退款",
    RefundStatus.CANCELLED: "已取消",
}


def _status_text(status) -> str:
    try:
        return _STATUS_MAP[OrderStatus(status)]
    except Exception:
        return str(status)


def status_text(status) -> str:
    """订单状态中文（供商城与管理台复用）。"""
    return _status_text(status)


def refund_status_text(status) -> str:
    try:
        return _REFUND_STATUS_MAP[RefundStatus(status)]
    except Exception:
        return str(status)


def order_card(order: Order) -> dict:
    items = "、".join(f"{i.get('name', '商品')} × {i.get('qty', 1)}" for i in order.items) or "—"
    fields = [
        {"label": "订单号", "value": order.order_sn},
        {"label": "订单状态", "value": _status_text(order.status)},
        {"label": "订单金额", "value": f"¥{float(order.total_amount):,.2f}"},
        {"label": "商品明细", "value": items},
        {"label": "收货地址", "value": order.shipping_address or "—"},
    ]
    if order.tracking_number:
        fields.append({"label": "物流单号", "value": f"{order.carrier or '快递'} {order.tracking_number}"})
    if order.delivered_at:
        fields.append({"label": "签收时间", "value": order.delivered_at.strftime("%Y-%m-%d %H:%M")})
    return {
        "type": "order",
        "title": "订单详情",
        "badge": _status_text(order.status),
        "fields": fields,
    }


def refund_card(refund: RefundApplication, order_sn: str, audit_id: Optional[int] = None) -> dict:
    fields = [
        {"label": "申请编号", "value": f"#{refund.id}"},
        {"label": "订单号", "value": order_sn},
        {"label": "退款金额", "value": f"¥{float(refund.refund_amount):,.2f}"},
        {"label": "退款原因", "value": refund.reason_detail or "—"},
        {"label": "当前状态", "value": refund_status_text(refund.status)},
    ]
    if audit_id:
        fields.append({"label": "审核单号", "value": f"AU{audit_id:04d}"})
    status = "pending" if refund.status == RefundStatus.PENDING else (
        "success" if refund.status in (RefundStatus.APPROVED, RefundStatus.COMPLETED) else "danger"
    )
    return {
        "type": "refund",
        "title": "退款申请",
        "badge": refund_status_text(refund.status),
        "status": status,
        "fields": fields,
    }
