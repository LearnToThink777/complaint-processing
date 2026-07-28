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
    """실패 시 최대 max_retries회 재시도(신뢰성). max_retries=0이면 무동작.

    재시도 대상은 '인프라 실패'(네트워크 타임아웃, 일시적 API 오류 등)뿐이다.
    CriticBlocked(출력 품질 문제로 막힘)는 재시도하지 않고 즉시 전파한다 — 이유:
      - MockLLM 이면 같은 context로 다시 불러도 결정론적이라 100% 똑같이 BLOCK된다
        (재시도가 통계적으로도 무의미).
      - ProxyLLM(실제 LLM) 이어도, 지금 구조는 '왜 막혔는지'(critic의 reason)를
        다음 시도의 프롬프트/context에 전혀 넘기지 않는다. 그래서 재시도는 그냥
        같은 입력으로 눈 감고 한 번 더 굴리는 것뿐이라 결과가 나아진다는 보장이 없다.

    TODO(실제 LLM 도입 시 반드시 처리): CriticBlocked를 잡아 재시도하려면, review.hard_fails의
    reason을 다음 시도의 context에 피드백으로 주입하는 경로를 새로 만들어야 한다
    (예: context["critic_feedback"] = [c.reason for c in review.hard_fails] 를 넣고
    ProxyLLM._system_prompt가 이를 프롬프트에 반영하도록). 그 경로가 생기기 전까지는
    CriticBlocked를 여기서 재시도하지 않는다 — 개선 없는 재시도는 오히려 실패를 감춘다.
    """

    def __init__(self, wrapped: LLMBackend, max_retries: int = 2) -> None:
        super().__init__(wrapped)
        self.max_retries = max_retries

    def structured(self, task: str, schema: type[T], context: dict[str, Any]) -> T:
        last: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                return self._wrapped.structured(task, schema, context)
            except CriticBlocked:
                raise  # 품질 문제는 인프라 재시도 대상이 아님 — 즉시 전파(위 TODO 참고)
            except Exception as exc:  # noqa: BLE001 — 네트워크/일시적 실패로 간주하고 재시도
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
        text = self._reviewable_text(result)
        # 배치 산출물(verdict_batch)은 원소 detail 을 한 덩어리로 합쳐 한 번에 검증한다 →
        # verify() 안의 claim 검증도 배치(1회)로 처리돼, 항목 수와 무관하게 Critic 호출이 늘지 않는다.
        return verify(text, law=law, facts=facts, semantic=self.semantic) if text else None

    @staticmethod
    def _reviewable_text(result: BaseModel) -> str:
        """검증 대상 텍스트 추출. 배치(verdicts/disclosures)면 원소 근거를 이어 붙인다.

        판정이면 code+detail, 이중공개면 감독원용 본문, 재협상이면 감독원용 근거.
        """
        if hasattr(result, "verdicts"):  # VerdictBatch — 전 항목 판정을 한 덩어리로
            return " ".join(f"{v.code} {v.detail}" for v in result.verdicts).strip()
        if hasattr(result, "disclosures"):  # DisclosureBatch — 감독원용 본문을 이어붙임
            return " ".join(str(d.supervisor_body) for d in result.disclosures).strip()
        if hasattr(result, "detail"):
            return f"{getattr(result, 'code', '')} {result.detail}".strip()
        if hasattr(result, "supervisor_body"):
            return str(result.supervisor_body)
        if hasattr(result, "evidence_for_supervisor"):
            return str(result.evidence_for_supervisor)
        return ""

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
