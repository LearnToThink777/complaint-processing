from __future__ import annotations

"""민원 처리 에이전트가 LLM에게 받아내는 구조화 출력 스키마입니다.

`민원 처리 콘솔 (단독 실행).html`은 이 값들을 전부 buildFrames() 안에
상수로 박아두었습니다. 이 파일은 "사람이 미리 써 둔 상수"였던 것을
"LLM이 채워야 할 구조화 출력"으로 승격시킨 스키마 정의입니다.

week02_structure_natural_language_requests.py와 동일한 규칙을 따릅니다.
  - Pydantic BaseModel + 한국어 Field(description=...)
  - LangChain with_structured_output / response_format 으로 바로 연결 가능
"""

from typing import Literal

from pydantic import BaseModel, Field


# 콘솔 시퀀스에 등장하는 6명의 액터 중 "말/글을 생성하는" 주체는 에이전트뿐입니다.
Verdict = Literal["위반", "미이행", "해당", "하자", "선례", "산정", "해당없음"]


class RegulatoryVerdict(BaseModel):
    """검토 항목 1건에 대한 규정 판정. 콘솔의 VERD[k] 상수에 대응합니다.

    입력(사건 사실 + 증거 + 적용 법률 항목) → 출력(조항·위반여부·근거).
    이것이 이 워크플로우에서 LLM이 하는 가장 핵심적인 '법률 검토' 추론입니다.
    """

    code: str = Field(description="적용 근거 코드/조항. 예: '제17조 적합성', '자본시장법 제49조', '분쟁조정 2024-1187'.")
    verdict: Verdict = Field(description="판정 결과 라벨. 위반/미이행/해당/하자/선례/산정/해당없음 중 하나.")
    ko: str = Field(description="한 줄 판정 요지. 예: '적합성원칙 위반 확인'.")
    detail: str = Field(description="판정 근거 상세. 사실관계에 기반한 짧은 설명. 예: '안정추구형 고객에 고위험 ELS 판매'.")


class DualDisclosure(BaseModel):
    """이중 공개 — 같은 판정을 두 독자에게 서로 다른 공개 등급으로 재작성.

    콘솔의 PLAINU(민원인용) + discloseR(감독원용) 상수에 대응합니다.
    같은 사실을 (1) 민원인에게는 법률 용어 없이 공감적으로,
    (2) 감독원에게는 법조문·수치를 포함한 기술적 리포트로 나눠 씁니다.
    내용(사실)은 동일하고 '표현 수위'만 다르게 하는 것이 규칙입니다.
    """

    complainant_title: str = Field(description="민원인용 안내 제목. 예: '진행 안내 #3 · 민원인용'.")
    complainant_body: str = Field(description="민원인용 본문. 법률 용어를 쓰지 않고 쉽고 공감적으로. 판정을 단정하지 않는다.")
    supervisor_title: str = Field(description="회사·감독원용 리포트 제목. 예: '검토 결과 #3 · 회사·감독원용'.")
    supervisor_body: str = Field(description="감독원용 본문. 적용 법률·판정·근거·남은 검토 건수를 포함한 기술적 요약.")


class SimilarCase(BaseModel):
    """사례 DB(벡터 검색)에서 조회된 유사 과거 분쟁 1건."""

    case: str = Field(description="유사 사례 식별자. 예: '분쟁조정 2023-0942 ELS'.")
    business_days: int = Field(description="그 사례의 실제 처리 소요 영업일 수.")


class SimilarCasesResult(BaseModel):
    """유사 사례 검색 + 완료일 추정 + 기한 초과 위험 판정.

    콘솔의 s.vector 상수 + '예상 완료 2026-08-29 > 처리 기한' 위험 배너에 대응.
    RAG(벡터 검색) 결과를 근거로 예상 완료일을 추정하고, 처리 기한과 비교합니다.
    """

    cases: list[SimilarCase] = Field(default_factory=list, description="검색된 유사 사례 목록.")
    estimated_completion: str = Field(description="추정 완료일 YYYY-MM-DD. 유사 사례 소요일 분포로 추정.")
    due_date: str = Field(description="현재 확정된 처리 기한 YYYY-MM-DD.")
    over_deadline_risk: bool = Field(description="추정 완료일이 처리 기한을 초과하면 True.")
    reasoning: str = Field(description="추정·위험 판정의 근거 한두 문장.")


