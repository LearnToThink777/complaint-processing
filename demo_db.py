from __future__ import annotations

"""DB 기반 조회/변경 함수 — 예전 demo_store 의 in-scope 더미 함수들을 대체한다.

demo_api.py 의 네 라우트(staff/intake, staff/checklist-plan, complainant/progress,
complainant/complaints)와 신규 승인/생성 라우트가 이 모듈을 부른다. 세션은 라우트가
FastAPI 의존성(get_session)으로 넘겨준다. 백그라운드 검토계획 생성은
agentic_plan.run_plan_generation 이 자기 세션을 따로 연다.

범위 밖 화면(직원 홈/상세/이력, 민원인 홈/이력/마이페이지, 상품유형)은 여전히
demo_store 의 더미를 쓴다 — 여기서는 접수→검토계획→승인 흐름만 실 DB 로 옮긴다.
"""

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import demo_store
from .models import (
    Approval,
    Case,
    CaseMediation,
    CaseMessage,
    ChecklistItemRow,
    ReviewPlan,
    StageEvent,
)
from .schemas import VERDICT_LABELS, DualDisclosure

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
    "verdict_generating": 1,  # 판정 생성 중 — 민원인 화면엔 여전히 '검토 중'
    "verdict": 2,
    "negotiating": 3,
    "closed": 4,
}

# 사건 status → 단계 메시지의 stage_key(=_STEP_TEMPLATE 의 key). 상태머신 어휘(negotiating)와
# 단계 어휘(negotiation)가 달라 정규화가 필요하다. 이중공개 게시 시 기본 단계를 유도하는 데 쓴다.
_STATUS_TO_STAGE: dict[str, str] = {
    "intake": "intake",
    "plan_generating": "intake",
    "plan_ready": "intake",
    "reviewing": "reviewing",
    "verdict_generating": "reviewing",
    "verdict": "verdict",
    "negotiating": "negotiation",
    "closed": "closed",
}

# 접수 목록에 노출할 상태(검토 시작 전 단계들).
_INTAKE_STATUSES = ("intake", "plan_generating", "plan_ready")

# 처리현황 목록에 노출할 상태(검토계획 승인 이후 = 실제 '처리'에 들어간 사건들).
_PROCESSING_STATUSES = ("reviewing", "verdict_generating", "verdict", "negotiating", "closed")

_COMPLETION_DAYS = 40  # 접수 시 예상 완료일 = 접수일 + N일(데모용 단순 규칙)


def _status_ko(status: str) -> str:
    meta = demo_store.CASE_STATUS.get(status)
    return meta["ko"] if meta else status


# ---- 직원: 홈 요약 카드 + 최근 처리 사건 (DB 집계) -------------------------
# 예전엔 demo_store 에 24/7/18/15 같은 숫자가 상수로 박혀 있어서, 사건을 아무리 접수해도
# 홈 화면 숫자가 꿈쩍하지 않았다. 아래는 전부 cases/stage_events 에서 센 실제 값이다.


def _verdict_digest(plan: ReviewPlan | None) -> str:
    """원장의 판정 라벨 분포를 한 줄로. 예: '위반 2 · 해당없음 1'. 판정 전이면 빈 문자열."""
    if plan is None:
        return ""
    tally: dict[str, int] = {}
    for it in plan.items:
        if it.verdict:
            tally[it.verdict] = tally.get(it.verdict, 0) + 1
    return " · ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))


def staff_summary(session: Session) -> dict[str, Any]:
    """직원 홈 요약 카드 — 전부 DB 실측값."""
    rows = session.execute(select(Case)).scalars().all()
    today = date.today()

    open_cases = [c for c in rows if c.status != "closed"]
    due_soon = [c for c in open_cases
                if (d := c.due_date or c.expected_completion) and 0 <= _days_left(d) <= 3]
    # 'AI 검토 대기' = 사람이 다음 행동을 해야 하는 사건: 검토계획 승인 대기 + 판정 생성 전.
    ai_wait = [c for c in rows if c.status in ("plan_ready", "reviewing")]
    closed_today = session.execute(
        select(StageEvent).where(StageEvent.to_status == "closed",
                                 StageEvent.at >= datetime.combine(today, datetime.min.time()))
    ).scalars().all()

    return {
        "officer": "홍길동",
        "team": "준법감시팀",
        "cards": [
            {"key": "todo", "label": "처리 중인 사건", "value": len(open_cases), "unit": "건",
             "hint": f"전체 {len(rows)}건", "tone": "info"},
            {"key": "due_soon", "label": "기한 임박 사건", "value": len(due_soon), "unit": "건",
             "hint": "3일 이내 마감", "tone": "bad"},
            {"key": "ai_wait", "label": "담당자 조치 대기", "value": len(ai_wait), "unit": "건",
             "hint": "검토계획 승인·판정 생성 필요", "tone": "warn"},
            {"key": "done_today", "label": "오늘 종결", "value": len(closed_today), "unit": "건",
             "hint": today.isoformat(), "tone": "good"},
        ],
    }


