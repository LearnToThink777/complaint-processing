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
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 아키텍처 개요 + 데이터 플로우(mermaid) |
| [`docs/SKILLS.md`](docs/SKILLS.md) | LLM 스킬 레퍼런스 #0~#7(입출력·프롬프트·예시) |
| [`docs/DIFFERENTIATION.md`](docs/DIFFERENTIATION.md) | 챌린지 주제 대비 차별점 정리 |
| [`docs/SUBMISSION.md`](docs/SUBMISSION.md) | 챌린지 제출 문서(개요·데모 시나리오) |
| [`docs/refactoring/`](docs/refactoring/README.md) | GoF 패턴 리팩토링 기록 |
| [`docs/critic-verification.md`](docs/critic-verification.md) | 출력 검증(Critic) 설계 |

## 구조

이 폴더는 chonnam-clone 저장소 **밖**(`Downloads/complaint_processing`)에 독립적으로 둔 것입니다.

```
complaint_processing/
  schemas.py     # LLM 구조화 출력 5종(검토 계획 포함) + 색인 라벨(ChunkLabels) + 사건 입력 (Pydantic)
  llm.py         # 호출 경계: MockLLM / ProxyLLM / RetrievalLLM — 같은 시그니처
  fixtures.json  # 더미 답변 (콘솔 상수와 동일 내용)
  agent.py       # 오케스트레이터: 언제 LLM을 부를지 아는 상태 기계
  run.py         # 실행기 (콘솔 호환 frames JSON 생성)
  retrieval.py   # 검색 코어: 청킹 · 메타 파싱 · VectorStore · 유사사례 조립 (LLM 아님)
  build_index.py # (a) 오프라인 색인 스크립트 → corpus_index.json
```

## 실행

```bash
cd C:\Users\alstj\Downloads\complaint_processing
python run.py                              # 더미로 전체 시퀀스
python run.py --json frames.json           # 콘솔 호환 JSON 저장

# 또는 Downloads에서 모듈로:
cd C:\Users\alstj\Downloads
python -m complaint_processing.run
```

## 웹 API (FastAPI + Swagger)

콘솔이 정적 `frames.json`을 `fetch`하던 구조를, **HTTP API로 노출**했습니다.
`api.py`는 기존 계약(`agent.py`/`schemas.py`/`llm.py`)을 안 건드리고 얇은 어댑터로 얹은
것이라, `facade.run_complaint_case()`와 `llm.get_backend().structured()`를 그대로 재사용합니다.
스키마가 곧 Pydantic 계약이므로 **Swagger 문서는 자동 생성**됩니다.

```bash
cd C:\Users\alstj\Downloads
pip install -r complaint_processing/requirements.txt
uvicorn complaint_processing.api:app --reload   # http://127.0.0.1:8000
```

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
| `GET /api/mediation` | mediation | 중재 기록 배열(`MediationRecord[]`) |
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

**프론트엔드 — API 우선 + 정적 폴백**: FastAPI가 `viewer.html`·`mediation.html`도 같은
오리진에서 서빙합니다(맨 끝 `StaticFiles` 마운트). 두 HTML은 먼저 `/api/frames`·`/api/mediation`을
부르고, 실패하면 기존 정적 `frames.json`·`mediation.json`으로 폴백합니다 — 서버 위(`/viewer.html`)
든 `file://`로 열든 둘 다 동작합니다. Docker(`Dockerfile`)도 `http.server` 대신 uvicorn으로
API와 정적 프론트를 한 서버에서 서빙하도록 바꿨습니다.

## 테스트

```bash
cd C:\Users\alstj\Downloads
pip install -r complaint_processing/requirements.txt   # fastapi/httpx 포함 (API 테스트에 필요)
pytest complaint_processing/tests                       # 16 passed
```

| 테스트 파일 | 검증 |
|---|---|
| `tests/test_golden_frames.py` | 프레임 재생성 == 골든 `frames.json`(리팩토링 안전망) |
| `tests/test_mediation.py` | `mediation.json` 불변식(스키마·seq·refs) |
| `tests/test_critic.py` | Critic 라우터 + `CriticLLM` PASS/BLOCK 불변식 |
| `tests/test_api.py` | FastAPI `TestClient` 스모크 + `/api/frames`==골든 + #6/#7 개인화·트랙 |

