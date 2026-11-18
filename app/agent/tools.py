"""Agent 工具层：订单 / 物流 / 发票 / 退款。

工具统一返回 ToolResult（context 供大模型引用，card 供前端渲染），
业务判定全部落在 SQL 与规则上，LLM 只负责组织语言。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Invoice, InvoiceStatus, Order, OrderStatus, RefundApplication
from app.services import refund as refund_svc


@dataclass
class ToolResult:
    context: str = ""
    card: Optional[dict] = None
    ok: bool = True
    extra: dict = field(default_factory=dict)


def _fmt_time(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"


async def query_order(
    session: AsyncSession, user_id: int, order_sn: Optional[str]
) -> ToolResult:
    order = await refund_svc.get_user_order(session, user_id, order_sn)
    if not order:
        return ToolResult(
            context="未查询到匹配的订单记录。",
            ok=False,
            extra={"need_order_sn": True},
        )
    items = "、".join(f"{i.get('name')}×{i.get('qty', 1)}" for i in order.items)
    ctx = (
        f"订单号 {order.order_sn}；状态 {refund_svc.order_card(order)['badge']}；"
        f"金额 ¥{float(order.total_amount):,.2f}；商品 {items}；"
        f"下单时间 {_fmt_time(order.created_at)}；收货地址 {order.shipping_address}"
    )
    if order.paid_at:
        ctx += f"；付款时间 {_fmt_time(order.paid_at)}"
    if order.shipped_at:
        ctx += f"；发货时间 {_fmt_time(order.shipped_at)}"
    if order.delivered_at:
        ctx += f"；签收时间 {_fmt_time(order.delivered_at)}"
    if order.tracking_number:
        ctx += f"；物流 {order.carrier or '快递'} {order.tracking_number}"
    return ToolResult(context=ctx, card=refund_svc.order_card(order), extra={"order": order})


async def query_logistics(
    session: AsyncSession, user_id: int, order_sn: Optional[str]
) -> ToolResult:
    order = await refund_svc.get_user_order(session, user_id, order_sn)
    if not order:
        return ToolResult(context="未查询到匹配的订单，无法定位物流。", ok=False, extra={"need_order_sn": True})

    if order.status == OrderStatus.PENDING:
        summary = "订单尚未付款，暂未生成物流单。"
        timeline = [("下单", order.created_at, True), ("付款", None, False), ("发货", None, False), ("签收", None, False)]
    elif order.status == OrderStatus.PAID:
        summary = f"订单已付款，仓库备货中，预计 24 小时内发出；物流单号 {order.tracking_number or '待生成'}。"
        timeline = [("下单", order.created_at, True), ("付款", order.paid_at, True), ("发货", None, False), ("签收", None, False)]
    elif order.status == OrderStatus.SHIPPED:
        summary = (
            f"包裹已由 {order.carrier or '快递'} 揽收，运单号 {order.tracking_number or '—'}，"
            f"预计 1-3 天送达。"
        )
        timeline = [("下单", order.created_at, True), ("付款", order.paid_at, True), ("发货", order.shipped_at, True), ("签收", None, False)]
    elif order.status == OrderStatus.DELIVERED:
        summary = f"包裹已于 {_fmt_time(order.delivered_at)} 签收，签收后 7 天内可申请无理由退货。"
        timeline = [("下单", order.created_at, True), ("付款", order.paid_at, True), ("发货", order.shipped_at, True), ("签收", order.delivered_at, True)]
    else:
        summary = "订单已取消，无物流信息。"
        timeline = [("下单", order.created_at, True), ("取消", order.created_at, True)]

    ctx = f"订单 {order.order_sn} 物流状态：{summary}"
    card = {
        "type": "timeline",
        "title": f"物流跟踪 · {order.order_sn}",
        "badge": order.carrier or "物流",
        "fields": [
            {"label": "运单号", "value": order.tracking_number or "待生成"},
            {"label": "当前状态", "value": refund_svc.order_card(order)["badge"]},
        ],
        "timeline": [
            {"label": label, "time": _fmt_time(t), "done": done} for label, t, done in timeline
        ],
    }
    return ToolResult(context=ctx, card=card, extra={"order": order})


async def query_invoice(
    session: AsyncSession, user_id: int, order_sn: Optional[str]
) -> ToolResult:
    order = await refund_svc.get_user_order(session, user_id, order_sn)
    if not order:
        return ToolResult(
            context="未查询到订单，无法查询发票。电子发票需绑定订单开具。",
            ok=False,
            extra={"need_order_sn": True},
        )

    invoice = (
        await session.exec(select(Invoice).where(Invoice.order_id == order.id))
    ).first()
    if not invoice or invoice.status == InvoiceStatus.NONE:
        ctx = (
            f"订单 {order.order_sn} 尚未开具发票。平台支持电子普通发票，"
            f"付款后可在订单详情提交抬头与税号，1 个工作日内开具并发送至邮箱。"
        )
        card = {
            "type": "invoice",
            "title": f"发票 · {order.order_sn}",
            "badge": "未开票",
            "status": "pending",
            "fields": [
                {"label": "订单金额", "value": f"¥{float(order.total_amount):,.2f}"},
                {"label": "可开票金额", "value": f"¥{float(order.total_amount):,.2f}"},
                {"label": "发票类型", "value": "电子普通发票"},
            ],
        }
    else:
        ctx = (
            f"订单 {order.order_sn} 发票状态：{invoice.status}；"
            f"发票号 {invoice.invoice_no or '开具中'}；抬头 {invoice.title}；金额 ¥{float(invoice.amount):,.2f}。"
        )
        card = {
            "type": "invoice",
            "title": f"发票 · {order.order_sn}",
            "badge": "已开票" if invoice.status == InvoiceStatus.ISSUED else "开具中",
            "status": "success" if invoice.status == InvoiceStatus.ISSUED else "pending",
            "fields": [
                {"label": "发票号", "value": invoice.invoice_no or "开具中"},
                {"label": "抬头", "value": invoice.title},
                {"label": "税号", "value": invoice.tax_no or "—"},
                {"label": "金额", "value": f"¥{float(invoice.amount):,.2f}"},
                {"label": "开具时间", "value": _fmt_time(invoice.issued_at)},
            ],
        }
    return ToolResult(context=ctx, card=card, extra={"order": order})


async def query_refund_status(
    session: AsyncSession, user_id: int, order_sn: Optional[str]
) -> ToolResult:
    stmt = select(RefundApplication).where(RefundApplication.user_id == user_id)
    if order_sn:
        order = await refund_svc.get_user_order(session, user_id, order_sn)
        if order:
            stmt = stmt.where(RefundApplication.order_id == order.id)
    refund = (await session.exec(stmt.order_by(RefundApplication.created_at.desc()).limit(1))).first()

    if not refund:
        return ToolResult(context="该用户名下没有查询到退款申请记录。", ok=False)

    order = await session.get(Order, refund.order_id)
    ctx = (
        f"退款申请 #{refund.id}（订单 {order.order_sn if order else '—'}）"
        f"当前状态 {refund_svc.refund_status_text(refund.status)}，"
        f"金额 ¥{float(refund.refund_amount):,.2f}，原因「{refund.reason_detail}」。"
    )
    if refund.admin_note:
        ctx += f" 审核备注：{refund.admin_note}"
    card = refund_svc.refund_card(refund, order.order_sn if order else "—")
    return ToolResult(context=ctx, card=card, extra={"refund": refund})


async def refunds_of_user(session: AsyncSession, user_id: int) -> List[RefundApplication]:
    rows = await session.exec(
        select(RefundApplication)
        .where(RefundApplication.user_id == user_id)
        .order_by(RefundApplication.created_at.desc())
        .limit(5)
    )
    return list(rows.all())


# ============================================================
# 商品工具：库存 / 价格 / 卖点（商城与客服共用 products 表）
# ============================================================
def _name_score(question: str, name: str) -> int:
    """用 2-gram 重合度粗匹配商品名，避免引入额外依赖。"""
    q = question.replace(" ", "")
    n = name.replace(" ", "")
    if n and n in q:
        return len(n) + 10
    grams = {n[i : i + 2] for i in range(len(n) - 1)}
    hit = sum(1 for g in grams if g in q)
    # 商品名里的数字/型号也算强特征
    return hit


async def query_product(session: AsyncSession, question: str) -> ToolResult:
    from app.models import Product

    products = list(
        (
            await session.exec(select(Product).where(Product.is_active == True))  # noqa: E712
        ).all()
    )
    if not products:
        return ToolResult(context="商品库暂时为空。", ok=False)

    scored = sorted(products, key=lambda p: _name_score(question, p.name), reverse=True)
    best = scored[0]
    score = _name_score(question, best.name)
    if score < 3:
        return ToolResult(
            context="用户咨询商品，但没有匹配到具体商品（可能是同义叫法）。",
            ok=False,
            extra={"need_product": True},
        )

    stock_text = f"现货 {best.stock} 件" if best.stock > 0 else "暂时缺货"
    ctx = (
        f"商品：{best.name}（{best.category}）；售价 ¥{float(best.price):,.2f}"
        + (f"，划线价 ¥{float(best.original_price):,.2f}" if best.original_price else "")
        + f"；库存：{stock_text}；累计销量 {best.sales}；评分 {best.rating}；"
        f"卖点：{best.summary}；详情：{best.description}；标签：{'、'.join(best.tags or [])}"
    )
    card = {
        "type": "product",
        "title": best.name,
        "badge": "有货" if best.stock > 0 else "缺货",
        "status": "success" if best.stock > 0 else "danger",
        "fields": [
            {"label": "售价", "value": f"¥{float(best.price):,.2f}"},
            {"label": "库存", "value": stock_text},
            {"label": "分类", "value": best.category},
            {"label": "销量 / 评分", "value": f"{best.sales} 件 · {best.rating}"},
            {"label": "卖点", "value": best.summary or "—"},
        ],
    }
    return ToolResult(context=ctx, card=card, extra={"product_id": best.id})
