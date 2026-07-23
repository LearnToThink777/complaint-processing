from __future__ import annotations

"""웹 API 계층 — FastAPI + Swagger(OpenAPI).

민원 처리 에이전트를 HTTP로 노출한다. 기존 계약(agent.py/schemas.py/llm.py)은
건드리지 않고 얇은 어댑터로 얹었다:

  - 파이프라인(POST /api/cases/run, GET /api/frames)  → facade.run_complaint_case() 재사용
  - LLM 스킬 5종(POST /api/skills/*)                  → llm.get_backend(...).structured() 재사용
  - 중재 기록(GET /api/mediation)                     → mediation.json → MediationRecord 검증

이 파일은 스키마(Pydantic)를 response_model 로 그대로 물려, FastAPI 가
  /docs      (Swagger UI)
  /redoc     (ReDoc)
  /openapi.json
을 자동 생성하게 한다 — 별도 Swagger 정의 파일이 필요 없다.

정적 프론트(viewer.html/mediation.html/frames.json/mediation.json)도 같은 오리진에서
서빙하므로(맨 끝 StaticFiles 마운트), 브라우저는 CORS 없이 /api/* 를 부르고
서버가 없을 때만 정적 JSON 으로 폴백한다.

실행:
    uvicorn complaint_processing.api:app --reload            # (Downloads 에서)
    python -m complaint_processing.api                       # 동일(하단 __main__)
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import mediation_live
from .decorators import CriticBlocked, CriticLLM, unwrap
from .demo_api import router as demo_router
from .facade import run_complaint_case
from .llm import LLMBackend, get_backend
from .schemas import (
    ChecklistPlan,
    ComplaintCase,
    ConsumerRightsGuide,
    DualDisclosure,
    GeneralGuidance,
    MediationRecord,
    RegulatoryVerdict,
    RenegotiationDraft,
    SimilarCase,
    SimilarCasesResult,
)

_PKG_DIR = Path(__file__).resolve().parent
_CORPUS_INDEX = _PKG_DIR / "corpus_index.json"
_FIXTURES = json.loads((_PKG_DIR / "fixtures.json").read_text(encoding="utf-8"))
# 골든(frames.json)을 만든 기준일 — GET /api/frames 가 골든과 어긋나지 않도록 고정.
_GOLDEN_TODAY = date(2026, 7, 15)


# ===========================================================================
# API 전용 모델 — schemas.py(순수 LLM 계약)를 오염시키지 않도록 여기 둔다.
# ===========================================================================


class BackendOptions(BaseModel):
    """백엔드 조립 옵션 — llm.get_backend 인자로 그대로 흘러간다."""

    use_llm: bool = Field(default=False, description="True면 실제 LLM 호출, False면 오프라인 더미(MockLLM).")
    provider: str = Field(default="mlapi-nano", description="실제 LLM provider: mlapi-nano/mlapi-mini/proxy.")
    retrieval: bool = Field(default=False, description="True면 corpus_index.json 으로 #0/#3을 실검색.")
    critic: bool = Field(default=False, description="True면 출력 검증(Critic)을 근거에 대조.")


class Frame(BaseModel):
    """viewer.html 이 렌더하는 프레임 1칸. presentation.FramePresenter 가 쌓는 dict 미러."""

    case_id: str
    product: str
    classification: str | None = None
    track: str | None = None
    general_guidance: dict[str, Any] | None = None
    status: str
    status_en: str
    due_date: str | None = None
    checklist: list[dict[str, Any]]
    ledger: list[dict[str, Any]]
    history: list[dict[str, Any]]
    disclose_u: dict[str, Any]
    disclose_r: dict[str, Any]
    vector: list[dict[str, Any]] | None = None
    rights_guide: dict[str, Any] | None = None
    nego_state: str
    risk: bool
    phase_ko: str
    phase_en: str
    hop: str


class RunCaseRequest(BaseModel):
    """POST /api/cases/run 요청 — 사건 + 백엔드 옵션."""

    case: ComplaintCase
    options: BackendOptions = Field(default_factory=BackendOptions)


class RunCaseResponse(BaseModel):
    """전체 파이프라인 결과 — 프레임 + 관측/검증 요약(run.py 콘솔 출력과 동일 정보)."""

    frames: list[Frame]
    observability: dict[str, Any] | None = Field(
        default=None, description="LLM 호출 계측 요약(calls/ok/failed/total_ms)."
    )
    critic: dict[str, Any] | None = Field(
        default=None, description="출력 검증 요약(reviewed/PASS/ESCALATE/BLOCK). critic=False면 null."
    )


class ChecklistPlanRequest(BaseModel):
    """[LLM #0] 검토 계획 — 사건 사실 → 분류 + 검토 항목 도출."""

    facts: str = Field(description="사건 사실관계 요약(자연어).")
    product_en: str = Field(default="", description="상품 유형 영문. 예: 'ELS mis-selling'.")
    options: BackendOptions = Field(default_factory=BackendOptions)


class VerdictRequest(BaseModel):
    """[LLM #1] 규정 판정 — 검토 항목 1건을 사건 사실에 대조."""

    item_no: int = Field(description="검토 항목 번호.")
    item: str = Field(description="검토 항목 설명. 예: '적합성 원칙 위반 여부'.")
    law: str = Field(description="적용 근거 법령/절차명.")
    facts: str = Field(description="사건 사실관계 요약.")
    options: BackendOptions = Field(default_factory=BackendOptions)


class DisclosureRequest(BaseModel):
    """[LLM #2] 이중 공개 — 같은 판정을 민원인용/감독원용으로 나눠 작문."""

    item_no: int = Field(description="검토 항목 번호(제목에 '#n'으로 들어간다).")
    verdict: RegulatoryVerdict = Field(description="이중 공개의 원천이 되는 규정 판정 결과.")
    remaining: int = Field(default=0, description="남은 검토 항목 수(감독원용 본문에 반영).")
    options: BackendOptions = Field(default_factory=BackendOptions)


class SimilarCasesRequest(BaseModel):
    """[LLM #3] 유사사례 검색 + 완료일 추정 + 기한 초과 위험 판정."""

    product_en: str = Field(description="상품 유형 영문(검색 필터).")
    due_date: str = Field(default="", description="현재 처리 기한 YYYY-MM-DD.")
    facts: str = Field(default="", description="검색 질의로 쓸 사건 사실(retrieval=True일 때).")
    options: BackendOptions = Field(default_factory=BackendOptions)


class RenegotiationRequest(BaseModel):
    """[LLM #4] 재협상 재료 초안 — 에이전트는 자문만, 확정은 사람."""

    blocking: list[str] = Field(default_factory=list, description="완료를 지연시키는 미완 검토 항목 라벨.")
    due_date: str = Field(default="", description="현재 처리 기한 YYYY-MM-DD.")
    similar_cases: list[SimilarCase] = Field(default_factory=list, description="근거가 될 유사사례(#3 결과).")
    estimated_completion: str = Field(default="", description="유사사례로 추정한 완료일 YYYY-MM-DD.")
    options: BackendOptions = Field(default_factory=BackendOptions)


class RightsGuideRequest(BaseModel):
    """[LLM #6] 소비자 권익 보호 안내 — 종결 원장 근거로 개인화 안내."""

    ledger: list[dict[str, Any]] = Field(
        default_factory=list, description="적용 법률 원장(판정 결과 목록). RegulatoryVerdict.model_dump() 형태."
    )
    classification: str = Field(default="", description="사건 유형 분류 라벨.")
    facts: str = Field(default="", description="사건 사실관계 요약(선택).")
    options: BackendOptions = Field(default_factory=BackendOptions)


class GeneralGuidanceRequest(BaseModel):
    """[LLM #7] 비법률 일반 민원 안내 — 규정 판정 없이 실질 안내."""

    facts: str = Field(description="사건 사실관계/문의 내용(자연어).")
    classification: str = Field(default="", description="사건 유형 분류 라벨(선택).")
    options: BackendOptions = Field(default_factory=BackendOptions)


# ===========================================================================
# 백엔드 조립·호출 헬퍼
# ===========================================================================


def _resolve_index(retrieval: bool) -> str | None:
    """retrieval=True 이고 corpus_index.json 이 있으면 그 경로, 아니면 None(더미 폴백)."""
    if retrieval and _CORPUS_INDEX.exists():
        return str(_CORPUS_INDEX)
    return None


def _run_skill(
    task: str,
    schema: type[BaseModel],
    context: dict[str, Any],
    options: BackendOptions,
    *,
    facts: str = "",
) -> Any:
    """스킬 1건: 백엔드 조립 → structured() 1회 호출. 실패는 HTTP 오류로 변환."""
    try:
        backend: LLMBackend = get_backend(
            use_llm=options.use_llm,
            retrieval_index=_resolve_index(options.retrieval),
            provider=options.provider,
            facts=facts,
            critic=options.critic,
        )
        return backend.structured(task, schema, context)
    except CriticBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:  # 키/설정 누락 등 (예: MlapiLLM __init__)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 그 외(네트워크·LLM 오류)는 502
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


# ===========================================================================
# FastAPI 앱
# ===========================================================================

_TAGS = [
    {"name": "pipeline", "description": "전체 민원 처리 파이프라인 실행 → viewer.html 프레임."},
    {"name": "skills", "description": "LLM 이 실제로 판단/작문하는 5개 지점을 개별 엔드포인트로."},
    {"name": "mediation", "description": "상담·검사 중재 기록 → mediation.html."},
]

app = FastAPI(
    title="민원 처리 에이전트 API",
    version="1.0.0",
    description=(
        "금융 민원 처리 에이전트를 HTTP 로 노출합니다. 콘솔이 상수로 박아두던 판정·작문을 "
        "실제 LLM(또는 오프라인 더미)이 채웁니다. 스키마는 Pydantic 계약 그대로이며, "
        "이 문서(Swagger UI)는 그 스키마에서 자동 생성됩니다."
    ),
    openapi_tags=_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", summary="헬스 체크", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


# ---- 파이프라인 -----------------------------------------------------------


@app.post("/api/cases/run", response_model=RunCaseResponse, tags=["pipeline"], summary="전체 파이프라인 실행")
def run_case(req: RunCaseRequest) -> RunCaseResponse:
    """사건 하나를 접수→검토→이중공개→(재협상)→종결까지 돌려 프레임 전체를 만든다.

    options.use_llm=False(기본)면 오프라인 더미로 즉시 실행된다. retrieval=True면
    corpus_index.json 으로 #0/#3을 실검색으로 바꾼다. critic=True면 산출물을 근거에 대조한다.
    """
    opts = req.options
    try:
        frames, backend = run_complaint_case(
            req.case,
            use_llm=opts.use_llm,
            retrieval_index=_resolve_index(opts.retrieval),
            provider=opts.provider,
            critic=opts.critic,
        )
    except CriticBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    observability = backend.summary() if hasattr(backend, "summary") else None
    critic = unwrap(backend, CriticLLM)
    return RunCaseResponse(
        frames=frames,
        observability=observability,
        critic=critic.summary() if critic is not None else None,
    )


@app.get("/api/frames", response_model=list[Frame], tags=["pipeline"], summary="데모 프레임(골든과 동일 설정)")
def get_frames(case: str = "default") -> list[dict[str, Any]]:
    """fixtures.json 의 데모 사건을 골든(frames.json)과 동일한 설정으로 실행해 프레임을 돌려준다.

    viewer.html 이 우선적으로 부르는 엔드포인트다(정적 frames.json 폴백보다 먼저).
    use_llm=False + corpus_index.json + today=2026-07-15 로 고정해 재현성을 보장한다.
    - case="default"(기본): ELS 불완전판매(legal 트랙) 데모.
    - case="general"      : 비법률 일반 민원(general 트랙) 트리아지 데모.
    """
    fixture_key = "case_general" if case == "general" else "case"
    complaint = ComplaintCase.model_validate(_FIXTURES[fixture_key])
    frames, _ = run_complaint_case(
        complaint,
        use_llm=False,
        retrieval_index=_resolve_index(True),
        today=_GOLDEN_TODAY,
    )
    return frames


# ---- 중재 ----------------------------------------------------------------


@app.get("/api/mediation", response_model=list[MediationRecord], tags=["mediation"], summary="중재 기록 목록")
def get_mediation() -> list[MediationRecord]:
    """mediation.json(정적 픽스처, 레코드 배열)을 MediationRecord 목록으로 검증해 돌려준다.

    mediation.html 과 viewer.html 이 부른다(둘 다 배열로 소비: .map/.findIndex).
    """
    path = _PKG_DIR / "mediation.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="mediation.json 이 없습니다.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [MediationRecord.model_validate(r) for r in raw]


# ---- 라이브 중재 (턴 단위 세션 — LLM 이 양측을 롤플레이하며 원장을 실시간으로 쌓는다) ----
# 정적 /api/mediation 은 폴백용으로 그대로 둔다. 아래는 mediation_live.py 세션 스토어의
# 얇은 HTTP 어댑터: start(세션 생성) → turn(한 발언 진행) → get(현재 상태) 3단.
# 키 없음/LLM 실패는 스토어가 조용히 더미(정적 스크립트)로 폴백하고 fell_back=True 로 알린다.


class MediationStartRequest(BaseModel):
    """POST /api/mediation/live/start — 라이브 중재 세션 시작."""

    scenario_id: str | None = Field(default=None, description="시나리오 case_id. 미지정이면 첫 시나리오.")
    use_llm: bool = Field(default=True, description="True면 실제 LLM 롤플레이, False면 더미 스크립트 재생.")
    provider: str = Field(default="mlapi-nano", description="LLM provider. 기본 gpt-5-nano(mlapi-nano) — 속도/품질 균형. 더 좋은 품질은 mlapi-mini(gpt-5-mini).")


def _session_or_404(sid: str) -> "mediation_live.MediationSession":
    sess = mediation_live.get(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다(서버 재시작 시 소멸).")
    return sess


@app.get("/api/mediation/live/scenarios", tags=["mediation"], summary="라이브 중재 — 시나리오 목록")
def mediation_scenarios() -> list[dict[str, str]]:
    """시작 화면용 시나리오(id/도메인) 목록. mediation.json 시드에서 뽑는다."""
    return mediation_live.scenarios()


@app.post("/api/mediation/live/start", tags=["mediation"], summary="라이브 중재 — 세션 시작")
def mediation_start(req: MediationStartRequest) -> dict[str, Any]:
    """새 세션을 만들고 '빈 원장'(당사자·도메인·경계만) + 세션 id 를 돌려준다."""
    try:
        sess = mediation_live.start(req.scenario_id, use_llm=req.use_llm, provider=req.provider)
    except RuntimeError as exc:  # 시드 없음 등
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sid": sess.sid,
        "scenario_id": sess.scenario_id,
        "record": sess.record.model_dump(),
        "done": sess.done,
        "turn_index": sess.turn_index,
        "max_turns": sess.max_turns,
        "live": sess.use_llm,
        "fell_back": sess.fell_back,
    }


@app.post("/api/mediation/live/{sid}/turn", tags=["mediation"], summary="라이브 중재 — 한 발언 진행")
def mediation_turn(sid: str) -> dict[str, Any]:
    """세션을 한 턴 진행한다(LLM 1회 또는 더미 스크립트 1슬라이스). 갱신된 record 반환."""
    sess = _session_or_404(sid)
    try:
        return mediation_live.next_turn(sess)
    except Exception as exc:  # noqa: BLE001 — 예기치 못한 오류는 502
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/api/mediation/live/{sid}", tags=["mediation"], summary="라이브 중재 — 현재 상태")
def mediation_state(sid: str) -> dict[str, Any]:
    """세션의 현재 record 전체와 진행 상태를 돌려준다."""
    sess = _session_or_404(sid)
    return {
        "sid": sess.sid,
        "scenario_id": sess.scenario_id,
        "record": sess.record.model_dump(),
        "done": sess.done,
        "turn_index": sess.turn_index,
        "max_turns": sess.max_turns,
        "live": sess.use_llm,
        "fell_back": sess.fell_back,
    }


# ---- LLM 스킬 5종 ---------------------------------------------------------


@app.post("/api/skills/checklist-plan", response_model=ChecklistPlan, tags=["skills"], summary="#0 검토 계획 수립")
def skill_checklist_plan(req: ChecklistPlanRequest) -> Any:
    return _run_skill(
        "checklist_plan",
        ChecklistPlan,
        {"facts": req.facts, "product_en": req.product_en},
        req.options,
        facts=req.facts,
    )


@app.post("/api/skills/verdict", response_model=RegulatoryVerdict, tags=["skills"], summary="#1 규정 판정")
def skill_verdict(req: VerdictRequest) -> Any:
    return _run_skill(
        "verdict",
        RegulatoryVerdict,
        {"item_no": req.item_no, "item": req.item, "law": req.law, "facts": req.facts},
        req.options,
    )


@app.post("/api/skills/disclosure", response_model=DualDisclosure, tags=["skills"], summary="#2 이중 공개")
def skill_disclosure(req: DisclosureRequest) -> Any:
    return _run_skill(
        "disclosure",
        DualDisclosure,
        {"item_no": req.item_no, "verdict": req.verdict.model_dump(), "remaining": req.remaining},
        req.options,
    )


@app.post("/api/skills/similar-cases", response_model=SimilarCasesResult, tags=["skills"], summary="#3 유사사례 검색")
def skill_similar_cases(req: SimilarCasesRequest) -> Any:
    return _run_skill(
        "similar_cases",
        SimilarCasesResult,
        {"product_en": req.product_en, "due_date": req.due_date},
        req.options,
        facts=req.facts,
    )


@app.post("/api/skills/renegotiation", response_model=RenegotiationDraft, tags=["skills"], summary="#4 재협상 재료 초안")
def skill_renegotiation(req: RenegotiationRequest) -> Any:
    similar = [c.model_dump() for c in req.similar_cases]
    context = {
        "blocking": req.blocking,
        "due_date": req.due_date,
        "similar_cases": similar,
        "estimated_completion": req.estimated_completion,
        "facts": {
            "due_date": req.due_date,
            "estimated_completion": req.estimated_completion,
            "similar_cases": similar,
        },
    }
    return _run_skill("renegotiation", RenegotiationDraft, context, req.options)


@app.post("/api/skills/rights-guide", response_model=ConsumerRightsGuide, tags=["skills"], summary="#6 소비자 권익 보호 안내")
def skill_rights_guide(req: RightsGuideRequest) -> Any:
    """이 사건의 원장(실제 판정)에 근거한 개인화 권익 안내 — 일반 FAQ가 아님(챌린지 주제②)."""
    return _run_skill(
        "rights_guide",
        ConsumerRightsGuide,
        {"ledger": req.ledger, "classification": req.classification, "facts": req.facts},
        req.options,
        facts=req.facts,
    )


@app.post("/api/skills/general-guidance", response_model=GeneralGuidance, tags=["skills"], summary="#7 비법률 일반 민원 안내")
def skill_general_guidance(req: GeneralGuidanceRequest) -> Any:
    """규정 판정 없이 사용자 상황에 맞춘 실질 안내(트리아지 general 트랙). 법률 소지 보이면 escalation_hint로 전환 안내."""
    return _run_skill(
        "general_guidance",
        GeneralGuidance,
        {"classification": req.classification, "facts": req.facts},
        req.options,
        facts=req.facts,
    )


# ---- 데모 프론트 엔드포인트 (직원 대시보드 + 민원인 앱) --------------------
# 기존 파이프라인/스킬 엔드포인트는 그대로 두고, 시연용 라우트를 얇게 얹는다.
# 반드시 정적 마운트("/") 앞에 include 해야 /api/* 가 가려지지 않는다.
app.include_router(demo_router)


# ---- React SPA 서빙 (빌드 산출물) -----------------------------------------
# `npm run build` 결과가 complaint_processing/ui/ 에 있으면 /ui 로 서빙한다.
# HashRouter 를 쓰므로 별도 catch-all 없이 index.html 하나로 전 화면이 동작한다.
_UI_DIR = _PKG_DIR / "ui"
if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")


# ---- 정적 프론트 서빙 (맨 끝: /api/* 라우트 뒤에 마운트해야 가림 없음) -----------
# viewer.html / mediation.html / frames.json / mediation.json 을 같은 오리진에서 서빙.
app.mount("/", StaticFiles(directory=str(_PKG_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
