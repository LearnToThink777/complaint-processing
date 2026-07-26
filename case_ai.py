from __future__ import annotations

"""승인 후 사건 AI 처리 — 규정 판정(ledger) 생성 + 사건별 유사사례 실검색.

agentic_plan.py 가 '접수→검토계획'을 담당한다면, 이 모듈은 그 다음 단계다:
  - run_verdict_generation : 직원이 처리현황에서 '판정 생성'을 누르면 백그라운드로 돌며,
        승인된 검토계획의 항목 전부를 verdict_batch LLM 1회 호출로 판정해 DB(checklist_items)에
        영속하고 사건을 status='verdict'(판정 완료)로 전이한다. 이것이 없어서 그동안 사건이
        '검토 중'에 영구히 멈춰 있었다.
  - search_similar_for_case: 처리현황에서 선택한 '그 사건'의 접수 사실·키워드로 결정례를
        실검색한다(하드코딩 질의 아님). 코퍼스에 같은 상품유형 결정례가 없으면(예: 보험)
        전체 결정례에서 의미상 가장 가까운 선례로 폴백하고 그 사실을 reasoning 에 명시한다.

검색 인프라(VectorStore 싱글턴)는 agentic_plan 이 이미 소유하므로 그대로 재사용한다.
LLM 키 부재/네트워크 오류 시엔 흐름을 끊지 않는다 — 판정은 오프라인 더미(MockLLM)로,
검색은 빈 결과 + 안내 문구로 강등한다(검토계획 생성의 fallback 철학과 동일).
"""

import time
from datetime import date
from typing import Any

from .schemas import RegulatoryVerdict, VerdictBatch


# ---- 신뢰도 검증(critic) — 경량 규칙 -----------------------------------------
# NOTE: 지금은 판정 텍스트만 보고 배지를 매기는 '경량 규칙'이다(추가 LLM 호출 없음).
#       향후 critic.py 의 CriticLLM(판정을 근거 법령·사실에 실제로 대조하는 검증)으로
#       교체·확장할 수 있다 — 그때 이 함수 자리에 CriticLLM 호출을 끼우면 배지 소비 측
#       (처리현황 UI/critic_summary)은 그대로 둔 채 정확도만 올릴 수 있게 설계해 두었다.
# 판정이 스스로 '아직 확정 못 했다'고 말하는 표지. 이게 들어 있으면 길이와 무관하게
# 사람 확인이 필요하다(PASS 금지).
#
# 왜 필요해졌나: 판정 프롬프트에 "무엇이 확인되면 판정이 뒤집히는지 반드시 적어라"를
# 넣자 detail 이 항상 길어졌고, 길이만 보던 옛 규칙(len >= 20 → PASS)에서 전 항목이
# PASS 를 받게 됐다. '녹취를 확인해야 한다'는 유보가 담긴 판정이 '근거 일치 · 자동 통과'
# 배지를 다는 상태였다 — 배지가 의미를 잃는다.
_UNSETTLED_MARKERS = (
    "확인이 필요", "확인 필요", "확인되어야", "확인되면", "확인된다면", "확인할 필요",
    "추가 자료", "추가 확인", "자료가 제출되면", "제출되면", "보완이 필요",
    "판단 필요", "판단이 필요", "확정 불가", "단정하기 어렵", "보기 어렵",
    "판정을 보류", "보류", "가능성이 있", "가능성 있", "소지가 있", "여지가 있",
    "뒤집힐", "바뀔 수 있",
)


