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
    Customer,
    NotificationSetting,
    ReviewPlan,
    Staff,
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

# 종결 처리를 허용하는 상태 — 판정이 나온 뒤부터다. close_case 의 서버 검증과 화면의
# can_close 가 같은 규칙을 봐야 하므로(화면만 막고 API 가 열려 있으면 안 된다) 여기 한 곳에 둔다.
_CLOSEABLE_STATUSES = ("verdict", "negotiating")

_COMPLETION_DAYS = 40  # 접수 시 예상 완료일 = 접수일 + N일(데모용 단순 규칙)

# ---- 처리 기록(stage_events)의 표현 사전 -------------------------------------
# 사건이 '어떻게 처리됐는지'의 단일 진실 원천은 stage_events 다. 그동안 이 테이블은
# 단계 날짜를 뽑는 데만 쓰여서, 화면에는 정적인 카드만 남고 '무슨 일이 있었는지'는
# 어디에도 안 보였다. 아래 사전이 같은 기록을 청중별 어휘로 옮긴다:
#   - 직원   : 원문 그대로(actor·note 포함) — 감사 추적이 목적
#   - 민원인 : 공개해도 되는 전이만, 민원인 말로 — 내부 진행(생성 중 등)은 내보내지 않는다
_ACTOR_KO = {"citizen": "민원인", "staff": "담당자", "system": "시스템"}

_CITIZEN_EVENT: dict[str, dict[str, str]] = {
    "intake": {"title": "민원 접수", "body": "민원이 접수되어 담당자가 배정되었어요."},
    "reviewing": {"title": "검토 착수",
                  "body": "담당자가 검토 계획을 확정하고 사실관계·법률 검토를 시작했어요."},
    "verdict": {"title": "검토 완료",
                "body": "검토가 끝나 결과가 정리되었어요. 자세한 내용은 담당자 안내를 확인해 주세요."},
    "negotiating": {"title": "협의 진행",
                    "body": "검토 결과를 바탕으로 금융회사와 협의가 진행되고 있어요."},
    "closed": {"title": "종결", "body": "모든 절차가 완료되어 민원이 종결되었어요."},
}

# 처리현황 목록의 '다음 조치' 열 — 담당자가 이 사건에서 무엇을 해야 하는지.
# 상태만 보여 주면 "그래서 뭘 하면 되나"가 화면에 없다.
_NEXT_ACTION = {
    "reviewing": "AI 판정 생성",
    "verdict_generating": "판정 생성 대기",
    "verdict": "판정 확정 · 안내문 게시",
    "negotiating": "협상·중재 진행",
    "closed": "완료",
}

# 처리현황 목록에서 정렬 가능한 열. 프론트 테이블 헤더의 sort key 와 1:1.
CASE_SORT_KEYS = ("case_id", "customer", "type", "status", "intake_date",
                  "due_date", "verdict", "updated_at")

# 상태 필터 프리셋(정확한 status 키 대신 쓸 수 있는 묶음).
_STATUS_PRESETS: dict[str, tuple[str, ...]] = {
    "all": _PROCESSING_STATUSES,
    "open": ("reviewing", "verdict_generating", "verdict", "negotiating"),
    "attention": ("reviewing", "verdict"),  # 담당자 조치가 남은 사건
}


def _status_ko(status: str) -> str:
    meta = demo_store.CASE_STATUS.get(status)
    return meta["ko"] if meta else status


# 민원인 화면에 찍히는 상태 라벨. 직원용 상태머신 어휘('AI 검토계획 생성 중',
# '검토계획 승인 대기')는 내부 처리 단계라 민원인에게 그대로 내보내지 않는다 —
# 5단계 트래커와 같은 어휘로 옮겨 '지금 내 민원이 어디까지 왔는지'만 말한다.
_CITIZEN_STATUS_KO = ["접수 완료", "검토 중", "판정 완료", "협의 중", "종결"]


def _citizen_status_ko(status: str) -> str:
    return _CITIZEN_STATUS_KO[CITIZEN_STEP.get(status, 0)]


# ---- 처리 기록: 사건 1건의 '무슨 일이 있었는지' ------------------------------


def _case_stage_events(session: Session, case: Case) -> list[StageEvent]:
    return session.execute(
        select(StageEvent).where(StageEvent.case_fk == case.id).order_by(StageEvent.at, StageEvent.id)
    ).scalars().all()


def case_events(session: Session, case: Case) -> list[dict[str, Any]]:
    """직원용 처리 기록 — 상태 전이 이력 원문(누가·언제·무엇을·왜).

    같은 상태 안에서 일어난 일(판정 수정, 중재 요청 추가 등)도 StageEvent 로 남아 있어
    from==to 인 행이 섞인다. 그 경우는 상태 변화가 아니라 '처리 메모'로 표시한다.
    """
    out = []
    for ev in _case_stage_events(session, case):
        moved = ev.from_status != ev.to_status
        out.append({
            "at": ev.at.isoformat() if ev.at else None,
            "actor": ev.actor,
            "actor_ko": _ACTOR_KO.get(ev.actor, ev.actor),
            "from_status": ev.from_status,
            "from_ko": _status_ko(ev.from_status) if ev.from_status else None,
            "to_status": ev.to_status,
            "to_ko": _status_ko(ev.to_status),
            "kind": "transition" if moved else "note",
            "note": ev.note,
        })
    return out


