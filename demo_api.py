from __future__ import annotations

"""데모 API 라우터 — 프론트(직원 대시보드 + 민원인 앱)가 부르는 시연용 엔드포인트.

기존 api.py 의 파이프라인/스킬 엔드포인트는 건드리지 않는다. 여기 라우트는
demo_store.py 의 시드 데이터를 라벨과 함께 돌려주는 얇은 어댑터일 뿐이다.
api.py 에서 `app.include_router(demo_router)` 로 한 줄만 얹어 붙인다(정적 마운트 앞).

네임스페이스:
  GET  /api/staff/summary                         직원 홈 요약 카드 + 최근 처리 사건
  GET  /api/staff/intake                           신규 이관 사건 목록
  GET  /api/staff/checklist-plan/{case_id}         선택 사건 AI 자동 검토계획
  GET  /api/staff/cases/{case_id}                  사건 상세(원장/AI검증/유사사례/기한/재협상)
  GET  /api/staff/history                           고객 과거 민원 이력(+반복패턴/일관성점수)
  GET  /api/staff/me                                직원 계정/알림/활동로그/세션
  GET  /api/complainant/home                        민원인 홈
  GET  /api/complainant/progress                    민원인 진행현황(5단계 타임라인)
  GET  /api/complainant/history                     민원인 민원 이력
  GET  /api/complainant/me                          민원인 프로필/알림/메뉴
  GET  /api/complainant/product-types               민원접수 폼 상품유형
  POST /api/complainant/complaints                  신규 민원 제출(시연용 메모리 접수)
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import demo_store

router = APIRouter(prefix="/api", tags=["demo"])


# ---- 직원 대시보드 --------------------------------------------------------


@router.get("/staff/summary", summary="직원 홈 — 요약 카드 + 최근 처리 사건")
def staff_summary() -> dict[str, Any]:
    return {
        "summary": demo_store.staff_summary(),
        "recent": demo_store.staff_recent_cases(),
    }


@router.get("/staff/intake", summary="사건접수 — 신규 이관 사건 목록")
def staff_intake() -> list[dict[str, Any]]:
    return demo_store.staff_intake()


@router.get("/staff/checklist-plan/{case_id}", summary="사건접수 — AI 자동 검토계획")
def staff_checklist_plan(case_id: str) -> dict[str, Any]:
    plan = demo_store.staff_checklist_plan(case_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="검토 계획을 찾을 수 없습니다.")
    return plan


@router.get("/staff/cases/{case_id}", summary="처리현황 — 사건 상세 원장/AI검증/유사사례")
def staff_case_detail(case_id: str) -> dict[str, Any]:
    detail = demo_store.staff_case_detail(case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="사건을 찾을 수 없습니다.")
    return detail


@router.get("/staff/history", summary="이력 — 고객 과거 민원 + 반복패턴 + 일관성점수")
def staff_history(customer: str | None = None) -> dict[str, Any]:
    hist = demo_store.staff_customer_history(customer)
    if hist is None:
        raise HTTPException(status_code=404, detail="이력을 찾을 수 없습니다.")
    return hist


@router.get("/staff/me", summary="마이페이지 — 직원 계정/알림/활동로그/세션")
def staff_me() -> dict[str, Any]:
    return demo_store.staff_profile()


# ---- 민원인 앱 ------------------------------------------------------------


@router.get("/complainant/home", summary="민원인 홈")
def complainant_home() -> dict[str, Any]:
    return demo_store.complainant_home()


@router.get("/complainant/progress", summary="민원인 진행현황(5단계 타임라인)")
def complainant_progress() -> dict[str, Any]:
    return demo_store.complainant_progress()


@router.get("/complainant/history", summary="민원인 민원 이력")
def complainant_history() -> list[dict[str, Any]]:
    return demo_store.complainant_history()


@router.get("/complainant/me", summary="민원인 프로필/알림/메뉴")
def complainant_me() -> dict[str, Any]:
    return demo_store.complainant_profile()


@router.get("/complainant/product-types", summary="민원접수 폼 상품유형")
def complainant_product_types() -> list[dict[str, Any]]:
    return demo_store.complainant_product_types()


class ComplaintSubmission(BaseModel):
    """POST /api/complainant/complaints 요청 — 민원인이 앱에서 제출하는 신규 민원."""

    product_type: str = Field(description="금융상품 유형 key. 예: 'els_dls'.")
    facts: str = Field(description="사실관계 입력(자연어).")
    attachments: list[str] = Field(default_factory=list, description="첨부 파일명 목록(시연용).")


@router.post("/complainant/complaints", summary="신규 민원 제출(시연용 접수)")
def submit_complaint(req: ComplaintSubmission) -> dict[str, Any]:
    return demo_store.submit_complaint(req.product_type, req.facts, req.attachments)