def derive_critic(v: RegulatoryVerdict) -> str:
    """규정 판정 1건 → 신뢰도 배지(PASS/ESCALATE/BLOCK). 경량 규칙 기반(임시).

    PASS 는 '이 판정은 근거 위에서 확정됐다'는 뜻이므로 아끼는 것이 맞다. 사람이 더 볼
    필요가 남아 있으면 ESCALATE 로 올려 보내는 편이, 확인이 필요한 판정을 통과시키는
    것보다 안전하다(오탐의 비용 < 미탐의 비용).
    """
    detail = (v.detail or "").strip()
    if not detail:
        # 근거 상세 없이 내려진 판정 — '근거 밖'으로 보고 차단(사람이 반드시 확인).
        return "BLOCK"
    if len(detail) < 20 or v.verdict in ("산정", "선례"):
        # 근거가 빈약하거나(짧은 상세) 수치·선례를 인용하는 판정은 사람 확인이 필요.
        return "ESCALATE"
    if any(m in detail for m in _UNSETTLED_MARKERS) or any(m in (v.ko or "") for m in _UNSETTLED_MARKERS):
        # 판정문 스스로 확인이 남았다고 말한다 — 확정으로 통과시키지 않는다.
        return "ESCALATE"
    return "PASS"


CRITIC_ORDER = {"BLOCK": 0, "ESCALATE": 1, "PASS": 2}


# ---- 규정 판정 생성(승인 후, 백그라운드) ------------------------------------


def _fallback_verdict(item: str, law: str) -> RegulatoryVerdict:
    """LLM 사용 불가 시 최소 판정 — 담당자 확인이 필요함을 명시(옛 더미가 아님)."""
    return RegulatoryVerdict(
        code=law or "내부 처리기준",
        verdict="해당없음",
        ko=f"{item} — 자동 판정 보류",
        detail="AI 판정 자동 생성이 일시적으로 불가하여 판정을 보류했습니다. 담당자 확인이 필요합니다.",
    )


def _call_verdict_batch(items: list[dict[str, Any]], facts: str, *, provider: str) -> list[RegulatoryVerdict]:
    """verdict_batch LLM 1회 호출 → 판정 목록(개수는 보장되지 않는다). 실패 시 예외."""
    from .llm import get_backend

    ctx = {
        "items": [{"n": it["seq"], "item": it["item"], "law": it["law"]} for it in items],
        "facts": facts,
    }
    be = get_backend(use_llm=True, provider=provider, observe=False)
    return list(be.structured("verdict_batch", VerdictBatch, ctx).verdicts)


def _generate_verdicts(
    items: list[dict[str, Any]], facts: str, *, provider: str
) -> tuple[list[tuple[RegulatoryVerdict, bool]], str, str]:
    """검토 항목 전부를 판정한다. 모자란 항목은 그 항목들만 다시 물어 채운다.

    반환: ([(verdict, is_fallback), ...], provider_used, error) — 항목 수와 길이가 같다.

    재요청이 필요한 이유(실측): 항목이 5개일 때 gpt-5-nano 가 1개만 돌려주는 일이 있다.
    예전엔 모자란 만큼을 조용히 '자동 판정 보류'로 채웠는데, 그 보류가 PASS 배지를 달고
    원장에 앉아 '검증까지 통과한 판정'처럼 보였다. 이제는 ① 빠진 항목만 한 번 더 물어보고
    ② 그래도 못 받으면 fallback 임을 플래그로 올려 배지를 ESCALATE 로 내린다.
    """
    try:
        verdicts = _call_verdict_batch(items, facts, provider=provider)
    except Exception as exc:  # 키 없음/네트워크/LLM 오류 — 흐름을 끊지 않고 전부 fallback
        return [(_fallback_verdict(it["item"], it["law"]), True) for it in items], "fallback", repr(exc)

    error = ""
    if len(verdicts) < len(items):
        missing = items[len(verdicts):]
        error = f"batch returned {len(verdicts)}/{len(items)}; retried {len(missing)}"
        try:
            verdicts += _call_verdict_batch(missing, facts, provider=provider)
        except Exception as exc:
            error += f"; retry failed: {exc!r}"

    out: list[tuple[RegulatoryVerdict, bool]] = [(v, False) for v in verdicts[: len(items)]]
    for it in items[len(out):]:
        out.append((_fallback_verdict(it["item"], it["law"]), True))
    return out, provider, error


