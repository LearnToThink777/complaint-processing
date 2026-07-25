from __future__ import annotations

"""DB 부트스트랩 — SQLite 엔진 · 세션 · 초기화/시드.

민원 접수→검토계획→승인 흐름의 영속 계층 진입점. 기본은 패키지 안의 단일 파일
SQLite(data/complaint.db) 라 별도 인프라가 필요 없다. COMPLAINT_DB_URL 로 다른
DB(예: Postgres)로 갈아끼울 수 있게 URL 만 환경변수로 뺐다.

주의(스레딩): AI 검토계획 생성은 FastAPI BackgroundTasks(스레드풀)에서 돈다.
SQLite 는 기본적으로 커넥션을 만든 스레드에서만 쓸 수 있으므로 check_same_thread=False
가 필요하고, 백그라운드 작업은 요청 세션을 넘겨받지 말고 session_scope() 로 자기
세션을 새로 열어야 한다.
"""

import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Case, CaseMessage, StageEvent

_PKG_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = _PKG_DIR / "data" / "complaint.db"
DB_URL = os.environ.get("COMPLAINT_DB_URL", f"sqlite:///{_DEFAULT_DB_PATH}")

# check_same_thread=False: BackgroundTasks 스레드풀에서 커넥션을 만지므로 필수(SQLite 한정).
_connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI 의존성 — 요청 1건 동안 세션을 열고 끝에 닫는다."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """백그라운드 작업용 — 자기 세션을 새로 열고 commit/rollback/close 를 책임진다."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# 화면 공백 방지용 시드 — 예전 demo_store.STAFF_INTAKE_CASES 를 DB 행으로 옮긴 것.
# 이 사건들은 status="intake"(검토계획 생성 전)에서 시작한다 — 직원이 사건접수에서
# 검토계획을 승인하면 처리현황(demo_db.staff_case_detail)으로 넘어가 판정 대상이 된다.
# channel="referred": 직원 이관 사건(민원인 앱 제출이 아님).
_SEED_INTAKE: list[dict] = [
    {"case_id": "C-2024-05130", "customer": "김서연", "product_type": "els_dls", "product_en": "ELS mis-selling", "type": "ELS 불완전판매", "intake_date": "2024-05-21", "track": "legal",
     "facts": "안정추구형으로 분류된 개인 고객에게 원금 비보장 고위험 ELS를 판매. 원금손실 위험 고지가 불충분했고, 판매 녹취 일부 누락 및 서명 불일치."},
    {"case_id": "C-2024-05129", "customer": "오민석", "product_type": "fund", "product_en": "DLF loss", "type": "DLF 손실", "intake_date": "2024-05-21", "track": "legal",
     "facts": "고령 고객에게 손실 위험이 큰 DLF를 원금보장형인 것처럼 안내해 가입. 만기 시 큰 손실이 발생했고 위험등급 설명이 부족했다."},
    {"case_id": "C-2024-05128", "customer": "배지현", "product_type": "fund", "product_en": "fund mis-selling", "type": "펀드 설명부족", "intake_date": "2024-05-21", "track": "legal",
     "facts": "펀드 가입 시 수수료 구조와 환매 조건에 대한 설명이 충분하지 않았다는 민원. 투자성향 진단 절차가 형식적으로 진행됨."},
    {"case_id": "C-2024-05127", "customer": "유재현", "product_type": "els_dls", "product_en": "unsuitable recommendation", "type": "투자권유 부적정", "intake_date": "2024-05-21", "track": "legal",
     "facts": "투자경험이 없는 고객에게 위험도가 높은 상품을 반복 권유. 적합성 판단 근거가 불명확하고 권유 과정 기록이 미비."},
    {"case_id": "C-2024-05126", "customer": "한지은", "product_type": "deposit", "product_en": "deposit maturity", "type": "예금 만기 미이행", "intake_date": "2024-05-21", "track": "legal",
     "facts": "예금 만기 도래 후 자동 재예치 처리가 고객 동의 없이 이루어졌고, 만기 안내가 제때 이루어지지 않았다."},
    {"case_id": "C-2024-05125", "customer": "정무진", "product_type": "etc", "product_en": "card dispute", "type": "신용카드 분쟁", "intake_date": "2024-05-21", "track": "general",
     "facts": "해외 결제 이중청구로 보이는 건에 대한 조회·정정 요청. 절차 안내가 필요한 일반 민원."},
    {"case_id": "C-2024-05124", "customer": "김하늘", "product_type": "insurance", "product_en": "insurance claim denial", "type": "보험금 지급거절", "intake_date": "2024-05-21", "track": "legal",
     "facts": "보험금 청구가 고지의무 위반을 이유로 거절됨. 고지 대상 여부와 인과관계에 대한 다툼이 있다."},
]


