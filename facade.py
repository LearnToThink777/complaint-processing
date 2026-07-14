from __future__ import annotations

"""퍼사드(Facade) — 구조(Structural) 패턴.

사건 하나를 처리하는 여러 단계(백엔드 조립 → 에이전트 생성 → 실행)를 한 함수 뒤로
숨긴다. 호출부(run.py, 테스트, 향후 웹 API)는 내부 배선(get_backend/ComplaintAgent)을
직접 다루지 않고 이 진입점만 부르면 된다.
"""

from typing import Any

from .agent import ComplaintAgent
from .llm import LLMBackend, get_backend
from .schemas import ComplaintCase


def run_complaint_case(
    case: ComplaintCase,
    *,
    use_llm: bool = False,
    retrieval_index: str | None = None,
    **backend_opts: Any,
) -> tuple[list[dict[str, Any]], LLMBackend]:
    """사건 → (프레임 목록, 백엔드).

    backend_opts 는 get_backend 의 관측/재시도/캐시 플래그(observe/retries/cache)로 전달된다.
    백엔드를 함께 돌려주므로 호출부가 관측 트레이스(ObservableLLM.summary 등)를 읽을 수 있다.
    """
    backend = get_backend(
        use_llm=use_llm, retrieval_index=retrieval_index, facts=case.facts, **backend_opts
    )
    agent = ComplaintAgent(case, llm=backend)
    frames = agent.run()
    return frames, backend