def staff_recent_cases(session: Session, limit: int = 5) -> list[dict[str, Any]]:
    """최근 손댄 사건 — 처리 단계에 들어간 사건을 갱신 최신순으로."""
    rows = session.execute(
        select(Case).where(Case.status.in_(_PROCESSING_STATUSES))
        .order_by(Case.updated_at.desc(), Case.id.desc()).limit(limit)
    ).scalars().all()
    out = []
    for c in rows:
        meta = demo_store.CASE_STATUS.get(c.status, {})
        out.append({
            "case_id": c.case_id,
            "customer": c.customer or "민원인",
            "type": c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원"),
            # 사람이 내린 '수용/기각' 결정 필드는 아직 없다 — 지어내지 않고 사건 상태를 보여준다.
            "outcome": {"code": c.status, "ko": meta.get("ko", c.status),
                        "tone": meta.get("tone", "muted")},
            "verdict_digest": _verdict_digest(_latest_plan(session, c)),
            "processed_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "",
            "officer": "홍길동",
        })
    return out


# ---- 직원: 고객 이력 (DB 집계) ---------------------------------------------


def staff_customer_history(session: Session, customer: str | None = None) -> dict[str, Any] | None:
    """고객 1명의 과거 민원 이력 + 반복 접수 패턴. 전부 DB 실측(예전엔 하드코딩 6행)."""
    names = session.execute(select(Case.customer).where(Case.customer != "")).scalars().all()
    if not names:
        return None
    if customer not in set(names):
        # 지정이 없거나 없는 고객이면 가장 많이 접수한 고객을 기본으로 보여준다.
        customer = max(set(names), key=names.count)

    rows = session.execute(
        select(Case).where(Case.customer == customer)
        .order_by(Case.intake_date.desc(), Case.id.desc())
    ).scalars().all()

    types = [c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원") for c in rows]
    top = max(set(types), key=types.count) if types else ""
    count = types.count(top) if top else 0
    pattern = (
        {"type": top, "count": count,
         "message": f"동일 유형({top}) 민원이 총 {count}회 접수되었습니다."}
        if count >= 2 else None
    )

    return {
        "customer": customer,
        "customer_no": "",  # 데모에는 고객번호 체계가 없다 — 없는 값을 지어내지 않는다.
        "repeat_pattern": pattern,
        "rows": [{
            "case_id": c.case_id,
            "intake_date": c.intake_date,
            "type": c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원"),
            "outcome": {"code": c.status, "ko": _status_ko(c.status),
                        "tone": demo_store.CASE_STATUS.get(c.status, {}).get("tone", "muted")},
            "result": _verdict_digest(_latest_plan(session, c)) or "-",
            "repeat": None,
        } for c in rows],
    }


def staff_profile(session: Session) -> dict[str, Any]:
    """직원 마이페이지 — 계정/알림 설정은 정적(로그인 기능 없음), 활동로그는 실제 처리 이력."""
    events = session.execute(
        select(StageEvent, Case.case_id).join(Case, Case.id == StageEvent.case_fk)
        .where(StageEvent.actor == "staff").order_by(StageEvent.id.desc()).limit(8)
    ).all()
    profile = dict(demo_store.staff_profile())
    profile["activity_log"] = [{
        "at": ev.at.strftime("%Y-%m-%d %H:%M") if ev.at else "",
        "action": ev.note or f"{ev.from_status} → {ev.to_status}",
        "detail": cid,
        "ip": "",
    } for ev, cid in events]
    return profile


# ---- 민원인: 홈 / 이력 (DB 집계) -------------------------------------------


def complainant_home(session: Session) -> dict[str, Any]:
    """민원인 홈 — 진행 중인 내 민원 + 최근 안내(진행현황에 게시된 실제 메시지)."""
    case = _latest_citizen_case(session)
    if case is None:
        return {"greeting_name": "김지은", "current_case": None, "notices": []}

    notices = session.execute(
        select(CaseMessage)
        .where(CaseMessage.case_fk == case.id, CaseMessage.audience == "complainant")
        .order_by(CaseMessage.at.desc(), CaseMessage.id.desc()).limit(3)
    ).scalars().all()

    return {
        "greeting_name": case.customer or "고객",
        "current_case": {
            "case_id": case.case_id,
            "title": case.complaint_type or f"{_PRODUCT_LABEL.get(case.product_type, '')} 관련 민원".strip(),
            "status": case.status,
            "status_ko": _status_ko(case.status),
            "intake_date": case.intake_date,
            "expected_completion": case.expected_completion,
            "days_left": _days_left(case.expected_completion),
            "risk": _days_left(case.expected_completion) <= 7,
        },
        "notices": [{
            "icon": "document" if m.sender == "담당자" else "megaphone",
            "title": m.title or f"{m.sender} 안내",
            "body": m.body,
            "at": m.at.strftime("%Y-%m-%d %H:%M") if m.at else "",
        } for m in notices],
    }


def complainant_history(session: Session) -> list[dict[str, Any]]:
    """민원인 이력 — 이 사람이 접수한 민원 전부(최신순). 예전엔 하드코딩 4건."""
    case = _latest_citizen_case(session)
    who = case.customer if case else ""
    rows = session.execute(
        select(Case).where(Case.channel == "citizen", Case.customer == who)
        .order_by(Case.intake_date.desc(), Case.id.desc())
    ).scalars().all()
    out = []
    for c in rows:
        closed_at = None
        if c.status == "closed":
            at = session.execute(
                select(StageEvent.at).where(StageEvent.case_fk == c.id, StageEvent.to_status == "closed")
                .order_by(StageEvent.id.desc())
            ).scalars().first()
            closed_at = at.date().isoformat() if at else None
        out.append({
            "case_id": c.case_id,
            "type": c.complaint_type or f"{_PRODUCT_LABEL.get(c.product_type, '')} 관련 민원".strip(),
            "intake_date": c.intake_date,
            "status": c.status,
            "status_ko": _status_ko(c.status),
            "closed_at": closed_at,
            "expected_completion": c.expected_completion,
        })
    return out


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


def get_case_or_none(session: Session, case_id: str) -> Case | None:
    """사건 1건 조회(공개 헬퍼) — 라우트가 사건 필드(facts/product_en 등)에 직접 접근할 때."""
    return _get_case(session, case_id)


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
    if case.status == "plan_generating":
        return None  # 이미 진행 중 — 중복 트리거하지 않는다.
    # 그 외 상태는 모두 재생성을 허용한다. 검토 항목이 0개로 굳어 판정이 생성되지 않은
    # 사건(옛 생성 로직의 결과)을 처리현황에서 되살리려면 이 경로가 열려 있어야 한다.
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


# ---- 직원: 처리현황(사건 목록 + 사건 원장/판정 + 유사사례) ------------------
# 예전엔 demo_store.STAFF_CASE_DETAILS(단일 하드코딩 사건)를 봤다. 이제 검토계획을
# 승인해 '처리'에 들어간 실제 사건들을 DB 에서 목록으로 주고, 각 사건의 원장(판정 결과)을
# checklist_items 에 영속된 verdict 컬럼에서 조립한다. 유사사례는 case_ai 가 사건별로 실검색.


def staff_cases(session: Session) -> list[dict[str, Any]]:
    """처리 단계(검토계획 승인 이후)에 들어간 사건 목록. 최신순. 직원이 골라 원장을 본다."""
    rows = session.execute(
        select(Case).where(Case.status.in_(_PROCESSING_STATUSES))
        .order_by(Case.updated_at.desc(), Case.id.desc())
    ).scalars().all()
    out = []
    for c in rows:
        label = c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원")
        out.append({
            "case_id": c.case_id,
            "customer": c.customer or "민원인",
            "type": label,
            "track": c.track,
            "status": c.status,
            "status_ko": _status_ko(c.status),
            "intake_date": c.intake_date,
            "has_verdict": c.status in ("verdict", "negotiating", "closed"),
        })
    return out


def _verdict_status(case: Case, plan: ReviewPlan | None) -> str:
    """처리현황 원장의 판정 진행 상태 — none(생성 전)/generating(생성 중)/ready(완료)."""
    if case.status == "verdict_generating":
        return "generating"
    if case.status in ("verdict", "negotiating", "closed"):
        return "ready"
    return "none"


def _ledger_from_plan(plan: ReviewPlan | None) -> list[dict[str, Any]]:
    """승인된 검토계획의 항목 → 처리현황 원장 행(항목/근거/판정/신뢰도 배지/수정 이력).

    seq 를 함께 실어 보낸다 — 직원이 특정 행의 판정을 고칠 때 이 번호로 지목한다.
    """
    if plan is None:
        return []
    rows = []
    for i, it in enumerate(plan.items, start=1):
        ai = it.ai_original or {}
        # AI 원안과 지금 값이 다른가 = 담당자가 손댄 행인가.
        edited = it.verdict_source == "staff"
        rows.append({
            "seq": it.seq or i,
            "item": it.item,
            "law": it.law,
            "source": it.source,  # 'baseline' 이면 검색 근거 없이 공통 판매원칙으로 세운 항목
            "code": it.verdict_code or it.law,
            "verdict": it.verdict or "—",
            "ko": it.verdict_ko,
            "detail": it.verdict_detail,
            "critic": it.critic,
            "critic_meta": demo_store.CRITIC_BADGES.get(it.critic, {}),
            "verdict_source": it.verdict_source or "ai",
            "edited": edited,
            # 수정된 행에서만 원안을 함께 준다(화면이 'AI 원안 → 담당자 확정'을 대조 표시).
            "ai_original": ai if edited else None,
            "override_reason": it.override_reason,
            "overridden_by": it.overridden_by,
            "overridden_at": it.overridden_at.isoformat() if it.overridden_at else None,
        })
    return rows


def _find_item(session: Session, case_id: str, seq: int) -> ChecklistItemRow:
    """사건의 최신 검토계획에서 seq 번 항목을 찾는다. 없으면 LookupError(라우트가 404)."""
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    plan = _latest_plan(session, case)
    if plan is None:
        raise LookupError("검토계획이 없습니다.")
    for i, it in enumerate(plan.items, start=1):
        if (it.seq or i) == seq:
            return it
    raise LookupError(f"검토 항목 #{seq} 을(를) 찾을 수 없습니다.")


def override_verdict(session: Session, case_id: str, seq: int, *, verdict: str, ko: str,
                     detail: str, reason: str, code: str | None = None,
                     staff: str = "홍길동") -> dict[str, Any]:
    """직원이 AI 판정을 직접 고쳐 확정한다. AI 원안은 ai_original 에 보존한다.

    AI 판정은 제안이고 확정은 사람이 한다는 것이 이 시스템의 전제인데, 그동안 화면에서
    고칠 방법이 없어 AI 가 틀려도 그대로 남았다. 여기서 그 통로를 연다.
    바뀐 행은 verdict_source='staff' + critic='CONFIRMED'(AI 신뢰도 검증 대상 아님)가 된다.
    """
    item = _find_item(session, case_id, seq)
    if not reason.strip():
        raise ValueError("판정을 수정하려면 사유를 입력해야 합니다.")
    if not item.ai_original:
        # 최초 수정이면 지금 값(=AI 원안)을 스냅샷으로 남긴다.
        item.ai_original = {"verdict": item.verdict, "code": item.verdict_code,
                            "ko": item.verdict_ko, "detail": item.verdict_detail,
                            "critic": item.critic}
    item.verdict = verdict
    item.verdict_ko = ko
    item.verdict_detail = detail
    if code:
        item.verdict_code = code
    item.critic = "CONFIRMED"
    item.verdict_source = "staff"
    item.override_reason = reason.strip()
    item.overridden_by = staff
    item.overridden_at = datetime.utcnow()

    case = _get_case(session, case_id)
    if case is not None:
        session.add(StageEvent(
            case_fk=case.id, from_status=case.status, to_status=case.status, actor="staff",
            note=f"검토 항목 #{seq} 판정 담당자 수정: "
                 f"{(item.ai_original or {}).get('verdict', '—')} → {verdict} · 사유: {reason.strip()}",
        ))
    session.commit()
    return staff_case_detail(session, case_id) or {}


def revert_verdict(session: Session, case_id: str, seq: int, staff: str = "홍길동") -> dict[str, Any]:
    """담당자 수정을 되돌려 AI 원안으로 복구한다."""
    item = _find_item(session, case_id, seq)
    ai = item.ai_original or {}
    if item.verdict_source != "staff" or not ai:
        raise ValueError("되돌릴 담당자 수정 이력이 없습니다.")
    item.verdict = ai.get("verdict", "")
    item.verdict_code = ai.get("code", "")
    item.verdict_ko = ai.get("ko", "")
    item.verdict_detail = ai.get("detail", "")
    item.critic = ai.get("critic", "")
    item.verdict_source = "ai"
    item.override_reason = ""
    item.overridden_by = ""
    item.overridden_at = None

    case = _get_case(session, case_id)
    if case is not None:
        session.add(StageEvent(
            case_fk=case.id, from_status=case.status, to_status=case.status, actor="staff",
            note=f"검토 항목 #{seq} 판정을 AI 원안으로 되돌림({staff})",
        ))
    session.commit()
    return staff_case_detail(session, case_id) or {}


def staff_case_detail(session: Session, case_id: str) -> dict[str, Any] | None:
    """처리현황 사건 상세 — 접수 내용(SSOT) + 원장(판정 결과) + 판정 진행 상태.

    유사사례는 여기 넣지 않는다(case_ai 가 실검색하는 별도 엔드포인트) — 응답을 가볍게 유지.
    """
    case = _get_case(session, case_id)
    if case is None:
        return None
    plan = _latest_plan(session, case)
    ledger = _ledger_from_plan(plan)
    counts = {"PASS": 0, "ESCALATE": 0, "BLOCK": 0, "CONFIRMED": 0}
    for row in ledger:
        if row["critic"] in counts:
            counts[row["critic"]] += 1

    due = case.due_date or case.expected_completion
    days_left = _days_left(due)
    return {
        "case_id": case.case_id,
        "type": case.complaint_type or _PRODUCT_LABEL.get(case.product_type, "민원"),
        "customer": case.customer or "민원인",
        "channel": case.channel,
        "status": case.status,
        "status_ko": _status_ko(case.status),
        "track": case.track,
        # 접수 내용(SSOT) — 직원이 '무엇이 접수됐는지'를 원문으로 확인한다.
        "facts": case.facts,
        "product_type": case.product_type,
        "product_en": case.product_en,
        "attachments": case.attachments or [],
        "keywords": case.keywords or {},
        "intake_date": case.intake_date,
        "due_date": due,
        "days_left": days_left,
        "over_deadline_risk": bool(due) and days_left <= 7,
        # 원장(판정 결과) — verdict_status 로 UI 가 생성 버튼/스피너/원장을 분기한다.
        "verdict_status": _verdict_status(case, plan),
        "classification": plan.classification if plan else (case.complaint_type or ""),
        "reasoning": plan.reasoning if plan else "",
        "ledger": ledger,
        "critic_summary": {"reviewed": len(ledger), **counts},
        # 직원이 판정을 고칠 때 고를 수 있는 라벨(schemas.Verdict 와 항상 일치).
        "verdict_options": list(VERDICT_LABELS),
        # 협상·중재 진행(요청/개시/쟁점 원장). 없으면 None — 화면이 '요청 없음'으로 그린다.
        "mediation": mediation_payload(session, case),
    }


def start_verdict_generation(session: Session, case_id: str) -> str | None:
    """직원이 '판정 생성'을 누르면 호출 — 사건을 verdict_generating 으로 잡고 case_id 반환.

    승인된 검토계획이 있고(reviewing/verdict 상태) 아직 생성 중이 아닐 때만 예약한다.
    실제 LLM 판정은 라우트가 BackgroundTasks 로 case_ai.run_verdict_generation 을 예약해 수행.
    이미 생성 중이면 None(중복 트리거 방지).
    """
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    if case.status == "verdict_generating":
        return None  # 이미 진행 중
    if case.status not in ("reviewing", "verdict"):
        # 검토계획 승인(=reviewing) 전에는 판정할 원장이 없다. verdict 는 재생성 허용.
        raise ValueError("검토계획 승인 후에 판정을 생성할 수 있습니다.")
    prev = case.status
    case.status = "verdict_generating"
    session.add(StageEvent(case_fk=case.id, from_status=prev, to_status="verdict_generating",
                           actor="staff", note="AI 규정 판정 생성 요청"))
    session.commit()
    return case.case_id


# ---- 협상·중재: 요청 → 개시 → 턴 진행(사건에 붙여 DB 영속) -----------------
# 중재 콘솔(mediation.html)의 라이브 세션은 프로세스 메모리에만 있어서, 어느 민원 사건의
# 중재인지 이어지지 않았고 민원인·직원 화면 어디에도 내역이 보이지 않았다. 여기서 사건에
# 붙이고(CaseMediation) 턴마다 레코드를 스냅샷해, 양쪽 화면이 같은 사본을 읽게 한다.

_MEDIATION_STATUS_KO = {
    "requested": "중재 요청됨",
    "open": "중재 진행 중",
    "closed": "중재 종료",
}

_REQUESTER_KO = {"complainant": "민원인", "staff": "담당자"}


def _subject(word: str) -> str:
    """한국어 주격조사를 받침에 맞춰 붙인다 — '민원인이' / '담당자가'.

    받침 유무는 한글 음절 코드로 판정한다(가~힣 구간에서 (코드-0xAC00) % 28 != 0 이면 받침 있음).
    """
    if not word:
        return word
    last = word[-1]
    if "가" <= last <= "힣":
        return word + ("이" if (ord(last) - 0xAC00) % 28 else "가")
    return word + "이(가)"  # 한글이 아니면 판정 불가 — 양쪽을 병기한다.


def _get_mediation(session: Session, case: Case) -> CaseMediation | None:
    return session.execute(
        select(CaseMediation).where(CaseMediation.case_fk == case.id)
    ).scalar_one_or_none()


def mediation_payload(session: Session, case: Case) -> dict[str, Any] | None:
    """사건의 중재 진행 상태 → 화면이 그대로 렌더할 수 있는 dict. 요청이 없으면 None."""
    med = _get_mediation(session, case)
    if med is None:
        return None
    rec = med.record or {}
    return {
        "case_id": case.case_id,
        "status": med.status,
        "status_ko": _MEDIATION_STATUS_KO.get(med.status, med.status),
        "requested_by": med.requested_by,
        "requested_by_ko": _REQUESTER_KO.get(med.requested_by, med.requested_by),
        # 화면이 '민원인가 요청' 같은 조사 오류를 내지 않도록 주격조사까지 붙여 보낸다.
        "requested_by_subject": _subject(_REQUESTER_KO.get(med.requested_by, med.requested_by)),
        "reason": med.reason,
        "scenario_id": med.scenario_id,
        "sid": med.sid,
        "turn_index": med.turn_index,
        "max_turns": med.max_turns,
        "done": med.status == "closed",
        "requested_at": med.created_at.isoformat() if med.created_at else None,
        "updated_at": med.updated_at.isoformat() if med.updated_at else None,
        # MediationRecord 원본 — 중재 콘솔(mediation.html)이 그대로 렌더한다.
        "record": rec,
        # 앱 화면(직원 처리현황 · 민원인 진행현황)이 바로 쓰는 평면화 뷰.
        "parties": rec.get("parties", []),
        "issues": rec.get("issues", []),
        "log": rec.get("log", []),
        "balance": rec.get("balance", {}),
        "domain": rec.get("domain", ""),
        "boundary": rec.get("boundary", ""),
    }


def request_mediation(session: Session, case_id: str, *, requested_by: str,
                      reason: str) -> dict[str, Any]:
    """민원인 또는 직원이 그 사건에 협상·중재를 요청한다(멱등 — 이미 있으면 사유만 덧붙인다).

    요청 사실은 ① 사건 상태(negotiating) ② 단계 이력(StageEvent) ③ 양쪽 화면에 보이는
    안내 메시지(CaseMessage)로 동시에 남는다 — '요청했는데 아무 데도 안 보인다'를 막는다.
    """
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    who = _REQUESTER_KO.get(requested_by, requested_by)
    med = _get_mediation(session, case)
    if med is None:
        med = CaseMediation(case_fk=case.id, status="requested",
                            requested_by=requested_by, reason=reason.strip())
        session.add(med)
    elif reason.strip():
        med.reason = (f"{med.reason}\n" if med.reason else "") + f"[{who}] {reason.strip()}"

    if case.status not in ("negotiating", "closed"):
        prev = case.status
        case.status = "negotiating"
        session.add(StageEvent(case_fk=case.id, from_status=prev, to_status="negotiating",
                               actor="citizen" if requested_by == "complainant" else "staff",
                               note=f"{who}의 협상·중재 요청"))
    else:
        session.add(StageEvent(case_fk=case.id, from_status=case.status, to_status=case.status,
                               actor="citizen" if requested_by == "complainant" else "staff",
                               note=f"{who}의 협상·중재 요청(추가)"))

    # 민원인 진행현황 '협의' 단계에 보이는 안내 + 직원 화면용 기록.
    session.add(CaseMessage(
        case_fk=case.id, stage_key="negotiation", audience="complainant",
        sender="민원인" if requested_by == "complainant" else "담당자",
        title="협상·중재 요청 접수",
        body=(f"{_subject(who)} 협상·중재를 요청했어요. 중재자가 양측의 주장을 같은 기록으로 정리하고, "
              f"쟁점별로 어느 쪽에 유리·불리한 사실이 있는지 함께 보여드릴게요."
              + (f"\n요청 사유: {reason.strip()}" if reason.strip() else "")),
        seq=_next_seq(session, case, "negotiation", "complainant"),
    ))
    session.add(CaseMessage(
        case_fk=case.id, stage_key="negotiation", audience="staff", sender="시스템",
        title="협상·중재 요청",
        body=f"요청자: {who}. 사유: {reason.strip() or '(미기재)'}",
        seq=_next_seq(session, case, "negotiation", "staff"),
    ))
    session.commit()
    return mediation_payload(session, case) or {}


def save_mediation_session(session: Session, case_id: str, *, sid: str, scenario_id: str,
                           record: dict[str, Any], turn_index: int, max_turns: int,
                           done: bool) -> dict[str, Any]:
    """라이브 세션의 현재 레코드를 사건에 스냅샷한다(개시·턴 진행 후 공통 호출).

    세션 자체는 mediation_live 가 메모리로 들고 있지만, 스냅샷이 DB 에 있으므로 서버가
    재시작돼 세션이 사라져도 지금까지의 중재 내역은 양쪽 화면에 그대로 남는다.
    """
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    med = _get_mediation(session, case)
    if med is None:
        med = CaseMediation(case_fk=case.id, requested_by="staff")
        session.add(med)
    med.sid = sid
    med.scenario_id = scenario_id
    med.record = record
    med.turn_index = turn_index
    med.max_turns = max_turns
    med.status = "closed" if done else "open"
    med.updated_at = datetime.utcnow()
    if case.status not in ("negotiating", "closed"):
        prev = case.status
        case.status = "negotiating"
        session.add(StageEvent(case_fk=case.id, from_status=prev, to_status="negotiating",
                               actor="staff", note="협상·중재 개시"))
    session.commit()
    return mediation_payload(session, case) or {}


def complainant_mediation(session: Session) -> dict[str, Any] | None:
    """민원인 화면용 — 지금 보고 있는 사건의 중재 내역."""
    case = _latest_citizen_case(session)
    if case is None:
        return None
    return mediation_payload(session, case)


def product_label(product_type: str) -> str:
    """상품유형 키 → 화면 라벨(공개 헬퍼). 사건 분류가 아직 없을 때 중재 주제로 쓴다."""
    label = _PRODUCT_LABEL.get(product_type, "")
    return f"{label} 관련 민원" if label else "금융 민원"


def latest_citizen_case(session: Session) -> Case | None:
    """민원인 화면이 보고 있는 사건(공개 헬퍼) — 라우트가 case_id 를 얻을 때."""
    return _latest_citizen_case(session)


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


def _complainant_messages_by_stage(session: Session, case: Case) -> dict[str, list[dict[str, Any]]]:
    """이 사건의 민원인용(audience=complainant) 메시지를 stage_key 로 묶어 돌려준다.

    각 메시지는 진행현황 폴딩 카드가 그대로 렌더할 수 있는 형태({sender/title/body/at}).
    이중공개의 민원인용 본문 + 시드/제출 안내가 여기 함께 모인다.
    """
    rows = session.execute(
        select(CaseMessage)
        .where(CaseMessage.case_fk == case.id, CaseMessage.audience == "complainant")
        .order_by(CaseMessage.seq, CaseMessage.id)
    ).scalars().all()
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for m in rows:
        by_stage.setdefault(m.stage_key, []).append({
            "sender": m.sender,
            "title": m.title,
            "body": m.body,
            "at": m.at.isoformat() if m.at else None,
        })
    return by_stage


def complainant_progress(session: Session) -> dict[str, Any]:
    case = _latest_citizen_case(session)
    if case is None:
        empty_steps = [{**tpl, "date": None, "messages": [], "message_count": 0} for tpl in _STEP_TEMPLATE]
        return {"case_id": None, "title": "진행 중인 민원이 없어요", "intake_date": None,
                "expected_completion": None, "days_left": 0, "risk": False, "current": 0,
                "steps": empty_steps, "mediation": None}

    current = CITIZEN_STEP.get(case.status, 0)
    # 상태 전이 시점을 각 단계 날짜로 표기(승인=reviewing, 판정=verdict, …).
    # 단계 template key → 그 단계로 진입한 status 들(어휘 차이: negotiation↔negotiating).
    _STAGE_ENTRY_STATUSES = {
        "reviewing": ("reviewing",),
        "verdict": ("verdict",),
        "negotiation": ("negotiating",),
        "closed": ("closed",),
    }
    stage_date: dict[str, str] = {}
    for stage_key, statuses in _STAGE_ENTRY_STATUSES.items():
        at = session.execute(
            select(StageEvent.at).where(StageEvent.case_fk == case.id, StageEvent.to_status.in_(statuses))
            .order_by(StageEvent.id.asc())
        ).scalars().first()
        if at is not None:
            stage_date[stage_key] = at.date().isoformat()

    messages_by_stage = _complainant_messages_by_stage(session, case)

    steps = []
    for i, tpl in enumerate(_STEP_TEMPLATE):
        step = dict(tpl)
        if tpl["key"] == "intake":
            step["date"] = case.intake_date
        else:
            step["date"] = stage_date.get(tpl["key"])
        msgs = messages_by_stage.get(tpl["key"], [])
        step["messages"] = msgs
        step["message_count"] = len(msgs)
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
        # 협상·중재 진행(요청·쟁점 원장). 없으면 None — 화면이 '중재 요청' 버튼만 그린다.
        "mediation": mediation_payload(session, case),
    }


