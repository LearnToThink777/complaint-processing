from __future__ import annotations

"""로그인 엔드포인트 — /api/auth/*.

지영 브랜치(api/auth/router.py)에서 가져왔다. 바뀐 것:
  - prefix 를 /api/auth 로 (이 저장소의 프론트는 /api/* 규약을 쓴다 — demo_api 도 prefix="/api")
  - 세션 의존성을 db.get_session 으로
  - 로그인 성공/실패를 activity_log 에 남긴다 — 계정 행위 로그를 사건 이력(stage_events)과
    분리해 둔 이유가 이것이다(models.ActivityLog 주석 참고).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ActivityLog
from . import schemas, service
from .deps import current_identity, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _log(session: Session, owner_type: str, owner_id: str, action: str,
         detail: str, request: Request) -> None:
    session.add(ActivityLog(
        owner_type=owner_type, owner_id=owner_id, action=action, detail=detail,
        ip=request.client.host if request.client else "",
    ))
    session.commit()


@router.post("/login", response_model=schemas.TokenResponse, summary="로그인 — 민원인·직원 공통")
def login(body: schemas.LoginRequest, request: Request,
          session: Session = Depends(get_session)) -> Any:
    user = service.authenticate_user(session, body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )
    _log(session, user.user_type, user.id, "로그인", "성공", request)
    return schemas.TokenResponse(
        access_token=service.create_access_token(user.id, user.user_type),
        refresh_token=service.create_refresh_token(user.id, user.user_type),
        user_type=user.user_type,
        name=user.name,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="로그아웃")
def logout(request: Request, identity=Depends(current_identity),
           session: Session = Depends(get_session)) -> None:
    # JWT 는 stateless — 실제 무효화는 클라이언트가 토큰을 버리는 것으로 이뤄진다.
    # 서버가 할 수 있는 건 '언제 나갔는지'를 남기는 것이다.
    if identity is not None:
        _log(session, identity.user_type, identity.id, "로그아웃", "", request)


@router.post("/refresh", response_model=schemas.AccessTokenResponse, summary="access 토큰 재발급")
def refresh(body: schemas.RefreshRequest, session: Session = Depends(get_session)) -> Any:
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                           detail="유효하지 않은 리프레시 토큰입니다.")
    try:
        payload = service.decode_token(body.refresh_token)
        if payload.get("token_kind") != "refresh":
            raise invalid
        user_id = payload["sub"]
        user_type = payload["type"]
    except (JWTError, KeyError) as exc:
        raise invalid from exc

    user = service.find_user(session, user_type, user_id)
    if user is None:
        raise invalid
    return schemas.AccessTokenResponse(
        access_token=service.create_access_token(user.id, user.user_type))


@router.get("/me", response_model=schemas.UserInfo, summary="로그인한 계정 정보")
def me(current_user=Depends(get_current_user)) -> Any:
    base: dict[str, Any] = {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "user_type": current_user.user_type,
        "phone": current_user.phone,
    }
    if current_user.user_type == "customer":
        base["verified"] = current_user.verified
    else:
        base["dept"] = current_user.dept
        base["rank"] = current_user.rank
    return base
