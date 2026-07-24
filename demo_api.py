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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import demo_db, demo_store, perf
from .agentic_plan import extract_keywords, run_plan_generation
from .db import get_session
from .schemas import CaseKeywords

router = APIRouter(prefix="/api", tags=["demo"])


# ---- 직원 대시보드 --------------------------------------------------------


@router.get("/staff/summary", summary="직원 홈 — 요약 카드 + 최근 처리 사건")
def staff_summary() -> dict[str, Any]:
    return {
        "summary": demo_store.staff_summary(),
        "recent": demo_store.staff_recent_cases(),
    }


@router.get("/staff/intake", summary="사건접수 — 신규 이관/제출 사건 목록")
def staff_intake(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return demo_db.staff_intake(session)


@router.get("/staff/checklist-plan/{case_id}", summary="사건접수 — AI 자동 검토계획")
def staff_checklist_plan(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    plan = demo_db.staff_checklist_plan(session, case_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="사건을 찾을 수 없습니다.")
    return plan


@router.post("/staff/checklist-plan/{case_id}/generate", summary="사건접수 — AI 검토계획 생성 트리거")
def generate_checklist_plan(
    case_id: str,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """이관/시드 사건에 대해 실제 LLM 검토계획 생성을 시작한다(백그라운드).

    민원인 제출 사건은 접수 즉시 자동 생성되므로 이 엔드포인트는 직원 화면의 수동
    트리거(재생성 포함)용이다. 반환 즉시 status=plan_generating; 프론트가 폴링한다.
    """
    scheduled = demo_db.start_generation(session, case_id)
    if scheduled is None:
        raise HTTPException(status_code=409, detail="지금은 검토계획을 생성할 수 없습니다(이미 진행 중이거나 사건 없음).")
    background.add_task(run_plan_generation, scheduled)
    return demo_db.staff_checklist_plan(session, case_id) or {"case_id": case_id, "status": "generating"}


@router.get("/perf/summary", summary="성능 — LLM 호출 응답시간 기록/집계")
def perf_summary(task: str | None = None, limit: int = 50,
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    """검토계획 생성·스킬 호출의 소요시간 통계(평균/최소/최대/p50/p95) + 최근 기록.

    task 예: 'checklist_plan_agentic', 'skill:verdict'. 원본은 DB(performance_logs),
    사람이 읽는 사본은 PERFORMANCE_LOG.md 에 있다(docs/PERFORMANCE.md 참고).
    """
    return perf.summary(session, task=task, limit=limit)


@router.post("/staff/checklist-plan/{case_id}/approve", summary="사건접수 — 검토계획 승인")
def approve_checklist_plan(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """직원이 검토계획을 승인 → 사건이 '검토 중'으로 전이(민원인/직원 양쪽 화면 반영)."""
    try:
        return demo_db.approve_plan(session, case_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


# ---- 민원인 웹 포털 --------------------------------------------------------


@router.get("/complainant/home", summary="민원인 홈")
def complainant_home() -> dict[str, Any]:
    return demo_store.complainant_home()


@router.get("/complainant/progress", summary="민원인 진행현황(5단계 타임라인)")
def complainant_progress(session: Session = Depends(get_session)) -> dict[str, Any]:
    return demo_db.complainant_progress(session)


@router.get("/complainant/history", summary="민원인 민원 이력")
def complainant_history() -> list[dict[str, Any]]:
    return demo_store.complainant_history()


@router.get("/complainant/me", summary="민원인 프로필/알림/메뉴")
def complainant_me() -> dict[str, Any]:
    return demo_store.complainant_profile()


@router.get("/complainant/product-types", summary="민원접수 폼 상품유형")
def complainant_product_types() -> list[dict[str, Any]]:
    return demo_store.complainant_product_types()


class AnalyzeRequest(BaseModel):
    """POST /api/complainant/analyze 요청 — 접수 전 '쟁점 미리보기'용(DB 저장 없음)."""

    product_type: str = Field(description="금융상품 유형 key. 예: 'els_dls'.")
    facts: str = Field(description="사실관계 입력(자연어).")


@router.post("/complainant/analyze", response_model=CaseKeywords,
             summary="접수 전 AI 쟁점 분석 — 사실관계에서 검색 키워드 추출(미리보기)")
def analyze_complaint(req: AnalyzeRequest) -> CaseKeywords:
    """민원인이 제출하기 전에 '무엇을 쟁점으로 접수하게 되는지' 미리 보여준다.

    민원인은 법률 검색어를 모른다 — 여기서 자연어 사실관계를 법령·결정례가 쓰는 검색어로
    승격(extract_keywords)해 칩으로 되돌린다. 민원인이 확인·보정한 키워드가 제출 시 함께
    실려 검토계획 검색 품질을 끌어올린다. DB 에는 저장하지 않는다(제출 시점에 저장).
    빈약한 입력이어도 실패하지 않는다(extract_keywords 가 항상 CaseKeywords 반환).
    """
    product_en = demo_db.PRODUCT_EN.get(req.product_type, "general")
    return extract_keywords(req.facts, product_en, provider="mlapi-nano")


class ComplaintSubmission(BaseModel):
    """POST /api/complainant/complaints 요청 — 민원인이 앱에서 제출하는 신규 민원."""

    product_type: str = Field(description="금융상품 유형 key. 예: 'els_dls'.")
    facts: str = Field(description="사실관계 입력(자연어).")
    attachments: list[str] = Field(default_factory=list, description="첨부 파일명 목록(시연용).")
    keywords: dict[str, Any] | None = Field(
        default=None,
        description="접수 전 AI 쟁점 분석(/analyze)에서 민원인이 확인·보정한 검색 키워드(CaseKeywords). "
        "있으면 검토계획 생성이 이 키워드를 재사용한다(백그라운드 재추출 생략).",
    )


@router.post("/complainant/complaints", summary="신규 민원 제출 → 접수 + AI 검토계획 자동 생성")
def submit_complaint(
    req: ComplaintSubmission,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """민원인 제출을 DB 에 접수하고, 접수 즉시 실제 LLM 검토계획 생성을 백그라운드로 예약한다.

    응답은 즉시 반환(접수번호+상태). 검토계획은 직원 화면이 폴링하며 채워진다.
    """
    result = demo_db.submit_complaint(session, req.product_type, req.facts, req.attachments, req.keywords)
    background.add_task(run_plan_generation, result["case_id"])
    return result
