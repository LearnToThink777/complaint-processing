from __future__ import annotations

"""SQLAlchemy ORM 모델 — 민원 접수→AI 검토계획→직원 승인→처리 흐름의 영속 스키마.

이 파일은 그동안 demo_store.py 가 하드코딩 상수/메모리 리스트로 흉내 내던 것을
실제 테이블로 대체한다(민원 접수·검토계획·승인·단계 이력만 — 범위 밖 더미는 유지).

핵심 개념(schemas.py 의 Pydantic 계약과 1:1 대응):
  - Case              : 사건 1건(민원인 제출 or 직원 이관). status 로 상태머신을 돈다.
  - ReviewPlan        : 그 사건의 AI 자동 검토계획(schemas.ChecklistPlan 에 대응).
  - ChecklistItemRow  : 검토 항목 1건(schemas.ChecklistItem = item/law/source + UI 체크 status).
  - Approval          : 직원의 검토계획 승인 기록(누가/언제).
  - StageEvent        : 상태 전이 이력(감사 로그 + 민원인/직원 타임라인 근거).
  - CaseMessage       : 단계별 공개 메시지(이중공개의 청중별 본문). audience 로 민원인/직원 분리.
  - CaseMediation     : 그 사건의 협상·중재 진행(요청·세션·쟁점 원장 스냅샷).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class Case(Base):
    """사건 1건. status 가 상태머신(intake→plan_generating→plan_ready→reviewing→…)을 돈다."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String, unique=True, index=True)  # "C-2025-06-101"
    channel: Mapped[str] = mapped_column(String, default="citizen")  # citizen(민원인 제출) | referred(직원 이관)
    customer: Mapped[str] = mapped_column(String, default="")
    product_type: Mapped[str] = mapped_column(String, default="")  # 한글 키: "els_dls"
    product_en: Mapped[str] = mapped_column(String, default="")  # retrieval 필터: "ELS mis-selling"
    complaint_type: Mapped[str] = mapped_column(String, default="")  # AI 분류 라벨(생성 후 채워짐)
    track: Mapped[str] = mapped_column(String, default="legal")  # legal | general
    facts: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 접수 시 추출한 검색 키워드(schemas.CaseKeywords.model_dump())
    attachments: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="intake", index=True)  # 상태머신 키
    intake_date: Mapped[str] = mapped_column(String, default="")  # "2025-06-01" (UI 표기용 문자열)
    due_date: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_completion: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    plans: Mapped[list["ReviewPlan"]] = relationship(
        back_populates="case", order_by="ReviewPlan.id", cascade="all, delete-orphan"
    )
    events: Mapped[list["StageEvent"]] = relationship(
        back_populates="case", order_by="StageEvent.id", cascade="all, delete-orphan"
    )
    messages: Mapped[list["CaseMessage"]] = relationship(
        back_populates="case", order_by="CaseMessage.seq, CaseMessage.id", cascade="all, delete-orphan"
    )
    mediation: Mapped["CaseMediation | None"] = relationship(
        back_populates="case", uselist=False, cascade="all, delete-orphan"
    )


class ReviewPlan(Base):
    """AI 자동 검토계획(schemas.ChecklistPlan 대응). 한 사건에 여러 개 두어 이력을 남긴다."""

    __tablename__ = "review_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_fk: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    classification: Mapped[str] = mapped_column(String, default="")
    track: Mapped[str] = mapped_column(String, default="legal")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="generating")  # generating|ready|approved|failed
    provider: Mapped[str] = mapped_column(String, default="")  # 감사: 어떤 모델이 생성했는지
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # 생성 소요시간(perf.py 가 기록)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    case: Mapped["Case"] = relationship(back_populates="plans")
    items: Mapped[list["ChecklistItemRow"]] = relationship(
        back_populates="plan", order_by="ChecklistItemRow.seq", cascade="all, delete-orphan"
    )


