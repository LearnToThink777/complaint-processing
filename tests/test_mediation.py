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


# ---------------------------------------------------------------------------
# 라이브 세션 스토어(mediation_live) — 더미(오프라인) 경로 스모크
#
# 라이브 세션은 정적 레코드와 '같은 모양'의 MediationRecord 를 턴마다 쌓아 만든다.
# 더미 모드(use_llm=False)는 정적 mediation.json 을 스크립트로 되짚으므로 결정론적이고,
# 위 정적 데이터가 지키던 불변식을 그대로 지켜야 한다(+ 스크립트 충실도).
# ---------------------------------------------------------------------------

from complaint_processing import mediation_live


def _drive_to_end(scenario_id: str) -> "mediation_live.MediationSession":
    sess = mediation_live.start(scenario_id, use_llm=False)  # 더미 스크립트 재생(결정론적)
    for _ in range(200):  # 안전 상한 — 정상적으로는 스크립트 소진 시 done
        if sess.done:
            break
        mediation_live.next_turn(sess)
    assert sess.done, f"{scenario_id}: 세션이 종료되지 않음(무한 진행 방지 상한 도달)"
    return sess


def test_live_start_is_empty_but_valid() -> None:
    for sc in mediation_live.scenarios():
        sess = mediation_live.start(sc["id"], use_llm=False)
        rec = sess.record
        assert rec.log == [] and rec.issues == [] and rec.balance.entries == [], (
            f"{sc['id']}: 라이브 시작본은 빈 원장이어야 함"
        )
        assert rec.parties and rec.domain, f"{sc['id']}: 당사자/도메인은 채워져 있어야 함"
        MediationRecord.model_validate(rec.model_dump())  # 빈 상태도 스키마 유효


def test_live_session_holds_invariants() -> None:
    # 생성된 레코드가 정적 데이터와 똑같은 불변식(스키마·seq 연속·refs 실재)을 지키는지.
    for sc in mediation_live.scenarios():
        rec = _drive_to_end(sc["id"]).record
        MediationRecord.model_validate(rec.model_dump())
        seqs = [e.seq for e in rec.log]
        assert seqs == list(range(1, len(seqs) + 1)), f"{sc['id']}: 생성 log seq 가 1..N 연속이 아님 → {seqs}"
        log_seqs = set(seqs)
        cited: set[int] = set()
        for it in rec.issues:
            cited.update(it.refs)
        for e in rec.balance.entries:
            cited.add(e.ref)
        missing = sorted(cited - log_seqs)
        assert not missing, f"{sc['id']}: 생성 레코드가 log 에 없는 근거를 인용 → {missing}"


def test_live_dummy_reproduces_static_counts() -> None:
    # 더미 폴백은 정적 스크립트를 그대로 되짚으므로, 소진 후 로그·쟁점·밸런스 개수가
    # 원본 mediation.json 과 일치해야 한다(폴백 충실도).
    static = {r.case_id: r for r in _records()}
    for sc in mediation_live.scenarios():
        rec = _drive_to_end(sc["id"]).record
        src = static[sc["id"]]
        assert len(rec.log) == len(src.log), (
            f"{sc['id']}: 생성 log {len(rec.log)} ≠ 정적 {len(src.log)}"
        )
        assert len(rec.issues) == len(src.issues), (
            f"{sc['id']}: 생성 쟁점 {len(rec.issues)} ≠ 정적 {len(src.issues)}"
        )
        assert len(rec.balance.entries) == len(src.balance.entries), (
            f"{sc['id']}: 생성 밸런스 {len(rec.balance.entries)} ≠ 정적 {len(src.balance.entries)}"
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
