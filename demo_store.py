from __future__ import annotations

"""데모 데이터 스토어 — 프론트 대시보드/앱이 소비하는 시연용 시드 데이터.

이 파일은 기존 백엔드 계약(agent.py/schemas.py/facade.py)을 전혀 건드리지 않는다.
목적은 "관리자 시연"에서 사건 목록·이력·마이페이지처럼 여러 건이 필요한 화면을
실제처럼 채우는 것이다. 실제 파이프라인(GET /api/frames, POST /api/cases/run)은
그대로 살아 있고, 이 스토어는 그 위에 얇게 얹힌 시연 계층이다.

핵심 개념 구분(중요):
  - AI 산출물         : ledger[].verdict (위반/미이행/해당/하자/선례/산정) — 에이전트가 만든 규정 판정
  - AI 신뢰도 검증    : ledger[].critic (PASS/ESCALATE/BLOCK)             — Critic이 근거 대조로 검증
  - 사람의 최종 결정  : decision.outcome (고객수용/일부수용/기각)          — 협상 과정에서 의사결정 주체(사람)가 결정
  - 파생 지표         : consistency_score                                 — 이번 결정과 과거 결정의 정합도(계산값)

즉 판정결과(수용/일부수용/기각)는 LLM이 정하지 않는다. 화면에서도 "담당자 결정"으로 표기한다.
"""

from typing import Any

# ---------------------------------------------------------------------------
# 상태/라벨 사전 — 화면 배지와 백엔드 개념을 한 곳에서 맞춘다.
# ---------------------------------------------------------------------------

# 사람이 내리는 최종 결정(협상 결과). LLM 산출물이 아니다.
DECISION_OUTCOMES = {
    "accepted": {"ko": "고객 수용", "tone": "good"},
    "partial": {"ko": "일부 수용", "tone": "warn"},
    "rejected": {"ko": "기각", "tone": "bad"},
}

# AI 신뢰도 검증(Critic) 3단계. critic.py 의 verdict 와 동일 개념.
CRITIC_BADGES = {
    "PASS": {"ko": "PASS", "tone": "good", "desc": "근거 일치 · 자동 통과"},
    "ESCALATE": {"ko": "ESCALATE", "tone": "warn", "desc": "불확실 · 사람 확인 필요"},
    "BLOCK": {"ko": "BLOCK", "tone": "bad", "desc": "근거 밖 인용 · 차단"},
}

# 처리 상태 흐름(직원 화면). 접수→검토계획→승인→처리 상태머신 라벨.
# (demo_db/agentic_plan 의 status 전이와 맞춘다 — 상태 라벨의 단일 진실 원천.)
CASE_STATUS = {
    "intake": {"ko": "접수 대기", "tone": "muted"},
    "referred": {"ko": "이관됨", "tone": "info"},
    "plan_generating": {"ko": "AI 검토계획 생성 중", "tone": "info"},
    "plan_ready": {"ko": "검토계획 대기", "tone": "warn"},
    "reviewing": {"ko": "검토 중", "tone": "info"},
    "verdict": {"ko": "판정 완료", "tone": "info"},
    "negotiating": {"ko": "협의 중", "tone": "warn"},
    "closed": {"ko": "종결", "tone": "good"},
}


# ---------------------------------------------------------------------------
# 직원 대시보드 — 홈
# ---------------------------------------------------------------------------

STAFF_SUMMARY = {
    "officer": "홍길동",
    "team": "준법감시팀",
    "cards": [
        {"key": "todo", "label": "오늘 처리할 항목", "value": 24, "unit": "건", "hint": "전체 32건", "tone": "info"},
        {"key": "due_soon", "label": "기한 임박 사건", "value": 7, "unit": "건", "hint": "3일 이내 마감", "tone": "bad"},
        {"key": "ai_wait", "label": "AI 검토 대기", "value": 18, "unit": "건", "hint": "검토 필요", "tone": "warn"},
        {"key": "done_today", "label": "오늘 완료", "value": 15, "unit": "건", "hint": "목표 20건", "tone": "good"},
    ],
}

