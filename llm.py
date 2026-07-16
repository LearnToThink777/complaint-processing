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
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .tasks import task_registry

T = TypeVar("T", bound=BaseModel)

FIXTURES_PATH = Path(__file__).with_name("fixtures.json")
ENV_PATH = Path(__file__).with_name(".env")


def build_system_prompt(task: str, context: dict[str, Any]) -> str:
    """공통 지시문(base_guide) + task별 프롬프트(build_prompt(context))를 이어붙인다.

    프롬프트 '내용'은 tasks.py의 각 build_prompt 함수가 소유한다(커맨드). 이 함수는
    실제 LLM 백엔드(ProxyLLM·GeminiLLM)가 공유하는 조립 규칙일 뿐이다 — 백엔드가
    바뀌어도 프롬프트는 동일하게 나온다.
    """
    reg = task_registry()
    base = reg.base_guide
    if task in reg:
        body = reg.get(task).build_prompt(context)
    else:  # 미등록 task 방어 — context를 통째로 덤프
        body = f"[컨텍스트]\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    return f"{base}\n\n{body}"


def _load_gemini_api_key() -> str:
    """.env(있으면)를 읽어 GEMINI_API_KEY(또는 GOOGLE_API_KEY)를 돌려준다."""
    import os

    try:  # python-dotenv 가 있으면 .env 를 환경변수로 로드
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
    except ModuleNotFoundError:
        pass  # 없으면 이미 환경변수에 있다고 가정
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            f".env 에 GEMINI_API_KEY 가 없습니다. Google AI Studio에서 발급받아 "
            f"{ENV_PATH} 에 'GEMINI_API_KEY=...' 로 넣으세요."
        )
    return key


class LLMBackend(ABC):
    """구조화 출력 백엔드의 공통 인터페이스 — 전략(Strategy) 패턴의 Strategy 역할.

    오케스트레이터(agent.py)는 이 인터페이스에만 의존하고, 실제 구현이 더미(MockLLM)인지
    실제 LLM(ProxyLLM)인지 모른다. 그래서 두 전략을 런타임에 바꿔 끼울 수 있다.
    """

    @abstractmethod
    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        ...


class MockLLM(LLMBackend):
    """fixtures.json 기반 더미 백엔드. 실제 LLM 없이 콘솔과 동일한 결과를 만듭니다.

    task별 payload 조립 로직은 이 클래스가 아니라 tasks.py의 TaskSpec.build_mock 이
    소유한다(커맨드 패턴). MockLLM은 task 이름으로 레지스트리를 조회해 그 빌더를
    호출하고, 결과를 스키마로 검증할 뿐이다.
    """

    def __init__(self, fixtures_path: Path = FIXTURES_PATH) -> None:
        self._fx = json.loads(fixtures_path.read_text(encoding="utf-8"))

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        spec = task_registry().get(task)          # 미등록 task면 ValueError
        payload = spec.build_mock(context, self._fx)
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

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        model = self._chat_model().with_structured_output(schema, method="function_calling")
        result = model.invoke(
            [
                {"role": "system", "content": build_system_prompt(task, context)},
                {"role": "user", "content": f"task={task} 에 대한 구조화 출력을 반환하라."},
            ]
        )
        # with_structured_output은 이미 schema 인스턴스를 주지만, dict로 올 경우까지 방어.
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            return schema.model_validate(result)
        raise RuntimeError(f"예상치 못한 LLM 응답 형태: {type(result)!r}")


