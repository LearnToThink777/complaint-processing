from __future__ import annotations

"""로그인 API 의 요청·응답 계약. 지영 브랜치(api/auth/schemas.py)를 그대로 가져왔다."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(description="로그인 ID(이메일). 민원인·직원 어느 쪽이든 같은 창구로 받는다.")
    password: str = Field(description="비밀번호.")


class TokenResponse(BaseModel):
    access_token: str = Field(description="API 호출에 쓰는 토큰(짧게 만료).")
    refresh_token: str = Field(description="access 토큰 재발급용(길게 유지).")
    token_type: str = "bearer"
    user_type: Literal["customer", "staff"] = Field(description="로그인한 사람의 종류 — 프론트가 어느 포털로 보낼지 결정한다.")
    name: str = Field(description="화면에 표시할 이름.")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(description="발급받은 refresh 토큰.")


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: str
    email: str
    name: str
    user_type: Literal["customer", "staff"]
    phone: Optional[str] = None
    # customer 전용
    verified: Optional[bool] = None
    # staff 전용
    dept: Optional[str] = None
    rank: Optional[str] = None
