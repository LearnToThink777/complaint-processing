from __future__ import annotations

"""비밀번호 해싱 · JWT 발급/검증 · 로그인 검사.

지영 브랜치(api/auth/service.py)의 로직을 그대로 쓴다 — 바뀐 것은 모델 import 경로뿐이다
(api.models.user → ..models). bcrypt 는 태은 브랜치도 같은 방식을 쓰기로 맞췄으므로
어느 쪽이 만든 계정이든 서로의 코드로 검증된다.
"""

import os
from datetime import datetime, timedelta
from typing import Any

import bcrypt
from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Customer, Staff

# 운영에서는 반드시 환경변수로 덮어쓴다(.env.example 참고). 개발 기본값을 그대로 쓰면
# 토큰을 누구나 위조할 수 있다.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False  # 해시가 아직 없는 계정(시드 직후) — 로그인 불가로 처리
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False  # bcrypt 포맷이 아닌 낡은 해시


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _create_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: str, user_type: str) -> str:
    return _create_token(
        {"sub": user_id, "type": user_type, "token_kind": "access"},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str, user_type: str) -> str:
    return _create_token(
        {"sub": user_id, "type": user_type, "token_kind": "refresh"},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def find_user(session: Session, user_type: str, user_id: str) -> Customer | Staff | None:
    if user_type == "customer":
        return session.execute(
            select(Customer).where(Customer.customer_id == user_id)).scalars().first()
    return session.execute(
        select(Staff).where(Staff.staff_id == user_id)).scalars().first()


def authenticate_user(session: Session, email: str, password: str) -> Customer | Staff | None:
    """이메일 하나로 민원인·직원을 모두 찾는다(로그인 창구가 하나다).

    성공하면 last_login_at 을 갱신한다 — 마이페이지 '세션' 칸이 이 값을 읽는다.
    """
    for model, id_col in ((Customer, Customer.email), (Staff, Staff.email)):
        user = session.execute(select(model).where(id_col == email)).scalars().first()
        if user is not None and verify_password(password, user.password_hash):
            user.last_login_at = datetime.utcnow()
            session.commit()
            return user
    return None
