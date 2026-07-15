from __future__ import annotations

"""LLM 백엔드 데코레이터 — 구조(Structural) : 데코레이터(Decorator) 패턴.

LLMBackend를 감싸 '관측·재시도·캐시' 같은 횡단 관심사(cross-cutting concern)를
도메인 코드(agent.py) 수정 없이 덧붙인다. 각 데코레이터는 스스로도 LLMBackend라서
얼마든지 겹쳐 끼울 수 있다:  ObservableLLM(RetryingLLM(CachingLLM(base))).

AgentOps(관측·평가·운영)의 삽입점이 바로 여기다 — 에이전트는 자기 호출이
계측되고 있다는 사실조차 모른다.

참고: 기존 RetrievalLLM(llm.py)도 개념상 같은 데코레이터다 — base 백엔드를 감싸
일부 task만 가로채고 나머지는 위임한다.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from .critic import CriticResult, SemanticVerifier, verify
from .llm import LLMBackend

T = TypeVar("T", bound=BaseModel)


class LLMDecorator(LLMBackend):
    """LLMBackend를 감싸는 데코레이터의 공통 베이스. 기본 동작은 '그대로 위임'."""

    def __init__(self, wrapped: LLMBackend) -> None:
        self._wrapped = wrapped

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        return self._wrapped.structured(task, schema, context)


@dataclass
class TraceEntry:
    """LLM 호출 1건의 관측 기록 — AgentOps의 최소 단위."""

    task: str
    ok: bool
    ms: float
    error: str | None = None


class ObservableLLM(LLMDecorator):
    """호출별 소요시간·성공/실패·task를 기록한다(Observability).

    출력은 손대지 않고 계측만 한다 — 감싸도 결과는 동일하다. 이것이 AgentOps가
    "왜 실패했는가/얼마나 걸렸는가"를 추적하는 이음새다.
    """

    def __init__(self, wrapped: LLMBackend, trace: list[TraceEntry] | None = None) -> None:
        super().__init__(wrapped)
        self.trace: list[TraceEntry] = trace if trace is not None else []

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        start = time.perf_counter()
        try:
            result = self._wrapped.structured(task, schema, context)
        except Exception as exc:  # noqa: BLE001 — 계측 후 그대로 재전파
            self.trace.append(TraceEntry(task, False, (time.perf_counter() - start) * 1000, repr(exc)))
            raise
        self.trace.append(TraceEntry(task, True, (time.perf_counter() - start) * 1000))
        return result

    def summary(self) -> dict[str, Any]:
        n = len(self.trace)
        ok = sum(1 for t in self.trace if t.ok)
        return {
            "calls": n,
            "ok": ok,
            "failed": n - ok,
            "total_ms": round(sum(t.ms for t in self.trace), 2),
        }


class RetryingLLM(LLMDecorator):
    """실패 시 최대 max_retries회 재시도(신뢰성). max_retries=0이면 무동작."""

    def __init__(self, wrapped: LLMBackend, max_retries: int = 2) -> None:
        super().__init__(wrapped)
        self.max_retries = max_retries

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        last: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                return self._wrapped.structured(task, schema, context)
            except Exception as exc:  # noqa: BLE001
                last = exc
        assert last is not None
        raise last


class CachingLLM(LLMDecorator):
    """동일 (task, schema, context) 호출 결과를 캐시해 재계산/재호출을 피한다(비용·지연 절감)."""

    def __init__(self, wrapped: LLMBackend) -> None:
        super().__init__(wrapped)
        self._cache: dict[str, Any] = {}

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        key = f"{task}|{schema.__name__}|{json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)}"
        if key not in self._cache:
            self._cache[key] = self._wrapped.structured(task, schema, context)
        return self._cache[key]


class CriticBlocked(Exception):
    """출력 검증이 BLOCK 판정을 냈을 때(enforce=True) 발생. 산출물이 사용자에게 가기 전에 막는다."""

    def __init__(self, task: str, result: CriticResult) -> None:
        self.task = task
        self.result = result
        reasons = "; ".join(c.reason for c in result.hard_fails)
        super().__init__(f"[{task}] 출력 검증 BLOCK — {reasons}")


class CriticLLM(LLMDecorator):
    """작업 백엔드 출력을 독립 검증하는 데코레이터(critic.py 라우터를 호출).

    작업 agent가 낸 결과(payload)를, 그 추론(CoT)이 아니라 결과물만 놓고 입력(context)에
    대조한다. context에 근거(law/facts)가 없는 task(예: disclosure)는 건너뛴다.
    enforce=False면 판정을 기록만 하고 통과(보고 전용), True면 BLOCK 시 CriticBlocked를 던진다.
    """

    def __init__(
        self,
        wrapped: LLMBackend,
        *,
        enforce: bool = False,
        semantic: SemanticVerifier | None = None,
    ) -> None:
        super().__init__(wrapped)
        self.enforce = enforce
        self.semantic = semantic
        self.reviews: list[tuple[str, CriticResult]] = []

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        result = self._wrapped.structured(task, schema, context)
        review = self._review(result, context)
        if review is not None:
            self.reviews.append((task, review))
            if self.enforce and review.verdict == "BLOCK":
                raise CriticBlocked(task, review)
        return result

    def _review(self, result: BaseModel, context: dict[str, Any]) -> CriticResult | None:
        law, facts = context.get("law"), context.get("facts")
        if law is None and facts is None:
            return None  # 검증할 근거가 context에 없음 → 건너뜀
        # 검증 대상 텍스트: 판정이면 code+detail, 이중공개면 감독원용 본문.
        if hasattr(result, "detail"):
            text = f"{getattr(result, 'code', '')} {result.detail}".strip()
        elif hasattr(result, "supervisor_body"):
            text = str(result.supervisor_body)
        else:
            return None
        return verify(text, law=law, facts=facts, semantic=self.semantic) if text else None

    def summary(self) -> dict[str, Any]:
        from collections import Counter

        c = Counter(r.verdict for _, r in self.reviews)
        return {"reviewed": len(self.reviews), "PASS": c["PASS"], "ESCALATE": c["ESCALATE"], "BLOCK": c["BLOCK"]}


def unwrap(backend: LLMBackend, cls: type) -> Any:
    """데코레이터 체인을 따라가며 cls 타입의 인스턴스를 찾는다(없으면 None)."""
    cur: Any = backend
    while cur is not None:
        if isinstance(cur, cls):
            return cur
        cur = getattr(cur, "_wrapped", None)
    return None