class ChecklistItemRow(Base):
    """검토 항목 1건 = 처리현황 사건 원장의 한 행.

    두 단계의 데이터가 한 행에 쌓인다:
      1) 검토계획(schemas.ChecklistItem) : item/law/source — 승인 전 AI가 도출한 '무엇을 볼지'
      2) 규정 판정(schemas.RegulatoryVerdict): verdict/verdict_code/verdict_ko/verdict_detail
         — 승인 후 직원이 '판정 생성'을 누르면 verdict_batch LLM이 항목별로 채우는 '판정 결과'
    critic 은 그 판정에 대한 신뢰도 검증 배지(PASS/ESCALATE/BLOCK). 판정 전에는 전부 빈 문자열.
    """

    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_fk: Mapped[int] = mapped_column(ForeignKey("review_plans.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 화면 번호(옛 더미의 "n")
    item: Mapped[str] = mapped_column(String, default="")
    law: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | approved
    # ---- 규정 판정(승인 후 채워짐) — schemas.RegulatoryVerdict 1:1 대응 ----
    verdict: Mapped[str] = mapped_column(String, default="")  # 판정 라벨: 위반/미이행/해당/하자/선례/산정/해당없음
    verdict_code: Mapped[str] = mapped_column(String, default="")  # 적용 근거 조항(law 를 정제/보강)
    verdict_ko: Mapped[str] = mapped_column(String, default="")  # 한 줄 판정 요지
    verdict_detail: Mapped[str] = mapped_column(Text, default="")  # 판정 근거 상세(사실관계 기반)
    critic: Mapped[str] = mapped_column(String, default="")  # 신뢰도 검증 배지: PASS/ESCALATE/BLOCK/CONFIRMED(판정 전엔 "")
    # ---- 담당자 판정 수정(오버라이드) ----
    # AI 판정은 제안이고 확정은 사람이 한다 — 그런데 그동안 화면에 고칠 방법이 없어
    # AI 가 틀려도 그대로 남았다. 아래 컬럼이 '누가 무엇을 왜 바꿨는지'를 남긴다.
    # ai_original 은 최초 AI 판정 스냅샷({verdict/code/ko/detail/critic}) — 수정 후에도
    # 원안과 대조할 수 있어야 감사가 성립하고, 되돌리기도 가능하다.
    ai_original: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verdict_source: Mapped[str] = mapped_column(String, default="ai")  # ai(AI 판정) | staff(담당자 확정)
    override_reason: Mapped[str] = mapped_column(Text, default="")  # 왜 바꿨는지(필수 입력)
    overridden_by: Mapped[str] = mapped_column(String, default="")
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped["ReviewPlan"] = relationship(back_populates="items")


class Approval(Base):
    """직원의 검토계획 승인 기록(누가/언제/메모). schemas 에는 없는 운영 메타."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_fk: Mapped[int] = mapped_column(ForeignKey("review_plans.id"), index=True)
    approved_by: Mapped[str] = mapped_column(String, default="홍길동")
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    note: Mapped[str] = mapped_column(Text, default="")


class PerformanceLog(Base):
    """성능/응답시간 기록 1건 — LLM 호출(검토계획 생성, 스킬 5종 등)의 소요시간·결과를 남긴다.

    perf.py::record() 가 여기 insert 하고, 동시에 사람이 읽는 노트북 파일
    (PERFORMANCE_LOG.md)에도 한 줄을 덧붙인다. 향후 수동 성능 테스트 결과도
    같은 함수로 여기 쌓을 수 있다(task 이름만 구분해서).
    """

    __tablename__ = "performance_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(String, index=True)  # 예: "checklist_plan_agentic", "skill:verdict"
    case_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String, default="ok")  # ok | fallback | error
    error: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class StageEvent(Base):
    """상태 전이 이력. 감사 로그이자 민원인/직원 양쪽 타임라인의 근거."""

    __tablename__ = "stage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_fk: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, default="")
    actor: Mapped[str] = mapped_column(String, default="system")  # system | staff | citizen
    at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    note: Mapped[str] = mapped_column(Text, default="")

    case: Mapped["Case"] = relationship(back_populates="events")


class CaseMediation(Base):
    """사건 1건에 붙은 협상·중재 진행 상태(사건당 최대 1건).

    협상·중재 콘솔(mediation.html)의 라이브 세션은 그동안 프로세스 메모리에만 있어서
    ① 서버를 재시작하면 사라지고 ② 어느 민원 사건의 중재인지 이어지지 않고 ③ 민원인·
    직원 화면 어디에도 그 내역이 안 보였다. 이 테이블이 그 셋을 함께 푼다:
      - case_fk        : 어느 민원 사건의 중재인지(양쪽 화면이 사건으로 조회)
      - requested_by   : 누가 요청했는지(complainant | staff)
      - record         : MediationRecord.model_dump() 스냅샷 — 턴을 진행할 때마다 갱신.
                         쟁점 원장·공유 처리이력·중립성 밸런스가 통째로 여기 들어간다.
    라이브 세션(sid)은 여전히 메모리에 있지만, 스냅샷이 DB 에 있으므로 세션이 사라져도
    지금까지의 중재 내역은 양쪽 화면에 그대로 남는다.
    """

    __tablename__ = "case_mediations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_fk: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True, unique=True)
    status: Mapped[str] = mapped_column(String, default="requested")  # requested|open|closed
    requested_by: Mapped[str] = mapped_column(String, default="complainant")  # complainant | staff
    reason: Mapped[str] = mapped_column(Text, default="")  # 중재를 요청한 사유(요청자 입력)
    scenario_id: Mapped[str] = mapped_column(String, default="")  # mediation.json 시드 시나리오
    sid: Mapped[str] = mapped_column(String, default="")  # 라이브 세션 id(메모리·재시작 시 소멸)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    max_turns: Mapped[int] = mapped_column(Integer, default=0)  # 이 세션의 턴 상한(진행률 표시용)
    record: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # MediationRecord 스냅샷
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    case: Mapped["Case"] = relationship(back_populates="mediation")


class CaseMessage(Base):
    """단계별 공개 메시지 1건. 이중공개(schemas.DualDisclosure)의 청중별 본문이 여기 영속된다.

    이중공개는 같은 판정을 청중별로 다르게 써서 '각자의 화면에 분리 게시'하는 것이 취지다.
    그 두 본문을 audience 로 갈라 저장한다:
      - complainant : 민원인 진행현황(Progress) 트래커에 노출
      - staff       : 직원·감독원 화면에 노출
    stage_key 로 처리단계(접수/검토중/판정완료/협의/종결)에 매핑해, 진행현황이 단계별로
    메시지를 묶어 보여줄 수 있게 한다(demo_db._STEP_TEMPLATE 의 key 와 동일 어휘).
    """

    __tablename__ = "case_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_fk: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    stage_key: Mapped[str] = mapped_column(String, default="intake", index=True)  # intake|reviewing|verdict|negotiation|closed
    audience: Mapped[str] = mapped_column(String, default="complainant", index=True)  # complainant | staff
    sender: Mapped[str] = mapped_column(String, default="담당자")  # 담당자 | 민원인 | AI 분석 | 시스템
    title: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 같은 단계 내 정렬
    at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    case: Mapped["Case"] = relationship(back_populates="messages")