def run_verdict_generation(case_id: str, *, provider: str = "mlapi-nano") -> None:
    """직원이 처리현황에서 '판정 생성'을 누르면 BackgroundTasks 로 도는 작업.

    승인된 검토계획의 항목 전부를 판정해 checklist_items 에 영속하고, 사건을
    status='verdict'(판정 완료)로 전이한다. 소요시간·결과는 perf 로 기록한다.
    자기 세션(session_scope)을 새로 연다(요청 세션을 넘겨받지 않는다 — 스레드 경계).
    """
    from sqlalchemy import select

    from . import perf
    from .db import SessionLocal, session_scope
    from .models import Case, CaseMessage, ChecklistItemRow, ReviewPlan, StageEvent

    t0 = time.perf_counter()
    provider_used = "fallback"
    error = ""
    item_count = 0

    with session_scope() as s:
        case = s.execute(select(Case).where(Case.case_id == case_id)).scalar_one_or_none()
        if case is None or case.status != "verdict_generating":
            return  # start_verdict_generation 이 이미 상태를 잡아둔 경우에만 진행
        plan = s.execute(
            select(ReviewPlan).where(ReviewPlan.case_fk == case.id).order_by(ReviewPlan.id.desc())
        ).scalars().first()
        items = list(plan.items) if plan else []
        item_dicts = [{"seq": it.seq or (i + 1), "item": it.item, "law": it.law} for i, it in enumerate(items)]
        item_count = len(item_dicts)

        if item_dicts:
            results, provider_used, error = _generate_verdicts(item_dicts, case.facts, provider=provider)
            counts = {"PASS": 0, "ESCALATE": 0, "BLOCK": 0}
            kept = 0
            for row, (v, is_fallback) in zip(items, results):
                # 담당자가 이미 확정한 판정은 재생성이 덮어쓰지 않는다 — AI 는 제안, 확정은 사람.
                # 새 AI 판정은 ai_original 에만 갱신해 두어 '원안이 이렇게 바뀌었다'를 비교할 수 있게 한다.
                # 판정을 못 받아 보류로 채운 행은 절대 PASS 가 될 수 없다(사람이 봐야 한다).
                snapshot = {"verdict": v.verdict, "code": v.code, "ko": v.ko,
                            "detail": v.detail,
                            "critic": "ESCALATE" if is_fallback else derive_critic(v)}
                row.ai_original = snapshot
                if row.verdict_source == "staff":
                    kept += 1
                    counts[row.critic] = counts.get(row.critic, 0) + 1
                    continue
                row.verdict = v.verdict
                row.verdict_code = v.code
                row.verdict_ko = v.ko
                row.verdict_detail = v.detail
                row.critic = snapshot["critic"]
                counts[row.critic] = counts.get(row.critic, 0) + 1
            summary_line = f"판정 {item_count}건 완료 · PASS {counts['PASS']}/ESCALATE {counts['ESCALATE']}/BLOCK {counts['BLOCK']}"
            if kept:
                summary_line += f" · 담당자 확정 {kept}건 유지"
        else:
            # 일반 안내 트랙 등 검토 항목이 없는 사건 — 판정할 원장이 없다.
            provider_used = "n/a"
            summary_line = "검토 항목이 없어 규정 판정을 생략했습니다(일반 안내 트랙)."

        if plan is not None:
            plan.status = "judged"

        prev = case.status
        case.status = "verdict"
        s.add(StageEvent(case_fk=case.id, from_status=prev, to_status="verdict", actor="system",
                         note=f"AI 규정 판정 생성 완료 — {summary_line}"))
        # 민원인 진행현황(판정 완료 단계)에 안내 1건 게시(법률어 없이).
        s.add(CaseMessage(
            case_fk=case.id, stage_key="verdict", audience="complainant", sender="AI 분석",
            title="검토 결과 안내",
            body=("접수하신 내용에 대한 검토가 마무리되어 판정 결과가 정리되었어요. "
                  "담당자가 결과를 최종 확인한 뒤 다음 안내를 드릴게요."),
            seq=0,
        ))
        duration_ms = (time.perf_counter() - t0) * 1000

    # session_scope 밖에서 기록 — perf.record 는 자기 세션을 새로 열어 독립 커밋한다.
    with SessionLocal() as perf_session:
        perf.record(
            perf_session,
            task="verdict_batch",
            case_id=case_id,
            provider=provider_used,
            duration_ms=duration_ms,
            tool_calls=0,
            item_count=item_count,
            outcome="ok" if provider_used not in ("fallback",) else "fallback",
            error=error,
        )