def _citizen_entries_by_stage(session: Session, case: Case) -> dict[str, list[dict[str, Any]]]:
    """민원인용 처리 기록 — 단계별로 '실제 있었던 일(전이)'과 '받은 안내(메시지)'를 시간순 병합.

    전이는 _CITIZEN_EVENT 에 문장이 정의된 것만 넣는다(내부 생성 단계는 제외). 안내 메시지는
    audience=complainant 만 — 직원·감독기관용 본문은 민원인 기록에 섞이지 않는다.
    """
    by_stage: dict[str, list[dict[str, Any]]] = {}

    seen: set[str] = set()
    for ev in _case_stage_events(session, case):
        copy = _CITIZEN_EVENT.get(ev.to_status)
        # 상태가 바뀌지 않은 행(판정 수정 등 내부 처리)은 민원인 기록에 넣지 않는다.
        if copy is None or ev.from_status == ev.to_status:
            continue
        # 판정을 재생성하면 verdict 로 들어오는 전이가 여러 번 쌓인다 — 민원인 입장에서는
        # 같은 '검토 완료'가 반복될 뿐이므로 단계별로 처음 도달한 시점만 남긴다.
        if ev.to_status in seen:
            continue
        seen.add(ev.to_status)
        stage = _STATUS_TO_STAGE.get(ev.to_status, "intake")
        by_stage.setdefault(stage, []).append({
            "kind": "event",
            "sender": "시스템",
            "title": copy["title"],
            "body": copy["body"],
            "at": ev.at.isoformat() if ev.at else None,
            "_sort": ev.at or datetime.min,
        })

    rows = session.execute(
        select(CaseMessage)
        .where(CaseMessage.case_fk == case.id, CaseMessage.audience == "complainant")
        .order_by(CaseMessage.seq, CaseMessage.id)
    ).scalars().all()
    for m in rows:
        by_stage.setdefault(m.stage_key, []).append({
            "kind": "message",
            "sender": m.sender,
            "title": m.title,
            "body": m.body,
            "at": m.at.isoformat() if m.at else None,
            "_sort": m.at or datetime.min,
        })

    for entries in by_stage.values():
        entries.sort(key=lambda e: e["_sort"])
        for e in entries:
            e.pop("_sort", None)
    return by_stage


def _last_activity_at(session: Session, case: Case) -> str | None:
    """이 사건에서 마지막으로 무언가 일어난 시각(전이/안내 중 최신)."""
    ev = session.execute(
        select(StageEvent.at).where(StageEvent.case_fk == case.id)
        .order_by(StageEvent.at.desc(), StageEvent.id.desc())
    ).scalars().first()
    msg = session.execute(
        select(CaseMessage.at).where(CaseMessage.case_fk == case.id)
        .order_by(CaseMessage.at.desc(), CaseMessage.id.desc())
    ).scalars().first()
    stamps = [t for t in (ev, msg, case.updated_at) if t is not None]
    return max(stamps).isoformat() if stamps else None


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


def _outcome_payload(c: Case) -> dict[str, Any]:
    """사건의 '결과' 배지 — 종결된 사건은 사람이 내린 결정을, 진행 중이면 현재 상태를 보여준다.

    종결 기능이 없던 동안에는 결정 필드가 비어 있어 항상 status 로 대신했다. 이제 종결 시
    outcome(수용/일부수용/기각)이 남으므로, 있으면 그것을 우선한다.
    """
    if c.outcome:
        meta = demo_store.DECISION_OUTCOMES[c.outcome]
        return {"code": c.outcome, "ko": meta["ko"], "tone": meta["tone"]}
    meta = demo_store.CASE_STATUS.get(c.status, {})
    return {"code": c.status, "ko": meta.get("ko", c.status), "tone": meta.get("tone", "muted")}


def staff_recent_cases(session: Session, limit: int = 5) -> list[dict[str, Any]]:
    """최근 손댄 사건 — 처리 단계에 들어간 사건을 갱신 최신순으로."""
    rows = session.execute(
        select(Case).where(Case.status.in_(_PROCESSING_STATUSES))
        .order_by(Case.updated_at.desc(), Case.id.desc()).limit(limit)
    ).scalars().all()
    out = []
    for c in rows:
        out.append({
            "case_id": c.case_id,
            "customer": c.customer or "민원인",
            "type": c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원"),
            "outcome": _outcome_payload(c),
            "verdict_digest": _verdict_digest(_latest_plan(session, c)),
            "processed_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "",
            "officer": "홍길동",
        })
    return out


# ---- 직원: 고객 이력 (DB 집계) ---------------------------------------------


