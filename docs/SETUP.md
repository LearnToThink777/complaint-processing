# 로컬 실행 가이드 (Docker)

다른 개발자가 이 저장소를 clone해서 로컬에서 바로 띄우는 방법. Docker만 있으면
Python/Node 버전 맞출 필요 없이 동일한 환경으로 실행된다.

## 사전 요구사항

- Docker
- Git

## 1. Clone

```bash
git clone https://github.com/LearnToThink777/complaint-processing.git complaint_processing
cd complaint_processing
```

> `corpus_index.json`(법령 코퍼스 벡터 색인)이 74MB라 clone이 다소 걸릴 수 있다.

## 2. 환경변수 준비

```bash
cp .env.example .env
```

`.env`를 안 채워도 앱은 정상 동작한다 — 키가 없으면 실제 LLM 대신 오프라인
더미(fixtures/정적 스크립트) 응답으로 자동 폴백한다.

> **`MLAPI_*`는 아무나 발급받을 수 있는 공개 서비스가 아니다.** 카카오테크캠퍼스
> 부트캠프 참가자에게 개인별로 지급되는 사설 OpenAI 호환 프록시(mlapi.run)라서,
> 부트캠프 미참가자는 가입 페이지 자체가 없다 — Groq/Gemini API 키처럼 콘솔에서
> 발급받는 게 아니다. **이 프로젝트를 그냥 clone해서 보는 외부 개발자는 이 키를
> 채울 수 없고, 못 채워도 문제없다** — 더미 데이터로 전체 화면·플로우가 똑같이
> 동작한다. 라이브 LLM 호출만 못 볼 뿐이다.

부트캠프 참가자라면 **AI LXP → AI Cloud → Serverless 모델** 메뉴에서, 쓰려는
모델(nano/mini) 항목의 **'모델 설명'** 탭에 들어가면 API 키와 엔드포인트(base URL)를
확인할 수 있다. 그 값으로 아래 3개를 채우면 된다:

```
MLAPI_API_KEY=...
MLAPI_NANO_BASE_URL=...
MLAPI_BASE_URL=...
```

이 세 값으로 `mlapi-nano`(GPT-5 nano)·`mlapi-mini`(GPT-5 mini) 두 provider가 모두
켜진다. `GEMINI_API_KEY`는 채팅 LLM과 무관하고 벡터 색인을 새로 만들 때만
필요하므로(임베딩 전용, 누구나 https://aistudio.google.com 에서 무료 발급 가능),
그냥 실행만 할 거면 비워둬도 된다.

## 3. 빌드 & 실행

```bash
docker build -t complaint-processing .
docker run -p 8000:8000 --env-file .env complaint-processing
```

`.env`는 `.dockerignore`로 이미지에 포함되지 않으므로, 런타임에 `--env-file`로
주입해야 키가 적용된다.

## 4. 접속

| 화면 | URL | 비고 |
|---|---|---|
| Swagger API 문서 | http://localhost:8000/docs | 전체 엔드포인트 확인·테스트 |
| 관리자 시연용 SPA | http://localhost:8000/ui | React 기반 직원/민원인 대시보드 |
| 협상 중재 콘솔 | http://localhost:8000/mediation.html | 세션 시작 전 GPT-5 nano/mini 선택 가능 |

키를 안 채웠어도 세 화면 모두 정상적으로 뜨고, 실제 LLM이 필요한 부분만 자동으로
더미 데이터로 대체된다.

## 참고

- LLM provider는 `mlapi-nano`(기본, 빠름)와 `mlapi-mini`(고품질, 느림) 두 가지뿐이다.
- 세부 아키텍처는 [`ARCHITECTURE.md`](ARCHITECTURE.md), LLM 스킬별 입출력은
  [`SKILLS.md`](SKILLS.md) 참고.
