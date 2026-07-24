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


def _search(source_type: str, query: str, product_en: str = "", k: int = 6) -> str:
    store = _get_store()
    if store is None:
        return json.dumps([], ensure_ascii=False)
    filters = {"product_en": product_en} if (source_type == "decision" and product_en) else None
    try:
        hits = store.search(query, source_type=source_type, filters=filters, k=k)
    except Exception:
        return json.dumps([], ensure_ascii=False)
    out = []
    for _, c in hits:
        law = f"{c.metadata.get('law_name', '')} {c.metadata.get('article', '')}".strip()
        out.append({
            "source": c.chunk_id,
            "law": law or c.metadata.get("case_display", ""),
            "text": (c.text or "")[:400],
        })
    return json.dumps(out, ensure_ascii=False)


def _build_tools() -> list[Any]:
    """검색 도구 2종을 LangChain tool 로 만들어 반환. import 실패 시 빈 목록."""
    from langchain_core.tools import tool

    @tool
    def search_statutes(query: str, k: int = 6) -> str:
        """사건 사실로 관련 법령·조문을 검색한다. 검토 항목의 근거 법령으로 인용할 것.
        query: 검색할 사건 사실/쟁점 키워드. k: 가져올 조문 수(기본 6)."""
        return _search("statute", query, k=k)

    @tool
    def search_precedents(query: str, product_en: str = "", k: int = 4) -> str:
        """유사 분쟁조정 결정례를 검색한다. 검토 방향·배상 선례 참고용.
        query: 사건 사실/쟁점. product_en: 상품유형 필터(선택). k: 가져올 사례 수(기본 4)."""
        return _search("decision", query, product_en=product_en, k=k)

    return [search_statutes, search_precedents]


# ---- 폴백 계획 --------------------------------------------------------------


def _fallback_plan(product_en: str) -> ChecklistPlan:
    """LLM 사용 불가 시 최소 실계획(옛 더미가 아님). 담당자 확인이 필요함을 명시."""
    return ChecklistPlan(
        classification=f"{product_en or '민원'} (자동분류 보류)",
        track="legal",
        items=[
            ChecklistItem(item="사실관계 확인", law="내부 처리기준", source="fallback"),
            ChecklistItem(item="관련 법령 검토", law="금융소비자보호법", source="fallback"),
        ],
        reasoning="AI 검토계획 자동 생성이 일시적으로 불가하여 기본 검토 항목으로 접수했습니다. 담당자 확인이 필요합니다.",
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
            "이제 위 검색 결과만 근거로 최종 검토계획을 스키마로 출력하라. "
            "사실·검색 근거에 없는 조문/수치는 지어내지 마라. 법률 분쟁이 아니면 track='general' 로 두고 "
            "items 는 비워도 된다."
        )))
        structured = chat.with_structured_output(ChecklistPlan, method="function_calling")
        result = structured.invoke(messages)
        plan = result if isinstance(result, ChecklistPlan) else ChecklistPlan.model_validate(result)
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
