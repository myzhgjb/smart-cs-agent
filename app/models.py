"""数据模型。

上游使用 SQLModel + PostgreSQL + pgvector，这里保留 SQLModel 的数据建模方式，
但把向量列换成「分词的文本 + 内存倒排索引」，从而不依赖任何数据库扩展。
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, String, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# 枚举
# ============================================================
class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"        # 待审核
    APPROVED = "APPROVED"      # 审核通过
    REJECTED = "REJECTED"      # 审核驳回
    COMPLETED = "COMPLETED"    # 已退款
    CANCELLED = "CANCELLED"


class RefundReason(str, Enum):
    QUALITY_ISSUE = "QUALITY_ISSUE"
    SIZE_NOT_FIT = "SIZE_NOT_FIT"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    CHANGED_MIND = "CHANGED_MIND"
    OTHER = "OTHER"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AuditAction(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    NONE = "NONE"
    PROCESSING = "PROCESSING"
    ISSUED = "ISSUED"


# ============================================================
# 用户 / 订单 / 发票
# ============================================================
class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    password_hash: str = Field(max_length=255)
    email: str = Field(index=True, max_length=120)
    full_name: str = Field(max_length=60)
    phone: Optional[str] = Field(default=None, max_length=20)
    member_level: str = Field(default="普通会员", max_length=20)
    is_admin: bool = Field(default=False)
    is_active: bool = Field(default=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Order(SQLModel, table=True):
    __tablename__ = "orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_sn: str = Field(index=True, unique=True, max_length=32)
    user_id: int = Field(index=True, foreign_key="users.id")
    status: OrderStatus = Field(
        default=OrderStatus.PENDING, sa_column=Column(String, index=True, nullable=False)
    )
    total_amount: float = Field(default=0.0)
    items: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    tracking_number: Optional[str] = Field(default=None, max_length=40)
    carrier: Optional[str] = Field(default=None, max_length=30)
    shipping_address: str = Field(default="")
    paid_at: Optional[NaiveDatetime] = Field(default=None)
    shipped_at: Optional[NaiveDatetime] = Field(default=None)
    delivered_at: Optional[NaiveDatetime] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Invoice(SQLModel, table=True):
    __tablename__ = "invoices"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(index=True, foreign_key="orders.id")
    status: InvoiceStatus = Field(default=InvoiceStatus.NONE, sa_column=Column(String))
    title: str = Field(default="个人")
    tax_no: Optional[str] = Field(default=None, max_length=40)
    amount: float = Field(default=0.0)
    invoice_no: Optional[str] = Field(default=None, max_length=40)
    issued_at: Optional[NaiveDatetime] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class RefundApplication(SQLModel, table=True):
    __tablename__ = "refund_applications"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(index=True, foreign_key="orders.id")
    user_id: int = Field(index=True, foreign_key="users.id")
    status: RefundStatus = Field(
        default=RefundStatus.PENDING, sa_column=Column(String, index=True)
    )
    reason_category: RefundReason = Field(
        default=RefundReason.OTHER, sa_column=Column(String)
    )
    reason_detail: str = Field(default="", sa_column=Column(Text))
    refund_amount: float = Field(default=0.0)
    admin_note: Optional[str] = Field(default=None, sa_column=Column(Text))
    reviewed_at: Optional[NaiveDatetime] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: str = Field(index=True, max_length=128)
    user_id: int = Field(index=True)
    order_id: Optional[int] = Field(default=None, index=True)
    refund_application_id: Optional[int] = Field(default=None, index=True)
    trigger_reason: str = Field(default="", max_length=200)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, sa_column=Column(String, index=True))
    action: AuditAction = Field(default=AuditAction.PENDING, sa_column=Column(String, index=True))
    context_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    admin_note: Optional[str] = Field(default=None, sa_column=Column(Text))
    handled_by: Optional[int] = Field(default=None)
    handled_at: Optional[NaiveDatetime] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


# ============================================================
# 私有知识库
# ============================================================
class KnowledgeDoc(SQLModel, table=True):
    __tablename__ = "knowledge_docs"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    filename: str = Field(max_length=255)
    category: str = Field(default="通用政策", max_length=60, index=True)
    source: str = Field(default="内置", max_length=20)  # 内置 / 上传
    chunk_count: int = Field(default=0)
    char_count: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    doc_id: int = Field(index=True, foreign_key="knowledge_docs.id")
    content: str = Field(sa_column=Column(Text))
    tokens: str = Field(default="", sa_column=Column(Text))  # 空格分隔的分词结果
    seq: int = Field(default=0)
    category: str = Field(default="通用政策", max_length=60, index=True)
    title: str = Field(default="", max_length=200)
    is_active: bool = Field(default=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


# ============================================================
# 会话记录（供管理台回放 / 多轮上下文）
# ============================================================
class ConversationLog(SQLModel, table=True):
    __tablename__ = "conversation_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: str = Field(index=True, max_length=128)
    user_id: int = Field(index=True)
    role: str = Field(max_length=16)  # user / assistant / system
    content: str = Field(default="", sa_column=Column(Text))
    intent: Optional[str] = Field(default=None, max_length=20)
    sources: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    extra: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(default_factory=utcnow, index=True)


# ============================================================
# 商城：商品 / 购物车（订单复用 orders 表，客服可直接查询）
# ============================================================
class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: Optional[int] = Field(default=None, primary_key=True)
    sku: str = Field(index=True, unique=True, max_length=32)
    name: str = Field(max_length=120)
    category: str = Field(default="数码影音", max_length=30, index=True)
    price: float = Field(default=0.0)
    original_price: Optional[float] = Field(default=None)
    stock: int = Field(default=0)
    unit: str = Field(default="件", max_length=10)
    emoji: str = Field(default="📦", max_length=8)
    gradient: str = Field(default="linear-gradient(135deg,#eef2ff,#c7d2fe)", max_length=120)
    summary: str = Field(default="", max_length=120)
    description: str = Field(default="", sa_column=Column(Text))
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    sales: int = Field(default=0)
    rating: float = Field(default=4.8)
    is_active: bool = Field(default=True, index=True)
    sort: int = Field(default=0)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class CartItem(SQLModel, table=True):
    __tablename__ = "cart_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    product_id: int = Field(index=True, foreign_key="products.id")
    qty: int = Field(default=1)
    created_at: NaiveDatetime = Field(default_factory=utcnow)
