from __future__ import annotations

"""중재 데이터 불변식 테스트 — mediation.json 회귀 방지.

세 상담 시나리오 데이터가 지켜야 할 규칙을 고정한다:
  1. MediationRecord 스키마로 검증된다.
  2. log 의 seq 는 1..N 연속이다 (콘솔이 [1]부터 빠짐없이 표시).
  3. 모든 근거(issue.refs, balance.entries.ref)는 log 안에 실재한다
     — 아직 등장하지 않은 미래 시점을 근거로 인용하던 버그의 재발 방지.

    pytest 로:  pytest complaint_processing/tests
    단독 실행:  python complaint_processing/tests/test_mediation.py
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
_ROOT = _PKG.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from complaint_processing.schemas import MediationRecord


def _records() -> list[MediationRecord]:
    data = json.loads((_PKG / "mediation.json").read_text(encoding="utf-8"))
    return [MediationRecord.model_validate(r) for r in data]


def test_schema_valid() -> None:
    recs = _records()
    assert len(recs) == 3, f"시나리오 3건이어야 함, 현재 {len(recs)}건"


def test_log_seq_is_continuous() -> None:
    for rec in _records():
        seqs = [e.seq for e in rec.log]
        assert seqs == list(range(1, len(seqs) + 1)), (
            f"{rec.case_id}: log seq 가 1..N 연속이 아님 → {seqs}"
        )


def test_refs_exist_in_log() -> None:
    for rec in _records():
        log_seqs = {e.seq for e in rec.log}
        cited: set[int] = set()
        for it in rec.issues:
            cited.update(it.refs)
        for e in rec.balance.entries:
            cited.add(e.ref)
        missing = sorted(cited - log_seqs)
        assert not missing, (
            f"{rec.case_id}: log 에 없는 근거 번호를 인용함(미래 참조 버그) → {missing}"
        )


if __name__ == "__main__":
    failed = False
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS: {name}")
            except AssertionError as exc:
                print(f"FAIL: {name}: {exc}")
                failed = True
    sys.exit(1 if failed else 0)