def seed_intake(session: Session) -> None:
    """cases 가 비었을 때만 이관 사건 시드를 넣는다(중복 삽입 방지)."""
    exists = session.execute(select(Case.id).limit(1)).first()
    if exists:
        return
    for row in _SEED_INTAKE:
        case = Case(
            case_id=row["case_id"],
            channel="referred",
            customer=row["customer"],
            product_type=row["product_type"],
            product_en=row["product_en"],
            complaint_type=row["type"],
            track=row["track"],
            facts=row["facts"],
            attachments=[],
            status="intake",
            intake_date=row["intake_date"],
        )
        session.add(case)
        session.flush()
        session.add(StageEvent(case_fk=case.id, from_status=None, to_status="intake", actor="system", note="이관 접수(시드)"))
    session.commit()


# 민원인 진행현황(인터랙티브 트래커) 데모용 citizen 사건 — 시드 사건은 전부 referred 라
# citizen 사건이 하나도 없으면 진행현황이 비어 보인다. 트래커를 항상 채우기 위한 데모 1건.
_CITIZEN_DEMO_ID = "C-2025-06-001"

# 단계별 공개 메시지 시드(스크린샷 톤). (stage_key, audience, sender, title, body, day_offset)
# day_offset: 사건 접수(base) 이후 며칠째 발생했는지 — 버블 시각 표기용.
_SEED_MESSAGES: list[tuple[str, str, str, str, str, int]] = [
    ("intake", "complainant", "시스템", "접수 완료",
     "민원이 정상적으로 접수되었어요. 담당자가 배정되어 내용을 확인하고 있어요.", 0),
    ("intake", "complainant", "담당자", "추가 자료 요청",
     "정확한 검토를 위해 거래내역서(최근 3개월)와 상품 가입 시 안내 자료를 추가로 제출해 주세요.", 1),
    ("intake", "complainant", "민원인", "",
     "요청하신 자료를 첨부해 제출했습니다. 확인 부탁드립니다.", 2),
    ("reviewing", "complainant", "담당자", "검토 착수",
     "제출해 주신 자료를 바탕으로 법률 검토와 사실관계 확인을 시작했어요. 조금만 기다려 주세요.", 6),
    ("reviewing", "complainant", "AI 분석", "AI 분석 완료",
     "제출 자료의 주요 내용을 요약했고, 이상 거래 정황은 확인되지 않았어요. 추가 검토를 진행합니다.", 8),
    ("verdict", "complainant", "담당자", "검토 결과 안내",
     "확인 결과, 고객님의 투자성향에 비해 위험도가 높은 상품이 안내된 정황이 있어요. "
     "판매 과정의 설명이 충분했는지를 중심으로 검토가 마무리되었습니다.", 18),
    ("negotiation", "complainant", "담당자", "협의 진행 안내",
     "검토 결과를 바탕으로 금융회사와 배상 여부·범위에 대한 협의를 진행하고 있어요. "
     "결과가 정해지면 바로 알려드릴게요.", 26),
    # 직원·감독원용(청중 분리 시연) — 같은 사건의 기술적 요약.
    ("verdict", "staff", "담당자", "검토 결과 #1 · 회사·감독원용",
     "금융소비자보호법 제17조 적합성원칙 위반 확인(안정추구형 고객 대상 고위험 ELS 판매). "
     "제19조 설명의무 이행 여부 추가 검토 중. 남은 검토 2건.", 18),
    ("negotiation", "staff", "담당자", "협의 자료 #1 · 회사·감독원용",
     "유사 결정례(2024-1041) 기준 배상 40~60% 범위 검토. 인과관계·손해액 산정 쟁점 협의 예정.", 26),
]


