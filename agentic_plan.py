from __future__ import annotations

"""AI 자동 검토계획 생성 — 실제 LLM 에이전트(tool calling) 방식.

기존 RetrievalLLM(llm.py) 은 checklist_plan 을 '결정론적 벡터검색 + 고정 절차항목'으로
채웠다. LLM 이 스스로 판단하는 게 아니라 코드가 정한 순서대로 항목을 만든 것이다.

이 모듈은 그 자리를 진짜 에이전트 루프로 바꾼다:
  1. LLM 에게 법령/결정례 검색 도구(tool)를 바인딩한다.
  2. LLM 이 사건 사실을 읽고 '필요하다고 판단하면' 스스로 도구를 호출해 근거를 모은다.
  3. 검색 근거를 바탕으로 최종 ChecklistPlan(schemas) 을 구조화 출력한다.

검색 도구는 기존 retrieval.py(VectorStore) 를 그대로 재사용해 LangChain tool 로 감쌌다.
LLM 호출은 MlapiLLM 과 동일한 프록시(mlapi.run)·인증(_load_mlapi_config)을 쓴다.

키 없음/네트워크/LLM 오류 시엔 예전 더미(STAFF_CHECKLIST_PLANS)로 돌아가지 않고,
_fallback_plan() 이 '담당자 확인 필요' 최소 실계획을 만들어 흐름이 끊기지 않게 한다.
"""

import json
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

# 검색 스코프(어떤 종류를, 어느 발급기관까지 근거로 삼을지)는 retrieval.py 가 단일 진실
# 원천이다 — 검색 호출부가 llm.py(스킬)·case_ai.py(유사사례)·여기(검토계획) 셋으로 갈라져
# 있어 각자 정하게 두면 같은 사건에 경로마다 다른 근거가 나온다(실제로 그랬다).
from .retrieval import (
    PRECEDENT_SOURCES as _PRECEDENT_SOURCES,
    STATUTE_SOURCES as _STATUTE_SOURCES,
    doc_key as _doc_key,
    finance_scoped as _finance_scoped,
)
from .schemas import ChecklistItem, ChecklistPlan

_PKG_DIR = Path(__file__).resolve().parent
_CORPUS_INDEX = _PKG_DIR / "corpus_index.json"

# provider → (모델 id, base_url 환경변수). get_backend 의 _REAL_BACKENDS 와 동일 규칙.
_PROVIDERS: dict[str, tuple[str, str]] = {
    "mlapi-nano": ("openai/gpt-5-nano", "MLAPI_NANO_BASE_URL"),
    "mlapi-mini": ("openai/gpt-5-mini", "MLAPI_BASE_URL"),
}

# 도구 호출 '라운드' 상한. 성능 기록으로 확인된 병목이 순차 LLM 왕복이라, 라운드를
# 최소로 둔다: 1이면 (도구 1라운드 실행) → (곧바로 최종 구조화 출력)으로 LLM 호출이
# 총 2회(에이전트형 tool calling의 하한). 예전 4는 "더 부를 도구 있나?"를 되묻는
# 왕복을 매번 1회씩 낭비했다. 더 깊은 탐색이 필요하면 이 값을 올린다(호출 수↑·시간↑).
_MAX_TOOL_ROUNDS = 1

_LLM_TIMEOUT_S = 90  # 단일 LLM 호출 타임아웃 — 멈추면 빠르게 fallback 으로 강등

# ---- VectorStore 지연 싱글턴 ------------------------------------------------
# corpus_index.json(74MB) 로드 + e5 임베딩 모델 생성은 매우 무겁다. 프로세스당 1회만
# 만들고 Lock 으로 감싸 백그라운드 스레드 동시 접근을 막는다.
_STORE: Any = None
_STORE_LOCK = threading.Lock()
_STORE_FAILED = False


