"""FastAPI 入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import func, select

from app.api import admin as admin_api
from app.api import auth as auth_api
from app.api import chat as chat_api
from app.api import mall as mall_api
from app.api import ws as ws_api
from app.core.config import BASE_DIR, settings
from app.core.db import async_session_maker, init_db
from app.models import KnowledgeChunk, KnowledgeDoc
from app.rag.bm25 import index
from app.rag.ingest import ingest_directory, refresh_index
from app.seed import ensure_seed
from app.seed_products import ensure_products

FRONTEND_DIR = Path(__file__).parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    seeded = await ensure_seed()
    added_products = await ensure_products()
    if added_products:
        print(f"[Seed] 已写入 {added_products} 个商品")

    async with async_session_maker() as session:
        doc_count = (await session.exec(select(func.count()).select_from(KnowledgeDoc))).one()

    if doc_count == 0:
        docs = await ingest_directory(settings.KB_DIR, source="内置")
        print(f"[KB] 已导入 {len(docs)} 篇内置知识文档")
    else:
        count = await refresh_index()
        print(f"[KB] 索引就绪，共 {count} 个知识片段")

    if seeded:
        print("[Seed] 已生成演示用户 / 订单 / 发票数据")

    print(f"[App] {settings.PROJECT_NAME} v{settings.VERSION} 启动完成 -> http://127.0.0.1:8000")
    yield


app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth_api.router, chat_api.router, mall_api.router, admin_api.router, ws_api.router):
    app.include_router(router, prefix=settings.API_PREFIX)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/shop", include_in_schema=False)
async def shop_page():
    return FileResponse(FRONTEND_DIR / "shop.html")


@app.get("/health")
async def health():
    async with async_session_maker() as session:
        docs = (await session.exec(select(func.count()).select_from(KnowledgeDoc))).one()
    return {
        "status": "ok",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "llm": settings.LLM_MODEL,
        "kb_chunks": index.size,
        "kb_docs": int(docs),
        "features": [
            "多轮对话 + 意图路由",
            "订单 / 物流 / 发票工具调用",
            "退款风控 + 人工审核（HITL）",
            "私有知识库 BM25 检索",
            "SSE 流式回复",
            "管理台会话回放",
        ],
    }
