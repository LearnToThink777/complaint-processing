# Phase 1 — 전략(Strategy) · 팩토리 메서드(Factory Method)

> **적용 디자인 패턴: 행위 - 전략(Strategy), 생성 - 팩토리 메서드(Factory Method).**
> 목표는 "진짜 벡터DB·진짜 LLM으로 갈아끼우기"를 코드 수정 없이 가능하게 만드는 것.
> 겉보기 동작은 불변(골든 테스트 4건 통과).

## 1. 검색 점수 → 전략(Strategy)
- `retrieval.py`의 `VectorStore._score()`(구 112번째 줄 부근)에 어휘 겹침(Jaccard) 계산이
  **하드코딩**돼 있고 "여기 임베딩으로 교체하라"는 주석만 있던 부분을, **전략 패턴**을 적용해
  `ScorerStrategy`(인터페이스) + `LexicalScorer`(기본 구현)로 분리했다.
- `VectorStore`는 이제 점수 계산을 주입받은 `scorer`에 위임한다(`__init__(chunks, scorer=None)`,
  기본값 `LexicalScorer`). 필터·정렬 로직은 점수 방식과 무관하게 그대로 둔다.
- **효과**: 진짜 임베딩은 `EmbeddingScorer(ScorerStrategy)`를 새로 만들어
  `VectorStore(chunks, scorer=EmbeddingScorer(...))`로 주입만 하면 된다. `VectorStore`와
  검색 호출부(agent/llm)는 한 줄도 바뀌지 않는다.

## 2. LLM 백엔드 → 전략(Strategy) 명시화
- `llm.py`의 `LLMBackend`가 `structured()`에서 `raise NotImplementedError`만 하던 '느슨한'
  인터페이스였던 부분을, `abc.ABC` + `@abstractmethod`로 바꿔 **전략 인터페이스**임을 코드로
  명시했다(`MockLLM`/`ProxyLLM`/`RetrievalLLM`이 교체 가능한 구체 전략).
- 구조 변경은 없고(이미 전략 형태였음), "이것이 Strategy의 Strategy 역할"이라는 계약을
  타입 시스템으로 강제한 것.

## 3. `get_backend()` → 팩토리 메서드(Factory Method)
- `llm.py`의 `get_backend()`가 `use_llm`/`retrieval_index`에 따라 어떤 구체 백엔드를 생성·조합할지
  결정하던 부분을 **팩토리 메서드**로 문서화·정돈했다. 호출부는 "어떤 전략이 필요한지"만
  말하고, 구체 클래스 생성·조합은 이 함수가 캡슐화한다.

## 확인
`pytest complaint_processing/tests` → 4건 통과 (frames.json 재생성 결과 불변).