def _get_store() -> Any:
    """corpus_index.json 로 VectorStore 를 1회 빌드해 캐시한다. 실패하면 None."""
    global _STORE, _STORE_FAILED
    if _STORE is not None or _STORE_FAILED:
        return _STORE
    with _STORE_LOCK:
        if _STORE is not None or _STORE_FAILED:
            return _STORE
        try:
            if not _CORPUS_INDEX.exists():
                _STORE_FAILED = True
                return None
            from .retrieval import Chunk, EmbeddingScorer, VectorStore, default_local_embed_fn

            raw = json.loads(_CORPUS_INDEX.read_text(encoding="utf-8"))
            chunks = [Chunk.model_validate(c) for c in raw]
            scorer = None
            if any(c.embedding for c in chunks):
                try:  # 색인과 같은 로컬 임베딩(e5-base). 실패 시 어휘겹침 폴백.
                    scorer = EmbeddingScorer(embed_fn=default_local_embed_fn())
                except Exception:
                    scorer = None
            _STORE = VectorStore(chunks, scorer=scorer)
        except Exception:
            _STORE_FAILED = True
            _STORE = None
    return _STORE


def warm_store() -> None:
    """VectorStore(74MB 코퍼스 + e5 임베딩 모델)를 미리 적재한다.

    첫 검토계획 생성이 콜드스타트 비용을 물지 않도록 서버 기동 시 백그라운드 스레드에서
    호출한다(api.py). 이미 적재됐으면 즉시 반환. 실패해도 조용히 넘어간다(검색 없이도
    생성은 fallback 으로 동작).
    """
    try:
        _get_store()
    except Exception:
        pass


# ---- LangChain 도구: 기존 검색을 tool 로 노출 -------------------------------


# source_type → 근거를 인용할 때 붙일 종류 라벨(LLM 이 무엇을 인용하는지 알도록).
_SOURCE_KIND_KO = {
    "statute": "법령",
    "law_interp": "법령해석례",
    "decision": "분쟁조정 결정례",
    "admin_decision": "행정 결정례",
}


def _citation(c: Any) -> str:
    """청크 → 근거 인용 문자열. 코퍼스 종류마다 식별 필드가 달라 여기서 흡수한다."""
    m = c.metadata
    if c.source_type == "statute":
        return f"{m.get('law_name', '')} {m.get('article', '')}".strip()
    if c.source_type == "law_interp":
        return f"법제처 법령해석례 {m.get('안건번호', m.get('doc_id', ''))}".strip()
    if c.source_type == "admin_decision":
        return f"{m.get('org_name', '')} {m.get('의결번호', m.get('doc_id', ''))}".strip()
    return m.get("case_display", c.chunk_id)


