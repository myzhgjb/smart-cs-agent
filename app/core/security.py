"""认证与密码哈希。

上游使用 passlib + bcrypt（bcrypt 对 Python 3.13 的 wheel 兼容性不稳），
这里改为标准库 hashlib.pbkdf2_hmac，零第三方依赖。
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings

ALGORITHM = "HS256"
_ITERATIONS = 120_000

def extract_token(request: Request) -> str:
    """兼容三种取 token 方式。

    云端网关会覆盖 Authorization 头，所以前端优先用 X-Auth-Token；
    本地开发仍支持标准 Bearer；WebSocket 用查询参数。
    """
    # 注意顺序：云端网关会注入自己的 Authorization 头，必须优先读我们自己的凭证
    custom = request.headers.get("x-auth-token")
    if custom:
        return custom.strip()
    query_token = (request.query_params.get("token") or "").strip()
    if query_token:
        return query_token
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


# ============================================================
# 密码
# ============================================================
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


# ============================================================
# JWT
# ============================================================
def create_access_token(user_id: int, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user_id(request: Request) -> int:
    token = extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证无效")
    return int(payload["sub"])


def get_admin_user_id(request: Request) -> int:
    token = extract_token(request)
    user_id = get_current_user_id(request)
    payload = decode_token(token) or {}
    if not payload.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user_id
