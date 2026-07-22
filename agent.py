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

from typing import Any

from .llm import LLMBackend, get_backend
from .presentation import FramePresenter
from .schemas import (
    ChecklistPlan,
    ComplaintCase,
    ConsumerRightsGuide,
    DisclosureBatch,
    DualDisclosure,
    GeneralGuidance,
    RegulatoryVerdict,
    RenegotiationDraft,
    SimilarCasesResult,
    VerdictBatch,
)


class ComplaintAgent:
    """민원 처리 오케스트레이터 — "언제 LLM을 부를지"를 아는 상태 기계.

    판정·작문 자체는 LLM(`self.llm.structured`)이 하고, 사건 생성·원장 append·상태 전이·
    완결성 게이트·프레임 스냅샷은 이 클래스가 결정론적으로 담당한다. 상태가 바뀔 때마다
    `emit()`으로 옵서버(`FramePresenter`)에 통지해 viewer 프레임을 쌓는다.

    처리 트랙은 접수 시 #0이 판정한다: legal(전체 규정 처리 파이프라인) / general(경량 안내
    `_run_general`). LLM 호출 지점은 메서드 docstring의 `[LLM #n]` 라벨 참조 — 전체 스킬
    레퍼런스는 docs/SKILLS.md.
    """

    def __init__(
        self,
        case: ComplaintCase,
        llm: LLMBackend | None = None,
        observers: list | None = None,
    ) -> None:
        self.case = case
        self.llm = llm or get_backend(use_llm=False)
        # 검토 항목 판정·이중공개를 루프 전에 배치로 받아 담아두는 캐시(호출 횟수 절감).
        self._verdicts: dict[int, RegulatoryVerdict] = {}
        self._disclosures: dict[int, DualDisclosure] = {}
        # 상태 — 콘솔의 s 객체와 동일한 필드 구성
        self.status = ("접수 대기", "Awaiting intake")
        # 접수 전엔 어떤 민원인지 모른다 — 분류·검토 항목 둘 다 이관 시 LLM #0이 채운다.
        # 이관 이후엔 고정: 협상은 기한만 다루지 재분류하지 않는다.
        self.classification: str | None = None
        # 처리 트랙 — 이관 시 #0이 legal(법률 분쟁)/general(일반 안내)로 판정. 접수 전엔 미정.
        self.track: str | None = None
        # general 트랙에서만 채워지는 비법률 일반 안내(#7). legal 트랙에선 None.
        self.general_guidance: dict[str, Any] | None = None
        self.checklist: list[dict[str, Any]] = []
        self.ledger: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.discloseU = {"title": "민원인용 안내 / To complainant", "body": "아직 안내가 시작되지 않았습니다."}
        self.discloseR = {"title": "회사·감독원용 리포트 / To supervisor", "body": "—"}
        self.vector: list[dict[str, Any]] | None = None
        # 종결 시 원장 근거로 만드는 소비자 권익 보호 안내(#6). 종결 전엔 없음.
        self.rights_guide: dict[str, Any] | None = None
        self.nego_state = "none"
        self.risk = False
        self.due_date: str | None = None
        # 옵서버(Observer): 상태 변화(emit)를 통지받는 대상들. 기본은 프레임 프레젠터 1개.
        # 프레임 조립(뷰 포맷)은 여기서 하지 않고 프레젠터가 담당한다.
        self._presenter = FramePresenter()
        self._observers: list = [self._presenter, *(observers or [])]

    @property
    def frames(self) -> list[dict[str, Any]]:
        """수집된 프레임 = 프레임 프레젠터가 모아 둔 것."""
        return self._presenter.frames

    # ---- 결정론적 헬퍼 (LLM 아님) -------------------------------------------

    def _hist(self, tag: str, ko: str, link: str) -> None:
        self.history.append({"tag": tag, "ko": ko, "link": link, "step": len(self.frames)})

    def emit(self, phase: tuple[str, str], hop_label: str) -> None:
        """상태 변화를 옵서버들에게 통지 — 각 옵서버가 스냅샷을 처리한다."""
        for obs in self._observers:
            obs.capture(self, phase, hop_label)

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

    def review_all(self) -> dict[int, RegulatoryVerdict]:
        """[LLM #1·배치] 전 검토 항목의 규정 판정을 한 번의 호출로.

        항목별로 verdict를 N회 부르는 대신(reasoning 모델에서 시간이 선형 증가) 사건 사실을
        공유하는 전 항목을 한 프롬프트에 담아 배열로 받는다. 오프라인(MockLLM)에서는
        _mock_verdict_batch가 항목별 더미를 그대로 재사용하므로 출력이 배칭 전과 동일하다.
        Critic은 이 배치 산출물 하나만 검증하므로 검증 호출도 함께 줄어든다.
        """
        items = [{"n": c["n"], "item": c["item"], "law": c["law"]} for c in self.checklist]
        batch = self.llm.structured("verdict_batch", VerdictBatch, {"items": items, "facts": self.case.facts, "law": [c["law"] for c in self.checklist]})
        return {c["n"]: v for c, v in zip(self.checklist, batch.verdicts)}

    def disclose_all(self, verdicts: dict[int, RegulatoryVerdict]) -> dict[int, DualDisclosure]:
        """[LLM #2·배치] 전 항목의 이중 공개를 한 번의 호출로.

        remaining(남은 검토 건수)은 처리 순서대로 total-n 으로 계산해 항목별과 동일하게 맞춘다
        (항목 n을 처리하면 1..n이 done → 남은 건수 = total-n). 오프라인 출력이 배칭 전과 동일.
        """
        total = len(self.checklist)
        items = [
            {"n": c["n"], "verdict": verdicts[c["n"]].model_dump(), "remaining": total - c["n"]}
            for c in self.checklist
        ]
        batch = self.llm.structured("disclosure_batch", DisclosureBatch, {"items": items})
        return {c["n"]: d for c, d in zip(self.checklist, batch.disclosures)}

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

    def guide_rights(self) -> ConsumerRightsGuide:
        """[LLM #6] 종결 시 원장(실제 판정)을 근거로 소비자 권익 보호 안내를 생성.

        일반 FAQ가 아니라 이 사건의 원장·분류에 맞춘 개인화 안내다 — 위반이 확인된
        사안과 무혐의 사안의 안내가 서로 다르다. 에이전트는 안내까지만, 권리 행사는 사람이 결정.
        """
        return self.llm.structured(
            "rights_guide",
            ConsumerRightsGuide,
            {"ledger": self.ledger, "classification": self.classification, "facts": self.case.facts},
        )

    def general_guide(self) -> GeneralGuidance:
        """[LLM #7] 비법률 일반 민원에 대한 경량 안내. 규정 판정·원장 없이 바로 실질 안내.

        트리아지(#0)가 general로 분류한 사건에서만 호출된다. 법률 분쟁 소지가 보이면
        escalation_hint로 정식 민원 전환을 안내한다(오분류 안전망).
        """
        return self.llm.structured(
            "general_guidance",
            GeneralGuidance,
            {"classification": self.classification, "facts": self.case.facts},
        )

    def draft_renegotiation(self, sim: SimilarCasesResult) -> RenegotiationDraft:
        """[LLM #4] 재협상 재료 초안 — 결정은 사람이, 에이전트는 자문만.

        #3(retrieve_similar_cases)이 찾은 유사사례·예상완료일을 그대로 넘긴다.
        evidence_for_supervisor가 "유사사례 근거"를 요구하는데(schemas.py), 정작
        유사사례 데이터를 안 주면 LLM이 근거를 지어낼 수밖에 없다 — 그래서 넘긴다.
        같은 값을 facts로도 넘겨야 CriticLLM이 evidence_for_supervisor의 인용을
        이 유사사례 숫자에 대조해 검증한다(없으면 law/facts 둘 다 없어 검증이 건너뛰어짐).
        """
        similar_cases = [c.model_dump() for c in sim.cases]
        return self.llm.structured(
            "renegotiation",
            RenegotiationDraft,
            {
                "blocking": [c["item"] for c in self.checklist if not c["done"]],
                "due_date": self.due_date,
                "similar_cases": similar_cases,
                "estimated_completion": sim.estimated_completion,
                "facts": {
                    "due_date": self.due_date,
                    "estimated_completion": sim.estimated_completion,
                    "similar_cases": similar_cases,
                },
            },
        )

    # ---- 처리 루프 한 항목: LLM 판정 → 원장 반영 → LLM 이중 공개 --------------

    def _process_item(self, n: int) -> None:
        item = next(c for c in self.checklist if c["n"] == n)
        self.status = ("처리 중", "In progress")

        # 판정·이중공개는 루프 진입 전에 배치로 미리 받아둔 값을 쓴다(LLM 호출은 여기서 안 함).
        # 배치가 없으면(안전망) 항목별 단발 호출로 폴백한다.
        verdict = self._verdicts.get(n) if self._verdicts else None
        if verdict is None:
            verdict = self.review_item(n)  # 폴백: LLM #1(단발)
        item["done"] = True
        self.ledger.append(verdict.model_dump())
        self._hist("②", f"[③→②] {item['item']} → {verdict.code} {verdict.verdict}", f"적용 법률 원장 · {verdict.code}")

        disc = self._disclosures.get(n) if self._disclosures else None
        if disc is None:
            disc = self.dual_disclose(n, verdict, self._remaining())  # 폴백: LLM #2(단발)
        self.discloseR = {"title": disc.supervisor_title, "body": disc.supervisor_body}
        self.discloseU = {"title": disc.complainant_title, "body": disc.complainant_body}
        self.emit(("처리 루프", "Processing loop"), "항목 처리 결과 → ② 원장 반영 · 이중 공개")

    # ---- 경량 경로: 비법률 일반 민원 (트리아지 general) -----------------------

    def _run_general(self) -> list[dict[str, Any]]:
        """비법률 일반 안내·행정 민원 경로. 규정 판정·원장·이중공개·유사사례 없이
        바로 실질 안내(#7)를 제공하고 종결한다. run()에서 트랙이 general일 때만 진입.

        (진입 시점엔 이미 pre-intake emit·① 이력·분류·트랙이 정해져 있다.)
        """
        self._hist("③", f"사건 사실 분석 → [{self.classification}] · 비법률 일반 안내로 분류(트리아지)", "트리아지 · 트랙 결정")
        self.discloseR = {"title": "일반 안내 접수 / To supervisor",
                          "body": f"{self.classification} — 법률 분쟁 아님(일반 안내 트랙). 규정 처리 없이 실질 안내로 종결."}
        self.discloseU = {"title": "접수 완료 안내 / To complainant",
                          "body": "문의가 접수되었습니다. 규정 검토가 필요한 분쟁이 아니라, 바로 안내해 드릴게요."}
        self.emit(("접수·트리아지", "Intake & triage"), "법률 분쟁 아님 → 경량 안내 경로로 분기")

        guide = self.general_guide()  # LLM #7 — 사건 사실에 맞춘 실질 안내
        self.general_guidance = guide.model_dump()
        self.status = ("종결", "Closed")
        self.discloseU = {"title": "안내 / To complainant", "body": guide.answer}
        esc = f" · 분쟁 전환 안내 있음" if guide.escalation_hint else ""
        self._hist("①", f"일반 안내 제공 · 종결 (셀프처리 {'가능' if guide.self_service else '일부 필요'}{esc})", "이력 종료")
        self.emit(("종결", "Closure"), "비법률 일반 안내 제공 · 종결")
        return self.frames

    # ---- 전체 워크플로우 -----------------------------------------------------

    def run(self) -> list[dict[str, Any]]:
        # 0) 대기
        self.emit(("시작 전", "Pre-intake"), "사건 접수 전 · 대기")

        # 1) 접수·이관 — 사건 사실을 읽고서야 트랙·검토 항목이 정해진다.
        self.status = ("이관됨", "Transferred")
        self._hist("①", "민원 이력 시작 · 사건 생성", "사건 저장소 · 이력 개시")
        plan = self.plan_checklist()  # LLM #0 — 분류 + 트리아지(legal/general) + 검토 항목 도출
        self.classification = plan.classification  # 여기서 딱 한 번 정해지고 종결까지 고정
        self.track = plan.track

        # 1-a) 트리아지 분기 — 비법률 일반 민원이면 규정 처리 없이 경량 안내로 종결한다.
        if self.track == "general":
            return self._run_general()

        # 1-b) 법률 분쟁 트랙 — 규정 판정·원장 처리 (아래 전체 파이프라인)
        self._hist("②", "적용 법률 원장 초기화 (비어 있음)", "적용 법률 원장")
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

        # 2) 처리 루프 — 판정·이중공개를 항목마다 부르지 않고 배치로 한 번에 받아둔다.
        #    (verdict N회 + disclosure N회 → 각 1회. reasoning 모델 시간을 크게 줄인다.)
        #    _process_item 은 이 캐시를 읽어 원장 반영·이중공개·프레임 emit 만 결정론으로 수행한다.
        self._verdicts = self.review_all()  # LLM #1·배치 (1회)
        self._disclosures = self.disclose_all(self._verdicts)  # LLM #2·배치 (1회)

        # 처리 루프 전반부 — 항목 수는 검토 계획(#0)이 사건마다 도출하므로 고정이 아니다
        ns = [c["n"] for c in self.checklist]
        mid = (len(ns) + 1) // 2
        for n in ns[:mid]:
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
            nego = self.draft_renegotiation(sim)
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

        # 5) 처리 루프 후반부
        for n in ns[mid:]:
            self._process_item(n)

        # 6) 완결성 게이트 (결정론: 남은 항목 0인지 확인) → 종결
        assert self._remaining() == 0, "미완 항목이 있으면 종결 불가"
        self._hist("②", "완결성 게이트 통과 — ② 원장으로 절차 확정", "적용 법률 원장 확정")
        self.status = ("종결", "Closed")
        self._hist("①", "상태=종결 · 전체 처리 이력 로그 종료", "이력 종료")
        close = self.close_disclose()  # LLM #5 — 실제 원장을 읽고서야 결과를 말할 수 있다
        self.discloseU = {"title": close.complainant_title, "body": close.complainant_body}
        self.discloseR = {"title": close.supervisor_title, "body": close.supervisor_body}
        # LLM #6 — 원장 근거 소비자 권익 보호 안내(자문·안내까지만, 행사는 본인 결정).
        guide = self.guide_rights()
        self.rights_guide = guide.model_dump()
        self._hist("", f"소비자 권익 보호 안내 생성 — 권리 {len(guide.rights)}건 · 확대경로 {len(guide.escalation)}건", "소비자 권익 안내")
        self.emit(("종결", "Closure"), "원장 기반 결과 재작문 · 소비자 권익 보호 안내 · 소요 기록 사례 DB 적재")

        return self.frames
