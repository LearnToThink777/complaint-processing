# Phase 0 — 골든 테스트 (안전망 구축)

> **적용 디자인 패턴: 없음.** 이 단계는 패턴 리팩토링이 아니라, 이후 Phase 1~4가
> "겉보기 동작을 바꾸지 않는지"를 기계로 검증할 안전망을 까는 준비 작업이다.
> 실제 GoF 패턴 적용은 Phase 1부터 기록된다.

## 왜 먼저 하나
리팩토링은 정의상 "동작 불변, 구조만 개선"이다. 그 불변을 눈이 아니라 테스트로
고정해 두어야, 이후 패턴을 갈아끼울 때 회귀를 즉시 잡을 수 있다.

## 무엇을 추가했나
- **`tests/test_golden_frames.py` (신규)** — `agent.py`가 `run.py --retrieval corpus_index.json`과
  동일한 설정(MockLLM + 검색)으로 만드는 프레임이, 커밋된 `frames.json`과 한 글자도
  다르지 않은지 고정한다. 이후 어느 Phase에서든 이 결과가 바뀌면 실패한다.
- **`tests/test_mediation.py` (신규)** — `mediation.json`의 불변식 3가지를 고정한다:
  스키마 유효성(`MediationRecord`), `log` seq가 1..N 연속, 모든 근거 ref가 `log` 안에 실재
  (아직 등장하지 않은 미래 시점을 근거로 인용하던 버그의 재발 방지).

## 확인
`pytest complaint_processing/tests` → 4건 통과. *(당시 수치. 이후 critic·api 테스트가 더해져 현재는 16건 — [CHANGELOG](../../CHANGELOG.md) 참조.)*

## 이후 각 Phase 규칙
`리팩토링 → pytest 통과 확인 → 이 md 기록 → 커밋` 순서를 반복한다.
