from __future__ import annotations

"""LLM 호출 경계(boundary).

민원 처리 콘솔은 '에이전트가 판정/작문한 결과'를 전부 상수로 박아놨습니다.
이 파일은 그 상수 자리를 하나의 함수 시그니처로 바꿉니다:

    structured(task, schema, context) -> schema 인스턴스

백엔드는 두 가지입니다.
  - MockLLM   : fixtures.json에서 더미 답을 꺼내 스키마로 검증해 돌려줌 (오프라인 기본값)
  - ProxyLLM  : fixed/llm.py의 chat_model()을 with_structured_output으로 감싼 실제 호출

두 백엔드가 '같은 스키마'를 반환하므로, 오케스트레이터(agent.py)는
어느 쪽이 붙었는지 몰라도 동일하게 동작합니다. 더미 → 실제 LLM 교체가
agent.py 수정 없이 이 파일 안에서만 일어납니다.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

FIXTURES_PATH = Path(__file__).with_name("fixtures.json")


class LLMBackend:
    """구조화 출력 백엔드의 공통 인터페이스."""

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        raise NotImplementedError


class MockLLM(LLMBackend):
    """fixtures.json 기반 더미 백엔드. 실제 LLM 없이 콘솔과 동일한 결과를 만듭니다.

    task 문자열로 fixtures의 어떤 답을 꺼낼지 라우팅합니다:
      - "verdict"       : context["item_no"] 로 verdict[str(n)] 조회
      - "disclosure"    : context["item_no"] + verdict/checklist 로 이중 공개 조립
      - "similar_cases" : similar_cases 그대로
      - "renegotiation" : renegotiation 그대로
    실제 LLM이라면 context(사건 사실·판정)를 읽고 생성할 값들입니다.
    """

    def __init__(self, fixtures_path: Path = FIXTURES_PATH) -> None:
        self._fx = json.loads(fixtures_path.read_text(encoding="utf-8"))

    def _checklist_meta(self, n: int) -> dict[str, Any]:
        for c in self._fx["checklist"]:
            if c["n"] == n:
                return c
        raise KeyError(f"checklist #{n} 없음")

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        payload: dict[str, Any]

        if task == "verdict":
            n = context["item_no"]
            payload = dict(self._fx["verdict"][str(n)])

        elif task == "disclosure":
            n = context["item_no"]
            d = self._fx["disclosure"][str(n)]
            remaining = context.get("remaining", 0)
            payload = {
                "complainant_title": f"진행 안내 #{n} · 민원인용 / Complainant",
                "complainant_body": d["complainant_body"],
                "supervisor_title": f"검토 결과 #{n} · 회사·감독원용 / Supervisor",
                # 남은 검토 건수는 오케스트레이터가 세어서 넘겨준 값을 반영(=콘솔과 동일 문구).
                "supervisor_body": f"{d['supervisor_body']} 남은 검토 {remaining}건 · 전체 근거 원장 반영.",
            }

        elif task == "similar_cases":
            payload = dict(self._fx["similar_cases"])

        elif task == "renegotiation":
            payload = dict(self._fx["renegotiation"])

        elif task == "closing_disclosure":
            # 종결 문구는 미리 정해둘 수 없다 — 실제 원장(ledger)의 판정을 읽고 나서야
            # '무슨 문제가 확인됐고 배상비율이 얼마인지' 알 수 있다.
            ledger = context.get("ledger", [])
            issues = [l for l in ledger if l["verdict"] in ("위반", "미이행", "하자", "해당")]
            award = next((l for l in ledger if l["verdict"] == "산정"), None)
            detail = award["detail"] if award else "배상비율 산정 결과 없음"
            found = bool(issues)
            payload = {
                "complainant_title": "처리 결과 안내 / To complainant",
                "complainant_body": (
                    f"검토 결과 {'문제가 확인되어 배상이 산정되었습니다' if found else '문제가 확인되지 않았습니다'}"
                    f"({detail}). 이후 절차와 제출 서류를 쉽게 안내드릴게요."
                ),
                "supervisor_title": "사건 종결 리포트 / To supervisor",
                "supervisor_body": f"{len(ledger)}개 항목 전부 ② 원장 반영. {detail}. 처리 이력 로그 종료.",
            }

        elif task == "checklist_plan":
            # 사건 사실을 읽고 분류 + 검토 항목 자체를 도출. 더미는 실제 검색 없이
            # fixtures의 데모 항목을 '이 사건에서 도출한 것처럼' 그대로 되돌린다
            # (실제로 사실을 읽어 코퍼스를 검색하는 버전은 RetrievalLLM).
            items = self._fx["checklist"]
            payload = {
                "classification": f"{self._fx['case']['product']} 의심",
                "items": [{"item": c["item"], "law": c["law"], "source": c["law"]} for c in items],
                "reasoning": "사건 사실에서 쟁점 키워드를 추출해 유형을 분류하고 관련 법령·절차 항목을 구성했습니다.",
            }

        elif task == "chunk_label":
            # 색인용 일상어 라벨. 실제 LLM이라면 청크를 읽고 생성할 값을,
            # 더미는 텍스트에서 순진하게 파생시킨다(요지=첫 구절, 키워드=명사 후보).
            text = context.get("text", "")
            head = re.split(r"[。.\n]", text.strip(), maxsplit=1)[0][:40]
            kws = list(dict.fromkeys(re.findall(r"[가-힣]{2,}", text)))[:5]
            payload = {
                "issue_summary": head,
                "keywords": kws,
                "everyday_questions": [f"{k} 관련해서 문제가 있어요" for k in kws[:3]],
            }

        else:
            raise ValueError(f"알 수 없는 task: {task}")

        # 실제 LLM 구조화 출력과 똑같이 '스키마 검증'을 거쳐 반환 → 더미도 타입 안전.
        return schema.model_validate(payload)


class ProxyLLM(LLMBackend):
    """fixed/llm.py의 프록시 chat_model()을 쓰는 실제 LLM 백엔드.

    week02와 동일한 관용구: chat_model().with_structured_output(schema, method="function_calling").
    PROXY_TOKEN이 .env에 있어야 하며, 없으면 생성 시점에 실패합니다.
    """

    def __init__(self) -> None:
        # 이 폴더는 chonnam-clone 저장소 밖(Downloads)에 독립적으로 둔 것이라
        # fixed.llm(프록시 chat_model)을 쓰려면 그 저장소 경로가 sys.path에 필요합니다.
        # 환경변수 CHONNAM_CLONE_REPO로 저장소 경로를 지정하세요.
        import os
        import sys

        repo = os.environ.get("CHONNAM_CLONE_REPO")
        if repo and repo not in sys.path:
            sys.path.insert(0, repo)

        try:
            from fixed.llm import chat_model
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "fixed.llm을 찾을 수 없습니다. chonnam-clone 저장소 경로를 "
                "CHONNAM_CLONE_REPO 환경변수로 지정하세요. "
                "예: set CHONNAM_CLONE_REPO=C:\\Users\\alstj\\Downloads\\kakaotechcampus04\\chonnam-clone"
            ) from exc

        self._chat_model = chat_model

    def _system_prompt(self, task: str, context: dict[str, Any]) -> str:
        base = (
            "너는 금융 민원 처리 에이전트다. 사건 사실관계와 적용 법률에 근거해서만 판단하고, "
            "사실을 지어내지 않는다. 애매하면 단정하지 않는다."
        )
        guides = {
            "checklist_plan": (
                "방금 이관받은 사건이다. 사건 유형 분류와 검토 항목 목록 둘 다 아직 정해지지 않았다 — "
                "사건 사실을 읽고 사건 유형을 분류하고(classification), 어떤 법령·절차 위반 여부를 "
                "검토해야 하는지 스스로 도출하라. 각 항목의 근거 법령·절차도 함께 밝혀라. "
                "사실에 없는 근거를 지어내지 않는다."
            ),
            "verdict": "주어진 검토 항목 1건을 사건 사실에 대조해 규정 판정을 내려라.",
            "disclosure": (
                "같은 판정을 두 독자에게 나눠 써라. 민원인용은 법률 용어 없이 쉽고 공감적으로, "
                "회사·감독원용은 법조문·판정·근거를 포함해 기술적으로. 사실은 동일하게 유지한다."
            ),
            "similar_cases": "유사 과거 분쟁 사례를 근거로 예상 완료일을 추정하고 처리 기한 초과 위험을 판정하라.",
            "renegotiation": (
                "기한 재협상 '재료'만 초안한다. 너는 자문·중재자이며 새 기한을 확정하지 않는다. "
                "결정은 사람(민원인·감독원)이 한다."
            ),
            "closing_disclosure": (
                "사건이 종결됐다. 미리 정해둔 결과를 말하지 말고, 주어진 원장(ledger)의 실제 판정들을 "
                "읽어 무슨 문제가 확인됐는지와 배상비율을 반영해 종결 안내를 작성하라. "
                "민원인용은 쉽고 공감적으로, 감독원용은 기술적으로."
            ),
            "chunk_label": (
                "색인 대상 텍스트 조각(법령 조문 또는 분쟁조정 결정문 섹션)을 읽고, 검색이 잘 되도록 "
                "쟁점 한 줄 요약·키워드·'일상어 질문'을 생성하라. 일상어 질문은 법률어를 모르는 "
                "민원인이 실제로 던질 법한 문장이어야 한다(예: '원금 다 잃었어요', '설명 못 들었어요')."
            ),
        }
        return f"{base}\n{guides.get(task, '')}\n[컨텍스트]\n{json.dumps(context, ensure_ascii=False, indent=2)}"

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        model = self._chat_model().with_structured_output(schema, method="function_calling")
        result = model.invoke(
            [
                {"role": "system", "content": self._system_prompt(task, context)},
                {"role": "user", "content": f"task={task} 에 대한 구조화 출력을 반환하라."},
            ]
        )
        # with_structured_output은 이미 schema 인스턴스를 주지만, dict로 올 경우까지 방어.
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema.model_validate(result)
        raise RuntimeError(f"예상치 못한 LLM 응답 형태: {type(result)!r}")


class RetrievalLLM(LLMBackend):
    """(b) 검색 백엔드 — task="checklist_plan"과 "similar_cases"만 진짜 벡터 검색으로 처리.

    나머지 task(#1 verdict / #2 disclosure / #4 renegotiation)는 검색과 무관하므로
    base 백엔드(기본 MockLLM)에 그대로 위임합니다. 즉 이 클래스는 '#0/#3 자리만'
    목업에서 실검색으로 갈아끼우는 데코레이터입니다.

    corpus_index.json(build_index.py 산출물)을 읽어 VectorStore를 만들고,
    - #0(checklist_plan): 사건 사실로 법령 코퍼스를 질의해 검토 항목 자체를 도출
    - #3(similar_cases) : 사건 사실 + 상품유형(product_en) 필터로 유사 결정문을 조회
    각각 대응 스키마로 조립합니다. agent.py는 이 사실을 모릅니다.
    """

    def __init__(
        self,
        index_path: str | Path,
        *,
        base: LLMBackend | None = None,
        facts: str = "",
        today: date | None = None,
    ) -> None:
        from .retrieval import Chunk, VectorStore

        self._base = base or MockLLM()
        self._facts = facts
        self._today = today or date.today()
        raw = json.loads(Path(index_path).read_text(encoding="utf-8"))
        self._store = VectorStore([Chunk.model_validate(c) for c in raw])

    # 코퍼스에 없는(=법조문이 아닌) 표준 처리 절차. 사건과 무관하게 항상 필요하므로
    # 검색 대상이 아니라 고정 워크플로 단계로 취급한다.
    _PROCEDURAL_ITEMS = [
        {"item": "판매 녹취·서류 확인", "law": "금융상품 판매 감독기준"},
        {"item": "유사 분쟁조정 사례 대비", "law": "금융분쟁조정위원회 결정사례"},
        {"item": "손해배상 비율 산정", "law": "분쟁조정 기준"},
    ]

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        if task == "checklist_plan":
            # 사건 사실을 코퍼스에 질의해 '어느 법령 위반 여부를 검토해야 하는지'
            # 실제로 찾아낸다. 항목 자체가 사전에 정해져 있지 않다 — 사실을 읽은
            # 뒤에야 몇 건이, 무엇이 나올지 결정된다.
            facts = context.get("facts", "")
            hits = self._store.search(facts, source_type="statute", k=len(self._store.chunks))
            items = []
            for _, c in hits:
                law_name = c.metadata.get("law_name", "")
                article = c.metadata.get("article", "")
                # 항목 문구는 '{법령} {조} 위반 여부'로 통일(가독성). 실제 근거는 source(청크 ID)가 담당.
                items.append({"item": f"{article} 위반 여부", "law": f"{law_name} {article}", "source": c.chunk_id})
            # 법조문 매칭 결과 뒤에, 사건과 무관하게 항상 필요한 절차 항목을 덧붙인다.
            items += [{**p, "source": p["law"]} for p in self._PROCEDURAL_ITEMS]
            sector = hits[0][1].metadata.get("sector", "") if hits else ""
            product_en = context.get("product_en", "")
            payload = {
                "classification": f"{product_en} 의심" + (f" ({sector} 권역)" if sector else ""),
                "items": items,
                "reasoning": (
                    f"사건 사실을 코퍼스({len(self._store.chunks)}청크)에 질의해 관련 법령 "
                    f"{len(hits)}건을 찾고, 표준 처리 절차 {len(self._PROCEDURAL_ITEMS)}건을 더해 검토 항목을 구성했습니다."
                ),
            }
            return schema.model_validate(payload)

        if task == "similar_cases":
            from .retrieval import assemble_similar_cases

            query = self._facts or context.get("product_en", "")
            payload = assemble_similar_cases(
                self._store,
                query=query,
                product_en=context["product_en"],
                due_date=context.get("due_date") or "",
                today=self._today,
            )
            return schema.model_validate(payload)

        return self._base.structured(task, schema, context)


def get_backend(use_llm: bool = False, retrieval_index: str | Path | None = None, *, facts: str = "") -> LLMBackend:
    """기본은 MockLLM(오프라인). use_llm=True면 프록시 LLM을 시도합니다.

    retrieval_index를 주면 그 위에 RetrievalLLM을 덧씌워 #3(유사사례)만 실검색으로
    바꿉니다. #1/#2/#4는 base(use_llm에 따라 Mock/Proxy)가 그대로 담당합니다.
    """

    base: LLMBackend = ProxyLLM() if use_llm else MockLLM()
    if retrieval_index:
        return RetrievalLLM(retrieval_index, base=base, facts=facts)
    return base
