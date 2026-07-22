from __future__ import annotations

"""웹 API 스모크 테스트 — 네트워크 없이(MockLLM) FastAPI TestClient 로 검증.

핵심 불변: GET /api/frames 가 커밋된 골든(frames.json)과 완전히 일치해야 한다 —
API 경로가 CLI/골든 경로와 어긋나면 여기서 잡힌다.

    pytest complaint_processing/tests
"""

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent            # complaint_processing/
_ROOT = _PKG.parent            # import 루트(이 패키지의 부모)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# fastapi/httpx 가 없으면(의존성 미설치) 이 모듈 전체를 건너뛴다 — 골든 테스트는 별개로 돈다.
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from complaint_processing.api import app  # noqa: E402

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_frames_matches_golden() -> None:
    """GET /api/frames == frames.json(골든). API가 골든과 동일 설정으로 도는지 고정."""
    golden = json.loads((_PKG / "frames.json").read_text(encoding="utf-8"))
    r = client.get("/api/frames")
    assert r.status_code == 200
    actual = r.json()
    assert len(actual) == len(golden), f"프레임 수 다름: {len(actual)} != {len(golden)}"
    for i, (a, g) in enumerate(zip(actual, golden)):
        assert a == g, f"프레임 {i} 불일치 — API 경로가 골든과 어긋남."


def test_mediation_is_list_of_records() -> None:
    r = client.get("/api/mediation")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and data, "중재 기록은 비어 있지 않은 배열이어야 한다."
    assert "case_id" in data[0] and "log" in data[0]


def test_run_case_offline() -> None:
    """POST /api/cases/run (기본=오프라인 더미) → 프레임 + 관측 요약."""
    case = json.loads((_PKG / "fixtures.json").read_text(encoding="utf-8"))["case"]
    r = client.post("/api/cases/run", json={"case": case})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["frames"], "프레임이 비어 있으면 안 된다."
    assert body["observability"]["calls"] >= 1
    assert body["critic"] is None  # critic=False 기본


def test_skill_verdict_offline() -> None:
    """POST /api/skills/verdict (오프라인 더미) → RegulatoryVerdict 형태."""
    r = client.post(
        "/api/skills/verdict",
        json={
            "item_no": 1,
            "item": "적합성 원칙 위반 여부",
            "law": "금융소비자보호법 제17조",
            "facts": "안정추구형 고객에게 고위험 ELS를 판매함.",
            "options": {"use_llm": False},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"code", "verdict", "ko", "detail"} <= set(body)


def test_skill_rights_guide_personalized() -> None:
    """POST /api/skills/rights-guide — 위반 원장이면 권리 안내, 무혐의면 접힌다(개인화)."""
    ledger_violation = [{"code": "제17조", "verdict": "위반", "ko": "위반 확인", "detail": "..."}]
    r = client.post(
        "/api/skills/rights-guide",
        json={"ledger": ledger_violation, "classification": "ELS 불완전판매 의심", "options": {"use_llm": False}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"summary", "rights", "documents", "escalation", "disclaimer"} <= set(body)
    assert len(body["rights"]) >= 1, "위반 사안이면 행사 가능한 권리가 있어야 한다."

    # 무혐의(위반 없음) → 권리 목록은 접히고 확대 경로만 남는다(개인화 증명).
    r2 = client.post(
        "/api/skills/rights-guide",
        json={"ledger": [{"code": "x", "verdict": "해당없음", "ko": "-", "detail": "-"}], "options": {"use_llm": False}},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["rights"] == [], "무혐의면 권리 목록이 비어야 한다(동일 답변이 아님)."


def test_frames_general_track() -> None:
    """GET /api/frames?case=general → 트리아지가 general 트랙으로 분기하고 경량 안내로 종결."""
    r = client.get("/api/frames", params={"case": "general"})
    assert r.status_code == 200, r.text
    frames = r.json()
    last = frames[-1]
    assert last["track"] == "general", "일반 민원은 general 트랙이어야 한다."
    assert last["status"] == "종결"
    assert last["ledger"] == [], "일반 트랙은 법률 원장이 없어야 한다."
    assert last["general_guidance"] and last["general_guidance"]["answer"], "일반 안내 응답이 있어야 한다."

    # 대조: 기본(legal) 트랙은 track=legal + 원장 있음
    legal = client.get("/api/frames").json()[-1]
    assert legal["track"] == "legal" and len(legal["ledger"]) >= 1


def test_skill_general_guidance() -> None:
    """POST /api/skills/general-guidance → GeneralGuidance 형태."""
    r = client.post(
        "/api/skills/general-guidance",
        json={"facts": "이체한도 변경 절차와 OTP 재발급 방법이 궁금합니다.", "options": {"use_llm": False}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"answer", "steps", "self_service", "contact", "escalation_hint"} <= set(body)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