def staff_customer_history(session: Session, customer: str | None = None) -> dict[str, Any] | None:
    """고객 1명(사람 단위)의 접수 이력 — 처리현황(사건 단위)과 역할이 다르다.

    처리현황은 '지금 처리할 사건'을 찾는 작업 큐이고, 여기는 '이 사람이 그동안 무엇을 몇 번
    접수했고 각 사건이 어떻게 끝났는지'를 보는 고객 프로필이다. 한 민원인이 여러 건을
    접수할 수 있으므로 사건 목록 + 요약 통계 + 반복 패턴을 함께 준다. 각 행은 처리현황의
    그 사건으로 건너갈 수 있게 case_id 를 싣는다.

    customer 는 정확한 이름이 아니어도 된다(부분일치 검색). 없으면 접수가 가장 많은 고객.
    """
    names = session.execute(select(Case.customer).where(Case.customer != "")).scalars().all()
    if not names:
        return None
    term = (customer or "").strip()
    if term and term not in set(names):
        # 부분일치로 한 번 더 찾아본다 — '지은'으로도 '김지은'을 찾을 수 있게.
        # 여러 명이 걸리면 접수가 가장 많은 고객을 고른다(검색 의도에 가장 가까운 쪽).
        hits = [n for n in dict.fromkeys(names) if term.lower() in n.lower()]
        term = max(hits, key=names.count) if hits else ""
    if not term:
        # 지정이 없거나 못 찾으면 가장 많이 접수한 고객을 기본으로 보여준다.
        term = max(set(names), key=names.count)
    customer = term

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
    intake_dates = sorted(c.intake_date for c in rows if c.intake_date)

    out_rows = []
    for c in rows:
        med = _get_mediation(session, c)
        events = _case_stage_events(session, c)
        out_rows.append({
            "case_id": c.case_id,
            "intake_date": c.intake_date,
            "type": c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원"),
            "channel": c.channel,
            "status": c.status,
            "outcome": {"code": c.status, "ko": _status_ko(c.status),
                        "tone": demo_store.CASE_STATUS.get(c.status, {}).get("tone", "muted")},
            "result": _verdict_digest(_latest_plan(session, c)) or "-",
            # 처리 기록이 몇 건 쌓였는지 + 마지막으로 움직인 시각. 사건을 열지 않고도
            # '이 사건이 실제로 진행되고 있는지'를 목록에서 알 수 있다.
            "event_count": len(events),
            "last_activity_at": _last_activity_at(session, c),
            "mediation_status_ko": (_MEDIATION_STATUS_KO.get(med.status, med.status)
                                    if med is not None else None),
            "in_progress": c.status not in ("closed",),
            "repeat": None,
        })

    return {
        "customer": customer,
        "customer_no": "",  # 데모에는 고객번호 체계가 없다 — 없는 값을 지어내지 않는다.
        "repeat_pattern": pattern,
        "summary": {
            "total": len(rows),
            "open": sum(1 for c in rows if c.status != "closed"),
            "closed": sum(1 for c in rows if c.status == "closed"),
            "first_intake": intake_dates[0] if intake_dates else None,
            "last_intake": intake_dates[-1] if intake_dates else None,
            "types": len(set(types)),
        },
        # 검색창 자동완성용 — 접수 건수 많은 순 고객 이름(데모 규모라 전량).
        "candidates": [
            {"customer": n, "count": names.count(n)}
            for n in sorted(dict.fromkeys(names), key=lambda n: -names.count(n))
        ],
        "rows": out_rows,
    }


# ---- 계정 · 알림 설정 -------------------------------------------------------
# '현재 사용자'는 로그인한 사람(auth/deps.current_identity 가 라우트에서 해결해 넘긴다)이고,
# 토큰이 없으면 시드 계정으로 폴백한다 — 인증을 신원 판별용으로만 쓰고 라우트를 막지 않기
# 때문에, 비로그인 데모 요청도 계속 동작해야 한다.


def current_staff(session: Session, staff_id: str | None = None) -> Staff | None:
    if staff_id:
        found = session.execute(select(Staff).where(Staff.staff_id == staff_id)).scalars().first()
        if found is not None:
            return found
    return session.execute(select(Staff).order_by(Staff.staff_id)).scalars().first()


def _actor_id(session: Session, actor: str, staff_id: str | None = None) -> str | None:
    """StageEvent 에 함께 넣을 사람 id — actor 종류에 따라 참조 대상이 갈린다(다형성).

    actor="system" 은 행위자가 사람이 아니므로 None 이다(빈 값이 아니라 '해당 없음').
    staff_id 는 로그인한 담당자 — 넘어오면 그 사람으로 귀속되고, 없으면 시드 계정이 된다.
    """
    if actor == "staff":
        me = current_staff(session, staff_id)
        return me.staff_id if me is not None else None
    if actor == "citizen":
        who = current_customer(session)
        return who.customer_id if who is not None else None
    return None


def current_customer(session: Session, customer_id: str | None = None) -> Customer | None:
    if customer_id:
        found = session.execute(
            select(Customer).where(Customer.customer_id == customer_id)).scalars().first()
        if found is not None:
            return found
    return session.execute(select(Customer).order_by(Customer.customer_id)).scalars().first()


def notification_settings(session: Session, owner_type: str, owner_id: str) -> list[dict[str, Any]]:
    """알림 목록 — 라벨·설명은 demo_store(표현 어휘), 켜짐 여부는 DB(상태).

    그동안 리터럴만 있어서 화면에서 토글해도 저장되지 않았다. 상태만 DB 로 옮기고
    표현은 그대로 둔다 — 라벨을 DB 에 복제하면 문구를 고칠 때 두 곳을 고쳐야 한다.
    """
    defaults = (demo_store.staff_profile() if owner_type == "staff"
                else demo_store.complainant_profile())["notifications"]
    saved = {k: bool(e) for k, e in session.execute(
        select(NotificationSetting.notif_key, NotificationSetting.enabled)
        .where(NotificationSetting.owner_type == owner_type, NotificationSetting.owner_id == owner_id)
    ).all()}
    return [{**n, "enabled": saved.get(n["key"], n["enabled"])} for n in defaults]