class RenegotiationDraft(BaseModel):
    """기한 재협상 '재료' 초안. 에이전트는 자문·중재만 하고 결정은 사람이 합니다.

    콘솔의 협상 갈래(negoText) + 지연 안내(discloseU) + 감독원 협의(discloseR)에 대응.
    """

    blocking_items: list[str] = Field(default_factory=list, description="완료를 지연시키는 검토 항목 라벨 목록.")
    reason_for_complainant: str = Field(description="민원인에게 전할 지연 사유(쉬운 말).")
    evidence_for_supervisor: str = Field(description="회사·감독원에 전할 지연 요인 + 유사사례 근거(기술적).")
    recommended_new_due_date: str = Field(description="에이전트가 '권고'하는 새 처리 기한 YYYY-MM-DD. 확정 아님.")
    note: str = Field(default="에이전트는 자문·중재만 — 새 만기는 사람(민원인·감독원)이 결정", description="권한 경계 고지문.")


class ChecklistItem(BaseModel):
    """검토 항목 1건. 사건 사실에서 도출된 결과물이지 사전에 정해진 상수가 아닙니다."""

    item: str = Field(description="검토 항목 설명. 예: '적합성 원칙 위반 여부'.")
    law: str = Field(description="적용 법령/절차 근거명(사람이 읽는 라벨). 예: '금융소비자보호법 제17조'.")
    source: str = Field(description="근거 조문/청크 식별자(vectorDB 조회). 코퍼스에 없으면 law와 동일 문자열.")


class ChecklistPlan(BaseModel):
    """이관(intake) 시 사건 사실만 보고 '무엇을 검토해야 하는지' 스스로 도출한 계획.

    어떤 민원이 들어올지는 접수 전엔 알 수 없습니다. 따라서 검토 항목 목록 자체를
    미리 정해두지 않고, 사건 사실을 읽은 뒤(=이관 시점)에야 관련 법령·절차를
    vectorDB에서 찾아 항목을 구성합니다. Claude/Codex에게 질문을 던지면 그때 가서
    관련 근거를 찾아 답하는 것과 같은 순서 — 콘솔의 체크리스트 상수 자리를 대체합니다.
    """

    classification: str = Field(
        description="사건 유형 분류 라벨. 민원인의 사실관계 서술을 AI가 읽고 분류한 결과. "
        "예: 'ELS 불완전판매 의심'. 접수 전엔 존재하지 않고, 이 호출 이후 종결까지 고정된다."
    )
    items: list[ChecklistItem] = Field(default_factory=list, description="이 사건에 필요하다고 판단한 검토 항목들.")
    reasoning: str = Field(description="사건 사실에서 어떤 쟁점을 읽어 이 항목들을 도출했는지 한두 문장.")


class ChunkLabels(BaseModel):
    """색인(indexing) 시점에 청크 1개에 붙이는 '파생 라벨'. LLM이 채웁니다.

    청킹(자르기)·정형 메타데이터(파싱)는 LLM 없이 처리하고, 오직 이
    '의미를 새로 만들어내는' 라벨만 LLM 몫입니다. build_index.py가 각 청크에
    대해 task="chunk_label" 로 이 스키마를 채운 뒤 청크와 함께 임베딩합니다.

    everyday_questions 가 핵심 — 사용자는 '돈 떼였어요'라고 묻는데 문서는
    '채무불이행에 따른 손해배상'이라 쓰여 있는 비대칭을, 색인 때 미리 메꿉니다.
    """

    issue_summary: str = Field(description="이 청크가 다루는 쟁점 한 줄 요약(법률어 허용).")
    keywords: list[str] = Field(default_factory=list, description="검색용 키워드 몇 개.")
    everyday_questions: list[str] = Field(
        default_factory=list,
        description="이 청크로 답할 수 있는 '일상어' 질문들. 예: '원금 다 잃었어요', '설명 못 들었어요'.",
    )


