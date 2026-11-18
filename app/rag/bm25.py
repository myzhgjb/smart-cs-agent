"""纯本地 BM25 检索。

为什么不继续用 pgvector：本机没有 PostgreSQL / Docker，DeepSeek 也没有
Embedding 接口。为了「数据不出本机、开箱即跑」，这里实现一个带中文分词的
内存 BM25 倒排索引，语义相近性由「词项覆盖率」兜底，够用于客服政策问答。
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import jieba

    jieba.setLogLevel(20)
    _HAS_JIEBA = True
except Exception:  # pragma: no cover - 分词器缺失时退化为字符二元组
    _HAS_JIEBA = False

_STOPWORDS = set(
    """的 了 和 是 就 都 而 及 与 着 或 一个 没有 我们 你们 他们 它们 这个 那个 这些 那些
    可以 请问 一下 怎么 如何 什么 为什么 是否 有 吗 呢 吧 啊 呀 哦 嗯 我 你 他 她 它 在 也 还
    需要 能够 进行 以及 对于 关于 如果 因为 所以 但是 然后 现在 已经 的话""".split()
)

_PUNCT_RE = re.compile(r"[\s\u3000，。！？；：、“”‘’（）《》【】·~`!@#$%^&*()\-+=\[\]{}\\|;:'\",.<>/?]+")


def tokenize(text: str) -> List[str]:
    """中文分词 + 清洗，返回词项列表。"""
    if not text:
        return []
    text = text.lower()
    if _HAS_JIEBA:
        raw = [w.strip() for w in jieba.cut(text)]
    else:
        raw = [c for c in text]
        raw += [text[i : i + 2] for i in range(len(text) - 1)]

    tokens: List[str] = []
    for w in raw:
        if not w or _PUNCT_RE.fullmatch(w):
            continue
        if w in _STOPWORDS:
            continue
        if len(w) == 1 and not re.match(r"[0-9a-z\u4e00-\u9fff]", w):
            continue
        tokens.append(w)
    return tokens


@dataclass
class Chunk:
    id: int
    doc_id: int
    title: str
    category: str
    content: str
    tokens: List[str] = field(default_factory=list)
    tf: Counter = field(default_factory=Counter)

    @property
    def length(self) -> int:
        return len(self.tokens)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    coverage: float

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk.id,
            "doc_id": self.chunk.doc_id,
            "title": self.chunk.title,
            "category": self.chunk.category,
            "content": self.chunk.content,
            "score": round(self.score, 4),
            "coverage": round(self.coverage, 4),
        }


class BM25Index:
    """线程安全的内存 BM25 索引（进程内单例）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._chunks: Dict[int, Chunk] = {}
        self._df: Counter = Counter()
        self._avg_len: float = 0.0
        self._lock = threading.RLock()

    # ---------------- 构建 ----------------
    def build(self, rows: Iterable[Tuple[int, int, str, str, str, str]]) -> None:
        """rows: (id, doc_id, title, category, content, tokens)"""
        with self._lock:
            self._chunks.clear()
            self._df.clear()
            total_len = 0
            for cid, doc_id, title, category, content, tokens in rows:
                tokens_list = tokens.split() if isinstance(tokens, str) else list(tokens)
                chunk = Chunk(
                    id=cid,
                    doc_id=doc_id,
                    title=title or "",
                    category=category or "通用政策",
                    content=content or "",
                    tokens=tokens_list,
                    tf=Counter(tokens_list),
                )
                self._chunks[cid] = chunk
                total_len += chunk.length
                for term in chunk.tf.keys():
                    self._df[term] += 1
            n = len(self._chunks)
            self._avg_len = (total_len / n) if n else 0.0

    @property
    def size(self) -> int:
        return len(self._chunks)

    # ---------------- 检索 ----------------
    def _idf(self, term: str) -> float:
        n = len(self._chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        top_k: int = 4,
        min_coverage: float = 0.15,
        category: Optional[str] = None,
    ) -> List[Hit]:
        with self._lock:
            if not self._chunks:
                return []
            q_tokens = tokenize(query)
            if not q_tokens:
                return []
            q_terms = list(dict.fromkeys(q_tokens))
            idf_map = {t: self._idf(t) for t in q_terms}
            total_idf = sum(idf_map.values()) or 1.0

            scored: List[Hit] = []
            for chunk in self._chunks.values():
                if category and chunk.category != category:
                    continue
                dl = chunk.length or 1
                score = 0.0
                matched_idf = 0.0
                for term in q_terms:
                    tf = chunk.tf.get(term, 0)
                    if not tf:
                        continue
                    idf = idf_map[term]
                    denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or dl))
                    score += idf * tf * (self.k1 + 1) / denom
                    matched_idf += idf
                if score <= 0:
                    continue
                coverage = matched_idf / total_idf
                if coverage < min_coverage:
                    continue
                scored.append(Hit(chunk=chunk, score=score, coverage=coverage))

            scored.sort(key=lambda h: (h.score, h.coverage), reverse=True)

            # 同一文档最多保留 2 个片段，保证结果多样性
            picked: List[Hit] = []
            per_doc: Counter = Counter()
            for hit in scored:
                if per_doc[hit.chunk.doc_id] >= 2:
                    continue
                picked.append(hit)
                per_doc[hit.chunk.doc_id] += 1
                if len(picked) >= top_k:
                    break
            return picked


index = BM25Index()