def set_notification_setting(session: Session, owner_type: str, owner_id: str,
                             notif_key: str, enabled: bool) -> list[dict[str, Any]]:
    """알림 하나를 켜거나 끈다. 없으면 만들고 있으면 갱신(upsert)."""
    row = session.execute(
        select(NotificationSetting).where(
            NotificationSetting.owner_type == owner_type,
            NotificationSetting.owner_id == owner_id,
            NotificationSetting.notif_key == notif_key)
    ).scalars().first()
    if row is None:
        session.add(NotificationSetting(owner_type=owner_type, owner_id=owner_id,
                                        notif_key=notif_key, enabled=enabled))
    else:
        row.enabled = enabled
    session.commit()
    return notification_settings(session, owner_type, owner_id)


def staff_profile(session: Session, staff_id: str | None = None) -> dict[str, Any]:
    """직원 마이페이지 — 계정은 staff 테이블, 알림은 DB, 활동로그는 실제 처리 이력."""
    me = current_staff(session, staff_id)
    # 활동 로그는 '내가' 한 처리만 보여야 한다. 예전엔 actor=='staff' 로만 걸러서, 직원이
    # 2명 이상이면 서로의 활동을 자기 것으로 표시하게 되어 있었다. 이제 actor_id 로 사람을
    # 지목한다(계정 도입 전 기록은 db.link_demo_identities 가 홍길동으로 귀속시켜 둔다 —
    # 그 시절 직원은 실제로 한 명이었다). 계정이 없으면 옛 방식으로 되돌아간다.
    cond = (StageEvent.actor_id == me.staff_id) if me is not None else (StageEvent.actor == "staff")
    events = session.execute(
        select(StageEvent, Case.case_id).join(Case, Case.id == StageEvent.case_fk)
        .where(cond).order_by(StageEvent.id.desc()).limit(8)
    ).all()

    profile = dict(demo_store.staff_profile())
    if me is not None:
        profile["account"] = {**profile["account"], "name": me.name, "team": me.dept,
                              "rank": me.rank, "email": me.email, "phone": me.phone}
        profile["notifications"] = notification_settings(session, "staff", me.staff_id)
        # 로그인이 없으니 IP 는 여전히 지어내지 않는다. 최종 로그인은 계정 컬럼에서 온다.
        profile["session"] = {"current_ip": "",
                              "last_login": me.last_login_at.strftime("%Y-%m-%d %H:%M") if me.last_login_at else ""}
    profile["activity_log"] = [{
        "at": ev.at.strftime("%Y-%m-%d %H:%M") if ev.at else "",
        "action": ev.note or f"{ev.from_status} → {ev.to_status}",
        "detail": cid,
        "ip": "",
    } for ev, cid in events]
    return profile


def complainant_profile(session: Session, customer_id: str | None = None) -> dict[str, Any]:
    """민원인 마이페이지 — 계정은 customers 테이블, 알림은 DB. 메뉴는 정적."""
    profile = dict(demo_store.complainant_profile())
    me = current_customer(session, customer_id)
    if me is not None:
        profile.update({"name": me.name, "email": me.email, "verified": me.verified})
        profile["notifications"] = notification_settings(session, "customer", me.customer_id)
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
            "status_ko": _citizen_status_ko(case.status),
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


def _citizen_cases(session: Session) -> list[Case]:
    """민원인 화면이 볼 수 있는 사건 전부(최신 접수순).

    한 민원인이 여러 건을 접수할 수 있으므로 화면(이력·진행현황)은 언제나 목록을 전제로 한다.
    """
    case = _latest_citizen_case(session)
    if case is None:
        return []
    return session.execute(
        select(Case).where(Case.channel == "citizen", Case.customer == case.customer)
        .order_by(Case.intake_date.desc(), Case.id.desc())
    ).scalars().all()


def complainant_history(session: Session) -> list[dict[str, Any]]:
    """민원인 이력 — 내가 접수한 민원 전부(최신순) + 사건별 진행 요약.

    예전에는 '유형·접수일·상태'만 있는 정적 카드였다. 민원 하나하나가 어떻게 처리됐는지는
    어디에도 없었다(진행현황은 가장 최근 사건 하나만 보여줬다). 이제 각 행이 그 사건의
    진행 단계·기록 건수·마지막 움직임을 함께 실어, 카드를 눌러 그 사건의 처리 기록으로
    들어갈 수 있게 한다(진행현황?case=…).
    """
    out = []
    for c in _citizen_cases(session):
        closed_at = None
        if c.status == "closed":
            at = session.execute(
                select(StageEvent.at).where(StageEvent.case_fk == c.id, StageEvent.to_status == "closed")
                .order_by(StageEvent.id.desc())
            ).scalars().first()
            closed_at = at.date().isoformat() if at else None
        entries = _citizen_entries_by_stage(session, c)
        entry_count = sum(len(v) for v in entries.values())
        step = CITIZEN_STEP.get(c.status, 0)
        med = _get_mediation(session, c)
        out.append({
            "case_id": c.case_id,
            "type": c.complaint_type or f"{_PRODUCT_LABEL.get(c.product_type, '')} 관련 민원".strip(),
            "intake_date": c.intake_date,
            "status": c.status,
            "status_ko": _citizen_status_ko(c.status),
            "closed_at": closed_at,
            "expected_completion": c.expected_completion,
            "days_left": _days_left(c.expected_completion),
            # 5단계 중 몇 번째까지 왔는지 — 카드에 미니 단계 표시를 그린다.
            "step": step,
            "step_total": len(_STEP_TEMPLATE),
            "step_title": _STEP_TEMPLATE[step]["title"],
            "entry_count": entry_count,
            "last_activity_at": _last_activity_at(session, c),
            "mediation_status_ko": (_MEDIATION_STATUS_KO.get(med.status, med.status)
                                    if med is not None else None),
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


def start_generation(session: Session, case_id: str, staff_id: str | None = None) -> str | None:
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
                           actor="staff", actor_id=_actor_id(session, "staff", staff_id), note="AI 검토계획 생성 요청"))
    session.commit()
    return case.case_id


