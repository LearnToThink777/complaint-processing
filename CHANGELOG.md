# 변경 기록 (CHANGELOG)

이 파일은 **작업 재개용 단일 복원 지점**이다. 컨텍스트가 끊겨도 이 문서만 보면
"무엇을·어디에 했고·검증됐는지"를 즉시 파악할 수 있게 한다.
형식은 [Keep a Changelog](https://keepachangelog.com/) 관례를 따른다.

관련 문서: [README.md](README.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
[docs/SKILLS.md](docs/SKILLS.md) · [docs/DIFFERENTIATION.md](docs/DIFFERENTIATION.md) ·
[docs/SUBMISSION.md](docs/SUBMISSION.md)

---

## [Unreleased] — 2026-07-19

세 갈래 작업(웹 API + 스킬 2종)을 추가. 기존 계약(`agent.py`/`schemas.py`/`llm.py`의
`structured` 시그니처)은 **깨지 않고 additive**로 얹었다. 전 구간 `pytest complaint_processing/tests`
**16건 통과**로 검증. 골든(`frames.json`)은 의도적 동작 변경마다 재생성(MockLLM 결정론, API 키 불필요).

### Phase 1 — 웹 API 계층 (FastAPI + Swagger) ✅
CLI/라이브러리였던 프로젝트에 HTTP API를 얹어 `/docs`(Swagger UI)·`/redoc`·`/openapi.json` 자동 생성.

- **신규 `api.py`** — FastAPI 앱. 파이프라인/중재/LLM 스킬을 얇은 어댑터로 노출.
  `facade.run_complaint_case()`·`llm.get_backend().structured()` 재사용, `schemas.py`를 response_model로 물림.
  - 엔드포인트: `GET /health`, `GET /`(→/docs), `POST /api/cases/run`, `GET /api/frames`,
    `GET /api/mediation`, `POST /api/skills/{checklist-plan,verdict,disclosure,similar-cases,renegotiation}`.
  - `StaticFiles` 마운트(맨 끝)로 `viewer.html`·`mediation.html`·`frames.json`·`mediation.json`을 같은 오리진 서빙. `CORSMiddleware` 추가.
- **`requirements.txt`** — `fastapi`, `uvicorn[standard]`, `httpx`(TestClient 의존) 추가.
- **`viewer.html` / `mediation.html`** — `/api/frames`·`/api/mediation` 우선 fetch → 실패 시 정적 JSON 폴백.
- **`Dockerfile`** — `python -m http.server` → `uvicorn ... api:app`(API+정적 동시 서빙), `frames.json` 사전 생성 폴백.
- **신규 `tests/test_api.py`** — `TestClient` 스모크 + `GET /api/frames == frames.json`(골든 정합) 고정.
- 실행: `cd C:\Users\alstj\Downloads && uvicorn complaint_processing.api:app --reload` → http://127.0.0.1:8000/docs

### Phase 2A — #6 소비자 권익 보호 안내 (Consumer Rights Guide) ✅
종결 시 **이 사건의 실제 원장(판정)에 근거한 개인화 안내** — 일반 FAQ가 아니라 위반 사안 vs 무혐의
사안의 안내가 다르다. 챌린지 주제②("대응 절차·권리 보호 방안 안내")의 공백을 메움. 에이전트는 안내까지만.

- **`schemas.py`** — `ConsumerRightsGuide`, `RightsAction` 추가.
- **`tasks.py`** — `rights_guide` task(mock+prompt). mock은 원장에 위반 없으면 권리 목록을 접어 개인화 흉내.
- **`agent.py`** — `guide_rights()`(`[LLM #6]`) + 종결 단계 배선, 상태 `self.rights_guide`.
- **`presentation.py`** — frame에 `rights_guide` 키.
- **`api.py`** — `POST /api/skills/rights-guide` + `Frame.rights_guide`.
- **`fixtures.json`** — `rights_guide` 데모(ELS 배상 60% 사안).
- **`viewer.html`** — 🛡 소비자 권익 보호 안내 패널(종결 프레임에서만).
- **`tests/test_api.py`** — 위반→권리 3건 / 무혐의→권리 접힘 개인화 검증.
- 골든 재생성: `rights_guide` 키 추가(비종결 null, 종결에만 채워짐).

### Phase 2B — #7 비법률 일반 민원 트리아지 (General Complaint Triage) ✅
접수(#0) 시 **법률 분쟁(legal) / 비법률 안내·행정 민원(general)** 을 먼저 분류해 general은 규정 처리
없이 경량 안내로 종결. 모든 민원을 법률 파이프라인에 밀어넣지 않는다. 말씀하신 "비법률 일반 민원" 대응.

- **`schemas.py`** — `ChecklistPlan.track`(legal/general) 필드, `GeneralGuidance` 추가.
- **`tasks.py`** — `classify_track()` 키워드 휴리스틱(오프라인), `general_guidance` task,
  `_mock_checklist_plan`이 track 부여.
- **`llm.py`** — `RetrievalLLM` #0가 트랙 반영(general이면 법령 검색 skip), legal payload에 `track` 추가.
- **`agent.py`** — `general_guide()`(`[LLM #7]`), `_run_general()` 경량 경로, `run()` 트리아지 분기,
  상태 `self.track`/`self.general_guidance`. **legal 히스토리 순서는 그대로 유지**(분기를 `plan_checklist` 이후로).
- **`presentation.py`** — frame에 `track`·`general_guidance` 키.
- **`api.py`** — `POST /api/skills/general-guidance`, `GET /api/frames?case=general` 데모, `Frame.track`/`general_guidance`.
- **`fixtures.json`** — `case_general`(이체한도 문의) + `general_guidance` 데모.
- **`viewer.html`** — 트랙 배지(⚖ 법률 / 🧭 일반), general 트랙이면 법률 패널 숨김, ⚖/🧭 데모 토글, 일반 안내 패널.
- **`tests/test_api.py`** — `?case=general` 트랙 정합 + 스킬 형태 검증.
- 안전망: general 처리 중 법률 소지 시 `GeneralGuidance.escalation_hint`로 정식 민원 전환 안내.
- 골든 재생성: `track`(비접수 null, 이후 legal)·`general_guidance`(null) 키 추가.

### 문서 (이번 문서화 회차)
- 신규: `CHANGELOG.md`(이 파일), `docs/ARCHITECTURE.md`, `docs/SKILLS.md`, `docs/SUBMISSION.md`, `docs/DIFFERENTIATION.md`.
- 갱신: `README.md`(스킬 표 #7·테스트 소절·문서 링크), `docs/refactoring/README.md`(파일 구성·테스트 수), 테스트 개수 16 통일.

### 현재 상태 요약
- **LLM 스킬 9종**(호출 라벨): #0 `checklist_plan`, #1 `verdict`, #2 `disclosure`, #3 `similar_cases`,
  #4 `renegotiation`, #5 `closing_disclosure`, #6 `rights_guide`, #7 `general_guidance`, (색인) `chunk_label`.
- **API 스킬 엔드포인트 7개**(#5·색인은 미노출).
- **테스트**: `pytest complaint_processing/tests` → **16 passed**.
- **데모 2트랙**: legal(ELS, `frames.json`/`GET /api/frames`) · general(`GET /api/frames?case=general`).
