# Phase 3 — 데코레이터(Decorator)

> **적용 디자인 패턴: 구조 - 데코레이터(Decorator).**
> 목표는 AgentOps(관측·재시도·캐시)를 도메인 코드 수정 0줄로 꽂을 이음새를 만드는 것.
> 겉보기 동작 불변(골든 테스트 4건 통과, 데코레이터는 출력을 손대지 않음).

## 무엇을 바꿨나
- `decorators.py`(신규)에 `LLMBackend`를 감싸는 **데코레이터** 계층을 추가했다. 각 데코레이터도
  스스로 `LLMBackend`라, `ObservableLLM(RetryingLLM(CachingLLM(base)))`처럼 겹쳐 끼울 수 있다.
  - `ObservableLLM` — 호출별 소요시간·성공/실패·task를 `TraceEntry`로 기록(Observability).
  - `RetryingLLM` — 실패 시 최대 N회 재시도(신뢰성).
  - `CachingLLM` — 동일 (task, schema, context) 호출 결과 캐시(비용·지연 절감).
- `llm.py`의 `get_backend()`(구 196~210번째 줄)가 base 백엔드만 만들어 반환하던 부분을,
  **데코레이터로 겉을 감싸도록** 확장했다: `observe`(기본 True)·`retries`·`cache` 플래그로
  필요한 데코레이터를 조립한다. `ObservableLLM`을 가장 바깥에 두어 에이전트가 실제로 부르는
  모든 호출을 계측한다.
- `run.py`: 실행 후 관측 요약(`호출 N건 · 성공/실패 · 총 ms`)을 출력하도록 한 줄 추가.

## 이미 있던 데코레이터
- `llm.py`의 `RetrievalLLM`은 이전부터 사실상 데코레이터였다(base 백엔드를 감싸 #0/#3만
  가로채고 나머지는 위임). 이번에 이 관계를 문서로 명시했다.

## 왜 이게 AgentOps의 이음새인가
관측·재시도·캐시는 "AI Agent의 운영/모니터링" 요구사항 그 자체다. 데코레이터로 넣었기에
`agent.py`(도메인 오케스트레이션)는 자기 호출이 계측/재시도/캐시되고 있다는 사실조차 모른다.
나중에 프롬프트 버전 태깅·토큰 집계·평가 훅도 같은 방식으로 데코레이터만 추가하면 된다.

## 확인
- `pytest complaint_processing/tests` → 4건 통과(frames.json 재생성 불변).
- 실제 실행 시 관측 트레이스에 LLM 호출 16건이 전부 성공으로 계측됨(감싸도 프레임 동일).
