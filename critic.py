from __future__ import annotations

"""출력 검증(Critic) — 작업 agent 산출물을 독립적으로 대조하는 4단계 라우터.

작업 agent(ComplaintAgent)가 입력→출력을 낸 뒤, 그 출력이 '입력 밖의 것을 지어냈는지'를
작업 agent의 추론(CoT)을 보지 않고 결과물만으로 대조한다. 자기채점이 아니라 독립 검증.

    detail(출력 문장들) ─▶ ① 분해(claim) ─▶ ② 분류 ─▶ ③ 검증 라우팅 ─▶ ④ 집계
                                             │
            structural_law  (제N조 인용)  ─▶ 허용 law 목록에 있나?   (LLM 불필요·확정)
            structural_fact (수치 인용)   ─▶ facts 안에 있는 수치인가? (LLM 불필요)
            semantic        (규범 판단)   ─▶ 근거에 함의되나?        (판단 필요 → 전략 주입)

핵심 규칙: BLOCK(자동 반려)은 '100% 확신'할 때만 — 인용 조문이 허용 목록에 없는 경우.
그 외 불확실(수치 확인 불가, 규범 판단 애매)은 전부 ESCALATE(사람에게)로 보낸다.
그래서 critic 자신의 오판이 정상 출력을 막는 사고가 구조적으로 안 난다.

GoF: 검증 방식을 claim 종류에 따라 고르는 전략(Strategy). CriticLLM 데코레이터(decorators.py)가
     structured() 결과에 이 라우터를 태운다.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

_ARTICLE = re.compile(r"제\d+조(?:의\d+)?")          # 제17조, 제52조의2
_LAWNAME = re.compile(r"[가-힣]{2,}법")               # 은행법, 자본시장법, 금융소비자보호법
_NUMBER = re.compile(r"(\d+)\s*(?:개월|년|%|원|만원|일|건)")  # 8개월, 40%, 60
_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
# 문장/절 경계 — 한국어 연결어미·구두점에서 자른다.
_SPLIT = re.compile(r"(?:습니다|됩니다|입니다|이며|으며|었으며|되며|므로|다\.|\.|,|·|또한|그리고|및)\s*")


@dataclass
class ClaimResult:
    claim: str
    kind: str            # structural_law | structural_fact | semantic
    passed: bool | None  # True=통과, False=확정 위반(하드), None=판단 불가(에스컬레이트)
    reason: str = ""


@dataclass
class CriticResult:
    verdict: str                         # PASS | BLOCK | ESCALATE
    claims: list[ClaimResult] = field(default_factory=list)

    @property
    def hard_fails(self) -> list[ClaimResult]:
        return [c for c in self.claims if c.kind == "structural_law" and c.passed is False]

    @property
    def uncertain(self) -> list[ClaimResult]:
        return [c for c in self.claims if c.passed is None]


# ---- 근거(context) 정규화 — law/ facts 가 list든 str든 dict든 받아준다 -----------

def _tokens(s: str) -> set[str]:
    return set(_TOKEN.findall(s))


def _law_refs(text: str) -> set[tuple[str, str]]:
    """텍스트에서 (법령명, 조문) 쌍을 뽑는다. 법령명이 앞에 없으면 ('', 조문)."""
    refs: set[tuple[str, str]] = set()
    for m in _ARTICLE.finditer(text):
        pre = text[: m.start()]
        names = _LAWNAME.findall(pre)
        refs.add((names[-1] if names else "", m.group(0)))
    return refs


def _valid_law_refs(law: Any) -> set[tuple[str, str]]:
    """허용된 근거 조문 집합. law 는 list[str] 또는 str."""
    items = law if isinstance(law, list) else [law] if law else []
    refs: set[tuple[str, str]] = set()
    for it in items:
        refs |= _law_refs(str(it))
    return refs


def _facts_text(facts: Any) -> str:
    if isinstance(facts, dict):
        return " ".join(str(v) for v in facts.values())
    return str(facts or "")


def _facts_numbers(facts: Any) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", _facts_text(facts))}


# ---- 의미(semantic) 검증 전략 — 오프라인 어휘겹침 / 실제 LLM 주입 -----------------

class SemanticVerifier(Protocol):
    def entails(self, claim: str, grounding: str) -> bool | None:
        """claim 이 grounding(근거)에 함의되면 True, 아니면 False, 판단 불가면 None."""
        ...


class LexicalEntailment:
    """오프라인 기본 전략: claim 어휘가 근거에 충분히 겹치면 '함의됨'으로 근사.

    확정 반증은 못 하므로 True(겹침 충분) 또는 None(불충분→에스컬레이트)만 낸다.
    실제로는 LLM 앙상블(온도↑ 3회 투표)로 교체하면 된다(전략 주입).
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def entails(self, claim: str, grounding: str) -> bool | None:
        cq = _tokens(claim)
        if not cq:
            return None
        overlap = len(cq & _tokens(grounding)) / len(cq)
        return True if overlap >= self.threshold else None