def seed_demo_tracker(session: Session) -> None:
    """민원인 진행현황 트래커가 항상 채워지도록 citizen 데모 사건 + 단계별 메시지를 시드한다.

    멱등: 데모 사건이 없으면 만들고, 그 사건에 메시지가 없을 때만 메시지를 넣는다.
    """
    case = session.execute(
        select(Case).where(Case.case_id == _CITIZEN_DEMO_ID)
    ).scalar_one_or_none()

    if case is None:
        today = date.today()
        case = Case(
            case_id=_CITIZEN_DEMO_ID,
            channel="citizen",
            customer="김지은",
            product_type="els_dls",
            product_en="ELS mis-selling",
            complaint_type="ELS 불완전판매",
            track="legal",
            facts="안정추구형으로 분류된 개인 고객에게 원금 비보장 고위험 ELS를 판매. "
                  "원금손실 위험 고지가 불충분했고 판매 과정 설명에 다툼이 있다.",
            attachments=["가입신청서.pdf", "상품설명서.pdf", "거래내역서.pdf"],
            status="negotiating",
            intake_date=(today - timedelta(days=34)).isoformat(),
            expected_completion=(today + timedelta(days=20)).isoformat(),
        )
        session.add(case)
        session.flush()  # id 확보
        base_ev = datetime.utcnow() - timedelta(days=30)
        for frm, to, actor, day in [
            (None, "intake", "citizen", 0),
            ("intake", "reviewing", "staff", 6),
            ("reviewing", "verdict", "system", 18),
            ("verdict", "negotiating", "staff", 26),
        ]:
            session.add(StageEvent(case_fk=case.id, from_status=frm, to_status=to, actor=actor,
                                   at=base_ev + timedelta(days=day), note="데모 시드"))
        session.flush()

    # 메시지는 이 데모 사건에 아직 없을 때만 심는다.
    has_msg = session.execute(
        select(CaseMessage.id).where(CaseMessage.case_fk == case.id).limit(1)
    ).first()
    if not has_msg:
        base_at = datetime.utcnow() - timedelta(days=30)
        seq_by_stage: dict[str, int] = {}
        for stage_key, audience, sender, title, body, day in _SEED_MESSAGES:
            seq = seq_by_stage.get(stage_key, 0)
            seq_by_stage[stage_key] = seq + 1
            session.add(CaseMessage(
                case_fk=case.id, stage_key=stage_key, audience=audience, sender=sender,
                title=title, body=body, seq=seq, at=base_at + timedelta(days=day, hours=seq),
            ))
    session.commit()


def _ensure_columns() -> None:
    """create_all 은 '없는 테이블'만 만들고 '기존 테이블에 새 컬럼'은 추가하지 못한다.

    개발용 단일 SQLite 를 지우지 않고도 스키마를 앞으로 나아가게 하는 최소 마이그레이션 —
    cases.keywords(접수 키워드 JSON)가 없으면 ALTER TABLE 로 더한다. 멱등(이미 있으면 스킵)이라
    매 기동마다 안전하게 호출한다. SQLite 외 DB(예: Postgres)는 정식 마이그레이션 도구를
    쓰는 것을 전제로 여기선 건드리지 않는다.
    """
    if not DB_URL.startswith("sqlite"):
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(cases)"))}
        if "keywords" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN keywords JSON DEFAULT '{}'"))

        # checklist_items 에 규정 판정 컬럼(승인 후 verdict_batch 가 채움)이 없으면 더한다.
        item_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(checklist_items)"))}
        for col in ("verdict", "verdict_code", "verdict_ko", "verdict_detail", "critic",
                    "override_reason", "overridden_by"):
            if col not in item_cols:
                conn.execute(text(f"ALTER TABLE checklist_items ADD COLUMN {col} TEXT DEFAULT ''"))
        # 담당자 판정 수정(오버라이드) 컬럼 — 기본값이 문자열이 아닌 것들은 따로.
        if "ai_original" not in item_cols:
            conn.execute(text("ALTER TABLE checklist_items ADD COLUMN ai_original JSON DEFAULT '{}'"))
        if "verdict_source" not in item_cols:
            conn.execute(text("ALTER TABLE checklist_items ADD COLUMN verdict_source TEXT DEFAULT 'ai'"))
        if "overridden_at" not in item_cols:
            conn.execute(text("ALTER TABLE checklist_items ADD COLUMN overridden_at DATETIME"))

        # 협상·중재 진행 테이블. create_all 이 테이블은 만들어 주지만, 이미 만들어진 뒤에
        # 컬럼을 더하면(예: max_turns) 반영되지 않으므로 여기서 채운다.
        med_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(case_mediations)"))}
        if med_cols and "max_turns" not in med_cols:
            conn.execute(text("ALTER TABLE case_mediations ADD COLUMN max_turns INTEGER DEFAULT 0"))


def init_db() -> None:
    """테이블 생성(없으면) + 경량 마이그레이션 + 시드. api.py 기동 시 1회 호출한다."""
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_columns()
    with SessionLocal() as session:
        seed_intake(session)
        seed_demo_tracker(session)
