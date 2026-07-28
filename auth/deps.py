from __future__ import annotations

"""현재 사용자 판별(FastAPI 의존성).

지영 브랜치(api/auth/dependencies.py)에서 가져왔고, 한 가지를 바꿨다:

이 저장소는 인증을 **신원 판별용으로만** 쓴다(라우트를 막지 않는다). 그래서 토큰이 없으면
401 을 던지는 대신 None 을 돌려주는 `current_identity` 를 기본으로 쓴다 — 로그인하지 않은
데모 흐름이 그대로 동작해야 하기 때문이다. 토큰을 필수로 요구하는 `get_current_user` 와
역할 가드(`require_staff`/`require_customer`)는 지영 것을 그대로 남겨 두었다.
나중에 차단으로 전환할 때 라우트에 그것들을 걸면 된다.
"""

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from ..db import get_session
from .service import decode_token, find_user

# auto_error=False: Authorization 헤더가 없어도 예외를 던지지 않는다(비로그인 허용).
_optional_bearer = HTTPBearer(auto_error=False)
_required_bearer = HTTPBearer()

_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="유효하지 않은 토큰입니다.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _resolve(token: str, session: Session) -> Any:
    """access 토큰 → 사용자. 실패하면 401 을 던진다.

    token_kind 를 확인하는 이유: refresh 토큰으로 API 를 호출하는 것을 막아야 한다
    (refresh 는 수명이 7일이라 그대로 통과시키면 짧은 만료가 무의미해진다).
    """
    try:
        payload = decode_token(token)
        if payload.get("token_kind") != "access":
            raise _INVALID
        user_id = payload["sub"]
        user_type = payload["type"]
    except (JWTError, KeyError) as exc:
        raise _INVALID from exc
    user = find_user(session, user_type, user_id)
    if user is None:
        raise _INVALID
    return user


def current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    session: Session = Depends(get_session),
) -> Any | None:
    """로그인했으면 그 사용자, 안 했으면 None.

    토큰을 보냈는데 그게 잘못된 경우는 None 이 아니라 401 이다 — 만료·위조를 조용히
    비로그인으로 강등하면 사용자가 '왜 남의 이름으로 보이는지' 알 수 없게 된다.
    """
    if credentials is None:
        return None
    return _resolve(credentials.credentials, session)


# ---- 아래는 토큰 필수(차단) 버전 — 지금은 라우트에 걸지 않는다 --------------------


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_required_bearer),
    session: Session = Depends(get_session),
) -> Any:
    return _resolve(credentials.credentials, session)


def require_staff(current_user=Depends(get_current_user)) -> Any:
    if current_user.user_type != "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="직원만 접근할 수 있습니다.")
    return current_user


def require_customer(current_user=Depends(get_current_user)) -> Any:
    if current_user.user_type != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="민원인만 접근할 수 있습니다.")
    return current_user


def staff_id_of(identity: Any | None) -> str | None:
    """인증된 사람이 직원이면 그 id. 아니면 None(호출부가 시드 계정으로 폴백한다)."""
    return identity.staff_id if identity is not None and identity.user_type == "staff" else None


def customer_id_of(identity: Any | None) -> str | None:
    return identity.customer_id if identity is not None and identity.user_type == "customer" else None
