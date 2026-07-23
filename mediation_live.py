from __future__ import annotations

"""라이브 중재 세션 스토어 — 턴 단위로 MediationRecord 를 쌓아가는 in-memory 상태.

정적 `mediation.json` 이 '완성된 상담 1건'이라면, 여기 세션은 그 레코드를 한 발언씩
'진행하면서' 만들어낸다. 각 턴은 LLM 을 1회 부르고(task="mediation_turn"), 돌아온
델타(MediationTurnResult)에 **seq/refs 번호를 스토어가 부여**해 record 에 병합한다.
그래서 mediation.html 의 표시 불변식(`min(refs) <= curSeq`)이 저절로 성립한다.

폴백: 키가 없거나(use_llm=False) LLM 이 실패하면, 같은 시나리오의 정적 레코드를
'스크립트'로 삼아 한 발언씩 되짚어 재생한다 — 기존 정적 데모와 동일한 결과가 나온다.

이 모듈은 api.py 밖에 두어 상태(세션)를 소유한다. demo_store.py 와 같은 in-memory 방식.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm import LLMBackend, get_backend
from .schemas import (
    AdvisoryBalance,
    AdvisoryEntry,
    MediationIssue,
    MediationLogEntry,
    MediationParty,
    MediationRecord,
    MediationTurnResult,
)

_PKG_DIR = Path(__file__).resolve().parent
_MEDIATION_JSON = _PKG_DIR / "mediation.json"

# 라이브 세션 턴 상한 — 서로 다른 쟁점 3~5개가 드러날 만큼 넉넉히(양측 교대 기준 ~6왕복).
_LIVE_MAX_TURNS = 12


# ---------------------------------------------------------------------------
# 시나리오 시드 — 정적 mediation.json 을 그대로 '라이브 시드 + 더미 스크립트'로 재사용
# ---------------------------------------------------------------------------


def _load_seeds() -> dict[str, dict[str, Any]]:
    """mediation.json(레코드 배열)을 case_id → 원본 dict 로. 없으면 빈 dict."""
    if not _MEDIATION_JSON.exists():
        return {}
    import json

    raw = json.loads(_MEDIATION_JSON.read_text(encoding="utf-8"))
    return {r["case_id"]: r for r in raw}


_SEEDS = _load_seeds()


def scenarios() -> list[dict[str, str]]:
    """시작 화면용 시나리오 목록(id/도메인)."""
    return [{"id": cid, "domain": r.get("domain", "")} for cid, r in _SEEDS.items()]


# ---------------------------------------------------------------------------
# 세션
# ---------------------------------------------------------------------------


@dataclass
class MediationSession:
    """라이브 중재 1건의 진행 상태. record 를 턴마다 키워 나간다."""

    sid: str
    scenario_id: str
    record: MediationRecord
    script: dict[str, Any]                    # 더미 폴백용 정적 레코드(mediation.json 원본)
    use_llm: bool
    provider: str
    max_turns: int
    backend: LLMBackend | None = None         # start 때 1회 조립(실패 시 None → 더미)
    mock_be: LLMBackend | None = None         # 더미 폴백용 MockLLM(지연 생성·캐시)
    seq: int = 0                              # 지금까지 부여한 마지막 log seq
    turn_index: int = 0                      # 진행한 발언 턴 수
    script_cursor: int = 0                   # 더미 스크립트(script["log"]) 소비 위치
    done: bool = False
    fell_back: bool = False                  # 라이브를 시도했으나 더미로 내려앉았는지

    def side_to_key(self, side: str) -> str:
        for p in self.record.parties:
            if p.side == side:
                return p.key
        return side

    def party_by_side(self, side: str) -> MediationParty | None:
        return next((p for p in self.record.parties if p.side == side), None)


# sid → 세션. 프로세스 메모리(데모용) — 재시작하면 사라진다.
_SESSIONS: dict[str, MediationSession] = {}


def start(scenario_id: str | None = None, *, use_llm: bool = True, provider: str = "mlapi") -> MediationSession:
    """새 라이브 세션을 만든다. scenario_id 미지정이면 첫 시나리오.

    record 는 당사자/도메인/경계 고지만 채운 '빈 원장'으로 시작하고, issues/log/balance 는
    턴을 진행하며 채운다. use_llm=True 라도 백엔드 조립이 실패하면 조용히 더미로 폴백한다.
    """
    if not _SEEDS:
        raise RuntimeError("mediation.json 시드가 없습니다.")
    if scenario_id not in _SEEDS:
        scenario_id = next(iter(_SEEDS))
    script = _SEEDS[scenario_id]

    parties = [MediationParty.model_validate(p) for p in script.get("parties", [])]
    record = MediationRecord(
        case_id=script["case_id"],
        domain=script.get("domain", ""),
        parties=parties,
        issues=[],
        balance=AdvisoryBalance(entries=[], note=script.get("balance", {}).get("note", AdvisoryBalance().note)),
        log=[],
        linked_case=script.get("linked_case"),
        boundary=script.get("boundary", MediationRecord.model_fields["boundary"].default),
    )

    # 더미는 정적 스크립트 발언 수만큼(원본 재현), 라이브는 고정 상한(생성 대화라 스크립트에
    # 매일 필요 없다). 라이브 상한이 너무 짧으면 서로 다른 쟁점 3~5개를 펼치기 전에 끝나므로 넉넉히.
    script_utterances = sum(1 for l in script.get("log", []) if l.get("kind") == "발언")
    max_turns = _LIVE_MAX_TURNS if use_llm else max(script_utterances, 1)

    backend: LLMBackend | None = None
    fell_back = False
    if use_llm:
        try:
            backend = get_backend(use_llm=True, provider=provider, observe=False)
        except Exception:  # noqa: BLE001 — 키/설정 누락 등은 조용히 더미 폴백
            backend, use_llm, fell_back = None, False, True

    sess = MediationSession(
        sid=uuid.uuid4().hex[:12],
        scenario_id=scenario_id,
        record=record,
        script=script,
        use_llm=use_llm,
        provider=provider,
        max_turns=max_turns,
        backend=backend,
        fell_back=fell_back,
    )
    _SESSIONS[sess.sid] = sess
    return sess


def get(sid: str) -> MediationSession | None:
    return _SESSIONS.get(sid)


# ---------------------------------------------------------------------------
# 턴 진행
# ---------------------------------------------------------------------------


def _script_slice(sess: MediationSession) -> dict[str, Any] | None:
    """더미 스크립트(정적 레코드)에서 '다음 턴 슬라이스'를 계산한다.

    스크립트 log(원본 seq 순)를 커서로 걷는다. 한 턴 = [커서 ~ 다음 '발언' + 뒤따르는
    자문/서기 lines]. 그 발언을 utterance 로, 사이의 자문/서기를 mediator_notes 로,
    이 원본 seq 구간에 min(refs)가 걸리는 쟁점을 issue_updates 로, ref 가 걸리는 밸런스를
    balance_updates 로 낸다(원본 seq 기준으로 매칭 — 스토어가 다시 새 seq 를 부여).

    반환 dict 는 `_mock_turn` payload + 스토어가 쓸 speaker_side. 스크립트 소진이면 None.
    """
    log = sess.script.get("log", [])
    n = len(log)
    lo = sess.script_cursor
    if lo >= n:
        return None
    # 커서 이후 첫 '발언' 찾기
    f = next((i for i in range(lo, n) if log[i].get("kind") == "발언"), None)
    if f is None:
        # 남은 건 자문/서기뿐 — 마지막 정리 턴(발언 없음)으로 소진하고 종료.
        notes = [{"kind": l["kind"], "text": l["text"]} for l in log[lo:] if l.get("kind") in ("자문", "서기")]
        sess.script_cursor = n
        return {"speaker_side": None, "payload": {
            "utterance": "", "mediator_notes": notes, "issue_updates": [],
            "balance_updates": [], "phase": "종료"}}
    # 발언 뒤로 다음 '발언' 직전까지 확장(뒤따르는 자문/서기 포함)
    e = next((i for i in range(f + 1, n) if log[i].get("kind") == "발언"), n)
    window = log[lo:e]
    lo_seq = window[0]["seq"]
    hi_seq = window[-1]["seq"]
    utter = log[f]
    speaker_key = utter.get("speaker", "")
    side = next((p.side for p in sess.record.parties if p.key == speaker_key), "A")
    notes = [{"kind": l["kind"], "text": l["text"]} for l in window if l.get("kind") in ("자문", "서기")]

    def _issue_draft(it: dict[str, Any]) -> dict[str, Any]:
        return {k: it[k] for k in (
            "code", "title", "for_a", "against_a", "for_b", "against_b", "agent_note", "decider", "status")}

    issue_updates = [
        _issue_draft(it) for it in sess.script.get("issues", [])
        if it.get("refs") and lo_seq <= min(it["refs"]) <= hi_seq
    ]
    balance_updates = [
        {"leans": b["leans"], "summary": b["summary"]}
        for b in sess.script.get("balance", {}).get("entries", [])
        if lo_seq <= b.get("ref", -1) <= hi_seq
    ]
    sess.script_cursor = e
    phase = "종료" if e >= n else "계속"
    return {"speaker_side": side, "payload": {
        "utterance": utter["text"], "mediator_notes": notes,
        "issue_updates": issue_updates, "balance_updates": balance_updates, "phase": phase}}


def _apply(sess: MediationSession, result: MediationTurnResult, speaker_side: str | None) -> dict[str, Any]:
    """턴 델타에 seq/refs 를 부여해 record 에 병합. 이번 턴에 추가된 항목만 돌려준다."""
    rec = sess.record
    added_log: list[MediationLogEntry] = []
    turn_seqs: list[int] = []

    # 1) 당사자 발언(있으면). speaker_side 가 None(마지막 정리 턴)이면 발언 없이 자문/서기만.
    utter_seq: int | None = None
    if speaker_side is not None and result.utterance.strip():
        sess.seq += 1
        utter_seq = sess.seq
        entry = MediationLogEntry(
            seq=utter_seq, kind="발언", speaker=sess.side_to_key(speaker_side), text=result.utterance.strip())
        rec.log.append(entry)
        added_log.append(entry)
        turn_seqs.append(utter_seq)

    # 2) 중재자 자문/서기
    for note in result.mediator_notes:
        sess.seq += 1
        entry = MediationLogEntry(seq=sess.seq, kind=note.kind, speaker="C", text=note.text)
        rec.log.append(entry)
        added_log.append(entry)
        turn_seqs.append(sess.seq)

    # 3) 쟁점 upsert (code 키). refs 는 이번 턴 seq 들을 누적.
    ref_seqs = turn_seqs or [sess.seq]
    added_issue_codes: list[str] = []
    for draft in result.issue_updates:
        existing = next((it for it in rec.issues if it.code == draft.code), None)
        if existing is None:
            rec.issues.append(MediationIssue(**draft.model_dump(), refs=sorted(set(ref_seqs))))
            added_issue_codes.append(draft.code)
        else:
            data = draft.model_dump()
            for k, v in data.items():
                setattr(existing, k, v)
            existing.refs = sorted(set(existing.refs) | set(ref_seqs))

    # 4) 중립성 밸런스 태깅 — ref 는 발언 seq(없으면 마지막 seq).
    bal_ref = utter_seq if utter_seq is not None else sess.seq
    for b in result.balance_updates:
        rec.balance.entries.append(AdvisoryEntry(ref=bal_ref, leans=b.leans, summary=b.summary))

    sess.turn_index += 1
    if result.phase == "종료" or sess.turn_index >= sess.max_turns:
        sess.done = True

    return {
        "added_log": [e.model_dump() for e in added_log],
        "added_issue_codes": added_issue_codes,
        "phase": result.phase,
    }


def next_turn(sess: MediationSession) -> dict[str, Any]:
    """세션을 한 턴 진행한다. LLM 1회(또는 더미 스크립트 1슬라이스) → record 갱신."""
    if sess.done:
        return {"done": True, "applied": None, "record": sess.record.model_dump(),
                "turn_index": sess.turn_index, "fell_back": sess.fell_back}

    # 더미 슬라이스는 라이브·폴백 양쪽에서 미리 계산해둔다(mock 빌더가 context 로 받는다).
    slice_ = _script_slice(sess)

    if sess.use_llm and sess.backend is not None:
        # 라이브: 편은 A↔B 교대. 스크립트가 남아 있으면 그 speaker 를 따르고, 없으면 교대.
        if slice_ and slice_["speaker_side"] is not None:
            side = slice_["speaker_side"]
        else:
            side = "A" if sess.turn_index % 2 == 0 else "B"
        speaker = sess.party_by_side(side)
        context = {
            "domain": sess.record.domain,
            "parties": [p.model_dump() for p in sess.record.parties],
            "speaker_side": side,
            "speaker": speaker.model_dump() if speaker else {},
            "transcript": [e.model_dump() for e in sess.record.log],
            "issues_so_far": [{"code": it.code, "title": it.title, "status": it.status} for it in sess.record.issues],
            "turn_index": sess.turn_index,
            "max_turns": sess.max_turns,
        }
        try:
            result = sess.backend.structured("mediation_turn", MediationTurnResult, context)
        except Exception:  # noqa: BLE001 — 이 턴부터 더미로 폴백
            sess.use_llm = False
            sess.fell_back = True
            result, side = _mock_result(sess, slice_)
    else:
        result, side = _mock_result(sess, slice_)

    applied = _apply(sess, result, side)
    return {"done": sess.done, "applied": applied, "record": sess.record.model_dump(),
            "turn_index": sess.turn_index, "fell_back": sess.fell_back}


def _mock_result(sess: MediationSession, slice_: dict[str, Any] | None) -> tuple[MediationTurnResult, str | None]:
    """더미 슬라이스를 MediationTurnResult 로 — 등록된 mock 빌더(structured 경유)를 탄다.

    스크립트 소진(slice_ is None)이면 즉시 종료 턴. 그 외엔 MockLLM 이 context["_mock_turn"]
    을 그대로 스키마로 검증해 돌려준다(라이브와 동일한 호출 계약).
    """
    if slice_ is None:
        sess.done = True
        return MediationTurnResult(utterance="", mediator_notes=[], issue_updates=[],
                                   balance_updates=[], phase="종료"), None
    if sess.mock_be is None:
        sess.mock_be = get_backend(use_llm=False, observe=False)
    result = sess.mock_be.structured("mediation_turn", MediationTurnResult, {"_mock_turn": slice_["payload"]})
    return result, slice_["speaker_side"]
