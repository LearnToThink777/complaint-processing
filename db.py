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
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Case, StageEvent

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
# case_id 는 기존과 동일하게 둬서 처리현황(STAFF_CASE_DETAILS, 아직 더미)과 어긋나지 않게 한다.
# channel="referred": 직원 이관 사건(민원인 앱 제출이 아님). status="intake": 검토계획 생성 전.
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


def init_db() -> None:
    """테이블 생성(없으면) + 경량 마이그레이션 + 시드. api.py 기동 시 1회 호출한다."""
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_columns()
    with SessionLocal() as session:
        seed_intake(session)
