"""商城接口：商品浏览、购物车、下单支付、我的订单。

订单直接写入 `orders` 表，与客服系统共用一份数据——下完单再去问客服，
查询到的就是刚下的这一笔。
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_user_id
from app.models import CartItem, Invoice, InvoiceStatus, Order, OrderStatus, Product, User, utcnow
from app.services import refund as refund_svc

router = APIRouter()

DEFAULT_ADDRESS = "江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼"


# ============================================================
# 模型
# ============================================================
class CartRequest(BaseModel):
    product_id: int
    qty: int = Field(default=1, ge=1, le=99)


class QtyRequest(BaseModel):
    qty: int = Field(ge=1, le=99)


class CheckoutRequest(BaseModel):
    address: str = ""
    remark: str = ""


def product_payload(p: Product) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "category": p.category,
        "price": float(p.price),
        "original_price": float(p.original_price) if p.original_price else None,
        "stock": p.stock,
        "unit": p.unit,
        "emoji": p.emoji,
        "gradient": p.gradient,
        "summary": p.summary,
        "description": p.description,
        "tags": p.tags or [],
        "sales": p.sales,
        "rating": p.rating,
        "is_active": p.is_active,
    }


# ============================================================
# 商品
# ============================================================
@router.get("/mall/products")
async def list_products(
    category: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "recommend",
    _: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Product).where(Product.is_active == True)  # noqa: E712
    if category and category not in ("全部", "全部商品"):
        stmt = stmt.where(Product.category == category)
    products = list((await session.exec(stmt)).all())

    if q:
        keyword = q.strip().lower()
        products = [
            p
            for p in products
            if keyword in p.name.lower()
            or keyword in p.summary.lower()
            or any(keyword in t.lower() for t in (p.tags or []))
        ]

    if sort == "price_asc":
        products.sort(key=lambda p: p.price)
    elif sort == "price_desc":
        products.sort(key=lambda p: p.price, reverse=True)
    elif sort == "sales":
        products.sort(key=lambda p: p.sales, reverse=True)
    else:
        products.sort(key=lambda p: (p.sort, -p.sales))

    return [product_payload(p) for p in products]


@router.get("/mall/categories")
async def categories(
    _: int = Depends(get_current_user_id), session: AsyncSession = Depends(get_session)
):
    products = (
        await session.exec(select(Product).where(Product.is_active == True))  # noqa: E712
    ).all()
    counts: dict[str, int] = {}
    for p in products:
        counts[p.category] = counts.get(p.category, 0) + 1
    return [{"name": "全部商品", "count": len(products)}] + [
        {"name": k, "count": v} for k, v in counts.items()
    ]


@router.get("/mall/products/{product_id}")
async def product_detail(
    product_id: int,
    _: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="商品已下架")
    return product_payload(product)


# ============================================================
# 购物车
# ============================================================
async def _cart_payload(session: AsyncSession, user_id: int) -> dict:
    rows = (
        await session.exec(
            select(CartItem, Product)
            .where(CartItem.user_id == user_id, CartItem.product_id == Product.id)
            .order_by(CartItem.created_at)
        )
    ).all()
    items, total, count = [], 0.0, 0
    for cart, product in rows:
        subtotal = float(product.price) * cart.qty
        total += subtotal
        count += cart.qty
        items.append(
            {
                "id": cart.id,
                "product": product_payload(product),
                "qty": cart.qty,
                "subtotal": round(subtotal, 2),
            }
        )
    return {"items": items, "total": round(total, 2), "count": count}


@router.get("/mall/cart")
async def get_cart(
    user_id: int = Depends(get_current_user_id), session: AsyncSession = Depends(get_session)
):
    return await _cart_payload(session, user_id)


@router.post("/mall/cart")
async def add_to_cart(
    body: CartRequest,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, body.product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="商品已下架")

    existing = (
        await session.exec(
            select(CartItem).where(
                CartItem.user_id == user_id, CartItem.product_id == body.product_id
            )
        )
    ).first()
    target_qty = (existing.qty if existing else 0) + body.qty
    if target_qty > product.stock:
        raise HTTPException(status_code=400, detail=f"库存不足，当前仅剩 {product.stock} 件")

    if existing:
        existing.qty = target_qty
        session.add(existing)
    else:
        session.add(CartItem(user_id=user_id, product_id=body.product_id, qty=body.qty))
    await session.commit()
    return await _cart_payload(session, user_id)


@router.patch("/mall/cart/{item_id}")
async def update_cart(
    item_id: int,
    body: QtyRequest,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(CartItem, item_id)
    if not item or item.user_id != user_id:
        raise HTTPException(status_code=404, detail="购物车条目不存在")
    product = await session.get(Product, item.product_id)
    if product and body.qty > product.stock:
        raise HTTPException(status_code=400, detail=f"库存不足，当前仅剩 {product.stock} 件")
    item.qty = body.qty
    session.add(item)
    await session.commit()
    return await _cart_payload(session, user_id)


@router.delete("/mall/cart/{item_id}")
async def remove_cart_item(
    item_id: int,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(CartItem, item_id)
    if item and item.user_id == user_id:
        await session.delete(item)
        await session.commit()
    return await _cart_payload(session, user_id)


# ============================================================
# 结算 / 支付 / 订单
# ============================================================
def _new_order_sn() -> str:
    return f"SN{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10, 99)}"


@router.post("/mall/checkout")
async def checkout(
    body: CheckoutRequest,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    cart = await _cart_payload(session, user_id)
    if not cart["items"]:
        raise HTTPException(status_code=400, detail="购物车是空的")

    user = await session.get(User, user_id)
    address = body.address.strip() or DEFAULT_ADDRESS

    items = []
    for row in cart["items"]:
        product = await session.get(Product, row["product"]["id"])
        if not product or product.stock < row["qty"]:
            raise HTTPException(status_code=400, detail=f"「{row['product']['name']}」库存不足")
        product.stock -= row["qty"]
        product.sales += row["qty"]
        session.add(product)
        items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "qty": row["qty"],
                "price": float(product.price),
            }
        )

    order = Order(
        order_sn=_new_order_sn(),
        user_id=user_id,
        status=OrderStatus.PENDING,
        total_amount=cart["total"],
        items=items,
        shipping_address=address,
        tracking_number=None,
        carrier=None,
        created_at=utcnow(),
    )
    session.add(order)

    for row in cart["items"]:
        item = await session.get(CartItem, row["id"])
        if item:
            await session.delete(item)

    await session.commit()
    await session.refresh(order)

    return {
        "order_sn": order.order_sn,
        "total": float(order.total_amount),
        "address": order.shipping_address,
        "buyer": user.full_name if user else "",
        "status": order.status,
    }


@router.post("/mall/orders/{order_sn}/pay")
async def pay_order(
    order_sn: str,
    user_id: int = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    order = (
        await session.exec(
            select(Order).where(Order.order_sn == order_sn, Order.user_id == user_id)
        )
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="该订单无需支付")

    order.status = OrderStatus.PAID
    order.paid_at = utcnow()
    order.tracking_number = None
    session.add(order)

    session.add(
        Invoice(
            order_id=order.id,
            status=InvoiceStatus.NONE,
            title="个人",
            amount=float(order.total_amount),
        )
    )
    await session.commit()
    return {"ok": True, "order_sn": order.order_sn, "status": order.status}


@router.get("/mall/orders")
async def my_orders(
    user_id: int = Depends(get_current_user_id), session: AsyncSession = Depends(get_session)
):
    orders = (
        await session.exec(
            select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(30)
        )
    ).all()

    result = []
    for order in orders:
        result.append(
            {
                "order_sn": order.order_sn,
                "status": order.status,
                "status_text": refund_svc.status_text(order.status),
                "total_amount": float(order.total_amount),
                "items": order.items,
                "tracking_number": order.tracking_number,
                "carrier": order.carrier,
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M"),
                "address": order.shipping_address,
            }
        )
    return result