def approve_plan(session: Session, case_id: str, approved_by: str = "홍길동",
                 staff_id: str | None = None) -> dict[str, Any]:
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
                               actor="staff", actor_id=_actor_id(session, "staff", staff_id), note="검토계획 승인 → 검토 착수"))
    session.commit()
    payload = _plan_payload(case, plan)
    payload["case_status"] = case.status
    payload["case_status_ko"] = _status_ko(case.status)
    return payload


# ---- 직원: 사건 종결 --------------------------------------------------------
# 그동안 'closed' 는 상태 라벨(demo_store.CASE_STATUS)·필터·집계·closed_at 파생에만
# 등장하고 실제로 그 상태로 보내는 코드가 없었다 — 사건이 종결에 도달할 수 없었다.


def _remaining_verdicts(plan: ReviewPlan | None) -> int:
    """판정이 아직 안 난 항목 수 — 계획을 이미 들고 있는 호출부(_case_row)용."""
    return sum(1 for it in plan.items if not it.verdict) if plan else 0


def remaining_count(session: Session, case: Case) -> int:
    """판정이 아직 안 난 검토 항목 수.

    status 가 아니라 verdict 로 센다 — approve_plan 이 계획 승인 시 모든 항목을 일괄
    'approved' 로 바꾸므로(항목별 판정 여부와 무관) status 로는 셀 수 없다. verdict 는
    기본값이 빈 문자열이고 case_ai 의 판정 생성에서 채워진다.
    """
    return _remaining_verdicts(_latest_plan(session, case))


def close_case(session: Session, case_id: str, outcome: str, note: str = "",
               staff_id: str | None = None) -> dict[str, Any]:
    """사건 종결 — status='closed' + 사람이 내린 결정(outcome) 기록 + 단계 이벤트.

    종결 시각은 컬럼으로 두지 않는다. 여기서 남기는 StageEvent(to_status="closed") 가
    유일한 출처이고 complainant_history 가 거기서 closed_at 을 파생한다.
    """
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    if outcome not in demo_store.DECISION_OUTCOMES:
        raise ValueError(f"알 수 없는 종결 결과입니다: {outcome}")
    if case.status == "closed":
        raise ValueError("이미 종결된 사건입니다.")
    if case.status not in _CLOSEABLE_STATUSES:
        raise ValueError(f"'{_status_ko(case.status)}' 단계에서는 종결할 수 없습니다. 판정이 나온 뒤에 종결하세요.")
    left = remaining_count(session, case)
    if left:
        raise ValueError(f"아직 판정이 나지 않은 검토 항목이 {left}건 있습니다. 판정을 마친 뒤 종결할 수 있습니다.")
    prev = case.status
    case.status = "closed"
    case.outcome = outcome
    session.add(StageEvent(
        case_fk=case.id, from_status=prev, to_status="closed", actor="staff", actor_id=_actor_id(session, "staff", staff_id),
        note=note or f"종결 처리({demo_store.DECISION_OUTCOMES[outcome]['ko']})",
    ))
    session.commit()
    return staff_case_detail(session, case_id)


# ---- 직원: 처리현황(사건 목록 + 사건 원장/판정 + 유사사례) ------------------
# 예전엔 demo_store.STAFF_CASE_DETAILS(단일 하드코딩 사건)를 봤다. 이제 검토계획을
# 승인해 '처리'에 들어간 실제 사건들을 DB 에서 목록으로 주고, 각 사건의 원장(판정 결과)을
# checklist_items 에 영속된 verdict 컬럼에서 조립한다. 유사사례는 case_ai 가 사건별로 실검색.


