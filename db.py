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

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Base,
    Case,
    CaseMessage,
    Customer,
    NotificationSetting,
    Staff,
    StageEvent,
)

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


# 계정 시드 — 로그인이 붙는 순간 '로그인 가능한 계정 0개'가 되지 않도록 여기서 만든다.
# 정보의 출처는 demo_store 의 정적 프로필(그동안 화면이 쓰던 값)이라 화면이 그대로 이어진다.
# 직원을 2명 두는 이유: 담당자가 1명이면 stage_events.actor_id 없이도 우연히 맞아서
# '남의 활동이 내 활동으로 보이는' 문제를 재현할 수 없다.
DEMO_CUSTOMER_ID = "CUST-0001"
DEMO_STAFF_ID = "STAFF-0001"

# 데모 자격증명은 팀 공통이다 — 지영(PR #2 seed.py)·태은(PR #3)이 같은 이메일·비밀번호로
# 맞춰 두었으므로, 누가 만든 DB 든 서로의 코드로 로그인된다. 바꾸면 그 호환이 깨진다.
_SEED_CUSTOMERS: list[dict] = [
    {"customer_id": DEMO_CUSTOMER_ID, "name": "김지은", "email": "jieun.kim@example.com",
     "phone": "010-2345-6789", "verified": True, "password": "customer1234!"},
]

_SEED_STAFF: list[dict] = [
    {"staff_id": DEMO_STAFF_ID, "name": "홍길동", "email": "hong.gildong@internal.com",
     "dept": "준법감시팀", "rank": "선임조사역", "phone": "010-1234-5678",
     "password": "employee1234!"},
    {"staff_id": "STAFF-0002", "name": "이수진", "email": "sujin.lee@internal.com",
     "dept": "준법감시팀", "rank": "조사역", "phone": "010-8765-4321",
     "password": "employee1234!"},
]

# 알림 기본값 — demo_store 의 리터럴 목록과 같은 키를 쓴다(화면 어휘를 그대로 잇는다).
_SEED_NOTIFS: dict[str, list[tuple[str, bool]]] = {
    "customer": [("progress", True), ("notice", True), ("event", False)],
    "staff": [("due_soon", True), ("ai_done", True), ("transfer", True), ("system", False)],
}


def seed_accounts(session: Session) -> None:
    """민원인·직원 계정과 알림 기본값을 넣는다. 이미 있으면 건너뛴다(멱등).

    비밀번호 해시는 계정을 만들 때 넣지만, **이미 만들어진 계정**(로그인 도입 전에 심어져
    password_hash 가 빈 행)도 있으므로 아래에서 따로 채워 준다 — 삽입만으로는 그 행에
    해시가 생기지 않아 로그인이 조용히 실패한다.
    """
    from .auth.service import hash_password  # 순환 import 방지 — auth 가 models 를 쓴다

    def _fields(row: dict) -> dict:
        out = {k: v for k, v in row.items() if k != "password"}
        out["password_hash"] = hash_password(row["password"])
        return out

    if not session.execute(select(Customer.customer_id).limit(1)).first():
        for row in _SEED_CUSTOMERS:
            session.add(Customer(**_fields(row)))
    if not session.execute(select(Staff.staff_id).limit(1)).first():
        for row in _SEED_STAFF:
            session.add(Staff(**_fields(row)))
    session.flush()

    # 해시 백필 — 로그인 도입 전에 심어진 계정(빈 password_hash)에만 채운다.
    # 이미 해시가 있는 계정은 건드리지 않는다(사용자가 바꾼 비밀번호를 시드로 되돌리면 안 된다).
    for model, id_attr, rows in ((Customer, "customer_id", _SEED_CUSTOMERS),
                                 (Staff, "staff_id", _SEED_STAFF)):
        for row in rows:
            obj = session.execute(
                select(model).where(getattr(model, id_attr) == row[id_attr])).scalars().first()
            if obj is not None and not obj.password_hash:
                obj.password_hash = hash_password(row["password"])

    owners = [("customer", c["customer_id"]) for c in _SEED_CUSTOMERS] + \
             [("staff", s["staff_id"]) for s in _SEED_STAFF]
    for owner_type, owner_id in owners:
        have = {k for (k,) in session.execute(
            select(NotificationSetting.notif_key)
            .where(NotificationSetting.owner_type == owner_type,
                   NotificationSetting.owner_id == owner_id)
        ).all()}
        for key, enabled in _SEED_NOTIFS[owner_type]:
            if key not in have:
                session.add(NotificationSetting(owner_type=owner_type, owner_id=owner_id,
                                                notif_key=key, enabled=enabled))
    session.commit()