# ---- 직원→민원인: 이중공개 게시(청중별 분리 영속) --------------------------


def _next_seq(session: Session, case: Case, stage_key: str, audience: str) -> int:
    """같은 사건·단계·청중에서 다음 정렬 seq(기존 최대 + 1, 없으면 0)."""
    top = session.execute(
        select(CaseMessage.seq)
        .where(CaseMessage.case_fk == case.id, CaseMessage.stage_key == stage_key,
               CaseMessage.audience == audience)
        .order_by(CaseMessage.seq.desc())
    ).scalars().first()
    return (top + 1) if top is not None else 0


def publish_disclosure(session: Session, disclosure: DualDisclosure,
                       stage_key: str | None = None,
                       case_id: str | None = None) -> dict[str, Any]:
    """이중공개를 청중별로 분리 게시한다 — 민원인용은 진행현황, 직원용은 직원 화면으로.

    case_id 를 주면 '그 사건'에 게시한다(처리현황에서 선택한 사건과 진행현황을 잇는다).
    없으면 진행현황이 현재 보여주는 citizen 데모 사건(_latest_citizen_case)이 대상이다.
    stage_key 가 없으면 사건 status 로 단계를 유도한다(기본 판정완료 계열).
    complainant_body → audience=complainant, supervisor_body → audience=staff 로 각각 1건 저장.
    """
    case = _get_case(session, case_id) if case_id else _latest_citizen_case(session)
    if case is None:
        raise LookupError("게시할 민원 사건이 없습니다.")
    stage = stage_key or _STATUS_TO_STAGE.get(case.status, "verdict")

    complainant_msg = CaseMessage(
        case_fk=case.id, stage_key=stage, audience="complainant", sender="담당자",
        title=disclosure.complainant_title, body=disclosure.complainant_body,
        seq=_next_seq(session, case, stage, "complainant"),
    )
    staff_msg = CaseMessage(
        case_fk=case.id, stage_key=stage, audience="staff", sender="담당자",
        title=disclosure.supervisor_title, body=disclosure.supervisor_body,
        seq=_next_seq(session, case, stage, "staff"),
    )
    session.add_all([complainant_msg, staff_msg])
    session.commit()
    return {"case_id": case.case_id, "stage_key": stage}