def _case_row(session: Session, c: Case) -> dict[str, Any]:
    """처리현황 목록 한 행 — 직원이 '고를지 말지'를 목록에서 판단할 수 있을 만큼 담는다."""
    plan = _latest_plan(session, c)
    due = c.due_date or c.expected_completion
    days_left = _days_left(due)
    med = _get_mediation(session, c)
    return {
        "case_id": c.case_id,
        "customer": c.customer or "민원인",
        "type": c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원"),
        "track": c.track,
        "channel": c.channel,
        "status": c.status,
        "status_ko": _status_ko(c.status),
        "status_tone": demo_store.CASE_STATUS.get(c.status, {}).get("tone", "muted"),
        "intake_date": c.intake_date,
        "due_date": due,
        "days_left": days_left if due else None,
        "over_deadline_risk": bool(due) and days_left <= 7 and c.status != "closed",
        "verdict_status": _verdict_status(c, plan),
        "verdict_digest": _verdict_digest(plan),
        "item_count": len(plan.items) if plan else 0,
        "has_verdict": c.status in ("verdict", "negotiating", "closed"),
        # 종결 결과(있으면) + 종결 가능 여부 — close_case 의 게이트와 같은 규칙을 화면이
        # 미리 보여줄 수 있도록 함께 싣는다(눌러서 409 를 받게 하지 않는다).
        "outcome": _outcome_payload(c),
        "remaining_verdicts": _remaining_verdicts(plan),
        "can_close": c.status in _CLOSEABLE_STATUSES and _remaining_verdicts(plan) == 0,
        "next_action": _NEXT_ACTION.get(c.status, "-"),
        "mediation_status": med.status if med is not None else "none",
        "mediation_status_ko": (_MEDIATION_STATUS_KO.get(med.status, med.status)
                               if med is not None else None),
        "last_activity_at": _last_activity_at(session, c),
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def staff_cases(session: Session, *, q: str | None = None, status: str | None = None,
                due_soon: bool = False, sort: str = "updated_at",
                order: str = "desc") -> dict[str, Any]:
    """처리 단계 사건 목록 — 조건 검색 + 열 기준 정렬.

    예전엔 처리 단계 사건을 조건 없이 전부 실어 보냈다(목록이 길어지면 담당자가 사건을
    찾을 방법이 없었다). 이제 필터·정렬을 서버가 책임진다:
      q        : 사건번호·고객명·유형 부분일치(대소문자 무시)
      status   : 정확한 status 키, 콤마 구분 다중, 또는 프리셋(all/open/attention)
      due_soon : 기한 7일 이내(또는 초과)만
      sort     : CASE_SORT_KEYS 중 하나 / order: asc|desc
    반환은 목록만이 아니라 {rows, total, facets, …} — facets 는 상태 필터 칩에 붙는 건수로,
    상태 조건만 뺀 나머지 조건을 적용해 센다(칩을 눌렀을 때 나올 건수와 같게).
    """
    statuses = _STATUS_PRESETS.get((status or "all").strip())
    if statuses is None:
        picked = tuple(s.strip() for s in (status or "").split(",") if s.strip())
        statuses = tuple(s for s in picked if s in _PROCESSING_STATUSES) or _PROCESSING_STATUSES

    stmt = select(Case).where(Case.status.in_(_PROCESSING_STATUSES))
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            Case.case_id.ilike(like) | Case.customer.ilike(like) | Case.complaint_type.ilike(like)
        )
    candidates = session.execute(stmt).scalars().all()

    # 파생 열(유형 라벨·기한·판정 진행)은 DB 컬럼이 아니라 조립된 값이다 — 정렬·기한 필터를
    # 행을 만든 뒤 파이썬에서 처리해, 어떤 열로 정렬해도 같은 값을 기준으로 삼게 한다.
    rows = [_case_row(session, c) for c in candidates]

    facets = {"all": len(rows)}
    for key in _PROCESSING_STATUSES:
        facets[key] = sum(1 for r in rows if r["status"] == key)
    facets["open"] = sum(1 for r in rows if r["status"] in _STATUS_PRESETS["open"])
    facets["attention"] = sum(1 for r in rows if r["status"] in _STATUS_PRESETS["attention"])
    facets["due_soon"] = sum(1 for r in rows if r["over_deadline_risk"])

    rows = [r for r in rows if r["status"] in statuses]
    if due_soon:
        rows = [r for r in rows if r["over_deadline_risk"]]

    sort_key = sort if sort in CASE_SORT_KEYS else "updated_at"
    reverse = (order or "desc").lower() != "asc"
    _verdict_rank = {"none": 0, "generating": 1, "ready": 2}
    _status_rank = {s: i for i, s in enumerate(_PROCESSING_STATUSES)}

    def key_of(r: dict[str, Any]):
        if sort_key == "verdict":
            return (_verdict_rank.get(r["verdict_status"], 0), r["case_id"])
        if sort_key == "status":
            return (_status_rank.get(r["status"], 99), r["case_id"])
        if sort_key == "due_date":
            # 기한이 없는 사건은 어느 방향으로 정렬해도 끝으로 보낸다(빈 값이 앞을 막지 않게).
            return (0 if r["due_date"] else 1, r["due_date"] or "", r["case_id"]) if not reverse \
                else (1 if r["due_date"] else 0, r["due_date"] or "", r["case_id"])
        return (r.get(sort_key) or "", r["case_id"])

    rows.sort(key=key_of, reverse=reverse)
    return {
        "rows": rows,
        "total": len(rows),
        "facets": facets,
        "sort": sort_key,
        "order": "desc" if reverse else "asc",
        "filters": {"q": term, "status": status or "all", "due_soon": due_soon},
        "sort_keys": list(CASE_SORT_KEYS),
    }


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
                     staff: str = "홍길동", staff_id: str | None = None) -> dict[str, Any]:
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
            case_fk=case.id, from_status=case.status, to_status=case.status, actor="staff", actor_id=_actor_id(session, "staff", staff_id),
            note=f"검토 항목 #{seq} 판정 담당자 수정: "
                 f"{(item.ai_original or {}).get('verdict', '—')} → {verdict} · 사유: {reason.strip()}",
        ))
    session.commit()
    return staff_case_detail(session, case_id) or {}


