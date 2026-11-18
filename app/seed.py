"""演示数据初始化（幂等）。"""
from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from app.core.db import async_session_maker
from app.core.security import hash_password
from app.models import (
    Invoice,
    InvoiceStatus,
    Order,
    OrderStatus,
    User,
    utcnow,
)


async def ensure_seed() -> bool:
    async with async_session_maker() as session:
        existing = (await session.exec(select(User))).first()
        if existing:
            return False

        now = utcnow()

        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            email="admin@xinghai.com",
            full_name="王敏",
            phone="13800000001",
            member_level="内部账号",
            is_admin=True,
        )
        user1 = User(
            username="user01",
            password_hash=hash_password("user123"),
            email="zhangxm@example.com",
            full_name="张小明",
            phone="13800000002",
            member_level="黄金会员",
        )
        user2 = User(
            username="user02",
            password_hash=hash_password("user123"),
            email="lisy@example.com",
            full_name="李思雨",
            phone="13800000003",
            member_level="白银会员",
        )
        session.add_all([admin, user1, user2])
        await session.commit()
        for u in (admin, user1, user2):
            await session.refresh(u)

        orders = [
            Order(
                order_sn="SN20241108001",
                user_id=user1.id,
                status=OrderStatus.DELIVERED,
                total_amount=599.00,
                items=[{"name": "星海 Air Pro 无线降噪耳机", "qty": 1, "price": 599.00}],
                tracking_number="SF1234567890123",
                carrier="顺丰速运",
                shipping_address="江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼",
                created_at=now - timedelta(days=6),
                paid_at=now - timedelta(days=6),
                shipped_at=now - timedelta(days=5),
                delivered_at=now - timedelta(days=3),
            ),
            Order(
                order_sn="SN20241112002",
                user_id=user1.id,
                status=OrderStatus.SHIPPED,
                total_amount=268.00,
                items=[
                    {"name": "星海 316 不锈钢保温杯 500ml", "qty": 1, "price": 128.00},
                    {"name": "纯棉船袜 5 双装", "qty": 2, "price": 70.00},
                ],
                tracking_number="ZTO8899001122",
                carrier="中通快递",
                shipping_address="江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼",
                created_at=now - timedelta(days=3),
                paid_at=now - timedelta(days=3),
                shipped_at=now - timedelta(days=1),
            ),
            Order(
                order_sn="SN20241115003",
                user_id=user1.id,
                status=OrderStatus.PAID,
                total_amount=3299.00,
                items=[{"name": "星海 Watch S2 智能手表 46mm", "qty": 1, "price": 3299.00}],
                tracking_number=None,
                carrier=None,
                shipping_address="江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼",
                created_at=now - timedelta(days=1, hours=3),
                paid_at=now - timedelta(days=1, hours=3),
            ),
            Order(
                order_sn="SN20241116004",
                user_id=user1.id,
                status=OrderStatus.DELIVERED,
                total_amount=158.00,
                items=[{"name": "无痕内衣 肤色 M 码", "qty": 1, "price": 158.00}],
                tracking_number="JD0099887766",
                carrier="京东物流",
                shipping_address="江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼",
                created_at=now - timedelta(days=4),
                paid_at=now - timedelta(days=4),
                shipped_at=now - timedelta(days=3),
                delivered_at=now - timedelta(days=2),
            ),
            Order(
                order_sn="SN20241117005",
                user_id=user1.id,
                status=OrderStatus.PENDING,
                total_amount=89.00,
                items=[{"name": "星海 100W 氮化镓充电器", "qty": 1, "price": 89.00}],
                tracking_number=None,
                carrier=None,
                shipping_address="江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼",
                created_at=now - timedelta(hours=5),
            ),
            Order(
                order_sn="SN20241110006",
                user_id=user2.id,
                status=OrderStatus.DELIVERED,
                total_amount=1280.00,
                items=[{"name": "星海 5L 空气炸锅 家用大容量", "qty": 1, "price": 1280.00}],
                tracking_number="YT7788990011",
                carrier="圆通速递",
                shipping_address="江苏省苏州市姑苏区干将东路 333 号",
                created_at=now - timedelta(days=12),
                paid_at=now - timedelta(days=12),
                shipped_at=now - timedelta(days=11),
                delivered_at=now - timedelta(days=10),
            ),
            Order(
                order_sn="SN20241114007",
                user_id=user2.id,
                status=OrderStatus.SHIPPED,
                total_amount=199.00,
                items=[{"name": "星海 通勤双肩包 15.6 英寸", "qty": 1, "price": 199.00}],
                tracking_number="SF9988776655443",
                carrier="顺丰速运",
                shipping_address="江苏省苏州市姑苏区干将东路 333 号",
                created_at=now - timedelta(days=2),
                paid_at=now - timedelta(days=2),
                shipped_at=now - timedelta(days=1),
            ),
        ]
        session.add_all(orders)
        await session.commit()
        for o in orders:
            await session.refresh(o)

        by_sn = {o.order_sn: o for o in orders}
        session.add_all(
            [
                Invoice(
                    order_id=by_sn["SN20241108001"].id,
                    status=InvoiceStatus.ISSUED,
                    title="张小明",
                    amount=599.00,
                    invoice_no="24310000000123456789",
                    issued_at=now - timedelta(days=5),
                ),
                Invoice(
                    order_id=by_sn["SN20241115003"].id,
                    status=InvoiceStatus.PROCESSING,
                    title="苏州科技大学",
                    tax_no="12320500MB1234567X",
                    amount=3299.00,
                ),
            ]
        )
        await session.commit()
        return True
