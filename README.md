# 민원 처리 에이전트 — LLM이 들어갈 자리

`민원 처리 콘솔 (단독 실행).html`은 겉보기엔 "에이전트가 일하는" 콘솔이지만,
실제로는 20여 스텝의 시나리오가 전부 `buildFrames()` 안에 **상수로 하드코딩**된
연출용 목업입니다. 이 패키지는 그 콘솔에서 **정말로 LLM이 판단/작문해야 하는
부분만** 뽑아내 실제 코드로 만든 것입니다.

기본은 **더미 JSON**(`fixtures.json`)으로 답하므로 프록시/키 없이 오프라인 실행됩니다.

## LLM이 들어가는 곳 (그 외는 결정론적 오케스트레이션)

| # | 스킬 | 콘솔의 하드코딩 위치 | 입력 → 출력 스키마 |
|---|------|---------------------|-------------------|
| 0 | **검토 계획 수립** | 체크리스트 상수 | 사건 사실 → `ChecklistPlan`(검토 항목 자체 + 근거를 vectorDB에서 도출) |
| 1 | **규정 판정** | `VERD` 객체 | 사건 사실 + 법률 항목 → `RegulatoryVerdict` |
| 2 | **이중 공개** | `PLAINU` + `discloseR` | 판정 → `DualDisclosure`(민원인용/감독원용) |
| 3 | **유사사례 검색 + 완료일 추정** | `s.vector` + 위험 배너 | 사건 유형 → `SimilarCasesResult` |
| 4 | **재협상 재료 초안** | `negoText` + 협상 공개문 | 발목잡는 항목 → `RenegotiationDraft` |
| 6 | **소비자 권익 보호 안내** | (신규 · 콘솔에 없음) | 종결 원장 → `ConsumerRightsGuide`(행사 가능 권리·절차·기한·확대경로) |
| 7 | **비법률 일반 민원 트리아지** | (신규 · 콘솔에 없음) | 사건 사실 → `ChecklistPlan.track`(legal/general) → general이면 `GeneralGuidance` |

> 전체 스킬 레퍼런스(입출력 스키마·프롬프트·예시)는 [`docs/SKILLS.md`](docs/SKILLS.md),
> 아키텍처·데이터 플로우는 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 참고.