class GeminiLLM(LLMBackend):
    """Google Gemini(무료 티어)를 쓰는 실제 LLM 백엔드.

    ProxyLLM과 같은 관용구(with_structured_output(schema, method="function_calling"))를
    쓰되, 백엔드가 fixed.llm 프록시가 아니라 langchain-google-genai의
    ChatGoogleGenerativeAI 다. 프롬프트 조립은 build_system_prompt(→ tasks.py의
    build_prompt)에 위임하므로, ProxyLLM 과 완전히 동일한 프롬프트가 나간다.

    API 키는 .env 의 GEMINI_API_KEY 에서 읽는다(없으면 생성 시점에 실패). 무료 티어는
    GPU·서버가 필요 없다 — 로컬은 HTTP 요청만 보내고 계산은 Google이 한다.
    """

    # gemini-flash-latest: 구글이 최신 무료 flash로 자동 연결하는 별칭. 특정 버전
    # (gemini-2.5-flash 등)은 신규 계정에 막히거나 deprecate되므로 별칭이 가장 견고.
    def __init__(self, model: str = "gemini-flash-latest", temperature: float = 0.0) -> None:
        api_key = _load_gemini_api_key()
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "langchain-google-genai 가 설치돼 있지 않습니다. "
                "pip install -r requirements.txt (또는 pip install langchain-google-genai) 하세요."
            ) from exc
        self.model_name = model
        # temperature=0: 판정/작문의 재현성을 위해 기본은 결정론적으로.
        self._llm = ChatGoogleGenerativeAI(model=model, temperature=temperature, google_api_key=api_key)

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        model = self._llm.with_structured_output(schema, method="function_calling")
        result = model.invoke(
            [
                {"role": "system", "content": build_system_prompt(task, context)},
                {"role": "user", "content": f"task={task} 에 대한 구조화 출력을 반환하라."},
            ]
        )
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


def get_backend(
    use_llm: bool = False,
    retrieval_index: str | Path | None = None,
    *,
    provider: str = "gemini",
    facts: str = "",
    observe: bool = True,
    retries: int = 0,
    cache: bool = False,
    critic: bool = False,
    critic_enforce: bool = False,
    today: date | None = None,
) -> LLMBackend:
    """LLM 전략을 골라 데코레이터까지 조립하는 팩토리 메서드(Factory Method).

    호출부는 "어떤 전략/기능이 필요한지"만 말하고, 어떤 구체 클래스를 어떻게 생성·조합할지는
    이 함수가 캡슐화한다. 기본은 MockLLM(오프라인). use_llm=True면 실제 LLM을 쓰며,
    어느 실제 백엔드를 쓸지는 provider로 고른다:
      - provider="gemini"(기본): GeminiLLM — Google Gemini 무료 티어(.env의 GEMINI_API_KEY)
      - provider="proxy"       : ProxyLLM — fixed.llm 프록시(chonnam-clone 저장소 필요)

    retrieval_index를 주면 그 위에 RetrievalLLM(데코레이터)을 덧씌워 #0/#3만 실검색으로
    바꾼다. #1/#2/#4/#5는 base(Mock/실제LLM)가 담당한다.

    관측/재시도/캐시는 데코레이터로 겉을 감싼다(AgentOps 이음새) — 감싸도 출력은 동일하다:
      - observe=True(기본): ObservableLLM 으로 호출별 소요시간·성공/실패 계측
      - retries>0        : RetryingLLM 으로 실패 재시도
      - cache=True       : CachingLLM 으로 동일 호출 결과 캐시
      - critic=True      : CriticLLM 으로 출력을 근거(law/facts)에 대조(할루시네이션 검증)
                           critic_enforce=True면 BLOCK 판정 시 CriticBlocked 예외로 산출 차단
                           실제 LLM(gemini) 모드면 semantic 검증도 GeminiSemanticVerifier로
                           올린다(어휘겹침 근사 대신 실제 함의 판정).
    today 를 주면 유사사례 예상 완료일 계산의 기준일을 고정한다(미지정 시 실제 date.today()).
    """

    if use_llm:
        base: LLMBackend = GeminiLLM() if provider == "gemini" else ProxyLLM()
    else:
        base = MockLLM()
    backend: LLMBackend = (
        RetrievalLLM(retrieval_index, base=base, facts=facts, today=today) if retrieval_index else base
    )

    # 지역 import로 순환참조 회피(decorators 는 llm.LLMBackend 를 import 한다).
    from .decorators import CachingLLM, CriticLLM, ObservableLLM, RetryingLLM

    if critic:
        # 실제 LLM(gemini) 모드면 Critic의 semantic 검증도 Gemini로. 그 외엔 기본(어휘겹침).
        semantic = None
        if use_llm and provider == "gemini":
            from .critic import GeminiSemanticVerifier

            semantic = GeminiSemanticVerifier()
        backend = CriticLLM(backend, enforce=critic_enforce, semantic=semantic)  # 출력을 근거에 대조
    if cache:
        backend = CachingLLM(backend)
    if retries:
        backend = RetryingLLM(backend, max_retries=retries)
    if observe:
        backend = ObservableLLM(backend)  # 가장 바깥 — 에이전트가 실제 부르는 전 호출을 계측
    return backend
