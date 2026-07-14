from __future__ import annotations

"""프레임 프레젠터 — 행위(Behavioral) : 옵서버(Observer) 패턴.

에이전트(Subject)는 상태가 바뀔 때마다 등록된 옵서버들에게 통지하고, 프레젠터(Observer)가
그 스냅샷을 viewer.html이 먹는 프레임 dict로 변환·수집한다. 이렇게 하면 도메인
오케스트레이션(agent.py)에서 '뷰 포맷 지식'(키 이름·라벨 등)을 떼어낼 수 있다.

같은 통지에 다른 옵서버(예: AgentOps 이벤트 수집기)를 추가로 붙여도 에이전트는 모른다.
"""

import copy
from typing import Any


class FramePresenter:
    """에이전트 상태 스냅샷을 viewer.html 프레임 dict로 변환·수집하는 옵서버."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def capture(self, agent: Any, phase: tuple[str, str], hop: str) -> None:
        """에이전트의 현재 상태를 프레임 한 칸으로 스냅샷해 보관(깊은 복사로 시점 고정)."""
        self.frames.append(
            copy.deepcopy(
                {
                    "case_id": agent.case.case_id,
                    "product": agent.case.product,
                    "classification": agent.classification,
                    "status": agent.status[0],
                    "status_en": agent.status[1],
                    "due_date": agent.due_date,
                    "checklist": agent.checklist,
                    "ledger": agent.ledger,
                    "history": agent.history,
                    "disclose_u": agent.discloseU,
                    "disclose_r": agent.discloseR,
                    "vector": agent.vector,
                    "nego_state": agent.nego_state,
                    "risk": agent.risk,
                    "phase_ko": phase[0],
                    "phase_en": phase[1],
                    "hop": hop,
                }
            )
        )
