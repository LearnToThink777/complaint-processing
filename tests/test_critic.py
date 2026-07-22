from __future__ import annotations

"""출력 검증(Critic) 라우터 + CriticLLM 데코레이터 테스트.

핵심 불변:
  1. 허용 목록에 없는 조문을 인용하면(할루시네이션) BLOCK.
  2. 허용 목록 안의 조문·근거 있는 수치는 BLOCK 되지 않는다.
  3. 정상 fixtures 의 판정들은 critic 을 붙여도 BLOCK 이 없다(오판으로 정상 출력을 막지 않음).
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
_ROOT = _PKG.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from complaint_processing.agent import ComplaintAgent
from complaint_processing.critic import verify
from complaint_processing.decorators import CriticLLM, unwrap
from complaint_processing.llm import get_backend
from complaint_processing.schemas import ComplaintCase


def test_hallucinated_law_blocks() -> None:
    # 사용자 예시: '여신전문금융업법 제34조'는 허용 law 목록에 없는 지어낸 조문.
    r = verify(
        "계약일로부터 8개월 경과했으며, 은행법 제52조의2에 따라 중도상환수수료 감액 대상입니다. "
        "또한 여신전문금융업법 제34조에 따라 3년 경과 시 수수료 전액 면제되므로, "
        "고객 귀책사유가 없어 전액 환급이 타당합니다.",
        law=["은행법 제52조의2", "여신전문금융업법 제50조의9"],
        facts={"contract_date": "2022-03-15", "elapsed_months": 8},
    )
    assert r.verdict == "BLOCK"
    assert any("제34조" in c.reason for c in r.hard_fails)


def test_valid_law_not_blocked() -> None:
    r = verify(
        "은행법 제52조의2에 따라 중도상환수수료 감액 대상입니다.",
        law=["은행법 제52조의2"],
        facts={"elapsed_months": 8},
    )
    assert r.verdict != "BLOCK"


def test_clean_fixture_verdicts_not_blocked() -> None:
    fx = json.loads((_PKG / "fixtures.json").read_text(encoding="utf-8"))
    facts = fx["case"]["facts"]
    for item in fx["checklist"]:
        v = fx["verdict"][str(item["n"])]
        r = verify(f"{v['code']} {v['detail']}", law=item["law"], facts=facts)
        assert r.verdict != "BLOCK", f"verdict {item['n']} 오판 BLOCK: {[c.reason for c in r.hard_fails]}"


def test_criticllm_on_full_run_reports_no_block() -> None:
    # 전체 실행(mock-only)에 critic(보고 전용)을 붙여도 정상 fixtures 는 BLOCK 이 없다.
    # 주: 검색(retrieval)을 켜면 검토항목이 코퍼스 순서로 재배열돼 fixture 판정과 조문이
    #     위치상 어긋날 수 있으므로(데모 데이터 특성), 검증 배선 테스트는 mock-only로 한다.
    # 호출 최적화 이후: verdict 는 배치(verdict_batch)로 한 묶음으로 검증되므로 reviewed 는
    #     항목 수가 아니라 '검증된 산출물 수'(verdict_batch + renegotiation ≈ 2)를 센다.
    fx = json.loads((_PKG / "fixtures.json").read_text(encoding="utf-8"))
    case = ComplaintCase.model_validate(fx["case"])
    be = get_backend(use_llm=False, critic=True)
    ComplaintAgent(case, llm=be).run()
    critic = unwrap(be, CriticLLM)
    assert critic is not None
    s = critic.summary()
    assert s["reviewed"] >= 1            # verdict_batch 가 한 묶음으로 검증됨(배칭)
    assert s["BLOCK"] == 0               # 정상 fixtures → 오판 차단 없음
