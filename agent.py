from __future__ import annotations

"""민원 처리 에이전트 오케스트레이터.

콘솔(민원 처리 콘솔.html)의 buildFrames()를 '진짜 에이전트'로 다시 쓴 것입니다.
차이는 딱 하나:
  - 콘솔     : discloseU/discloseR/verdict/vector 를 전부 손으로 박아둔 상수
  - 이 파일  : 그 자리마다 self.llm.structured(...) 를 호출해 LLM이 채운다

LLM이 아닌 부분(사건 생성, 원장 append, 상태 전이, 프레임 스냅샷)은
그대로 결정론적 오케스트레이션으로 남깁니다. 즉 이 클래스는
"언제 LLM을 부를지"를 아는 상태 기계이고, 판정/작문 자체는 LLM 몫입니다.

emit()가 쌓는 frames는 콘솔의 프레임 스키마와 호환되므로,
이 결과 JSON을 그대로 HTML 렌더러에 먹일 수 있습니다.
"""

import copy
from typing import Any

from .llm import LLMBackend, get_backend
from .schemas import (
    ChecklistPlan,
    ComplaintCase,
    DualDisclosure,
    RegulatoryVerdict,
    RenegotiationDraft,
    SimilarCasesResult,
)


class ComplaintAgent:
    def __init__(self, case: ComplaintCase, llm: LLMBackend | None = None) -> None:
        self.case = case
        self.llm = llm or get_backend(use_llm=False)
        # 상태 — 콘솔의 s 객체와 동일한 필드 구성
        self.status = ("접수 대기", "Awaiting intake")
        # 접수 전엔 어떤 민원인지 모른다 — 분류·검토 항목 둘 다 이관 시 LLM #0이 채운다.
        # 이관 이후엔 고정: 협상은 기한만 다루지 재분류하지 않는다.
        self.classification: str | None = None
        self.checklist: list[dict[str, Any]] = []
        self.ledger: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.discloseU = {"title": "민원인용 안내 / To complainant", "body": "아직 안내가 시작되지 않았습니다."}
        self.discloseR = {"title": "회사·감독원용 리포트 / To supervisor", "body": "—"}
        self.vector: list[dict[str, Any]] | None = None
        self.nego_state = "none"
        self.risk = False
        self.due_date: str | None = None
        self.frames: list[dict[str, Any]] = []

    # ---- 결정론적 헬퍼 (LLM 아님) -------------------------------------------

    def _hist(self, tag: str, ko: str, link: str) -> None:
        self.history.append({"tag": tag, "ko": ko, "link": link, "step": len(self.frames)})

    def emit(self, phase: tuple[str, str], hop_label: str) -> None:
        """현재 상태를 프레임으로 스냅샷. 콘솔 frames[] 한 칸에 대응."""
        self.frames.append(
            copy.deepcopy(
                {
                    "case_id": self.case.case_id,
                    "product": self.case.product,
                    "classification": self.classification,
                    "status": self.status[0],
                    "status_en": self.status[1],
                    "due_date": self.due_date,
                    "checklist": self.checklist,
                    "ledger": self.ledger,
                    "history": self.history,
                    "disclose_u": self.discloseU,
                    "disclose_r": self.discloseR,
                    "vector": self.vector,
                    "nego_state": self.nego_state,
                    "risk": self.risk,
                    "phase_ko": phase[0],
                    "phase_en": phase[1],
                    "hop": hop_label,
                }
            )
        )

    def _remaining(self) -> int:
        return sum(1 for c in self.checklist if not c["done"])

    # ---- LLM 호출 지점 5곳 ----------------------------------------------------

    def plan_checklist(self) -> ChecklistPlan:
        """[LLM #0] 이관 시 사건 사실만으로 검토 항목 자체를 도출 + 근거를 vectorDB에서 조회.

        접수 전에는 어떤 민원인지 모르므로 항목 목록이 존재하지 않는다. 이 호출이
        곧 '민원이 들어와야 비로소 무엇을 검토할지 알 수 있다'는 순서를 코드로 만든 것.
        """
        return self.llm.structured(
            "checklist_plan",
            ChecklistPlan,
            {"facts": self.case.facts, "product_en": self.case.product_en},
        )

    def review_item(self, n: int) -> RegulatoryVerdict:
        """[LLM #1] 규정 판정 — 검토 항목 1건을 사건 사실에 대조."""
        item = next(c for c in self.checklist if c["n"] == n)
        return self.llm.structured(
            "verdict",
            RegulatoryVerdict,
            {"item_no": n, "item": item["item"], "law": item["law"], "facts": self.case.facts},
        )

    def dual_disclose(self, n: int, verdict: RegulatoryVerdict, remaining: int) -> DualDisclosure:
        """[LLM #2] 이중 공개 — 같은 판정을 민원인용/감독원용으로 나눠 작문."""
        return self.llm.structured(
            "disclosure",
            DualDisclosure,
            {"item_no": n, "verdict": verdict.model_dump(), "remaining": remaining},
        )

    def retrieve_similar_cases(self) -> SimilarCasesResult:
        """[LLM #3] 유사 사례 검색(RAG) + 완료일 추정 + 기한 초과 위험 판정."""
        return self.llm.structured(
            "similar_cases",
            SimilarCasesResult,
            {"product_en": self.case.product_en, "due_date": self.due_date},
        )

    def close_disclose(self) -> DualDisclosure:
        """[LLM #5] 종결 이중 공개 — 원장(실제 판정 결과)을 바탕으로 결과를 다시 작문.

        종결 문구는 개별 판정과 무관하게 미리 정해둘 수 없다. 실제로 원장에 쌓인
        판정(review_item의 결과)을 읽고 나서야 '무슨 문제가 확인됐고 배상비율이
        얼마인지'를 말할 수 있다 — 실제 LLM을 쓰면 판정이 달라질 수 있으므로.
        """
        return self.llm.structured(
            "closing_disclosure",
            DualDisclosure,
            {"ledger": self.ledger, "checklist": self.checklist},
        )

    def draft_renegotiation(self) -> RenegotiationDraft:
        """[LLM #4] 재협상 재료 초안 — 결정은 사람이, 에이전트는 자문만."""
        return self.llm.structured(
            "renegotiation",
            RenegotiationDraft,
            {"blocking": [c["item"] for c in self.checklist if not c["done"]], "due_date": self.due_date},
        )

    # ---- 처리 루프 한 항목: LLM 판정 → 원장 반영 → LLM 이중 공개 --------------

    def _process_item(self, n: int) -> None:
        item = next(c for c in self.checklist if c["n"] == n)
        self.status = ("처리 중", "In progress")

        verdict = self.review_item(n)  # LLM #1
        item["done"] = True
        self.ledger.append(verdict.model_dump())
        self._hist("②", f"[③→②] {item['item']} → {verdict.code} {verdict.verdict}", f"적용 법률 원장 · {verdict.code}")

        remaining = self._remaining()
        disc = self.dual_disclose(n, verdict, remaining)  # LLM #2
        self.discloseR = {"title": disc.supervisor_title, "body": disc.supervisor_body}
        self.discloseU = {"title": disc.complainant_title, "body": disc.complainant_body}
        self.emit(("처리 루프", "Processing loop"), "항목 처리 결과 → ② 원장 반영 · 이중 공개")

    # ---- 전체 워크플로우 -----------------------------------------------------

    def run(self) -> list[dict[str, Any]]:
        # 0) 대기
        self.emit(("시작 전", "Pre-intake"), "사건 접수 전 · 대기")

        # 1) 접수·이관 — 사건 사실을 읽고서야 무엇을 검토할지 정해진다.
        self.status = ("이관됨", "Transferred")
        self._hist("①", "민원 이력 시작 · 사건 생성", "사건 저장소 · 이력 개시")
        self._hist("②", "적용 법률 원장 초기화 (비어 있음)", "적용 법률 원장")
        plan = self.plan_checklist()  # LLM #0 — 사건 사실 → 분류 + 검토 항목 도출 + vectorDB 조회
        self.classification = plan.classification  # 여기서 딱 한 번 정해지고 종결까지 고정
        self.checklist = [
            {"n": i + 1, "item": it.item, "law": it.law, "source": it.source, "done": False}
            for i, it in enumerate(plan.items)
        ]
        self._hist("③", f"사건 사실 분석 → [{self.classification}] 분류 + 검토 항목 {len(self.checklist)}건 도출", "검토 계획 · 조회 결과")
        self.due_date = "2026-08-24"  # 접수 +30 영업일 (규칙 기반)
        self._hist("", f"처리 기한 확정 — {self.due_date} (민원인 약속)", "처리 기한")
        self.discloseR = {"title": "사건 요약 이관 / To supervisor",
                          "body": f"{self.classification} 건. 사건 요약 + 근거자료 + 검토 예정 항목 "
                                  f"{len(self.checklist)}건을 감독원에 통지."}
        self.discloseU = {"title": "접수 완료 안내 / To complainant",
                          "body": f"민원이 정식 접수되었습니다. 예상 처리 기한은 {self.due_date}이며, 진행 상황을 단계별로 알려드릴게요."}
        self.emit(("접수·이관", "Intake & handoff"), "관련 법령·절차 조회(vectorDB) → 검토 계획 + 처리 기한 공유")

        # 2) 처리 루프 앞 3건
        for n in (1, 2, 3):
            self._process_item(n)

        # 3) 스케줄러 wake → 여유 판정 (LLM #3)
        self._hist("", "정해진 점검 시각 도래 — 상태 확인 (상시 감시 아님)", "내부 점검")
        sim = self.retrieve_similar_cases()
        self.vector = [{"case": c.case, "dur": f"{c.business_days} 영업일"} for c in sim.cases]
        self.risk = sim.over_deadline_risk
        self._hist("", f"유사 사례 조회 — 예상 완료 {sim.estimated_completion} vs 처리 기한 {sim.due_date}", "사례 저장소")
        self.emit(("여유 판정", "Slack check"), "유사 과거 건 조회 → 예상 완료일 vs 처리 기한")

        # 4) 재협상 (LLM #4) — 에이전트는 재료만, 사람이 결정
        if sim.over_deadline_risk:
            nego = self.draft_renegotiation()
            self.nego_state = "active"
            self.status = ("협상 중", "Renegotiating")
            self.discloseU = {"title": "처리 지연 안내 / To complainant", "body": nego.reason_for_complainant}
            self.discloseR = {"title": "기한 재조정 협의 / To supervisor", "body": nego.evidence_for_supervisor}
            self.emit(("협상", "Renegotiation"), "지연 사유 + 새 예상일 재료 제공")

            # 사람이 새 기한을 결정했다고 가정 (에이전트가 확정하지 않음)
            self.nego_state = "resolved"
            self.risk = False
            self.status = ("처리 중", "In progress")
            self.due_date = nego.recommended_new_due_date
            self._hist("", f"기한 재조정 합의 · 새 처리 기한 {self.due_date} (사람이 결정)", "처리 기한 재조정")
            self.emit(("협상", "Renegotiation"), "합의된 새 처리 기한 저장 · 내부 점검 재설정")

        # 5) 처리 루프 나머지 3건
        for n in (4, 5, 6):
            self._process_item(n)

        # 6) 완결성 게이트 (결정론: 남은 항목 0인지 확인) → 종결
        assert self._remaining() == 0, "미완 항목이 있으면 종결 불가"
        self._hist("②", "완결성 게이트 통과 — ② 원장으로 절차 확정", "적용 법률 원장 확정")
        self.status = ("종결", "Closed")
        self._hist("①", "상태=종결 · 전체 처리 이력 로그 종료", "이력 종료")
        close = self.close_disclose()  # LLM #5 — 실제 원장을 읽고서야 결과를 말할 수 있다
        self.discloseU = {"title": close.complainant_title, "body": close.complainant_body}
        self.discloseR = {"title": close.supervisor_title, "body": close.supervisor_body}
        self.emit(("종결", "Closure"), "원장 기반 결과 재작문 · 소요 기록 사례 DB 적재")

        return self.frames
