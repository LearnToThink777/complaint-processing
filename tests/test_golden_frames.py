from __future__ import annotations

"""골든(스냅샷) 테스트 — 리팩토링 안전망.

리팩토링은 '겉보기 동작을 바꾸지 않고 내부 구조만 개선'하는 작업이다.
그 불변(invariant)을 기계로 고정한다: MockLLM + 검색으로 재생성한 프레임이
커밋된 frames.json 과 한 글자도 다르면 안 된다.

frames.json 은 `python run.py --retrieval corpus_index.json --json frames.json`
(use_llm=False + corpus_index.json)의 산출물이다.

    pytest 로:  pytest complaint_processing/tests
    단독 실행:  python complaint_processing/tests/test_golden_frames.py
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent            # complaint_processing/
_ROOT = _PKG.parent            # import 루트 (이 패키지의 부모)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from complaint_processing.agent import ComplaintAgent
from complaint_processing.llm import get_backend
from complaint_processing.schemas import ComplaintCase


def regenerate_frames() -> list:
    """현재 코드로 프레임을 다시 만든다 (frames.json 을 만든 것과 동일한 설정)."""
    fixtures = json.loads((_PKG / "fixtures.json").read_text(encoding="utf-8"))
    case = ComplaintCase.model_validate(fixtures["case"])
    index = str((_PKG / "corpus_index.json").resolve())
    backend = get_backend(use_llm=False, retrieval_index=index, facts=case.facts)
    return ComplaintAgent(case, llm=backend).run()


def test_golden_frames() -> None:
    golden = json.loads((_PKG / "frames.json").read_text(encoding="utf-8"))
    actual = regenerate_frames()
    assert len(actual) == len(golden), f"프레임 수 다름: {len(actual)} != {len(golden)}"
    for i, (a, g) in enumerate(zip(actual, golden)):
        assert a == g, f"프레임 {i} 불일치 — 동작이 바뀌었습니다."


if __name__ == "__main__":
    try:
        test_golden_frames()
    except AssertionError as exc:
        print("FAIL:", exc)
        sys.exit(1)
    print(f"PASS: 골든 프레임 일치 ({len(regenerate_frames())} 프레임)")
