"""DeepSeek（OpenAI 兼容协议）客户端：普通调用 + 流式输出。"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core.config import settings


class LLMError(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }


def _payload(messages: List[Dict[str, str]], stream: bool, **kwargs: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "stream": stream,
        "temperature": kwargs.pop("temperature", 0.3),
        "max_tokens": kwargs.pop("max_tokens", 1200),
    }
    body.update(kwargs)
    return body


async def chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 800,
    response_format: Optional[Dict[str, str]] = None,
) -> str:
    if not settings.LLM_API_KEY:
        raise LLMError("未配置 LLM_API_KEY，请在 .env 中填写 DeepSeek API Key")
    body = _payload(messages, False, temperature=temperature, max_tokens=max_tokens)
    if response_format:
        body["response_format"] = response_format
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=_headers(),
                json=body,
            )
            if resp.status_code >= 400:
                raise LLMError(f"模型服务返回 {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
    except httpx.HTTPError as exc:
        raise LLMError(f"模型服务连接失败: {exc}") from exc


async def stream_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.4,
    max_tokens: int = 1200,
) -> AsyncIterator[str]:
    if not settings.LLM_API_KEY:
        raise LLMError("未配置 LLM_API_KEY，请在 .env 中填写 DeepSeek API Key")

    body = _payload(messages, True, temperature=temperature, max_tokens=max_tokens)
    timeout = httpx.Timeout(settings.LLM_TIMEOUT, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=_headers(),
                json=body,
            ) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "ignore")
                    raise LLMError(f"模型服务返回 {resp.status_code}: {detail[:200]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
    except httpx.HTTPError as exc:
        raise LLMError(f"模型服务连接失败: {exc}") from exc
