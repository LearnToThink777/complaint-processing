from __future__ import annotations

"""Task 정의 — 커맨드(Command) 패턴 + 레지스트리(싱글턴).

LLM 호출 '종류' 하나(task)를 객체 하나(TaskSpec)로 캡슐화한다.
예전에는 task 문자열이 세 군데에 흩어져 있었다:
  1) MockLLM.structured 의 if/elif 라우팅 (더미 payload 조립)
  2) ProxyLLM._system_prompt 의 guides dict (실제 LLM 지시문)
  3) 호출부(agent.py)의 self.llm.structured("task이름", ...)

그래서 task 하나를 추가/수정하려면 파일 두 곳(1·2)을 동시에 고쳐야 했다.
이제 TaskSpec 하나(지시문 guide + 더미 빌더 build_mock)를 레지스트리에 등록하면
백엔드 코드는 손대지 않는다 — 백엔드는 task 이름으로 레지스트리를 조회할 뿐이다.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable

# (context, fixtures) -> payload dict. 더미(MockLLM)가 스키마에 넣을 값을 조립하는 함수.
MockBuilder = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class TaskSpec:
    """LLM 호출 한 종류를 캡슐화한 커맨드.

    - name       : task 식별자
    - guide      : 실제 LLM(ProxyLLM)에게 줄 작업 지시문
    - build_mock : 더미(MockLLM)가 fixtures/context로 payload를 조립하는 함수
    출력 스키마는 호출부가 structured(task, schema, ...)로 넘겨주므로 여기 두지 않는다.
    """

    name: str
    guide: str
    build_mock: MockBuilder


# ---- 각 task 의 더미 payload 빌더 (예전 MockLLM.structured 의 if/elif 분기) --------

def _mock_verdict(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    n = context["item_no"]
    return dict(fx["verdict"][str(n)])


def _mock_disclosure(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    n = context["item_no"]
    d = fx["disclosure"][str(n)]
    remaining = context.get("remaining", 0)
    return {
        "complainant_title": f"진행 안내 #{n} · 민원인용 / Complainant",
        "complainant_body": d["complainant_body"],
        "supervisor_title": f"검토 결과 #{n} · 회사·감독원용 / Supervisor",
        # 남은 검토 건수는 오케스트레이터가 세어서 넘겨준 값을 반영(=콘솔과 동일 문구).
        "supervisor_body": f"{d['supervisor_body']} 남은 검토 {remaining}건 · 전체 근거 원장 반영.",
    }


def _mock_similar_cases(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    return dict(fx["similar_cases"])


def _mock_renegotiation(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    return dict(fx["renegotiation"])


def _mock_closing_disclosure(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 종결 문구는 미리 정해둘 수 없다 — 실제 원장(ledger)의 판정을 읽고 나서야
    # '무슨 문제가 확인됐고 배상비율이 얼마인지' 알 수 있다.
    ledger = context.get("ledger", [])
    issues = [l for l in ledger if l["verdict"] in ("위반", "미이행", "하자", "해당")]
    award = next((l for l in ledger if l["verdict"] == "산정"), None)
    detail = award["detail"] if award else "배상비율 산정 결과 없음"
    found = bool(issues)
    return {
        "complainant_title": "처리 결과 안내 / To complainant",
        "complainant_body": (
            f"검토 결과 {'문제가 확인되어 배상이 산정되었습니다' if found else '문제가 확인되지 않았습니다'}"
            f"({detail}). 이후 절차와 제출 서류를 쉽게 안내드릴게요."
        ),
        "supervisor_title": "사건 종결 리포트 / To supervisor",
        "supervisor_body": f"{len(ledger)}개 항목 전부 ② 원장 반영. {detail}. 처리 이력 로그 종료.",
    }


def _mock_checklist_plan(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 더미는 실제 검색 없이 fixtures의 데모 항목을 '이 사건에서 도출한 것처럼' 되돌린다
    # (사실을 읽어 코퍼스를 검색하는 버전은 RetrievalLLM).
    items = fx["checklist"]
    return {
        "classification": f"{fx['case']['product']} 의심",
        "items": [{"item": c["item"], "law": c["law"], "source": c["law"]} for c in items],
        "reasoning": "사건 사실에서 쟁점 키워드를 추출해 유형을 분류하고 관련 법령·절차 항목을 구성했습니다.",
    }


def _mock_chunk_label(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 색인용 일상어 라벨. 더미는 텍스트에서 순진하게 파생시킨다(요지=첫 구절, 키워드=명사 후보).
    text = context.get("text", "")
    head = re.split(r"[。.\n]", text.strip(), maxsplit=1)[0][:40]
    kws = list(dict.fromkeys(re.findall(r"[가-힣]{2,}", text)))[:5]
    return {
        "issue_summary": head,
        "keywords": kws,
        "everyday_questions": [f"{k} 관련해서 문제가 있어요" for k in kws[:3]],
    }


# ---- task 정의(커맨드 목록) — 실제 LLM 지시문(guide) + 더미 빌더 -----------------

_BASE_GUIDE = (
    "너는 금융 민원 처리 에이전트다. 사건 사실관계와 적용 법률에 근거해서만 판단하고, "
    "사실을 지어내지 않는다. 애매하면 단정하지 않는다."
)

_ALL_SPECS: list[TaskSpec] = [
    TaskSpec(
        "checklist_plan",
        (
            "방금 이관받은 사건이다. 사건 유형 분류와 검토 항목 목록 둘 다 아직 정해지지 않았다 — "
            "사건 사실을 읽고 사건 유형을 분류하고(classification), 어떤 법령·절차 위반 여부를 "
            "검토해야 하는지 스스로 도출하라. 각 항목의 근거 법령·절차도 함께 밝혀라. "
            "사실에 없는 근거를 지어내지 않는다."
        ),
        _mock_checklist_plan,
    ),
    TaskSpec(
        "verdict",
        "주어진 검토 항목 1건을 사건 사실에 대조해 규정 판정을 내려라.",
        _mock_verdict,
    ),
    TaskSpec(
        "disclosure",
        (
            "같은 판정을 두 독자에게 나눠 써라. 민원인용은 법률 용어 없이 쉽고 공감적으로, "
            "회사·감독원용은 법조문·판정·근거를 포함해 기술적으로. 사실은 동일하게 유지한다."
        ),
        _mock_disclosure,
    ),
    TaskSpec(
        "similar_cases",
        "유사 과거 분쟁 사례를 근거로 예상 완료일을 추정하고 처리 기한 초과 위험을 판정하라.",
        _mock_similar_cases,
    ),
    TaskSpec(
        "renegotiation",
        (
            "기한 재협상 '재료'만 초안한다. 너는 자문·중재자이며 새 기한을 확정하지 않는다. "
            "결정은 사람(민원인·감독원)이 한다. context의 similar_cases(유사사례별 소요 영업일)와 "
            "estimated_completion(그 사례들로 추정한 완료일)을 근거로 삼아 evidence_for_supervisor와 "
            "recommended_new_due_date를 작성하라. 근거에 없는 수치를 지어내지 않는다."
        ),
        _mock_renegotiation,
    ),
    TaskSpec(
        "closing_disclosure",
        (
            "사건이 종결됐다. 미리 정해둔 결과를 말하지 말고, 주어진 원장(ledger)의 실제 판정들을 "
            "읽어 무슨 문제가 확인됐는지와 배상비율을 반영해 종결 안내를 작성하라. "
            "민원인용은 쉽고 공감적으로, 감독원용은 기술적으로."
        ),
        _mock_closing_disclosure,
    ),
    TaskSpec(
        "chunk_label",
        (
            "색인 대상 텍스트 조각(법령 조문 또는 분쟁조정 결정문 섹션)을 읽고, 검색이 잘 되도록 "
            "쟁점 한 줄 요약·키워드·'일상어 질문'을 생성하라. 일상어 질문은 법률어를 모르는 "
            "민원인이 실제로 던질 법한 문장이어야 한다(예: '원금 다 잃었어요', '설명 못 들었어요')."
        ),
        _mock_chunk_label,
    ),
]


# ---- 레지스트리(싱글턴) — 프로세스 전체가 하나의 task 목록을 공유 -----------------


class TaskRegistry:
    """등록된 TaskSpec들을 보관하는 싱글턴. task 이름 → TaskSpec 조회 담당.

    싱글턴(Singleton): 프로세스 안에서 인스턴스가 하나만 존재하도록 보장한다.
    백엔드(MockLLM/ProxyLLM)는 각자 목록을 들고 있지 않고 이 하나를 조회한다.
    """

    _instance: "TaskRegistry | None" = None

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSpec] = {}

    def register(self, spec: TaskSpec) -> None:
        self._tasks[spec.name] = spec

    def get(self, name: str) -> TaskSpec:
        try:
            return self._tasks[name]
        except KeyError:
            raise ValueError(f"알 수 없는 task: {name}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._tasks

    @property
    def base_guide(self) -> str:
        """모든 task 프롬프트 앞에 붙는 공통 지시문."""
        return _BASE_GUIDE


def task_registry() -> TaskRegistry:
    """싱글턴 인스턴스를 돌려준다(최초 호출 때 _ALL_SPECS로 채워 1회 생성)."""
    if TaskRegistry._instance is None:
        reg = TaskRegistry()
        for spec in _ALL_SPECS:
            reg.register(spec)
        TaskRegistry._instance = reg
    return TaskRegistry._instance