def _hits_to_json(hits: list[Any], k: int) -> str:
    """검색 결과 → LLM 이 읽을 근거 목록. 문서 단위로 중복을 걷어 상위 k건만 남긴다.

    코퍼스는 한 결정문을 섹션(안건명/조치이유/조치내용…)별로 쪼개 색인해 두었다.
    걷지 않으면 상위 4건이 같은 문서 4섹션으로 채워져 실제 근거는 1건뿐인 일이 생긴다.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, c in hits:
        key = _doc_key(c)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "source": c.chunk_id,
            "kind": _SOURCE_KIND_KO.get(c.source_type, c.source_type),
            "law": _citation(c) or c.chunk_id,
            "title": c.metadata.get("title", ""),
            "text": (c.text or "")[:400],
        })
        if len(out) == k:
            break
    return json.dumps(out, ensure_ascii=False)


def _search(sources: tuple[str, ...], query: str, product_en: str = "", k: int = 6) -> str:
    """지정한 코퍼스 종류들에서 검색한다. 상품유형 필터가 0건이면 필터를 풀고 재검색한다.

    필터 폴백이 중요한 이유: product_en 메타는 분쟁조정 결정례 12청크에만 붙어 있어,
    필터를 걸면 보험·대출·예금 사건은 항상 0건이 된다. '해당 유형 없음'을 근거 없음으로
    끝내지 않고, 같은 쟁점의 다른 유형 선례라도 돌려줘 판단 재료를 남긴다.

    섹션 중복을 걷어내야 하므로 넉넉히(k*4) 뽑아 _hits_to_json 에서 문서 단위로 줄인다.
    """
    store = _get_store()
    if store is None:
        return json.dumps([], ensure_ascii=False)
    try:
        hits: list[Any] = []
        if product_en:
            hits = store.search(query, source_types=sources, filters={"product_en": product_en},
                                where=_finance_scoped, k=k * 4)
        if not hits:
            hits = store.search(query, source_types=sources, where=_finance_scoped, k=k * 4)
    except Exception:
        return json.dumps([], ensure_ascii=False)
    return _hits_to_json(hits, k)


def _search_statutes_layered(query: str, k: int = 6) -> str:
    """법령 조문에 자리를 먼저 배정하고, 남는 자리를 법령해석례로 채운다.

    한 후보군에 섞어 유사도만으로 뽑으면 수가 많은 쪽(해석례 147 vs 조문 23)이 자리를
    독식한다(실측: 3칸 중 2칸). 그런데 검토 항목의 근거로는 조문이 해석례보다 강하다 —
    해석례는 조문 해석의 보조 자료다. 그래서 절반 이상을 조문에 먼저 준다.
    조문이 그만큼 안 나오면(코퍼스에 없으면) 남은 자리는 자연히 해석례가 가져간다.
    """
    store = _get_store()
    if store is None:
        return json.dumps([], ensure_ascii=False)
    primary_k = max(1, (k + 1) // 2)
    try:
        laws = store.search(query, source_type="statute", k=primary_k)
        interps = store.search(query, source_types=("law_interp",), where=_finance_scoped, k=k * 4)
    except Exception:
        return json.dumps([], ensure_ascii=False)
    # 조문을 앞에 두고 해석례로 잔여 자리를 채운다(_hits_to_json 이 k개에서 자른다).
    return _hits_to_json(list(laws) + list(interps), k)


def _build_tools() -> list[Any]:
    """검색 도구 2종을 LangChain tool 로 만들어 반환. import 실패 시 빈 목록."""
    from langchain_core.tools import tool

    @tool
    def search_statutes(query: str, k: int = 6) -> str:
        """사건 사실로 관련 법령·조문과 법령해석례를 검색한다. 검토 항목의 근거로 인용할 것.
        반환 항목의 kind 가 '법령'이면 조문, '법령해석례'면 법제처 해석이다.
        query: 검색할 사건 사실/쟁점 키워드. k: 가져올 건수(기본 6)."""
        return _search_statutes_layered(query, k=k)

    @tool
    def search_precedents(query: str, product_en: str = "", k: int = 4) -> str:
        """유사 선례를 검색한다 — 분쟁조정 결정례와 금융위·금감원 행정 결정례(제재·조치 사례).
        검토 방향·배상 선례 참고용. 반환 항목의 kind 로 어느 쪽인지 구분된다.
        query: 사건 사실/쟁점. product_en: 상품유형 필터(선택, 0건이면 자동 해제).
        k: 가져올 사례 수(기본 4)."""
        return _search(_PRECEDENT_SOURCES, query, product_en=product_en, k=k)

    return [search_statutes, search_precedents]


# ---- 폴백 계획 --------------------------------------------------------------


# 금융소비자보호법 6대 판매원칙 — 예금·펀드·ELS·보험·대출 어느 유형에도 적용되는 공통 검토축.
# 검색이 그 분야 근거를 하나도 못 물어와 LLM 이 검토 항목을 0개로 낸 경우, 사건을 '검토 항목
# 없음'으로 흘려보내지 않고 이 축으로 최소 검토를 세운다(= 판정이 반드시 생성된다).
_BASELINE_COMMON: list[tuple[str, str]] = [
    ("고객 투자성향·재산상황 대비 상품 권유의 적합성", "금융소비자보호법 제17조(적합성원칙)"),
    ("상품의 주요 내용·위험에 대한 설명의무 이행 여부", "금융소비자보호법 제19조(설명의무)"),
    ("계약 체결 과정의 불공정영업행위 해당 여부", "금융소비자보호법 제20조(불공정영업행위 금지)"),
    ("권유 과정의 부당권유행위 해당 여부", "금융소비자보호법 제21조(부당권유행위 금지)"),
]

# 상품유형별 추가 검토축. product_en 에 포함된 키워드로 고른다(부분일치).
_BASELINE_BY_PRODUCT: list[tuple[tuple[str, ...], tuple[str, str]]] = [
    (("insurance",), ("고지의무 위반 주장의 대상성·인과관계", "상법 제651조·제655조(고지의무)")),
    (("loan", "대부"), ("대출 관련 구속성 판매(꺾기)·중도상환수수료 산정의 적정성",
                       "금융소비자보호법 제20조(불공정영업행위 금지)")),
    (("deposit",), ("만기·자동재예치 등 계약조건 안내와 고객 동의 확보 여부",
                    "금융소비자보호법 제19조(설명의무)")),
    (("ELS", "DLF", "DLS", "fund"), ("투자성 상품 적정성 진단 절차의 실질 이행 여부",
                                     "금융소비자보호법 제18조(적정성원칙)")),
]


def _baseline_items(product_en: str) -> list[ChecklistItem]:
    """상품유형에 맞는 최소 검토 항목. source='baseline' 로 표시해 화면·감사에서 구분 가능."""
    pe = (product_en or "").lower()
    items = [ChecklistItem(item=it, law=law, source="baseline") for it, law in _BASELINE_COMMON]
    for keys, (it, law) in _BASELINE_BY_PRODUCT:
        if any(kk.lower() in pe for kk in keys):
            items.append(ChecklistItem(item=it, law=law, source="baseline"))
    return items


def _fallback_plan(product_en: str) -> ChecklistPlan:
    """LLM 사용 불가 시 최소 실계획(옛 더미가 아님). 담당자 확인이 필요함을 명시."""
    return ChecklistPlan(
        classification=f"{product_en or '민원'} (자동분류 보류)",
        track="legal",
        items=_baseline_items(product_en),
        reasoning="AI 검토계획 자동 생성이 일시적으로 불가하여 금융소비자보호법 공통 판매원칙 기준의 "
                  "기본 검토 항목으로 접수했습니다. 담당자 확인이 필요합니다.",
    )


# ---- 질의 쪽 키워드 브리징 --------------------------------------------------
# 색인 쪽은 chunk_label 로 문서에 keywords/everyday_questions 를 붙여 임베딩한다(retrieval).
# 질의 쪽엔 그게 없었다 — 민원인의 빈약한 일상어 facts 가 그대로 검색 query 로 쓰였다.
# 여기서 접수 사실관계를 '검색용 키워드(CaseKeywords)'로 승격해, 아래 에이전트가 그 키워드·
# 질의로 search_statutes/search_precedents 를 호출하게 한다(하이브리드의 '추출' 절반).


def extract_keywords(facts: str, product_en: str, *, provider: str = "mlapi-nano") -> Any:
    """접수 사실관계에서 검색용 키워드(schemas.CaseKeywords)를 뽑는다.

    실LLM 우선, 키 없음/오류면 결정론적 오프라인 더미(_mock_keyword_extraction)로 폴백해
    흐름이 끊기지 않게 한다(검토계획 fallback 과 같은 철학). 반환은 항상 CaseKeywords.
    """
    from .schemas import CaseKeywords

    ctx = {"facts": facts, "product_en": product_en}
    for use_llm in (True, False):  # 실LLM → 실패 시 더미
        try:
            from .llm import get_backend

            be = get_backend(use_llm=use_llm, provider=provider, observe=False)
            return be.structured("keyword_extraction", CaseKeywords, ctx)
        except Exception:
            continue
    return CaseKeywords()


def _keywords_hint(keywords: Any) -> str:
    """CaseKeywords → 에이전트 첫 지시문에 붙일 '검색 힌트' 블록(하이브리드의 '프롬프트 강화' 절반).

    키워드가 없거나(폴백 전면 실패) 비어 있으면 빈 문자열 — 예전 동작과 동일하게 흘러간다.
    """
    if keywords is None:
        return ""
    terms = ", ".join([*(getattr(keywords, "issue_terms", None) or []),
                       *(getattr(keywords, "entities", None) or [])])
    queries = "; ".join(getattr(keywords, "search_queries", None) or [])
    if not terms and not queries:
        return ""
    lines = ["\n\n[접수 시 추출된 검색 키워드 — 이 질의로 먼저 검색하라]"]
    if terms:
        lines.append(f"- 쟁점·주체 키워드: {terms}")
    if queries:
        lines.append(f"- 추천 검색 질의: {queries}")
    lines.append("위 키워드·질의를 우선 활용해 search_statutes/search_precedents 를 호출하고, 부족하면 사실에서 스스로 보완하라.")
    return "\n".join(lines)


# ---- 에이전트 루프 ----------------------------------------------------------


def generate_checklist_plan_agentic(
    facts: str,
    product_en: str,
    *,
    provider: str = "mlapi-nano",
    keywords: Any = None,
) -> tuple[ChecklistPlan, str, int, float, str]:
    """실제 LLM 에이전트로 검토계획을 생성한다.

    반환: (plan, provider_used, tool_calls, duration_ms, error).
    provider_used 는 성공 시 provider 이름, 실패로 폴백하면 'fallback'.
    duration_ms 는 이 함수 전체(도구 호출 왕복 포함) 소요시간 — "왜 수십 초 걸리는지"를
    나중에 /api/perf/summary 로 따져볼 수 있게 항상 재는 것이 이 함수의 핵심 책임 중 하나다.
    """
    t0 = time.perf_counter()
    tool_calls = 0
    try:
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
        from langchain_openai import ChatOpenAI

        from .llm import _load_mlapi_config, build_system_prompt

        model_id, base_url_env = _PROVIDERS.get(provider, _PROVIDERS["mlapi-nano"])
        api_key, base_url = _load_mlapi_config(base_url_env)  # 키/URL 없으면 RuntimeError
        # temperature 미지정 — GPT-5 계열은 기본값(1)만 허용(MlapiLLM 주석 참고).
        # timeout: 멈춘 호출을 오래 붙들지 않고 예외 → fallback 으로. max_retries=0: 재시도로
        # 소요시간이 배가되는 것을 막는다(우리는 실패 시 fallback 이 있으므로 재시도 불필요).
        chat = ChatOpenAI(model=model_id, api_key=api_key, base_url=base_url,
                          timeout=_LLM_TIMEOUT_S, max_retries=0)

        tools = _build_tools()
        ctx = {"facts": facts, "product_en": product_en}
        messages: list[Any] = [
            SystemMessage(content=build_system_prompt("checklist_plan", ctx)),
            HumanMessage(content=(
                "사건 사실을 읽고, 필요하면 search_statutes/search_precedents 도구로 "
                "관련 법령·결정례를 검색해 근거를 모아라. 근거가 충분하면 도구를 더 부르지 말고 "
                "다음 단계에서 최종 검토계획을 낼 준비가 됐다고만 답하라." + _keywords_hint(keywords)
            )),
        ]

        if tools:
            llm_tools = chat.bind_tools(tools)
            tool_map = {t.name: t for t in tools}
            for _ in range(_MAX_TOOL_ROUNDS):
                ai = llm_tools.invoke(messages)
                messages.append(ai)
                calls = getattr(ai, "tool_calls", None) or []
                if not calls:
                    break  # 도구를 안 불렀으면 바로 최종 출력으로
                for call in calls:
                    tool_calls += 1
                    fn = tool_map.get(call["name"])
                    result = fn.invoke(call["args"]) if fn else "[]"
                    messages.append(ToolMessage(content=result, tool_call_id=call["id"]))
                # 도구 결과를 얻었으면 '더 부를까'를 되묻지 않고 곧장 최종 출력으로 간다
                # (그 되묻는 invoke 1회가 예전 병목이었다). 더 깊은 탐색은 _MAX_TOOL_ROUNDS↑.

        # 최종 구조화 출력 — _invoke_structured 와 동일 관용구(function_calling).
        messages.append(HumanMessage(content=(
            "이제 최종 검토계획을 스키마로 출력하라. 사실·검색 근거에 없는 조문/수치는 지어내지 마라.\n"
            "중요: 검색 결과가 빈약하다는 이유로 items 를 비우지 마라. 금융상품 거래에 관한 민원이면 "
            "검색 근거가 부족해도 금융소비자보호법의 공통 판매원칙(적합성·적정성·설명의무·불공정영업·"
            "부당권유)을 축으로 무엇을 확인해야 하는지 검토 항목을 세울 수 있다 — 그것이 이 단계의 일이다. "
            "track='general' 은 금융상품 거래 자체가 쟁점이 아닌 단순 안내·조회 민원일 때만 쓴다."
        )))
        structured = chat.with_structured_output(ChecklistPlan, method="function_calling")
        result = structured.invoke(messages)
        plan = result if isinstance(result, ChecklistPlan) else ChecklistPlan.model_validate(result)
        # 그래도 항목이 0개로 오면 공통 판매원칙 기준의 최소 검토축을 붙인다. 검토 항목이
        # 0개면 뒤따르는 판정 생성이 통째로 생략돼 사건이 '판정 없이' 끝나기 때문이다.
        #
        # track 조건을 걸지 않는 이유(실측): 대출 민원 C-2026-07-113 은 LLM 이 reasoning 에
        # 금소법 제19조·제17조·제21조를 스스로 짚어 놓고도 "아직 법적 분쟁이 확정되지 않았다"며
        # track='general' + items=0 으로 빠져나가 판정이 영영 생성되지 않았다. 근거 부족은
        # 판정을 안 할 이유가 되지 못한다 — 금융상품 사건이면(product_en 이 'general' 이 아니면)
        # 최소 검토축을 세우고 legal 트랙으로 되돌린다. 단순 안내·조회(product 'etc')는 제외.
        is_financial = bool(product_en) and product_en.lower() != "general"
        if not plan.items and is_financial:
            plan.items = _baseline_items(product_en)
            plan.track = "legal"
            plan.reasoning = (plan.reasoning or "").rstrip()
            plan.reasoning += (
                (" " if plan.reasoning else "")
                + "이 분야의 직접 근거를 충분히 확보하지 못했으나, 금융상품 거래 민원이므로 "
                  "금융소비자보호법 공통 판매원칙을 축으로 최소 검토 항목을 세웠습니다. "
                  "담당자 확인이 필요합니다."
            )
        duration_ms = (time.perf_counter() - t0) * 1000
        return plan, provider, tool_calls, duration_ms, ""
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000
        return _fallback_plan(product_en), "fallback", tool_calls, duration_ms, repr(exc)


# ---- 백그라운드 트리거 ------------------------------------------------------


def run_plan_generation(case_id: str, *, provider: str = "mlapi-nano") -> None:
    """접수 직후 BackgroundTasks 로 도는 작업 — 검토계획을 생성해 DB 에 저장한다.

    자기 세션(session_scope)을 새로 연다(요청 세션을 넘겨받지 않는다 — 스레드 경계).
    소요시간·도구호출 횟수는 perf.record() 로 DB(performance_logs) + PERFORMANCE_LOG.md 에 남긴다.
    """
    from sqlalchemy import select

    from . import perf
    from .db import session_scope
    from .models import Case, ChecklistItemRow, ReviewPlan, StageEvent

    with session_scope() as s:
        case = s.execute(select(Case).where(Case.case_id == case_id)).scalar_one_or_none()
        if case is None:
            return
        # ① 검색용 키워드를 확보한다. 민원인이 접수 전 AI 쟁점 분석(/analyze)에서 확인·보정한
        #    키워드가 이미 사건에 실려 있으면 그대로 재사용(재추출 없이 — 민원인 보정 존중 + LLM
        #    호출 절감). 없으면(직원 이관·시드 사건 등) 여기서 사실관계로부터 추출해 영속한다.
        # ② 확보한 키워드를 검토계획 에이전트에 넘겨 검색 질의를 강화한다(하이브리드).
        from .schemas import CaseKeywords

        if case.keywords:
            keywords = CaseKeywords.model_validate(case.keywords)
        else:
            keywords = extract_keywords(case.facts, case.product_en, provider=provider)
            case.keywords = keywords.model_dump()
        plan, provider_used, tool_calls, duration_ms, error = generate_checklist_plan_agentic(
            case.facts, case.product_en, provider=provider, keywords=keywords
        )
        rp = ReviewPlan(
            case_fk=case.id,
            classification=plan.classification,
            track=plan.track,
            reasoning=plan.reasoning,
            status="ready",
            provider=provider_used,
            duration_ms=duration_ms,
        )
        s.add(rp)
        s.flush()
        for i, it in enumerate(plan.items, start=1):
            rp.items.append(ChecklistItemRow(plan_fk=rp.id, seq=i, item=it.item, law=it.law, source=it.source))
        # AI 분류 결과를 사건에도 반영
        if plan.classification:
            case.complaint_type = plan.classification
        case.track = plan.track
        prev = case.status
        case.status = "plan_ready"
        s.add(StageEvent(case_fk=case.id, from_status=prev, to_status="plan_ready", actor="system",
                         note=f"AI 검토계획 생성 완료(provider={provider_used}, {duration_ms/1000:.1f}s)"))
        s.commit()  # perf.record() 가 별도 커밋을 하므로 그 전에 본 트랜잭션을 먼저 반영

    # session_scope 밖에서 기록 — perf.record() 는 자기 세션을 새로 열어 독립적으로 커밋한다.
    from .db import SessionLocal

    with SessionLocal() as perf_session:
        perf.record(
            perf_session,
            task="checklist_plan_agentic",
            case_id=case_id,
            provider=provider_used,
            duration_ms=duration_ms,
            tool_calls=tool_calls,
            item_count=len(plan.items),
            outcome="ok" if provider_used != "fallback" else "fallback",
            error=error,
        )