# ---- 4단계 라우터 --------------------------------------------------------------

def decompose(detail: str) -> list[str]:
    """① 출력 문장을 claim(원자적 주장) 단위로 분해."""
    return [p.strip() for p in _SPLIT.split(detail) if len(p.strip()) >= 2]


def classify(claim: str) -> str:
    """② claim 성격 분류. 법조문 인용이 최우선(허용목록으로 확정 검증 가능)."""
    if _ARTICLE.search(claim):
        return "structural_law"
    if _NUMBER.search(claim):
        return "structural_fact"
    return "semantic"


def verify(
    detail: str,
    *,
    law: Any = None,
    facts: Any = None,
    semantic: SemanticVerifier | None = None,
) -> CriticResult:
    """③ 검증 라우팅 + ④ 집계. detail(출력 문장) 을 law/facts(입력 근거)에 대조."""
    semantic = semantic or LexicalEntailment()
    valid_refs = _valid_law_refs(law)
    fact_nums = _facts_numbers(facts)
    grounding = f"{_facts_text(facts)}"

    results: list[ClaimResult] = []
    for claim in decompose(detail):
        kind = classify(claim)

        if kind == "structural_law":
            cited = _law_refs(claim)
            missing = [
                c for c in cited
                if not any(v[1] == c[1] and (c[0] == "" or v[0] == c[0]) for v in valid_refs)
            ]
            ok = not missing
            results.append(ClaimResult(
                claim, kind, ok,
                "" if ok else f"허용 근거에 없는 조문 인용: {', '.join(f'{n} {a}'.strip() for n, a in missing)}",
            ))

        elif kind == "structural_fact":
            nums = {int(n) for n in _NUMBER.findall(claim)}
            ok = True if nums and nums <= fact_nums else None
            results.append(ClaimResult(
                claim, kind, ok,
                "" if ok else "근거(facts)에서 확인되지 않는 수치 — 사람 확인 필요",
            ))

        else:  # semantic
            ent = semantic.entails(claim, grounding)
            results.append(ClaimResult(
                claim, kind, ent,
                "" if ent else "규범적 판단 — 근거 함의가 불확실, 사람 확인 필요",
            ))

    # ④ 집계: 확정 위반(조문 허용목록 밖)이 하나라도 있으면 BLOCK, 불확실이 있으면 ESCALATE.
    result = CriticResult("PASS", results)
    if result.hard_fails:
        result.verdict = "BLOCK"
    elif result.uncertain:
        result.verdict = "ESCALATE"
    return result


def result_to_dict(r: CriticResult) -> dict[str, Any]:
    return {
        "verdict": r.verdict,
        "claims": [{"claim": c.claim, "kind": c.kind, "pass": c.passed, "reason": c.reason} for c in r.claims],
    }


if __name__ == "__main__":  # 빠른 수동 확인 — 사용자가 준 예시
    ctx_law = ["은행법 제52조의2", "여신전문금융업법 제50조의9"]
    ctx_facts = {"contract_date": "2022-03-15", "elapsed_months": 8}
    detail = (
        "계약일로부터 8개월 경과했으며, 은행법 제52조의2에 따라 중도상환수수료 감액 대상입니다. "
        "또한 여신전문금융업법 제34조에 따라 3년 경과 시 수수료 전액 면제되므로, "
        "고객 귀책사유가 없어 전액 환급이 타당합니다."
    )
    print(json.dumps(result_to_dict(verify(detail, law=ctx_law, facts=ctx_facts)), ensure_ascii=False, indent=2))