# 최근 처리한 사건(홈 하단 테이블). outcome 은 사람이 내린 최종 결정.
STAFF_RECENT_CASES = [
    {"case_id": "C-2024-05123", "customer": "김민수", "type": "ELS 불완전판매", "outcome": "accepted", "processed_at": "2025-05-20 16:42", "officer": "홍길동"},
    {"case_id": "C-2024-05122", "customer": "이영희", "type": "DLF 손실", "outcome": "partial", "processed_at": "2025-05-20 15:31", "officer": "홍길동"},
    {"case_id": "C-2024-05121", "customer": "박준혁", "type": "예금상품 설명부족", "outcome": "rejected", "processed_at": "2025-05-20 14:22", "officer": "최지영"},
    {"case_id": "C-2024-05120", "customer": "정다은", "type": "투자권유 부적정", "outcome": "accepted", "processed_at": "2025-05-20 11:10", "officer": "홍길동"},
    {"case_id": "C-2024-05119", "customer": "최성민", "type": "신용카드 과다수수료", "outcome": "partial", "processed_at": "2025-05-20 10:05", "officer": "최지영"},
]


# ---------------------------------------------------------------------------
# 직원 대시보드 — 사건접수(신규 이관 목록) + AI 검토계획
# ---------------------------------------------------------------------------
# 예전 STAFF_INTAKE_CASES / STAFF_CHECKLIST_PLANS 더미는 제거됐다. 접수 사건과
# AI 자동 검토계획은 이제 DB(models.Case/ReviewPlan)에 저장되며 demo_db.py 가 조회한다.
# 시드 이관 사건은 db.py::_SEED_INTAKE 가 넣는다.


# ---------------------------------------------------------------------------
# 직원 대시보드 — 처리현황(사건 상세 원장 + AI 검증 + 유사사례 + 기한/재협상)
# ---------------------------------------------------------------------------

STAFF_CASE_DETAILS = {
    "C-2024-05130": {
        "case_id": "C-2024-05130",
        "type": "ELS 불완전판매",
        "customer": "김서연",
        "status": "reviewing",
        "due_date": "2024-05-23",
        "days_left": 2,
        "over_deadline_risk": True,
        # 사건 원장 — 각 행: AI 규정 판정(ko/verdict) + AI 신뢰도 검증 배지(critic)
        "ledger": [
            {"item": "적합성 원칙 위반 여부", "code": "금소법 §17", "verdict": "위반", "critic": "PASS"},
            {"item": "설명의무 이행 여부", "code": "금소법 §19", "verdict": "위반", "critic": "PASS"},
            {"item": "불완전판매 판단", "code": "금소법 §20", "verdict": "해당", "critic": "PASS"},
            {"item": "손해 인과관계", "code": "민법 §750", "verdict": "인과관계 인정", "critic": "ESCALATE"},
            {"item": "손해액 산정 적정성", "code": "배상 5750", "verdict": "일부 인정", "critic": "PASS"},
            {"item": "배상책임 범위", "code": "결정례 2024-1041", "verdict": "50% 배상", "critic": "BLOCK"},
        ],
        # 유사 과거사례(RAG 검색 결과 형태) — 유사도 %
        "similar_cases": [
            {"case_id": "C-2024-01045", "title": "ELS 불완전판매 · 50% 배상", "similarity": 92, "closed_at": "2024-02-14", "outcome": "accepted", "outcome_ko": "고객 수용"},
            {"case_id": "C-2023-08912", "title": "ELS 불완전판매 · 40% 배상", "similarity": 85, "closed_at": "2023-11-03", "outcome": "partial", "outcome_ko": "조정 성립"},
            {"case_id": "C-2023-07654", "title": "ELS 불완전판매 · 60% 배상", "similarity": 78, "closed_at": "2023-09-21", "outcome": "accepted", "outcome_ko": "고객 수용"},
        ],
        # 재협상 자료 검토(사람이 결정, 에이전트는 자료만 정리)
        "renegotiation": {
            "attachments": [
                {"name": "재협상_안_20240521.pdf", "size": "1.2MB", "uploaded_at": "2024-05-21 14:33"},
            ],
            "note": "예상 완료일이 처리 기한을 초과할 위험. 재협상 자료 검토 후 담당자가 새 기한을 결정합니다.",
        },
    },
}


# ---------------------------------------------------------------------------
# 직원 대시보드 — 이력(고객별 과거 민원 + 반복 패턴 + 일관성 점수)
# ---------------------------------------------------------------------------