# 콘솔이 다루는 하나의 사건 입력. LLM 호출들의 공통 컨텍스트가 됩니다.
class ComplaintCase(BaseModel):
    """민원 사건 입력. 콘솔 상단 CASE/Overview 카드에 대응."""

    case_id: str = Field(description="사건 번호. 예: 'C-2026-0713-018'.")
    product: str = Field(description="상품/민원 유형(한국어). 예: '주가연계증권(ELS) 불완전판매'.")
    product_en: str = Field(description="유형 영문. 예: 'ELS mis-selling'.")
    complainant: str = Field(description="민원인 표시명. 예: '홍*동 (개인)'.")
    intake_date: str = Field(description="접수일 YYYY-MM-DD.")
    facts: str = Field(description="사건 사실관계 요약(자연어). LLM 판정의 근거 텍스트.")


# ===========================================================================
# 중재(협상) 도메인 — 상담·검사 자리에서 에이전트가 '중간에서' 하는 일의 스키마.
#
# 기존 스키마(RegulatoryVerdict/DualDisclosure)가 '민원 처리의 결과물'이라면,
# 아래 스키마들은 그 결과가 나오기 전의 '협상·상담 과정' 그 자체를 담는다.
# 세 상담 시나리오(설명의무·꺾기·규정해석검사)에서 공통으로 관찰된
# 에이전트의 4가지 행동을 구조화한 것:
#   ① 양측 균형 자문   → MediationIssue (쟁점별 유리/불리 대칭 기록)
#   ② 판단 유보 선언   → MediationIssue.decider (판단 주체는 항상 에이전트 밖)
#   ③ 중립성 소명      → AdvisoryBalance (자문이 어느 쪽에 기울었는지 집계)
#   ④ 동일 이력 공유   → MediationLogEntry (양측이 같은 사본을 보는 처리이력)
# ===========================================================================

Leaning = Literal["A", "B", "neutral"]
IssueStatus = Literal["미확정", "확인중", "자료대기", "정리완료"]


class MediationParty(BaseModel):
    """중재 자리에 앉은 당사자 1명. 뷰 전환의 단위이기도 하다."""

    key: str = Field(description="뷰 식별 키(영문). 예: 'complainant', 'staff', 'supervisor'.")
    role: str = Field(description="역할 한국어 라벨. 예: '민원인', '회사 직원', '감독원 검사역'.")
    name: str = Field(description="표시명. 예: '김소연(63세)', '한지원 조사역'.")
    side: Literal["A", "B"] = Field(description="구도상 어느 편인지. A=민원인/피검사자, B=회사/감독원.")


class MediationIssue(BaseModel):
    """쟁점 1건에 대한 '양측 균형' 자문. 에이전트는 여기서 판정하지 않는다.

    핵심 규칙: for_a/against_a/for_b/against_b 를 모두 채워, 어느 한쪽에만
    유리하거나 불리한 사실만 적지 않는다. 시나리오에서 에이전트가 A에게
    유리한 소명 항목과 불리한 정황을 늘 함께 제시한 것을 그대로 옮긴 것.
    """

    code: str = Field(description="근거 조문/기준. 예: '금소법 제19조 설명의무', '제20조 불공정영업'.")
    title: str = Field(description="쟁점 한 줄. 예: '설명의무를 다했는지', '재진단이 자발적이었는지'.")
    for_a: str = Field(description="A(민원인/피검사자)에게 유리한 사실·소명 근거.")
    against_a: str = Field(description="A에게 불리하게 작용하는 정황.")
    for_b: str = Field(description="B(회사/감독원)에게 유리한 사실·근거.")
    against_b: str = Field(description="B의 주장에 걸리는 제한(단독 판단 기준이 못 되는 이유 등).")
    agent_note: str = Field(description="에이전트 자문 요지. 무엇이 핵심 판단축인지 + 판단 유보 취지.")
    decider: str = Field(description="이 쟁점의 최종 판단 주체. 항상 에이전트 밖. 예: '분쟁조정위·법원'.")
    status: IssueStatus = Field(description="쟁점 상태 라벨.")
    refs: list[int] = Field(default_factory=list, description="근거가 된 대화 메시지 번호들.")


