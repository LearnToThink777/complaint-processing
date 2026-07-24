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
    """검토 항목 1건. schemas.ChecklistItem(item/law/source) + UI 체크 상태(status)."""

    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_fk: Mapped[int] = mapped_column(ForeignKey("review_plans.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 화면 번호(옛 더미의 "n")
    item: Mapped[str] = mapped_column(String, default="")
    law: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | approved

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