# ---- 사건별 유사사례 실검색 -------------------------------------------------

# 검색된 선례가 어느 코퍼스에서 왔는지 화면에 밝힌다 — 분쟁조정 결정례와 행정 제재·조치
# 사례는 증거 무게가 다르므로 직원이 구분해서 읽어야 한다.
_SIMILAR_KIND_KO = {"decision": "분쟁조정 결정례", "admin_decision": "행정 결정례"}

# 코퍼스 메타의 상품유형 코드는 영문이다('fund mis-selling'). 화면 문구에 그대로 쓰면
# 직원에게 내부 코드가 노출되므로 한국어 상품명으로 옮겨 쓴다.
_PRODUCT_KO = {
    "deposit": "예금·적금",
    "fund": "펀드",
    "fund mis-selling": "펀드",
    "ELS mis-selling": "ELS·DLS",
    "insurance claim": "보험",
    "loan": "대출",
    "general": "일반 금융",
}


def _product_ko(product_en: str) -> str:
    """영문 상품유형 코드 → 화면에 쓰는 한국어 상품명. 모르는 코드는 '해당 상품'."""
    return _PRODUCT_KO.get(product_en, "해당 상품")


def _similar_query(facts: str, keywords: dict[str, Any] | None) -> str:
    """접수 사실 + 접수 시 추출한 키워드로 검색 질의를 만든다(질의 쪽 키워드 브리징)."""
    parts = [facts or ""]
    if keywords:
        parts += keywords.get("issue_terms") or []
        parts += keywords.get("search_queries") or []
    return " ".join(p for p in parts if p).strip()