class AdvisoryEntry(BaseModel):
    """자문 발언 1건이 어느 쪽에 유리/제한적으로 작용했는지의 태깅."""

    ref: int = Field(description="대화 메시지 번호.")
    leans: Leaning = Field(description="이 자문이 유리하게 작용한 쪽. A/B/neutral.")
    summary: str = Field(description="그 자문이 무엇을 유리/제한했는지 한 줄.")


class AdvisoryBalance(BaseModel):
    """중립성 밸런스 — 자문 전체가 어느 쪽으로 기울었는지 집계.

    '이 에이전트 저쪽 편 아니냐'는 당사자 의심([57]/[54])에 답하는 근거.
    A 유리 발언 수와 B 유리(=A 제한) 발언 수가 균형을 이루는지 보여준다.
    """

    entries: list[AdvisoryEntry] = Field(default_factory=list, description="자문별 기울기 태깅 목록.")
    note: str = Field(
        default="에이전트는 어느 편도 아니다 — 유리·불리 사실을 양측에 동일하게 기록한다.",
        description="중립성 고지문.",
    )


class MediationLogEntry(BaseModel):
    """공유 처리이력 한 줄. 양측이 '동일한 사본'을 본다는 점이 핵심.

    시나리오의 (자문)/(서기) 두 종류 발화를 하나의 시간축으로 합친 것.
    이중공개(청중별로 다르게 쓰는 글)와 달리, 이 로그는 양측에게 똑같다.
    """

    seq: int = Field(description="대화 메시지 번호(시간순 정렬 키).")
    kind: Literal["자문", "서기", "발언"] = Field(description="자문(해석)·서기(이력기록)·발언(당사자).")
    speaker: str = Field(description="화자 키. 'C'(에이전트) 또는 당사자 key.")
    text: str = Field(description="내용 한 줄 요약.")


class MediationRecord(BaseModel):
    """중재 콘솔이 다루는 상담·검사 1건 전체. mediation.html이 렌더한다."""

    case_id: str = Field(description="상담/검사 식별자. 예: 'M-2026-0714-002'.")
    domain: str = Field(description="도메인 한 줄. 예: 'ELS 원금손실, 설명의무 위반 민원'.")
    parties: list[MediationParty] = Field(default_factory=list, description="당사자 목록(=뷰 전환 단위).")
    issues: list[MediationIssue] = Field(default_factory=list, description="쟁점 중재 원장.")
    balance: AdvisoryBalance = Field(default_factory=AdvisoryBalance, description="중립성 밸런스 집계.")
    log: list[MediationLogEntry] = Field(default_factory=list, description="공유 처리이력 타임라인.")
    linked_case: str | None = Field(
        default=None,
        description="이 상담·중재가 넘어간 민원 처리 사건 번호(ComplaintCase.case_id). "
        "상담(사실확인·판단유보) → 처리(판정·이중공개)로 이어지는 같은 사건의 다음 단계. "
        "예: 'C-2026-0713-018'. 처리 단계로 넘어가지 않았으면 None.",
    )
    boundary: str = Field(
        default="에이전트는 규정 해석·사실 정리·이력 기록까지. 위반 여부 최종 판단은 감독원·분쟁조정위·법원.",
        description="에이전트 권한 경계 고지문(모든 시나리오 공통).",
    )