> #6(소비자 권익 보호 안내): 종결 시 **이 사건의 실제 원장(판정)에 근거해** 소비자가 지금
> 행사할 수 있는 권리·대응 절차·기한·준비 서류·확대 경로(금감원 분쟁조정·소액소송)를
> 개인화해 안내합니다. 일반 FAQ가 아니라 사건별로 달라지는 안내라는 점이 시중은행 챗봇과
> 갈리는 지점입니다(위반 사안 vs 무혐의 사안의 안내가 다름). 챌린지 주제②('대응 절차·권리
> 보호 방안 안내')에 대응하며, 에이전트는 **안내까지만** 하고 권리 행사는 본인이 결정합니다.
> 프로젝트 차별점 정리는 [`docs/DIFFERENTIATION.md`](docs/DIFFERENTIATION.md) 참고.

> #7(비법률 일반 민원 트리아지): 접수(#0) 시 사건을 **법률 분쟁(legal) / 비법률 안내·행정
> 민원(general)** 으로 먼저 분류합니다. general이면 규정 판정·원장 처리를 건너뛰고 사용자
> 상황에 맞춘 실질 안내(`GeneralGuidance`)로 바로 종결합니다 — 모든 민원을 법률 파이프라인에
> 밀어넣지 않습니다. 오분류 안전망으로, 안내 중 법률 소지가 보이면 `escalation_hint`로 정식
> 민원 전환을 안내합니다. 트랙 판정은 `tasks.py::classify_track`(오프라인 키워드 근사) /
> 실제 LLM 프롬프트가 담당합니다.

> #0(검토 계획 수립): 접수 전엔 어떤 민원이 들어올지 모르므로, **검토 항목 목록
> 자체를 미리 정해두지 않습니다.** `ComplaintAgent`는 생성 시점에 체크리스트가
> 비어 있고(`self.checklist = []`), 이관 시에야 사건 사실을 vectorDB에 질의해
> "무엇을 검토해야 하는지"와 "그 근거가 어느 조문인지"를 함께 도출합니다 —
> Claude/Codex에게 질문을 던지면 그때 가서 근거를 찾아 답하는 것과 같은 순서.
> `--retrieval` 없이는 MockLLM이 `fixtures.json`의 데모 항목을 "이 사건에서 도출한
> 것처럼" 되돌립니다.

LLM이 **아닌** 부분: 사건 생성·이력 개시·원장 append·상태 전이·처리 기한 계산·
완결성 게이트(항목 개수 세기)·프레임 스냅샷 → 전부 `agent.py`의 상태 기계가 담당.

핵심 설계 포인트 — **에이전트는 자문·중재만** 합니다. 재협상(#4)에서 새 기한은
`recommended_new_due_date`로 *권고*만 하고, 확정은 사람(민원인·감독원)이 합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | 변경 기록 — 작업 재개용 단일 복원 지점 |
| [`docs/SETUP.md`](docs/SETUP.md) | 로컬 실행 가이드(Docker) — 다른 개발자용 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 아키텍처 개요 + 데이터 플로우(mermaid) |
| [`docs/SKILLS.md`](docs/SKILLS.md) | LLM 스킬 레퍼런스 #0~#7(입출력·프롬프트·예시) |
| [`docs/DIFFERENTIATION.md`](docs/DIFFERENTIATION.md) | 챌린지 주제 대비 차별점 정리 |
| [`docs/SUBMISSION.md`](docs/SUBMISSION.md) | 챌린지 제출 문서(개요·데모 시나리오) |
| [`docs/refactoring/`](docs/refactoring/README.md) | GoF 패턴 리팩토링 기록 |
| [`docs/critic-verification.md`](docs/critic-verification.md) | 출력 검증(Critic) 설계 |

## 구조

이 저장소는 chonnam-clone(부트캠프 실습 저장소)과는 **독립된 별개 프로젝트**입니다 —
`provider="proxy"`를 쓸 때만 그 저장소 경로가 필요하고, 그 외엔 전혀 몰라도 됩니다.

```
complaint_processing/
  schemas.py         # LLM 구조화 출력 스키마 + 색인 라벨(ChunkLabels) + 사건/중재 입력 (Pydantic)
  tasks.py           # TaskRegistry — task별 프롬프트/mock 빌더 (커맨드 패턴)
  llm.py             # 호출 경계: MockLLM / MlapiLLM / ProxyLLM / RetrievalLLM — 같은 시그니처
  decorators.py      # ObservableLLM / RetryingLLM / CachingLLM / CriticLLM (데코레이터 체인)
  critic.py          # 출력 검증(Critic) — 4단계 claim 판정 라우터 + semantic 검증기
  fixtures.json      # 더미 답변 (콘솔 상수와 동일 내용)
  agent.py           # 오케스트레이터: 언제 LLM을 부를지 아는 상태 기계
  facade.py          # run_complaint_case() — run.py/api.py가 공유하는 진입점
  run.py             # CLI 실행기 (콘솔 호환 frames JSON 생성)
  api.py             # FastAPI 앱 — Swagger(/docs) + 정적 프론트 서빙
  demo_api.py        # 관리자 시연용 SPA 전용 API(/api/staff/*, /api/complainant/*)
  demo_store.py      # 위 데모 API가 쓰는 캔드(canned) 인메모리 데이터
  mediation_live.py  # 라이브 중재 세션 스토어(턴 단위 진행, LLM 폴백 포함)
  retrieval.py       # 검색 코어: 청킹 · 메타 파싱 · VectorStore · 유사사례 조립 (LLM 아님)
  build_index.py     # (a) 오프라인 색인 스크립트 → corpus_index.json
  viewer.html         # 정적 콘솔 — /api/frames 소비, 실패 시 frames.json 폴백
  mediation.html      # 정적 중재 콘솔 — 정적 재생 + 라이브 세션(GPT-5 nano/mini 선택) 둘 다 지원
  frontend/          # React SPA 소스(Vite) — 빌드 산출물은 ui/ 로 나가 /ui 에서 서빙
  ui/                # frontend/ 빌드 산출물(커밋됨) — 소스 수정 없인 다시 빌드할 필요 없음
  tests/             # pytest 스위트
  docs/              # 아키텍처·스킬·셋업 등 상세 문서
  Dockerfile         # 단일 컨테이너로 API+정적 프론트 서빙
```

## 실행

> Docker로 바로 띄우려면(다른 개발자용) [`docs/SETUP.md`](docs/SETUP.md) 참고.

```bash
python run.py                              # 더미로 전체 시퀀스
python run.py --json frames.json           # 콘솔 호환 JSON 저장

# 또는 이 저장소를 담은 상위 폴더에서 패키지로 실행하고 싶다면
# (패키지 이름이 폴더명과 같아야 함, 예: 상위 폴더에서):
python -m complaint_processing.run
```

## 웹 API (FastAPI + Swagger)

콘솔이 정적 `frames.json`을 `fetch`하던 구조를, **HTTP API로 노출**했습니다.
`api.py`는 기존 계약(`agent.py`/`schemas.py`/`llm.py`)을 안 건드리고 얇은 어댑터로 얹은
것이라, `facade.run_complaint_case()`와 `llm.get_backend().structured()`를 그대로 재사용합니다.
스키마가 곧 Pydantic 계약이므로 **Swagger 문서는 자동 생성**됩니다.

```bash
pip install -r requirements.txt
# 이 폴더가 상대 import로 짜여 있어(complaint_processing 패키지), 폴더명이
# 반드시 "complaint_processing"이어야 한다 — 아니라면 그 이름으로 바꾸거나
# clone 시 대상 폴더명을 지정하세요(docs/SETUP.md 참고).
uvicorn --app-dir .. complaint_processing.api:app --reload   # http://127.0.0.1:8000
```

> 폴더명 신경 쓰기 싫으면 Docker(`docs/SETUP.md`)로 띄우세요 — 이미지 안에서 자동으로 맞춰줍니다.

| 문서/UI | 경로 |
|---|---|
| Swagger UI | `/docs` |
| ReDoc | `/redoc` |
| OpenAPI 스펙(JSON) | `/openapi.json` |

엔드포인트(태그별):

| 메서드 · 경로 | 태그 | 반환(스키마) |
|---|---|---|
| `POST /api/cases/run` | pipeline | 프레임 전체 + 관측/검증 요약 |
| `GET /api/frames` | pipeline | 프레임 배열(골든과 동일 설정: 더미 + 색인 + `today=2026-07-15`) |
| `GET /api/mediation` | mediation | 정적 중재 기록 배열(`MediationRecord[]`) |
| `GET /api/mediation/live/scenarios` | mediation | 라이브 세션용 시나리오 목록 |
| `POST /api/mediation/live/start` | mediation | 라이브 세션 시작(`provider`: `mlapi-nano`/`mlapi-mini`) |
| `POST /api/mediation/live/{sid}/turn` | mediation | 라이브 세션 한 턴 진행 |
| `GET /api/mediation/live/{sid}` | mediation | 라이브 세션 현재 상태 |
| `POST /api/skills/checklist-plan` | skills | `ChecklistPlan` (#0) |
| `POST /api/skills/verdict` | skills | `RegulatoryVerdict` (#1) |
| `POST /api/skills/disclosure` | skills | `DualDisclosure` (#2) |
| `POST /api/skills/similar-cases` | skills | `SimilarCasesResult` (#3) |
| `POST /api/skills/renegotiation` | skills | `RenegotiationDraft` (#4) |
| `POST /api/skills/rights-guide` | skills | `ConsumerRightsGuide` (#6 · 소비자 권익 보호 안내) |
| `POST /api/skills/general-guidance` | skills | `GeneralGuidance` (#7 · 비법률 일반 민원 안내) |

`GET /api/frames?case=general` 로 비법률 일반 민원(general 트랙) 트리아지 데모도 볼 수 있습니다
(viewer.html 상단 **⚖ 법률 민원 / 🧭 일반 민원** 토글).

각 요청 body의 `options`(`use_llm`/`provider`/`retrieval`/`critic`)가 `get_backend`로 그대로
흘러갑니다. 기본은 오프라인 더미라 키·네트워크 없이 즉시 응답합니다.

**프론트엔드 — 세 갈래**: FastAPI 한 서버가 전부 같은 오리진에서 서빙합니다(Docker도 동일).

- `/viewer.html`·`/mediation.html` — 원래 콘솔. 먼저 `/api/frames`·`/api/mediation`을 부르고
  실패하면 정적 `frames.json`·`mediation.json`으로 폴백(`file://`로 직접 열어도 동작). `mediation.html`은
  정적 재생 모드 외에 **라이브 중재 모드**도 지원 — 세션 시작 전 `GPT-5 nano`/`mini`를 고를 수 있다.
- `/ui` — 관리자 시연용 React SPA(`frontend/`, Vite 빌드 산출물이 `ui/`에 커밋됨). 캔드 데이터는
  `demo_api.py`/`demo_store.py`, 일부 화면은 `provider` 선택 드롭다운으로 실제 스킬 API를 직접 호출.

각 요청 body/쿼리의 `provider`는 `mlapi-nano`(기본, 빠름)·`mlapi-mini`(고품질, 느림)·`proxy`
(chonnam-clone 필요) 중 하나입니다 — 자세한 키 발급 경로는 [`docs/SETUP.md`](docs/SETUP.md) 참고.

## 테스트

```bash
pip install -r requirements.txt   # fastapi/httpx 포함 (API 테스트에 필요)
pytest tests                       # 19 passed
```

| 테스트 파일 | 검증 |
|---|---|
| `tests/test_golden_frames.py` | 프레임 재생성 == 골든 `frames.json`(리팩토링 안전망) |
| `tests/test_mediation.py` | `mediation.json` 불변식(스키마·seq·refs) |
| `tests/test_critic.py` | Critic 라우터 + `CriticLLM` PASS/BLOCK 불변식 |
| `tests/test_api.py` | FastAPI `TestClient` 스모크 + `/api/frames`==골든 + #6/#7 개인화·트랙 |

> 골든(`frames.json`)은 **MockLLM 결정론**으로 생성되므로 API 키가 필요 없습니다. 파이프라인에
> 단계를 추가/변경하면 골든을 재생성해야 합니다(이 명령은 패키지 폴더의 **부모** 디렉터리에서 실행):
> `python -c "import json,pathlib; from complaint_processing.tests.test_golden_frames import regenerate_frames; pathlib.Path('complaint_processing/frames.json').write_text(json.dumps(regenerate_frames(),ensure_ascii=False,indent=2),encoding='utf-8')"`

## 더미 → 실제 LLM 교체

`agent.py`는 백엔드를 모릅니다. `llm.py`의 `get_backend(use_llm=True, provider=...)` 한 줄이
`MockLLM` → 실제 LLM으로 바뀔 뿐입니다. 스키마가 계약이라 오케스트레이터는 수정 없이 그대로 돕니다.

기본 경로는 `provider="mlapi-nano"`(빠름, `get_backend`의 기본값) — 부트캠프 발급 프록시
(`mlapi.run`)를 쓰며, 키 발급 경로·`.env` 설정은 [`docs/SETUP.md`](docs/SETUP.md)에 정리돼 있습니다.

```bash
python run.py --llm                        # 실제 LLM 호출 (provider 기본값 mlapi-nano)
```

`run.py`는 CLI에서 provider를 바꾸는 플래그가 없습니다 — `mlapi-mini`나 `provider="proxy"`
(`ProxyLLM`, 이 폴더 밖 chonnam-clone 저장소의 `fixed/llm.py::chat_model()` 사용)로 바꾸려면
`facade.run_complaint_case(case, use_llm=True, provider=...)`를 직접 호출하거나, 웹 API
쪽 엔드포인트(요청 body의 `provider` 필드)를 쓰면 됩니다. `proxy`를 쓰려면 그 저장소 경로를
알려주고 `.env`에 `PROXY_TOKEN`도 있어야 합니다:

```bash
set CHONNAM_CLONE_REPO=<chonnam-clone 저장소 경로>
```

## 콘솔에 다시 꽂기

`run.py --json`이 내보내는 프레임은 콘솔 `frames[]`와 호환되는 키를 씁니다
(`status`, `checklist`, `ledger`, `disclose_u/r`, `vector`, `nego_state` ...).
즉 HTML은 순수 렌더러가 되고, 데이터 생성은 이 에이전트가 맡는 구조로 분리됩니다.

## 검색(RAG) — #0 검토 계획 · #3 유사사례를 진짜 벡터 검색으로

기본은 `fixtures.json`을 통째로 돌려주는 목업입니다. 이걸 **실검색으로 바꾸는
2단 구조**(청킹 → 라벨링)를 두 조각으로 붙여뒀습니다. `agent.py`·`schemas.py`의
기존 계약은 안 건드리고, `schemas.py`엔 색인용 출력 스키마 `ChunkLabels`만 추가.

**청킹은 LLM이 안 합니다.** 코퍼스가 이미 구조를 갖고 있어서 규칙으로 잘립니다:

| 코퍼스 | 청킹 단위(구조 규칙) | 정형 메타(파싱) | LLM 라벨(색인 1회) |
|---|---|---|---|
| 법령 | 조(條) 1개 = 청크 1개 | 법령명·조번호·권역 | 쟁점 요약·일상어 질문 |
| 분쟁조정 결정문 | 섹션(개요/주장/판단/결정) 단위 | 사건번호·상품유형·배상비율·소요영업일 | 〃 |

LLM은 **일상어 라벨**에만 씁니다 — "손실보전 약속 정황"(문서) ↔ "돈 떼였어요"(민원인)의
비대칭을 색인 때 미리 메꿔 검색이 걸리게 합니다.

```
build_index.py   (a) 오프라인 색인 — 데이터 넣을 때 1회
   원본 → [청킹: retrieval.chunk_*] → [메타 파싱] → [LLM 일상어 라벨] → corpus_index.json

llm.py::RetrievalLLM   (b) 검색 백엔드 — #0/#3만 오버라이드, #1/#2/#4는 base에 위임
   corpus_index.json → VectorStore(메타 필터 + 유사도)
     ├─ #0: 사건 사실로 법령 코퍼스 질의 → 검토 항목 자체를 도출 → ChecklistPlan
     └─ #3: 사건 사실 + 상품유형 필터로 결정문 조회           → SimilarCasesResult
```

```bash
python build_index.py            # corpus_index.json 생성 (더미 라벨)
python build_index.py --llm      # 실제 LLM으로 일상어 라벨 생성
python run.py --retrieval        # #0(검토 계획)·#3(유사사례)만 실검색으로 (나머지는 더미)
python run.py --llm --retrieval  # 전부 실제 LLM + 실검색
```

> 검색 스코어링은 2단 전략입니다: 색인에 사전계산 임베딩이 없으면 `retrieval.py::LexicalScorer`
> (어휘 겹침·Jaccard 근사, 외부 의존성 0)로 폴백하고, `build_index.py --embed`로 임베딩을
> 미리 계산해두면 `EmbeddingScorer`(로컬 `sentence-transformers` 또는 Gemini 임베딩, 코사인
> 유사도)가 대신 쓰입니다 — 임베딩 클라이언트 생성이 실패해도(키 없음 등) 자동으로 Jaccard로
> 떨어지므로 색인 형식이 달라도 항상 동작합니다.

## 컴포넌트 구성

`agent.py`(상태 기계)는 `schemas.py`(Pydantic 계약)와 `LLMBackend`(전략 인터페이스)에만
의존하고, 실제 구현이 `MockLLM`/`MlapiLLM`/`ProxyLLM` 중 무엇인지, `ObservableLLM`/`CriticLLM`/
`RetrievalLLM` 같은 데코레이터가 몇 겹 감쌌는지는 모릅니다 — 그래서 더미 → 실제 LLM 교체가
`agent.py` 수정 없이 `get_backend()` 호출부(팩토리, `llm.py`)에서만 일어납니다. 전체 컴포넌트
다이어그램·의존 방향·데코레이터 체인 조립 순서는 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)의
mermaid 다이어그램을 참고하세요 — 이 README는 진입점 요약까지만 다룹니다.