def revert_verdict(session: Session, case_id: str, seq: int, staff: str = "홍길동",
                   staff_id: str | None = None) -> dict[str, Any]:
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
            case_fk=case.id, from_status=case.status, to_status=case.status, actor="staff", actor_id=_actor_id(session, "staff", staff_id),
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
    sibling_count = len(session.execute(
        select(Case.id).where(Case.customer == case.customer)
    ).scalars().all()) if case.customer else 1
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
        # 종결 결과(사람이 내린 결정) + 종결 가능 여부. close_case 의 게이트와 같은 규칙이다.
        "outcome": _outcome_payload(case),
        "outcome_options": [{"code": k, **v} for k, v in demo_store.DECISION_OUTCOMES.items()],
        "remaining_verdicts": _remaining_verdicts(plan),
        "can_close": case.status in _CLOSEABLE_STATUSES and _remaining_verdicts(plan) == 0,
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
        # 처리 기록 — 이 사건이 어떤 과정을 거쳤는지(감사 추적). 민원인 화면의 기록과 같은 원천.
        "events": case_events(session, case),
        # 이 사건에 게시된 내부·감독기관용 안내문(과거 게시분 포함). 예전엔 생성 직후 한 번만
        # 보이고 어디에도 남지 않았다.
        "staff_messages": [{
            "stage_key": m.stage_key,
            "sender": m.sender,
            "title": m.title,
            "body": m.body,
            "at": m.at.isoformat() if m.at else None,
        } for m in session.execute(
            select(CaseMessage)
            .where(CaseMessage.case_fk == case.id, CaseMessage.audience == "staff")
            .order_by(CaseMessage.at.desc(), CaseMessage.id.desc())
        ).scalars().all()],
        # 고객 단위 맥락 — 같은 고객의 다른 민원이 몇 건인지. 있으면 화면이 '고객 이력'으로
        # 건너갈 수 있게 한다(처리현황=사건 단위, 고객 이력=사람 단위의 역할 분담).
        "customer_case_count": sibling_count,
        "next_action": _NEXT_ACTION.get(case.status, "-"),
    }


def start_verdict_generation(session: Session, case_id: str,
                             staff_id: str | None = None) -> str | None:
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
                           actor="staff", actor_id=_actor_id(session, "staff", staff_id), note="AI 규정 판정 생성 요청"))
    session.commit()
    return case.case_id


# ---- 협상·중재: 요청 → 개시 → 턴 진행(사건에 붙여 DB 영속) -----------------
# 중재 라이브 세션은 프로세스 메모리에만 있어서, 어느 민원 사건의
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
        # MediationRecord 원본 — 중재 콘솔 화면이 그대로 렌더한다.
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
                      reason: str, staff_id: str | None = None) -> dict[str, Any]:
    """민원인 또는 직원이 그 사건에 협상·중재를 요청한다(멱등 — 이미 있으면 사유만 덧붙인다).

    요청 사실은 ① 사건 상태(negotiating) ② 단계 이력(StageEvent) ③ 양쪽 화면에 보이는
    안내 메시지(CaseMessage)로 동시에 남는다 — '요청했는데 아무 데도 안 보인다'를 막는다.
    """
    case = _get_case(session, case_id)
    if case is None:
        raise LookupError("사건을 찾을 수 없습니다.")
    who = _REQUESTER_KO.get(requested_by, requested_by)
    # 요청자에 따라 행위자 종류가 갈린다 — actor 와 actor_id 가 한 쌍으로 움직여야 한다.
    _kind = "citizen" if requested_by == "complainant" else "staff"
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
                               actor=_kind, actor_id=_actor_id(session, _kind, staff_id),
                               note=f"{who}의 협상·중재 요청"))
    else:
        session.add(StageEvent(case_fk=case.id, from_status=case.status, to_status=case.status,
                               actor=_kind, actor_id=_actor_id(session, _kind, staff_id),
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
                           done: bool, staff_id: str | None = None) -> dict[str, Any]:
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
                               actor="staff", actor_id=_actor_id(session, "staff", staff_id), note="협상·중재 개시"))
    session.commit()
    return mediation_payload(session, case) or {}


