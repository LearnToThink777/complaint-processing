# Phase 2 — 커맨드(Command) · 싱글턴(Singleton)

> **적용 디자인 패턴: 행위 - 커맨드(Command), 생성 - 싱글턴(Singleton).**
> 목표는 흩어진 `task` 정의를 한곳으로 모아, task 추가 시 백엔드 코드를 손대지 않게 하는 것.
> 겉보기 동작 불변(골든 테스트 4건 통과 + ProxyLLM 프롬프트·chunk_label 등가 확인).

## 문제 — task 문자열이 세 곳에 흩어짐
`task` 하나(예: `"verdict"`)의 정의가 세 군데로 나뉘어 있었다:
1. `llm.py`의 `MockLLM.structured()`(구 65~135번째 줄)의 `if/elif` 라우팅 — 더미 payload 조립
2. `llm.py`의 `ProxyLLM._system_prompt()`(구 92~125번째 줄)의 `guides` dict — 실제 LLM 지시문
3. 호출부 `agent.py`의 `structured("task", ...)`

→ task 하나를 추가하려면 1·2 두 파일을 동시에 고쳐야 했다(협업 시 충돌·누락 위험).

## 1. task 정의 → 커맨드(Command)
- 위 1·2에 흩어져 있던 task별 로직을, **커맨드 패턴**을 적용해 `tasks.py`의 `TaskSpec`
  객체 하나로 캡슐화했다. 하나의 `TaskSpec`이 `guide`(실제 LLM 지시문) +
  `build_mock`(더미 payload 빌더)를 함께 들고 있다.
- `MockLLM.structured()`는 이제 `if/elif` 없이 **레지스트리에서 TaskSpec을 조회해
  `spec.build_mock(context, fixtures)`를 호출**하고 스키마로 검증만 한다(70여 줄 → 4줄).
- `ProxyLLM._system_prompt()`는 내부 `guides` dict를 버리고 **레지스트리에서 `spec.guide`를
  조회**한다. 프롬프트 조립 형식(`base + guide + 컨텍스트`)은 그대로.

## 2. task 목록 → 레지스트리(Singleton)
- `tasks.py`에 `TaskRegistry`를 두고 **싱글턴**으로 만들었다(`task_registry()`가 최초 호출 때
  `_ALL_SPECS`로 1회 생성해 재사용). 프로세스 전체가 하나의 task 목록을 공유하고,
  백엔드(MockLLM/ProxyLLM)는 각자 목록을 들지 않고 이 하나를 조회한다.
- 미등록 task 조회 시 기존과 동일하게 `ValueError("알 수 없는 task: …")`.

## 효과
task 추가 = `tasks.py`의 `_ALL_SPECS`에 `TaskSpec` 하나 등록(+호출부). 백엔드 클래스
(`MockLLM`/`ProxyLLM`)는 **한 줄도 바뀌지 않는다.** 3중 편집 → 1곳 등록.

## 확인
- `pytest complaint_processing/tests` → 4건 통과(frames.json 재생성 불변).
- ProxyLLM 프롬프트 조립 문자열, `chunk_label` 더미 출력, 미등록 task 예외 메시지 등가 확인.
