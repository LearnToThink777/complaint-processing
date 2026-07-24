from __future__ import annotations

"""DB 기반 조회/변경 함수 — 예전 demo_store 의 in-scope 더미 함수들을 대체한다.

demo_api.py 의 네 라우트(staff/intake, staff/checklist-plan, complainant/progress,
complainant/complaints)와 신규 승인/생성 라우트가 이 모듈을 부른다. 세션은 라우트가
FastAPI 의존성(get_session)으로 넘겨준다. 백그라운드 검토계획 생성은
agentic_plan.run_plan_generation 이 자기 세션을 따로 연다.

범위 밖 화면(직원 홈/상세/이력, 민원인 홈/이력/마이페이지, 상품유형)은 여전히
demo_store 의 더미를 쓴다 — 여기서는 접수→검토계획→승인 흐름만 실 DB 로 옮긴다.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import demo_store
from .models import Approval, Case, ChecklistItemRow, ReviewPlan, StageEvent

# 상품유형(한글 키) → 검색/선례에 쓰는 영문 라벨. 중앙 매핑이 없어 새로 둔다.
PRODUCT_EN: dict[str, str] = {
    "deposit": "deposit",
    "fund": "fund mis-selling",
    "els_dls": "ELS mis-selling",
    "insurance": "insurance claim",
    "loan": "loan",
    "etc": "general",
}

# 상품유형(한글 키) → 화면 라벨. demo_store 의 상품유형 칩에서 파생.
_PRODUCT_LABEL: dict[str, str] = {t["key"]: t["label"] for t in demo_store.COMPLAINANT_PRODUCT_TYPES}

# 사건 status → 민원인 5단계 타임라인의 current 인덱스(0-base).
CITIZEN_STEP: dict[str, int] = {
    "intake": 0,
    "plan_generating": 0,
    "plan_ready": 0,
    "reviewing": 1,
    "verdict": 2,
    "negotiating": 3,
    "closed": 4,
}

# 접수 목록에 노출할 상태(검토 시작 전 단계들).
_INTAKE_STATUSES = ("intake", "plan_generating", "plan_ready")

_COMPLETION_DAYS = 40  # 접수 시 예상 완료일 = 접수일 + N일(데모용 단순 규칙)


def _status_ko(status: str) -> str:
    meta = demo_store.CASE_STATUS.get(status)
    return meta["ko"] if meta else status


# ---- 직원: 사건접수 목록 ----------------------------------------------------


def staff_intake(session: Session) -> list[dict[str, Any]]:
    """검토 시작 전 사건 목록(신규 이관 + 민원인 신규 제출). 최신순."""
    rows = session.execute(
        select(Case).where(Case.status.in_(_INTAKE_STATUSES)).order_by(Case.created_at.desc(), Case.id.desc())
    ).scalars().all()
    out = []
    for c in rows:
        label = c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원")
        out.append({
            "case_id": c.case_id,
            "customer": c.customer or "민원인",
            "type": label,
            "intake_date": c.intake_date,
            "track": c.track,
            "status": c.status,
        })
    return out


# ---- 직원: AI 자동 검토계획 ------------------------------------------------


def _latest_plan(session: Session, case: Case) -> ReviewPlan | None:
    return session.execute(
        select(ReviewPlan).where(ReviewPlan.case_fk == case.id).order_by(ReviewPlan.id.desc())
    ).scalars().first()


def _plan_payload(case: Case, plan: ReviewPlan | None) -> dict[str, Any]:
    if plan is None:
        status = "generating" if case.status == "plan_generating" else "pending"
        return {
            "case_id": case.case_id,
            "classification": case.complaint_type or "",
            "track": case.track,
            "status": status,
            "items": [],
            "reasoning": "",
        }
    return {
        "case_id": case.case_id,
        "classification": plan.classification,
        "track": plan.track,
        "status": plan.status,
        "provider": plan.provider,
        "duration_ms": plan.duration_ms,
        "items": [
            {"item": it.item, "law": it.law, "source": it.source, "status": it.status}
            for it in plan.items
        ],
        "reasoning": plan.reasoning,
    }


def _get_case(session: Session, case_id: str) -> Case | None:
    return session.execute(select(Case).where(Case.case_id == case_id)).scalar_one_or_none()


def staff_checklist_plan(session: Session, case_id: str) -> dict[str, Any] | None:
    case = _get_case(session, case_id)
    if case is None:
        return None
    return _plan_payload(case, _latest_plan(session, case))


def start_generation(session: Session, case_id: str) -> str | None:
    """검토계획 생성을 시작 상태로 만든다(수동 트리거 — 이관/시드 사건용).

    이미 생성 중이거나 승인된 뒤가 아니면 status→plan_generating 로 전이한다.
    실제 LLM 호출은 라우트가 BackgroundTasks 로 run_plan_generation 을 예약해 수행.
    반환: 예약할 case_id(없으면 None).
    """
    case = _get_case(session, case_id)
    if case is None:
        return None
    if case.status not in ("intake", "plan_ready", "reviewing"):
        # plan_generating(이미 진행 중) 등은 중복 트리거하지 않는다.
        if case.status == "plan_generating":
            return None
    prev = case.status
    case.status = "plan_generating"
    session.add(StageEvent(case_fk=case.id, from_status=prev, to_status="plan_generating",
                           actor="staff", note="AI 검토계획 생성 요청"))
    session.commit()
    return case.case_id


def approve_plan(session: Session, case_id: str, approved_by: str = "홍길동") -> dict[str, Any]:
    """직원이 검토계획을 승인 → 항목 체크·계획 승인·사건 status(plan_ready→reviewing) 전이.

    검토계획이 아직 준비(ready)되지 않았으면 ValueError(라우트가 409 로 변환).
    """
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    plan = _latest_plan(session, case)
    if plan is None or plan.status not in ("ready", "approved"):
        raise ValueError("승인할 수 있는 검토계획이 아직 준비되지 않았습니다.")
    if plan.status == "ready":
        plan.status = "approved"
        for it in plan.items:
            it.status = "approved"
        session.add(Approval(plan_fk=plan.id, approved_by=approved_by))
    if case.status in ("plan_ready", "plan_generating", "intake"):
        prev = case.status
        case.status = "reviewing"
        session.add(StageEvent(case_fk=case.id, from_status=prev, to_status="reviewing",
                               actor="staff", note="검토계획 승인 → 검토 착수"))
    session.commit()
    payload = _plan_payload(case, plan)
    payload["case_status"] = case.status
    payload["case_status_ko"] = _status_ko(case.status)
    return payload


# ---- 민원인: 진행현황 5단계 타임라인 ---------------------------------------

# 5단계 본문 문구(예전 COMPLAINANT_PROGRESS 에서 가져옴).
_STEP_TEMPLATE = [
    {"no": 1, "key": "intake", "title": "접수", "body": "민원이 정상적으로 접수되었어요. 담당자가 내용을 확인하고 있어요."},
    {"no": 2, "key": "reviewing", "title": "검토 중", "body": "법률 검토와 사실관계 확인을 진행하고 있어요. 조금만 기다려주세요!"},
    {"no": 3, "key": "verdict", "title": "판정 완료", "body": "검토가 끝나면 판정 결과를 안내드려요."},
    {"no": 4, "key": "negotiation", "title": "협의", "body": "필요 시 금융회사와 협의가 진행돼요."},
    {"no": 5, "key": "closed", "title": "종결", "body": "모든 절차가 완료되면 종결 안내를 드려요."},
]


def _latest_citizen_case(session: Session) -> Case | None:
    case = session.execute(
        select(Case).where(Case.channel == "citizen").order_by(Case.created_at.desc(), Case.id.desc())
    ).scalars().first()
    if case is None:  # 민원인 제출이 아직 없으면 가장 최근 사건이라도 보여준다.
        case = session.execute(select(Case).order_by(Case.created_at.desc(), Case.id.desc())).scalars().first()
    return case


def _days_left(expected: str | None) -> int:
    if not expected:
        return 0
    try:
        return (date.fromisoformat(expected) - date.today()).days
    except ValueError:
        return 0


def complainant_progress(session: Session) -> dict[str, Any]:
    case = _latest_citizen_case(session)
    if case is None:
        return {"case_id": None, "title": "진행 중인 민원이 없어요", "intake_date": None,
                "expected_completion": None, "days_left": 0, "risk": False, "current": 0, "steps": _STEP_TEMPLATE}

    current = CITIZEN_STEP.get(case.status, 0)
    # 승인(=reviewing 진입) 시점을 검토 단계 날짜로 표기.
    approved_at = session.execute(
        select(StageEvent.at).where(StageEvent.case_fk == case.id, StageEvent.to_status == "reviewing")
        .order_by(StageEvent.id.desc())
    ).scalars().first()

    steps = []
    for i, tpl in enumerate(_STEP_TEMPLATE):
        step = dict(tpl)
        if tpl["key"] == "intake":
            step["date"] = case.intake_date
        elif tpl["key"] == "reviewing" and approved_at is not None:
            step["date"] = approved_at.date().isoformat()
        else:
            step["date"] = None
        steps.append(step)

    days_left = _days_left(case.expected_completion)
    title = case.complaint_type or f"{_PRODUCT_LABEL.get(case.product_type, '')} 관련 민원".strip()
    return {
        "case_id": case.case_id,
        "title": title,
        "status": case.status,
        "status_ko": _status_ko(case.status),
        "intake_date": case.intake_date,
        "expected_completion": case.expected_completion,
        "days_left": days_left,
        "risk": days_left <= 7,
        "current": current,
        "steps": steps,
    }


# ---- 민원인: 신규 민원 제출 -------------------------------------------------


def submit_complaint(session: Session, product_type: str, facts: str,
                     attachments: list[str] | None = None) -> dict[str, Any]:
    """민원인이 앱에서 제출한 신규 민원을 접수(DB 저장)하고 검토계획 생성을 예약 상태로 만든다.

    라우트가 반환값의 case_id 로 BackgroundTasks(run_plan_generation)를 예약한다.
    """
    today = date.today()
    expected = (today + timedelta(days=_COMPLETION_DAYS)).isoformat()
    case = Case(
        case_id="",  # flush 후 id 로 생성
        channel="citizen",
        customer="김지은",  # 데모: 로그인 없음 → 고정 페르소나
        product_type=product_type,
        product_en=PRODUCT_EN.get(product_type, "general"),
        complaint_type="",
        track="legal",
        facts=facts,
        attachments=attachments or [],
        status="intake",
        intake_date=today.isoformat(),
        expected_completion=expected,
    )
    session.add(case)
    session.flush()  # id 확보
    case.case_id = f"C-{today.year}-{today.month:02d}-{100 + case.id:03d}"
    session.add(StageEvent(case_fk=case.id, from_status=None, to_status="intake", actor="citizen", note="민원인 앱 제출"))
    # 접수 즉시 검토계획 생성 단계로 전이(실 LLM 호출은 백그라운드).
    case.status = "plan_generating"
    session.add(StageEvent(case_fk=case.id, from_status="intake", to_status="plan_generating",
                           actor="system", note="AI 검토계획 생성 시작"))
    session.commit()
    return {
        "case_id": case.case_id,
        "product_type": product_type,
        "status": case.status,
        "status_ko": _status_ko(case.status),
        "received_at": "방금 전",
    }