# consistency_score 는 파생 지표: 같은 유형 과거 결정 대비 이번 결정의 정합도(높을수록 일관).
STAFF_CUSTOMER_HISTORY = {
    "김민수": {
        "customer": "김민수",
        "customer_no": "123-45-67890",
        "repeat_pattern": {"type": "ELS 불완전판매", "count": 3, "message": "동일 유형(ELS 불완전판매) 민원이 총 3회 접수되었습니다."},
        "rows": [
            {"case_id": "C-2024-05123", "intake_date": "2024-05-20", "type": "ELS 불완전판매", "outcome": "accepted", "result": "배상 50%", "repeat": None, "consistency": 92},
            {"case_id": "C-2023-11456", "intake_date": "2023-10-12", "type": "ELS 불완전판매", "outcome": "partial", "result": "배상 30%", "repeat": "동일 유형 2회차", "consistency": 85},
            {"case_id": "C-2023-07331", "intake_date": "2023-06-21", "type": "펀드 설명부족", "outcome": "rejected", "result": "-", "repeat": None, "consistency": 76},
            {"case_id": "C-2022-09110", "intake_date": "2022-08-05", "type": "보험금 지급거절", "outcome": "partial", "result": "배상 20%", "repeat": None, "consistency": 81},
            {"case_id": "C-2022-04122", "intake_date": "2022-04-18", "type": "신용카드 수수료", "outcome": "accepted", "result": "환급", "repeat": None, "consistency": 90},
            {"case_id": "C-2021-10203", "intake_date": "2021-10-30", "type": "대출금리 불만", "outcome": "rejected", "result": "-", "repeat": None, "consistency": 70},
        ],
    },
}

DEFAULT_HISTORY_CUSTOMER = "김민수"


# ---------------------------------------------------------------------------
# 직원 대시보드 — 마이페이지(계정/알림/활동로그/세션)
# ---------------------------------------------------------------------------

STAFF_PROFILE = {
    "account": {
        "name": "홍길동",
        "team": "준법감시팀",
        "rank": "선임조사역",
        "email": "hong.gildong@internal.com",
        "phone": "010-1234-5678",
        "verified": True,
    },
    "notifications": [
        {"key": "due_soon", "label": "기한 임박 알림", "enabled": True},
        {"key": "ai_done", "label": "AI 검토 완료 알림", "enabled": True},
        {"key": "transfer", "label": "이관 사건 알림", "enabled": True},
        {"key": "system", "label": "시스템 공지 알림", "enabled": False},
    ],
    "activity_log": [
        {"at": "2024-05-21 09:12", "action": "로그인", "detail": "성공", "ip": "10.20.30.40"},
        {"at": "2024-05-21 09:11", "action": "사건 검토", "detail": "C-2024-05130 열람", "ip": "10.20.30.40"},
        {"at": "2024-05-20 08:55", "action": "자료 다운로드", "detail": "재협상_안_20240521.pdf", "ip": "10.20.30.40"},
        {"at": "2024-05-20 16:42", "action": "사건 처리 완료", "detail": "C-2024-05123", "ip": "10.20.30.40"},
        {"at": "2024-05-20 15:31", "action": "메모 작성", "detail": "C-2024-05122", "ip": "10.20.30.40"},
    ],
    "session": {"current_ip": "10.20.30.40", "last_login": "2024-05-21 09:12 (Chrome / Windows)"},
}


# ---------------------------------------------------------------------------
# 민원인 웹 포털 — 프로필/홈/진행현황/이력
# ---------------------------------------------------------------------------

COMPLAINANT_PROFILE = {
    "name": "김지은",
    "email": "jieun.kim@example.com",
    "verified": True,
    "notifications": [
        {"key": "progress", "label": "민원 진행 알림", "hint": "진행 상황을 푸시로 알려드려요.", "enabled": True},
        {"key": "notice", "label": "중요 안내 알림", "hint": "중요한 공지나 안내를 알려드려요.", "enabled": True},
        {"key": "event", "label": "이벤트/혜택 알림", "hint": "이벤트 및 혜택 정보를 알려드려요.", "enabled": False},
    ],
    "menu": [
        {"key": "faq", "label": "자주 묻는 질문"},
        {"key": "support", "label": "고객센터 문의"},
        {"key": "about", "label": "서비스 정보", "value": "v1.0.0"},
    ],
}

COMPLAINANT_HOME = {
    "greeting_name": "김지은",
    "current_case": {
        "case_id": "C-2025-06-001",
        "title": "ELS 불완전판매 관련 민원",
        "status": "reviewing",
        "status_ko": "검토 중",
        "intake_date": "2025-06-01",
        "expected_completion": "2025-07-31",
        "days_left": 15,
        "risk": True,
    },
    "notices": [
        {"icon": "megaphone", "title": "담당 검토가 시작되었어요", "body": "사실관계 확인을 위한 검토가 진행 중입니다.", "at": "2시간 전"},
        {"icon": "document", "title": "추가 자료 제출 요청", "body": "계약서 사본을 추가로 제출해주세요.", "at": "1일 전"},
    ],
}