def staff_mediations(session: Session) -> list[dict[str, Any]]:
    """협상·중재 콘솔 목록 — 처리 단계 사건 + 각 사건의 중재 진행 상태.

    콘솔 한 곳에서 '중재가 열린 사건'과 '아직 열지 않은 사건'을 함께 고를 수 있게, 중재가
    없는 사건도 med_status='none' 으로 함께 준다. 예전엔 중재를 볼 수 있는 곳이 처리현황
    패널·사이드바 외부 콘솔로 흩어져 있었는데, 이 목록이 그 단일 진입점의 원천이다.
    정렬은 손이 가야 하는 순서 — 진행 중 → 요청됨 → 종결 → 미개시.
    """
    rows = session.execute(
        select(Case).where(Case.status.in_(_PROCESSING_STATUSES))
        .order_by(Case.updated_at.desc(), Case.id.desc())
    ).scalars().all()
    out = []
    for c in rows:
        med = _get_mediation(session, c)
        rec = (med.record or {}) if med is not None else {}
        status = med.status if med is not None else "none"
        out.append({
            "case_id": c.case_id,
            "customer": c.customer or "민원인",
            "type": c.complaint_type or _PRODUCT_LABEL.get(c.product_type, "민원"),
            "case_status": c.status,
            "case_status_ko": _status_ko(c.status),
            "med_status": status,
            "med_status_ko": _MEDIATION_STATUS_KO.get(status, "중재 없음"),
            "requested_by_ko": (_REQUESTER_KO.get(med.requested_by, med.requested_by)
                                if med is not None else None),
            "turn_index": med.turn_index if med is not None else 0,
            "max_turns": med.max_turns if med is not None else 0,
            "issue_count": len(rec.get("issues", [])),
            "updated_at": (med.updated_at.isoformat()
                           if med is not None and med.updated_at else None),
        })
    order = {"open": 0, "requested": 1, "closed": 2, "none": 3}
    out.sort(key=lambda r: order.get(r["med_status"], 9))
    return out


def complainant_mediation(session: Session, case_id: str | None = None) -> dict[str, Any] | None:
    """민원인 화면용 — 지금 보고 있는 사건의 중재 내역(case_id 없으면 가장 최근 사건)."""
    case = citizen_case_or_none(session, case_id)
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


def citizen_case_or_none(session: Session, case_id: str | None) -> Case | None:
    """민원인 화면이 열려는 사건 — case_id 가 있으면 그 사건, 없으면 가장 최근 사건.

    민원인은 자기가 접수한 사건만 볼 수 있어야 한다. case_id 가 citizen 채널이 아니거나
    다른 고객의 사건이면 None 을 돌려준다(라우트가 404) — 이관 사건(다른 고객)이 사건번호
    추측만으로 열리면 안 된다.
    """
    if not case_id:
        return _latest_citizen_case(session)
    case = _get_case(session, case_id)
    if case is None or case.channel != "citizen":
        return None
    latest = _latest_citizen_case(session)
    if latest is not None and case.customer != latest.customer:
        return None
    return case


def complainant_progress(session: Session, case_id: str | None = None) -> dict[str, Any]:
    """민원인 진행현황 — 사건 1건의 5단계 타임라인 + 단계별 처리 기록.

    예전엔 가장 최근 사건 하나만 열 수 있어서, 여러 건을 접수한 민원인은 지난 민원이
    어떻게 처리됐는지 볼 방법이 없었다. 이제 case_id 로 사건을 지정할 수 있고, 각 단계에는
    받은 안내(메시지)와 실제로 일어난 일(상태 전이)이 시간순으로 함께 쌓인다.
    """
    case = citizen_case_or_none(session, case_id)
    if case is None:
        if case_id:  # 지정한 사건이 없거나 내 사건이 아니다 — 조용히 다른 사건을 보여주지 않는다.
            raise LookupError("민원을 찾을 수 없습니다.")
        empty_steps = [{**tpl, "date": None, "entries": [], "entry_count": 0} for tpl in _STEP_TEMPLATE]
        return {"case_id": None, "title": "진행 중인 민원이 없어요", "intake_date": None,
                "expected_completion": None, "days_left": 0, "risk": False, "current": 0,
                "steps": empty_steps, "mediation": None, "cases": []}

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

    entries_by_stage = _citizen_entries_by_stage(session, case)

    steps = []
    for i, tpl in enumerate(_STEP_TEMPLATE):
        step = dict(tpl)
        if tpl["key"] == "intake":
            step["date"] = case.intake_date
        else:
            step["date"] = stage_date.get(tpl["key"])
        entries = entries_by_stage.get(tpl["key"], [])
        step["entries"] = entries
        step["entry_count"] = len(entries)
        steps.append(step)

    days_left = _days_left(case.expected_completion)
    title = case.complaint_type or f"{_PRODUCT_LABEL.get(case.product_type, '')} 관련 민원".strip()
    # 사건 전환용 목록 — 여러 건을 접수한 민원인이 진행현황에서 바로 사건을 바꿀 수 있게.
    cases = [{
        "case_id": c.case_id,
        "title": c.complaint_type or f"{_PRODUCT_LABEL.get(c.product_type, '')} 관련 민원".strip(),
        "intake_date": c.intake_date,
        "status_ko": _citizen_status_ko(c.status),
        "current": c.case_id == case.case_id,
    } for c in _citizen_cases(session)]
    return {
        "case_id": case.case_id,
        "title": title,
        "status": case.status,
        "status_ko": _citizen_status_ko(case.status),
        "intake_date": case.intake_date,
        "expected_completion": case.expected_completion,
        "days_left": days_left,
        "risk": days_left <= 7 and case.status != "closed",
        "current": current,
        "steps": steps,
        # 협상·중재 진행(요청·쟁점 원장). 없으면 None — 화면이 '중재 요청' 버튼만 그린다.
        "mediation": mediation_payload(session, case),
        # 내가 접수한 민원 목록(사건 전환용). 1건이면 화면이 전환 UI 를 그리지 않는다.
        "cases": cases,
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
    session.add(StageEvent(case_fk=case.id, from_status=None, to_status="intake", actor="citizen", actor_id=_actor_id(session, "citizen"), note="민원인 앱 제출"))
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
