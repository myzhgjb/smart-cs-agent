"""认证接口。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.security import create_access_token, get_current_user_id, verify_password
from app.models import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "member_level": user.member_level,
        "is_admin": user.is_admin,
    }


@router.post("/auth/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = (
        await session.exec(select(User).where(User.username == body.username))
    ).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被停用")
    return {
        "token": create_access_token(user.id, user.is_admin),
        "user": _user_payload(user),
    }


@router.get("/auth/me")
async def me(user_id: int = Depends(get_current_user_id), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_payload(user)
