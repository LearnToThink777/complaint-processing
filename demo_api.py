from __future__ import annotations

"""데모 API 라우터 — 프론트(직원 대시보드 + 민원인 앱)가 부르는 시연용 엔드포인트.

기존 api.py 의 파이프라인/스킬 엔드포인트는 건드리지 않는다. 여기 라우트는
demo_store.py 의 시드 데이터를 라벨과 함께 돌려주는 얇은 어댑터일 뿐이다.
api.py 에서 `app.include_router(demo_router)` 로 한 줄만 얹어 붙인다(정적 마운트 앞).

네임스페이스:
  GET  /api/staff/summary                         직원 홈 요약 카드 + 최근 처리 사건
  GET  /api/staff/intake                           신규 이관 사건 목록
  GET  /api/staff/checklist-plan/{case_id}         선택 사건 AI 자동 검토계획
  GET  /api/staff/cases                            처리현황 목록(조건 검색 + 열 정렬)
  GET  /api/staff/cases/{case_id}                  사건 상세(원장/AI검증/처리기록/기한/중재)
  GET  /api/staff/mediations                        협상·중재 콘솔 목록(사건별 중재 상태)
  GET  /api/staff/history                           고객 단위 접수 이력(+요약/반복패턴)
  GET  /api/staff/me                                직원 계정/알림/활동로그/세션
  POST /api/staff/disclosure/publish                이중공개를 청중별로 분리 게시(민원인/직원)
  GET  /api/complainant/home                        민원인 홈
  GET  /api/complainant/progress                    사건별 진행현황(5단계 + 처리 기록)
  GET  /api/complainant/history                     민원인 민원 이력(사건별 진행 요약)
  GET  /api/complainant/me                          민원인 프로필/알림/메뉴
  GET  /api/complainant/product-types               민원접수 폼 상품유형
  POST /api/complainant/complaints                  신규 민원 제출(시연용 메모리 접수)
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import demo_db, demo_store, mediation_live, perf
from .agentic_plan import extract_keywords, run_plan_generation
from .case_ai import run_verdict_generation, search_similar_for_case
from .auth.deps import current_identity, customer_id_of, staff_id_of
from .db import get_session
from .schemas import CaseKeywords, DualDisclosure

router = APIRouter(prefix="/api", tags=["demo"])


# ---- 직원 대시보드 --------------------------------------------------------


@router.get("/staff/summary", summary="직원 홈 — 요약 카드 + 최근 처리 사건")
def staff_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    """요약 숫자·최근 사건 모두 DB 실측값(예전엔 demo_store 하드코딩 상수였다)."""
    return {
        "summary": demo_db.staff_summary(session),
        "recent": demo_db.staff_recent_cases(session),
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
    identity=Depends(current_identity),
) -> dict[str, Any]:
    """이관/시드 사건에 대해 실제 LLM 검토계획 생성을 시작한다(백그라운드).

    민원인 제출 사건은 접수 즉시 자동 생성되므로 이 엔드포인트는 직원 화면의 수동
    트리거(재생성 포함)용이다. 반환 즉시 status=plan_generating; 프론트가 폴링한다.
    """
    scheduled = demo_db.start_generation(session, case_id, staff_id_of(identity))
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
def approve_checklist_plan(case_id: str, session: Session = Depends(get_session),
                           identity=Depends(current_identity)) -> dict[str, Any]:
    """직원이 검토계획을 승인 → 사건이 '검토 중'으로 전이(민원인/직원 양쪽 화면 반영)."""
    try:
        return demo_db.approve_plan(session, case_id, staff_id=staff_id_of(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/staff/cases", summary="처리현황 — 처리 단계 사건 목록(조건 검색 + 열 정렬)")
def staff_cases(
    q: str | None = Query(default=None, description="사건번호·고객명·유형 부분일치 검색어."),
    status: str | None = Query(
        default=None,
        description="상태 필터. 정확한 status 키(reviewing/verdict/negotiating/closed…), "
        "콤마 구분 다중, 또는 프리셋 all|open|attention. 기본 all.",
    ),
    due_soon: bool = Query(default=False, description="True 면 기한 7일 이내·초과 사건만."),
    sort: str = Query(default="updated_at",
                      description="정렬 기준 열. case_id|customer|type|status|intake_date|due_date|verdict|updated_at"),
    order: str = Query(default="desc", description="asc|desc"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """목록을 조건 없이 전부 실어 보내던 것을 검색·정렬 가능한 목록으로 바꿘 엔드포인트.

    응답은 {rows, total, facets, sort, order, filters} — facets 는 상태 칩에 붙는 건수다.
    """
    return demo_db.staff_cases(session, q=q, status=status, due_soon=due_soon,
                               sort=sort, order=order)


@router.get("/staff/cases/{case_id}", summary="처리현황 — 사건 상세(접수 내용 + 원장/판정)")
def staff_case_detail(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    detail = demo_db.staff_case_detail(session, case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="사건을 찾을 수 없습니다.")
    return detail


@router.post("/staff/cases/{case_id}/verdict", summary="처리현황 — AI 규정 판정(원장) 생성 트리거")
def generate_verdict(
    case_id: str,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    identity=Depends(current_identity),
) -> dict[str, Any]:
    """승인된 검토계획의 항목 전부를 실제 LLM(verdict_batch)으로 판정해 원장을 채운다.

    검토계획 승인(=검토 중) 이후 직원이 수동으로 누르는 트리거다. 반환 즉시
    verdict_status=generating; 프론트가 사건 상세를 폴링해 원장이 채워지길 기다린다.
    """
    try:
        scheduled = demo_db.start_verdict_generation(session, case_id, staff_id_of(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if scheduled is None:
        raise HTTPException(status_code=409, detail="이미 판정을 생성하고 있습니다.")
    background.add_task(run_verdict_generation, scheduled)
    return demo_db.staff_case_detail(session, case_id) or {"case_id": case_id, "verdict_status": "generating"}


class CaseCloseRequest(BaseModel):
    """POST /api/staff/cases/{case_id}/close — 직원이 사건을 종결 처리."""

    outcome: str = Field(description="종결 결과. 사건 상세의 outcome_options 중 하나(accepted|partial|rejected).")
    note: str = Field(default="", description="처리 기록에 남길 메모(비우면 결과 라벨로 자동 기재).")


@router.post("/staff/cases/{case_id}/close", summary="처리현황 — 사건 종결 처리")
def close_case(case_id: str, req: CaseCloseRequest,
               session: Session = Depends(get_session),
               identity=Depends(current_identity)) -> dict[str, Any]:
    """사건을 '종결'로 전이하고 사람이 내린 결정(수용/일부수용/기각)을 남긴다.

    판정이 안 끝난 검토 항목이 남아 있으면 409 — 원장이 미완인 채로 종결되지 않게 막는다.
    종결 시각은 별도 컬럼이 아니라 여기서 남는 처리 기록(StageEvent)에서 파생된다.
    """
    try:
        return demo_db.close_case(session, case_id, outcome=req.outcome, note=req.note,
                                  staff_id=staff_id_of(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class VerdictOverrideRequest(BaseModel):
    """PATCH /api/staff/cases/{case_id}/ledger/{seq} — 직원이 AI 판정을 직접 고쳐 확정."""

    verdict: str = Field(description="확정할 판정 라벨. 사건 상세의 verdict_options 중 하나.")
    ko: str = Field(default="", description="한 줄 판정 요지.")
    detail: str = Field(default="", description="판정 근거 상세.")
    code: str | None = Field(default=None, description="적용 근거 조항(비우면 기존 값 유지).")
    reason: str = Field(description="왜 AI 판정을 바꾸는지 — 감사 기록에 남는다(필수).")
    staff: str = Field(default="홍길동", description="수정한 담당자.")


@router.patch("/staff/cases/{case_id}/ledger/{seq}", summary="처리현황 — AI 판정을 담당자가 수정·확정")
def override_verdict(case_id: str, seq: int, req: VerdictOverrideRequest,
                     session: Session = Depends(get_session),
                     identity=Depends(current_identity)) -> dict[str, Any]:
    """AI 판정은 제안이고 확정은 사람이 한다 — 그 통로.

    AI 원안은 ai_original 에 보존되고, 바뀐 행은 '담당자 확정'으로 표시된다. 이후 판정을
    재생성해도 담당자가 확정한 행은 덮어쓰지 않는다.
    """
    try:
        return demo_db.override_verdict(
            session, case_id, seq, verdict=req.verdict, ko=req.ko, detail=req.detail,
            code=req.code, reason=req.reason,
            # 요청 본문의 staff 는 클라이언트가 자칭하는 값이다 — 로그인했으면 그 이름이 진실이다.
            staff=(identity.name if identity is not None else req.staff),
            staff_id=staff_id_of(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/staff/cases/{case_id}/ledger/{seq}/revert", summary="처리현황 — 담당자 수정을 AI 원안으로 되돌림")
def revert_verdict(case_id: str, seq: int, session: Session = Depends(get_session),
                   identity=Depends(current_identity)) -> dict[str, Any]:
    try:
        return demo_db.revert_verdict(session, case_id, seq, staff_id=staff_id_of(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/staff/cases/{case_id}/similar-cases", summary="처리현황 — 이 사건의 접수 내용으로 유사사례 실검색")
def staff_case_similar(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """선택된 사건의 접수 사실·키워드로 결정례를 실검색한다(하드코딩 질의가 아님).

    같은 상품유형 결정례가 코퍼스에 없으면 전체 결정례에서 가장 가까운 선례로 폴백한다.
    """
    case = demo_db.get_case_or_none(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="사건을 찾을 수 없습니다.")
    return search_similar_for_case(
        facts=case.facts,
        product_en=case.product_en,
        keywords=case.keywords or {},
        due_date=case.due_date or case.expected_completion or "",
    )


# ---- 협상·중재 (사건에 붙여 DB 영속 · 민원인/직원 양쪽 화면에 노출) --------
# 기존 /api/mediation/live/* 는 '사건과 무관한' 콘솔 데모용으로 그대로 둔다. 아래는 그
# 라이브 세션을 특정 민원 사건에 묶고, 턴마다 레코드를 DB 에 스냅샷하는 사건 스코프 API다.


class MediationRequestBody(BaseModel):
    """협상·중재 요청 — 민원인/직원 공통."""

    reason: str = Field(default="", description="중재를 요청하는 사유(선택).")


class MediationStartBody(BaseModel):
    """중재 세션 개시 — 직원이 콘솔을 열 때."""

    scenario_id: str | None = Field(default=None, description="중재 시나리오 id. 없으면 첫 시나리오.")
    use_llm: bool = Field(default=True, description="True면 실제 LLM 롤플레이, False면 더미 스크립트.")
    provider: str = Field(default="mlapi-nano", description="LLM provider.")


def _case_or_404(session: Session, case_id: str):
    case = demo_db.get_case_or_none(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="사건을 찾을 수 없습니다.")
    return case


@router.get("/staff/mediations", summary="협상·중재 콘솔 — 사건별 중재 진행 목록")
def staff_mediations(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """중재 콘솔의 좌측 목록 — 처리 중 사건과 각 사건의 중재 상태(없으면 'none').

    직원 화면에서 중재를 보는 자리가 여러 곳으로 흩어져 있던 것을 콘솔 한 곳으로 모으면서
    생긴 엔드포인트다. 처리현황은 사건별 요약만 보여주고, 진행은 전부 콘솔에서 한다.
    """
    return demo_db.staff_mediations(session)


@router.get("/staff/cases/{case_id}/mediation", summary="협상·중재 — 이 사건의 중재 내역")
def staff_mediation(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case_or_404(session, case_id)
    return {"case_id": case_id, "mediation": demo_db.mediation_payload(session, case)}


@router.post("/staff/cases/{case_id}/mediation/request", summary="협상·중재 — 직원이 중재 요청")
def staff_request_mediation(case_id: str, body: MediationRequestBody,
                            session: Session = Depends(get_session),
                            identity=Depends(current_identity)) -> dict[str, Any]:
    try:
        return demo_db.request_mediation(session, case_id, requested_by="staff", reason=body.reason,
                                        staff_id=staff_id_of(identity))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/staff/cases/{case_id}/mediation/start", summary="협상·중재 — 이 사건의 중재 세션 개시")
def staff_start_mediation(case_id: str, body: MediationStartBody,
                          session: Session = Depends(get_session)) -> dict[str, Any]:
    """라이브 중재 세션을 만들어 이 사건에 묶는다.

    당사자·도메인·대화는 시연 시나리오가 아니라 '이 사건'에서 만든다 — 그러지 않으면
    대출·예금 민원의 중재 화면에도 'ELS 원금손실 42%, 김소연(63세)'가 뜬다.
    이미 진행한 중재가 DB 에 있으면 그 원장을 이어받는다(재개시로 기록이 사라지지 않게).
    """
    case = _case_or_404(session, case_id)
    prior = demo_db.mediation_payload(session, case) or {}
    try:
        sess = mediation_live.start(
            body.scenario_id, use_llm=body.use_llm, provider=body.provider,
            case_ctx={
                "case_id": case.case_id,
                "customer": case.customer,
                "domain": case.complaint_type or demo_db.product_label(case.product_type),
                "facts": case.facts,
            },
            resume=prior.get("record") or None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return demo_db.save_mediation_session(
        session, case_id, sid=sess.sid, scenario_id=sess.scenario_id,
        record=sess.record.model_dump(), turn_index=sess.turn_index,
        max_turns=sess.max_turns, done=sess.done)


@router.post("/staff/cases/{case_id}/mediation/turn", summary="협상·중재 — 한 발언 진행")
def staff_mediation_turn(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """세션을 한 턴 진행하고 갱신된 레코드를 사건에 스냅샷한다.

    세션은 프로세스 메모리에 있어 서버 재시작 시 사라진다. 그때는 DB 스냅샷으로 세션을
    조용히 복원해 이어 간다 — 직원에게 '다시 개시하세요'를 요구하지 않는다.
    """
    case = _case_or_404(session, case_id)
    med = demo_db.mediation_payload(session, case)
    if not med or not med.get("sid"):
        raise HTTPException(status_code=409, detail="개시된 중재 세션이 없습니다. 먼저 중재를 개시하세요.")
    sess = mediation_live.get(med["sid"])
    if sess is None:  # 서버가 재시작됐다 — 쌓아 둔 원장 위에서 세션을 되살린다.
        sess = mediation_live.start(
            med.get("scenario_id"), use_llm=True,
            case_ctx={
                "case_id": case.case_id,
                "customer": case.customer,
                "domain": case.complaint_type or demo_db.product_label(case.product_type),
                "facts": case.facts,
            },
            resume=med.get("record") or None,
        )
    try:
        mediation_live.next_turn(sess)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    return demo_db.save_mediation_session(
        session, case_id, sid=sess.sid, scenario_id=sess.scenario_id,
        record=sess.record.model_dump(), turn_index=sess.turn_index,
        max_turns=sess.max_turns, done=sess.done)


@router.get("/staff/history", summary="고객 이력 — 사람 단위 접수 이력 + 요약 + 반복패턴")
def staff_history(customer: str | None = Query(default=None,
                                              description="고객명(부분일치 가능). 없으면 접수가 가장 많은 고객."),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    hist = demo_db.staff_customer_history(session, customer)
    if hist is None:
        raise HTTPException(status_code=404, detail="이력을 찾을 수 없습니다.")
    return hist


@router.get("/staff/me", summary="마이페이지 — 직원 계정/알림/활동로그/세션")
def staff_me(session: Session = Depends(get_session),
             identity=Depends(current_identity)) -> dict[str, Any]:
    return demo_db.staff_profile(session, staff_id_of(identity))


class NotificationToggle(BaseModel):
    """알림 하나를 켜거나 끈다. 그동안 화면 토글이 아무 곳에도 저장되지 않았다."""

    key: str = Field(description="알림 항목 키. 프로필 응답의 notifications[].key 중 하나.")
    enabled: bool = Field(description="켜기(true) / 끄기(false).")


@router.patch("/staff/me/notifications", summary="마이페이지 — 직원 알림 설정 저장")
def staff_set_notification(req: NotificationToggle,
                           session: Session = Depends(get_session)) -> dict[str, Any]:
    me = demo_db.current_staff(session)
    if me is None:
        raise HTTPException(status_code=404, detail="직원 계정이 없습니다.")
    return {"notifications": demo_db.set_notification_setting(
        session, "staff", me.staff_id, req.key, req.enabled)}


@router.patch("/complainant/me/notifications", summary="마이페이지 — 민원인 알림 설정 저장")
def complainant_set_notification(req: NotificationToggle,
                                 session: Session = Depends(get_session)) -> dict[str, Any]:
    me = demo_db.current_customer(session)
    if me is None:
        raise HTTPException(status_code=404, detail="민원인 계정이 없습니다.")
    return {"notifications": demo_db.set_notification_setting(
        session, "customer", me.customer_id, req.key, req.enabled)}


class PublishDisclosureRequest(BaseModel):
    """POST /api/staff/disclosure/publish 요청 — 직원이 생성한 이중공개를 청중별로 게시."""

    disclosure: DualDisclosure = Field(description="게시할 이중공개(민원인용/직원·감독원용 본문).")
    stage_key: str | None = Field(
        default=None,
        description="게시할 처리단계 key(intake/reviewing/verdict/negotiation/closed). "
        "없으면 사건 status 로 유도한다.",
    )
    case_id: str | None = Field(
        default=None,
        description="게시 대상 사건번호. 처리현황에서 선택한 사건에 게시하려면 지정한다. "
        "없으면 진행현황이 보여주는 citizen 데모 사건에 게시.",
    )


@router.post("/staff/disclosure/publish", summary="처리현황 — 이중공개를 청중별로 분리 게시")
def publish_disclosure(
    req: PublishDisclosureRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """직원이 생성한 이중공개를 청중별로 게시한다: 민원인용→민원인 진행현황, 직원용→직원 화면.

    같은 판정을 청중별로 다르게 쓴 두 본문을 각각 audience 로 갈라 영속한다. 민원인용은
    진행현황 트래커의 해당 단계에 바로 노출된다. 대상은 진행현황이 보여주는 citizen 데모 사건.
    """
    try:
        return demo_db.publish_disclosure(session, req.disclosure, req.stage_key, req.case_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- 민원인 웹 포털 --------------------------------------------------------


@router.get("/complainant/home", summary="민원인 홈")
def complainant_home(session: Session = Depends(get_session)) -> dict[str, Any]:
    return demo_db.complainant_home(session)


@router.get("/complainant/progress", summary="민원인 진행현황 — 사건별 5단계 타임라인 + 처리 기록")
def complainant_progress(
    case: str | None = Query(default=None,
                             description="열려는 사건번호. 없으면 가장 최근 접수 사건."),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """한 민원인이 여러 건을 접수할 수 있으므로 진행현황은 사건 단위로 연다.

    case 를 주면 그 사건의 타임라인(단계별 안내 + 상태 전이 기록)을, 없으면 최근 사건을
    돌려준다. 내 사건이 아니면 404 — 사건번호 추측으로 남의 사건을 열 수 없다.
    """
    try:
        return demo_db.complainant_progress(session, case)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/complainant/mediation", summary="민원인 — 내 민원의 협상·중재 내역")
def complainant_mediation(
    case: str | None = Query(default=None, description="사건번호. 없으면 가장 최근 사건."),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """민원인이 자기 사건의 중재 진행을 본다 — 직원 화면과 같은 사본(쟁점 원장·처리이력)."""
    return {"mediation": demo_db.complainant_mediation(session, case)}


@router.post("/complainant/mediation/request", summary="민원인 — 협상·중재 요청")
def complainant_request_mediation(body: MediationRequestBody,
                                  case: str | None = Query(default=None,
                                                           description="요청할 사건번호. 없으면 최근 사건."),
                                  session: Session = Depends(get_session)) -> dict[str, Any]:
    """민원인이 자기 사건에 협상·중재를 요청한다. 요청 즉시 양쪽 화면에 기록으로 남는다."""
    target = demo_db.citizen_case_or_none(session, case)
    if target is None:
        raise HTTPException(status_code=404, detail="진행 중인 민원이 없습니다.")
    return demo_db.request_mediation(session, target.case_id, requested_by="complainant",
                                     reason=body.reason)


@router.get("/complainant/history", summary="민원인 민원 이력")
def complainant_history(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return demo_db.complainant_history(session)


@router.get("/complainant/me", summary="민원인 프로필/알림/메뉴")
def complainant_me(session: Session = Depends(get_session),
                   identity=Depends(current_identity)) -> dict[str, Any]:
    return demo_db.complainant_profile(session, customer_id_of(identity))


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
