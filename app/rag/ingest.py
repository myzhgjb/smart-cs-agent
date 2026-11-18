"""知识库灌入与索引刷新。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from sqlmodel import delete, select

from app.core.config import settings
from app.core.db import async_session_maker
from app.models import KnowledgeChunk, KnowledgeDoc
from app.rag.bm25 import index, tokenize

SUPPORTED = {".md", ".txt", ".pdf", ".docx"}


# ============================================================
# 文本抽取
# ============================================================
def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        import pymupdf  # 本地已随 PDF 工具链安装

        parts: List[str] = []
        with pymupdf.open(str(path)) as doc:
            for page in doc:
                parts.append(page.get_text())
        return "\n".join(parts)
    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        blocks = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                blocks.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(blocks)
    raise ValueError(f"不支持的文件类型: {suffix}")


# ============================================================
# 切分
# ============================================================
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_long(text: str, size: int, overlap: int) -> List[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    pieces: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # 尽量在句号/换行处断开
        window = text[start:end]
        cut = max(window.rfind("。"), window.rfind("\n"), window.rfind("；"))
        if cut > size * 0.5 and end < len(text):
            end = start + cut + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in pieces if p]


def chunk_markdown(text: str) -> List[Tuple[str, str]]:
    """按标题切章节，返回 [(章节标题, 章节正文)]。"""
    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    current_title = "概述"
    buffer: List[str] = []
    for line in lines:
        m = _HEADING_RE.match(line.strip())
        if m:
            if "\n".join(buffer).strip():
                sections.append((current_title, buffer))
            current_title = m.group(2).strip() or current_title
            buffer = []
        else:
            buffer.append(line)
    if "\n".join(buffer).strip():
        sections.append((current_title, buffer))
    return [(title, "\n".join(body).strip()) for title, body in sections]


def build_chunks(text: str) -> List[Tuple[str, str]]:
    """返回 [(chunk 内容, 所属章节标题)]"""
    out: List[Tuple[str, str]] = []
    for title, body in chunk_markdown(text):
        if not body:
            continue
        for piece in _split_long(body, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP):
            # 把章节标题拼进片段，提升检索命中率与可读性
            out.append((f"【{title}】\n{piece}", title))
    return out


# ============================================================
# 入库
# ============================================================
async def ingest_file(
    path: Path,
    title: Optional[str] = None,
    category: str = "通用政策",
    source: str = "内置",
) -> KnowledgeDoc:
    text = extract_text(path)
    if not text.strip():
        raise ValueError("文档内容为空")

    doc_title = title or path.stem
    chunks = build_chunks(text)

    async with async_session_maker() as session:
        existing = (
            await session.exec(
                select(KnowledgeDoc).where(KnowledgeDoc.filename == path.name)
            )
        ).first()
        if existing:
            await session.exec(
                delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == existing.id)
            )
            doc = existing
            doc.title = doc_title
            doc.category = category
            doc.source = source
        else:
            doc = KnowledgeDoc(
                title=doc_title, filename=path.name, category=category, source=source
            )
            session.add(doc)
        await session.commit()
        await session.refresh(doc)

        for seq, (content, section) in enumerate(chunks):
            session.add(
                KnowledgeChunk(
                    doc_id=doc.id,
                    content=content,
                    tokens=" ".join(tokenize(content)),
                    seq=seq,
                    category=category,
                    title=f"{doc_title} · {section}" if section else doc_title,
                )
            )
        doc.chunk_count = len(chunks)
        doc.char_count = len(text)
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

    await refresh_index()
    return doc


async def ingest_directory(directory: Path, source: str = "内置") -> List[KnowledgeDoc]:
    docs: List[KnowledgeDoc] = []
    if not directory.exists():
        return docs
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SUPPORTED or not path.is_file():
            continue
        category = _guess_category(path.name)
        docs.append(await ingest_file(path, category=category, source=source))
    return docs


def _guess_category(filename: str) -> str:
    mapping = {
        "退": "退换货政策",
        "换": "退换货政策",
        "运费": "物流与运费",
        "物流": "物流与运费",
        "发货": "物流与运费",
        "发票": "发票与支付",
        "支付": "发票与支付",
        "会员": "会员与售后",
        "商品": "商品与选购",
        "选购": "商品与选购",
        "保修": "会员与售后",
    }
    for key, value in mapping.items():
        if key in filename:
            return value
    return "通用政策"


async def refresh_index() -> int:
    async with async_session_maker() as session:
        rows = (
            await session.exec(
                select(
                    KnowledgeChunk.id,
                    KnowledgeChunk.doc_id,
                    KnowledgeChunk.title,
                    KnowledgeChunk.category,
                    KnowledgeChunk.content,
                    KnowledgeChunk.tokens,
                ).where(KnowledgeChunk.is_active == True)  # noqa: E712
            )
        ).all()
    index.build(rows)
    return len(rows)


async def delete_doc(doc_id: int) -> None:
    async with async_session_maker() as session:
        await session.exec(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))
        doc = await session.get(KnowledgeDoc, doc_id)
        if doc:
            await session.delete(doc)
        await session.commit()
    await refresh_index()