# 진행현황(5단계 타임라인)은 이제 DB 기반이다 — demo_db.complainant_progress() 가
# 최근 민원인 Case 의 status 를 상태머신으로 풀어 steps/current 를 만든다.

COMPLAINANT_HISTORY = [
    {"case_id": "C-2025-06-001", "type": "ELS 불완전판매 관련 민원", "intake_date": "2025-06-01", "status": "reviewing", "status_ko": "진행중", "closed_at": None, "expected_completion": "2025-07-31"},
    {"case_id": "C-2025-03-015", "type": "펀드 환매 지연 관련 민원", "intake_date": "2025-03-15", "status": "closed", "status_ko": "종결", "closed_at": "2025-04-20"},
    {"case_id": "C-2025-01-010", "type": "대출 중도상환 수수료 관련 민원", "intake_date": "2025-01-10", "status": "closed", "status_ko": "종결", "closed_at": "2025-02-05"},
    {"case_id": "C-2024-11-020", "type": "보험금 지급 거절 관련 민원", "intake_date": "2024-11-20", "status": "closed", "status_ko": "종결", "closed_at": "2024-12-30"},
]

# 민원접수 폼 — 금융상품 유형 칩
COMPLAINANT_PRODUCT_TYPES = [
    {"key": "deposit", "label": "예금·적금"},
    {"key": "fund", "label": "펀드"},
    {"key": "els_dls", "label": "ELS·DLS"},
    {"key": "insurance", "label": "보험"},
    {"key": "loan", "label": "대출"},
    {"key": "etc", "label": "기타"},
]

# (민원인 제출은 이제 DB(models.Case)에 저장된다 — demo_db.submit_complaint 참조.)


# ---------------------------------------------------------------------------
# 조회 헬퍼 — 라벨을 붙여 프론트가 그대로 렌더할 수 있게 한다.
# ---------------------------------------------------------------------------


def _decorate_outcome(outcome: str | None) -> dict[str, Any] | None:
    """결정 코드(accepted/partial/rejected) → {code, ko, tone}. 사람이 내린 결정."""
    if not outcome:
        return None
    meta = DECISION_OUTCOMES.get(outcome)
    if not meta:
        return {"code": outcome, "ko": outcome, "tone": "muted"}
    return {"code": outcome, "ko": meta["ko"], "tone": meta["tone"], "decided_by": "담당자"}


def staff_summary() -> dict[str, Any]:
    return STAFF_SUMMARY


def staff_recent_cases() -> list[dict[str, Any]]:
    out = []
    for row in STAFF_RECENT_CASES:
        item = dict(row)
        item["outcome"] = _decorate_outcome(row["outcome"])
        out.append(item)
    return out


def staff_case_detail(case_id: str) -> dict[str, Any] | None:
    detail = STAFF_CASE_DETAILS.get(case_id) or next(iter(STAFF_CASE_DETAILS.values()), None)
    if not detail:
        return None
    out = dict(detail)
    # 원장 각 행에 라벨 부착
    out["ledger"] = [
        {**row, "critic_meta": CRITIC_BADGES.get(row.get("critic", ""), {})}
        for row in detail["ledger"]
    ]
    # AI 검증 요약(PASS/ESCALATE/BLOCK 집계)
    counts = {"PASS": 0, "ESCALATE": 0, "BLOCK": 0}
    for row in detail["ledger"]:
        counts[row.get("critic", "")] = counts.get(row.get("critic", ""), 0) + 1
    out["critic_summary"] = {"reviewed": len(detail["ledger"]), **counts}
    return out


def staff_customer_history(customer: str | None = None) -> dict[str, Any] | None:
    key = customer if customer in STAFF_CUSTOMER_HISTORY else DEFAULT_HISTORY_CUSTOMER
    hist = STAFF_CUSTOMER_HISTORY.get(key)
    if not hist:
        return None
    out = dict(hist)
    out["rows"] = [{**row, "outcome": _decorate_outcome(row["outcome"])} for row in hist["rows"]]
    return out


def staff_profile() -> dict[str, Any]:
    return STAFF_PROFILE


def complainant_home() -> dict[str, Any]:
    return COMPLAINANT_HOME


def complainant_history() -> list[dict[str, Any]]:
    return COMPLAINANT_HISTORY


def complainant_profile() -> dict[str, Any]:
    return COMPLAINANT_PROFILE


def complainant_product_types() -> list[dict[str, Any]]:
    return COMPLAINANT_PRODUCT_TYPES