def search_similar_for_case(
    *,
    facts: str,
    product_en: str,
    keywords: dict[str, Any] | None,
    due_date: str,
    today: date | None = None,
    k: int = 3,
) -> dict[str, Any]:
    """'이 사건'의 접수 내용으로 결정례를 실검색해 유사사례 + 완료일 추정을 만든다.

    같은 상품유형(product_en) 결정례를 먼저 찾고, 없으면(코퍼스에 해당 유형 결정례가
    없는 경우 — 예: 보험) 전체 결정례에서 의미상 가장 가까운 선례로 폴백한다. 폴백
    여부는 reasoning 과 product_matched 로 알린다. 각 사례에 유사도(%)·배상비율을 붙인다.
    """
    from .agentic_plan import _doc_key, _finance_scoped, _get_store
    from .retrieval import add_business_days

    today = today or date.today()
    due = due_date or ""
    empty = {
        "cases": [], "estimated_completion": due, "due_date": due,
        "over_deadline_risk": False, "product_matched": False, "corpus_widened": False,
        "reasoning": "유사 결정례 코퍼스를 불러오지 못해 검색을 건너뛰었습니다.",
    }

    store = _get_store()
    if store is None:
        return empty

    query = _similar_query(facts, keywords) or product_en

    # 상품유형이 맞는 분쟁조정 결정례를 먼저 찾고, 없으면 코퍼스를 넓혀 다시 찾는다.
    # 넓힐 때 분쟁조정 결정례(12청크)만 더 뒤지면 보험·대출 사건에도 ELS·DLF 결정례가
    # '가장 가까운 선례'로 붙는다 — product_en 메타가 그 12청크에만 있기 때문이다.
    # 그래서 넓힐 때는 금융위 검사 조치안(admin_decision)까지 한 후보군으로 합쳐
    # 유사도 순으로 섞는다. 그러면 보험 사건엔 보험사 검사 조치안이 위로 올라온다.
    product_matched = False
    corpus_widened = False
    try:
        hits: list[Any] = []
        if product_en:
            hits = store.search(query, source_type="decision", filters={"product_en": product_en}, k=k * 4)
            product_matched = bool(hits)
        if not hits:
            hits = store.search(query, source_types=("decision", "admin_decision"),
                                where=_finance_scoped, k=k * 8)
            corpus_widened = bool(hits)
    except Exception:
        return empty

    seen: dict[str, dict[str, Any]] = {}
    for score, c in hits:
        m = c.metadata
        # 분쟁조정 결정례는 case_no, 행정 결정례는 doc_id 로 사건을 식별한다.
        # (같은 결정문의 여러 섹션이 잡히므로 문서 단위로 접어야 '사례 3건'이 실제 3건이다.)
        no = m.get("case_no") or m.get("doc_id") or _doc_key(c)
        if no in seen:
            continue
        days = m.get("business_days")
        seen[no] = {
            "case": m.get("case_display") or m.get("title") or str(no),
            "kind": _SIMILAR_KIND_KO.get(c.source_type, c.source_type),
            "org": m.get("org_name", ""),
            "business_days": days,
            "award_ratio": m.get("award_ratio"),
            "product_en": m.get("product_en", ""),
            "similarity": round(max(0.0, min(1.0, float(score))) * 100),
        }
        if len(seen) == k:
            break
    cases = list(seen.values())
    if not cases:
        return {**empty, "reasoning": f"{_product_ko(product_en)} 관련 유사 선례를 찾지 못했습니다."}

    # 소요 영업일은 분쟁조정 결정례에만 붙어 있다. 행정 결정례만 잡힌 경우엔 완료일을
    # 추정하지 않고 기한을 그대로 둔다(0영업일로 계산해 '오늘 완료'라고 우기지 않는다).
    timed = [c["business_days"] for c in cases if isinstance(c["business_days"], int) and c["business_days"] > 0]
    if timed:
        avg = round(sum(timed) / len(timed))
        est_iso = add_business_days(today, avg).isoformat()
        risk = bool(due) and est_iso > due
        timing = (
            f" 소요 영업일이 기록된 {len(timed)}건 평균 약 {avg}영업일 → 오늘({today.isoformat()}) 기준 "
            f"예상 완료 {est_iso}"
            + (f" vs 처리 기한 {due} → {'초과 위험' if risk else '기한 내 가능'}." if due else ".")
        )
    else:
        avg, est_iso, risk = 0, due, False
        timing = " 검색된 선례에 처리 소요일 기록이 없어 완료일 추정은 보류하고 기존 기한을 유지합니다."

    if product_matched:
        lead = f"접수 내용과 같은 {_product_ko(product_en)} 분쟁조정 결정례 {len(cases)}건"
    elif corpus_widened:
        lead = (f"{_product_ko(product_en)} 분쟁조정 결정례가 없어, 금융위 검사·제재 결정례까지 넓혀 "
                f"의미상 가장 가까운 선례 {len(cases)}건")
    else:
        lead = f"접수 내용과 의미상 가장 가까운 선례 {len(cases)}건"
    return {
        "cases": cases,
        "estimated_completion": est_iso,
        "due_date": due,
        "over_deadline_risk": risk,
        "product_matched": product_matched,
        "corpus_widened": corpus_widened,
        "reasoning": f"{lead}을 접수 사실·키워드로 검색했습니다.{timing}",
    }