> 골든(`frames.json`)은 **MockLLM 결정론**으로 생성되므로 API 키가 필요 없습니다. 파이프라인에
> 단계를 추가/변경하면 골든을 재생성해야 합니다:
> `python -c "import json,pathlib; from complaint_processing.tests.test_golden_frames import regenerate_frames; pathlib.Path('complaint_processing/frames.json').write_text(json.dumps(regenerate_frames(),ensure_ascii=False,indent=2),encoding='utf-8')"`

## 더미 → 실제 LLM 교체

`agent.py`는 백엔드를 모릅니다. `llm.py`의 `get_backend(use_llm=True)` 한 줄이
`MockLLM` → `ProxyLLM`으로 바뀔 뿐이고, `ProxyLLM`은 chonnam-clone 저장소의
`fixed/llm.py::chat_model()`을 `with_structured_output(schema, method="function_calling")`로
감싸 week02와 똑같은 관용구로 호출합니다. 스키마가 계약이라 오케스트레이터는 수정 없이 그대로 돕니다.

이 폴더가 저장소 밖에 있으므로, `--llm`을 쓰려면 저장소 경로를 알려줘야 합니다:

```bash
set CHONNAM_CLONE_REPO=C:\Users\alstj\Downloads\kakaotechcampus04\chonnam-clone
python run.py --llm
```

(그 저장소의 `.env`에 `PROXY_TOKEN`도 설정돼 있어야 합니다.)

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

> 임베딩은 외부 의존성을 피해 `retrieval.py::VectorStore._score()`에서 **어휘 겹침
> (Jaccard)으로 근사**했습니다. 실제로는 그 한 줄을 임베딩 코사인 유사도로 교체하면 됩니다.

## 컴포넌트 구성 (누가 누구를 알고, 무엇을 주고받는가)

```
run.py
  └─ ComplaintAgent(agent.py)          ← 상태 기계 (오케스트레이터)
       ├─ ComplaintCase(schemas.py)     : 입력 컨텍스트 (읽기 전용)
       ├─ 결정론 상태
       │    status / checklist / ledger / history / due_date / frames
       └─ LLMBackend(llm.py)            ← 호출 경계 (agent.py는 구현을 모름)
            ├─ MockLLM   → fixtures.json 를 읽어 schema.model_validate()
            └─ ProxyLLM  → fixed/llm.py::chat_model() (chonnam-clone 저장소, CHONNAM_CLONE_REPO 필요)

LLM 호출 5곳 (agent.py 메서드 → schemas.py 반환 타입)
  plan_checklist()         -> ChecklistPlan       (이관 시 — 항목 자체가 여기서 정해짐)
  review_item()            -> RegulatoryVerdict
  dual_disclose()          -> DualDisclosure
  retrieve_similar_cases() -> SimilarCasesResult
  draft_renegotiation()    -> RenegotiationDraft
```

**의존 방향은 한쪽으로만 흐릅니다.**

| 컴포넌트 | 알고 있는 것 | 모르는 것 |
|---|---|---|
| `agent.py` | `LLMBackend.structured(task, schema, context)` 시그니처, `schemas.py`의 각 스키마 | 백엔드가 `MockLLM`인지 `ProxyLLM`인지 |
| `llm.py` (`MockLLM`/`ProxyLLM`) | 자신이 반환해야 할 `schemas.py`의 Pydantic 모델 | `agent.py`의 상태 전이 로직 |
| `schemas.py` | 아무것도 — 순수 데이터 계약 | 누가 자신을 채우는지, 누가 소비하는지 |
| `run.py` | `ComplaintAgent`를 생성해 `run()` 호출, 결과를 JSON/콘솔 포맷으로 출력 | LLM 호출이 몇 번 일어나는지, 어떤 백엔드인지 |

이 표가 곧 "더미 → 실제 LLM 교체가 `agent.py` 수정 없이 가능한" 이유입니다 —
`agent.py`는 `schemas.py`라는 계약과 `LLMBackend`라는 인터페이스에만 의존하고,
`llm.py`의 구체 구현(`MockLLM`/`ProxyLLM`)은 그 계약 뒤에 숨어 있습니다.