def link_demo_identities(session: Session) -> None:
    """계정 도입 전에 쌓인 사건·이력에 소유자를 귀속시킨다(비어 있는 것만).

    이름 매칭 백필을 일반 원칙으로 삼지는 않는다 — 이름은 식별자가 아니고 동명이인을
    가릴 수 없다. 다만 아래 둘은 귀속이 확실하다:

    1) 시드 페르소나('김지은') 사건 — 우리가 만든 계정이다.
    2) actor="staff" 인 기존 stage_events — 계정이 없던 동안 직원은 '홍길동' 한 명뿐이었고
       화면도 그 사건들의 담당자를 홍길동으로 표시해왔다(demo_db.staff_recent_cases).
       이걸 NULL 로 남기면 '소유자 미상' 행이 남아, 조회 시 모든 직원에게 보이거나
       아무에게도 안 보이거나 둘 중 하나가 된다 — 둘 다 사실과 다르다.

    시드가 아닌 이름의 사건은 건드리지 않고 NULL(소유자 미상)로 남긴다.
    """
    for row in _SEED_CUSTOMERS:
        session.execute(
            update(Case).where(Case.customer == row["name"], Case.customer_id.is_(None))
            .values(customer_id=row["customer_id"])
        )
        session.execute(
            update(StageEvent).where(StageEvent.actor == "citizen", StageEvent.actor_id.is_(None))
            .values(actor_id=row["customer_id"])
        )
    session.execute(
        update(StageEvent).where(StageEvent.actor == "staff", StageEvent.actor_id.is_(None))
        .values(actor_id=DEMO_STAFF_ID)
    )
    session.commit()


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
        # 종결 결과(수용/일부수용/기각). 종결 전에는 NULL 이므로 기본값을 두지 않는다.
        if "outcome" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN outcome TEXT"))

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

        # 계정 계층(customers/staff)이 생기면서 사건에 소유자·담당자가 붙는다.
        # 여기 ALTER 를 빠뜨리고 models.py 에만 선언하면 ORM 이 없는 컬럼을 SELECT 해서
        # cases 를 건드리는 모든 요청이 OperationalError 로 죽는다 — 반드시 쌍으로 유지한다.
        # nullable 로만 붙일 수 있다: SQLite 는 NOT NULL(기본값 없음)·UNIQUE·REFERENCES 컬럼을
        # 기존 테이블에 추가하지 못한다. 그래서 기존 사건은 소유자 미상(NULL)으로 남는다.
        for col in ("customer_id", "assigned_staff_id"):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE cases ADD COLUMN {col} TEXT"))

        # stage_events.actor_id — actor(system|staff|citizen)가 '종류'만 알려주고 '누구'인지는
        # 몰랐다. 이 블록이 없어서 stage_events 는 그동안 마이그레이션 대상이 아니었다.
        ev_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(stage_events)"))}
        if ev_cols and "actor_id" not in ev_cols:
            conn.execute(text("ALTER TABLE stage_events ADD COLUMN actor_id TEXT"))

        # 인덱스 보정 — create_all 은 기존 테이블을 통째로 건너뛰고 ALTER 는 인덱스를 만들 수
        # 없다. 이걸 빠뜨리면 새로 만든 DB 만 인덱스를 갖고 기존 DB 는 풀스캔이 되는데
        # 스키마 diff 로는 눈에 띄지 않는다.
        for idx, tbl, col in (
            ("ix_cases_customer_id", "cases", "customer_id"),
            ("ix_cases_assigned_staff_id", "cases", "assigned_staff_id"),
            ("ix_stage_events_actor_id", "stage_events", "actor_id"),
        ):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl}({col})"))


def init_db() -> None:
    """테이블 생성(없으면) + 경량 마이그레이션 + 시드. api.py 기동 시 1회 호출한다."""
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_columns()
    with SessionLocal() as session:
        seed_accounts(session)   # 사건보다 먼저 — 사건이 소유자를 참조한다
        seed_intake(session)
        seed_demo_tracker(session)
        link_demo_identities(session)  # 계정 도입 전 사건·이력에 소유자 귀속(비어 있는 것만)