# ---- 민원인: 신규 민원 제출 -------------------------------------------------


def submit_complaint(session: Session, product_type: str, facts: str,
                     attachments: list[str] | None = None,
                     keywords: dict[str, Any] | None = None) -> dict[str, Any]:
    """민원인이 앱에서 제출한 신규 민원을 접수(DB 저장)하고 검토계획 생성을 예약 상태로 만든다.

    라우트가 반환값의 case_id 로 BackgroundTasks(run_plan_generation)를 예약한다.
    keywords: 접수 전 AI 쟁점 분석(/analyze)에서 민원인이 확인·보정한 검색 키워드. 있으면
    사건에 저장해 두어 검토계획 생성이 재추출 없이 재사용한다(honor user edits + LLM 호출 절감).
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
        keywords=keywords or {},
        attachments=attachments or [],
        status="intake",
        intake_date=today.isoformat(),
        expected_completion=expected,
    )
    session.add(case)
    session.flush()  # id 확보
    case.case_id = f"C-{today.year}-{today.month:02d}-{100 + case.id:03d}"
    session.add(StageEvent(case_fk=case.id, from_status=None, to_status="intake", actor="citizen", note="민원인 앱 제출"))
    # 진행현황 트래커가 접수 직후에도 비지 않도록 접수 안내 메시지 1건을 심는다.
    session.add(CaseMessage(
        case_fk=case.id, stage_key="intake", audience="complainant", sender="시스템",
        title="접수 완료",
        body="민원이 정상적으로 접수되었어요. 담당자가 배정되어 내용을 확인하고 있어요.",
        seq=0,
    ))
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
