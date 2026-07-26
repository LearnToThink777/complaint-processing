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
# ko 는 화면에 그대로 찍히는 라벨이다 — 담당자는 개발자가 아니므로 PASS/ESCALATE/BLOCK
# 같은 내부 코드명 대신 한국어로 읽히는 말을 쓴다(코드값 자체는 그대로 PASS/…).
CRITIC_BADGES = {
    "PASS": {"ko": "근거 확인", "tone": "good", "desc": "인용 근거가 판정과 일치"},
    "ESCALATE": {"ko": "확인 필요", "tone": "warn", "desc": "근거가 불확실 — 담당자 확인 권장"},
    "BLOCK": {"ko": "근거 부족", "tone": "bad", "desc": "검색 근거 밖의 내용 — 그대로 쓰면 안 됨"},
    # 담당자가 AI 판정을 직접 고쳐 확정한 행. AI 신뢰도 검증의 대상이 아니다(검증할 AI 산출물이
    # 아니라 사람의 결정이므로) — 배지 자리에 '누가 정했는지'를 대신 표시한다.
    "CONFIRMED": {"ko": "담당자 확정", "tone": "info", "desc": "담당자가 직접 판정 · AI 검증 대상 아님"},
}

# 처리 상태 흐름(직원 화면). 접수→검토계획→승인→처리 상태머신 라벨.
# (demo_db/agentic_plan 의 status 전이와 맞춘다 — 상태 라벨의 단일 진실 원천.)
CASE_STATUS = {
    "intake": {"ko": "접수 대기", "tone": "muted"},
    "referred": {"ko": "이관됨", "tone": "info"},
    "plan_generating": {"ko": "AI 검토계획 생성 중", "tone": "info"},
    "plan_ready": {"ko": "검토계획 승인 대기", "tone": "warn"},
    "reviewing": {"ko": "검토 중", "tone": "info"},
    "verdict_generating": {"ko": "AI 판정 생성 중", "tone": "info"},
    "verdict": {"ko": "판정 완료", "tone": "info"},
    "negotiating": {"ko": "협의 중", "tone": "warn"},
    "closed": {"ko": "종결", "tone": "good"},
}


# ---------------------------------------------------------------------------
# 직원 대시보드 — 홈
# ---------------------------------------------------------------------------

# 직원 홈 요약 카드(24/7/18/15)와 '최근 처리한 사건' 5행 더미는 제거됐다. 사건을 아무리
# 접수해도 숫자가 꿈쩍하지 않는 화면이었다 — 이제 demo_db.staff_summary()/staff_recent_cases()
# 가 cases/stage_events 를 실제로 세어 돌려준다.


# ---------------------------------------------------------------------------
# 직원 대시보드 — 사건접수(신규 이관 목록) + AI 검토계획
# ---------------------------------------------------------------------------
# 예전 STAFF_INTAKE_CASES / STAFF_CHECKLIST_PLANS 더미는 제거됐다. 접수 사건과
# AI 자동 검토계획은 이제 DB(models.Case/ReviewPlan)에 저장되며 demo_db.py 가 조회한다.
# 시드 이관 사건은 db.py::_SEED_INTAKE 가 넣는다.


# ---------------------------------------------------------------------------
# 직원 대시보드 — 처리현황(사건 상세 원장 + AI 검증 + 유사사례)
# ---------------------------------------------------------------------------
# 예전의 STAFF_CASE_DETAILS(단일 하드코딩 사건) 더미는 제거됐다. 처리현황은 이제
# 실제 DB(models.Case + 승인된 ReviewPlan 의 판정 컬럼)를 조회한다 — demo_db.staff_case_detail.
# 사건 원장(판정 결과)은 승인 후 verdict_batch LLM 이 채우고(case_ai.run_verdict_generation),
# 유사사례는 사건별 접수 내용으로 실검색한다(case_ai.search_similar_for_case).


# ---------------------------------------------------------------------------
# 직원 대시보드 — 이력(고객별 과거 민원 + 반복 패턴 + 일관성 점수)
# ---------------------------------------------------------------------------

# 고객 이력 더미(하드코딩 6행 + consistency_score)는 제거됐다. consistency_score 는 근거
# 없이 숫자만 그럴듯한 파생 지표였다 — 계산 규칙이 실제로 정의될 때 다시 넣는다.
# 지금 이력은 demo_db.staff_customer_history() 가 cases 에서 그 고객 사건을 모아 만든다.


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
    # activity_log 는 demo_db.staff_profile() 이 stage_events(실제 처리 이력)에서 채운다.
    # 예전엔 '자료 다운로드 재협상_안_20240521.pdf' 같은 있지도 않은 활동이 박혀 있었다.
    "activity_log": [],
    # 로그인/세션 추적 기능이 없으므로 IP·최종 로그인 시각을 지어내지 않는다.
    "session": {"current_ip": "", "last_login": ""},
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

# 민원인 홈/이력/진행현황은 모두 DB 기반이다 — demo_db 의 complainant_home() /
# complainant_history() / complainant_progress() 가 그 사람의 실제 Case·CaseMessage 를 읽는다.
# (예전 COMPLAINANT_HOME·COMPLAINANT_HISTORY 하드코딩은 접수해도 안 바뀌는 화면이었다.)

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


def staff_profile() -> dict[str, Any]:
    return STAFF_PROFILE


def complainant_profile() -> dict[str, Any]:
    return COMPLAINANT_PROFILE


def complainant_product_types() -> list[dict[str, Any]]:
    return COMPLAINANT_PRODUCT_TYPES
