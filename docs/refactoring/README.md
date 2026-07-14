# 리팩토링 기록 — GoF 디자인 패턴(생성·구조·행위)

AgentOps 적용 전, 확장(진짜 벡터DB·진짜 LLM)과 협업을 위해 코드를 정처기 수준의 GoF
디자인 패턴으로 정돈한 과정. 모든 단계는 **겉보기 동작 불변**을 원칙으로 하며, 골든 테스트
(`complaint_processing/tests`)로 매 단계 검증했다.

## 단계별 기록
| Phase | 문서 | 적용 패턴 |
| --- | --- | --- |
| 0 | [phase-00-golden-test.md](phase-00-golden-test.md) | (안전망) 골든 테스트 |
| 1 | [phase-01-strategy-factory.md](phase-01-strategy-factory.md) | 전략, 팩토리 메서드 |
| 2 | [phase-02-command-singleton.md](phase-02-command-singleton.md) | 커맨드, 싱글턴 |
| 3 | [phase-03-decorator.md](phase-03-decorator.md) | 데코레이터 |
| 4 | [phase-04-observer-facade.md](phase-04-observer-facade.md) | 옵서버, 퍼사드 |
| 5 | [phase-05-state-review.md](phase-05-state-review.md) | (검토 후 미적용) 상태·템플릿메서드 |

## 패턴 분류 요약 (정처기 3분류)

### 생성(Creational)
- **팩토리 메서드(Factory Method)** — `llm.py` `get_backend()`: 요청한 조건에 맞는 LLM 백엔드
  + 데코레이터를 조립해 돌려준다. 호출부는 구체 클래스를 모른다.
- **싱글턴(Singleton)** — `tasks.py` `TaskRegistry`/`task_registry()`: task 목록을 프로세스당
  하나만 유지, 백엔드들이 공유 조회.

### 구조(Structural)
- **데코레이터(Decorator)** — `decorators.py` `ObservableLLM`/`RetryingLLM`/`CachingLLM`:
  LLM 호출에 관측·재시도·캐시를 도메인 수정 없이 덧씌운다(**AgentOps 이음새**).
  기존 `llm.py` `RetrievalLLM`도 같은 계열(일부 task만 가로채고 위임).
- **퍼사드(Facade)** — `facade.py` `run_complaint_case()`: 케이스→백엔드→에이전트→실행 배선을
  한 진입점 뒤로 숨긴다.

### 행위(Behavioral)
- **전략(Strategy)** — `retrieval.py` `ScorerStrategy`/`LexicalScorer`(임베딩 drop-in 지점),
  `llm.py` `LLMBackend`(Mock/Proxy 교체).
- **커맨드(Command)** — `tasks.py` `TaskSpec`: LLM 호출 한 종류를 객체로 캡슐화
  (지시문 guide + 더미 빌더 build_mock).
- **옵서버(Observer)** — `presentation.py` `FramePresenter`: 에이전트 상태 변화를 통지받아
  뷰 프레임으로 변환·수집. (`agent.py`가 Subject)
- **미디에이터(Mediator)** — 도메인 설계로 이미 실현(`mediation.html`/`MediationRecord`):
  당사자들이 중재 에이전트를 통해서만 교환.

## 테스트
```
pytest complaint_processing/tests        # 골든 프레임 + 중재 데이터 불변식 (4건)
python complaint_processing/run.py --retrieval corpus_index.json   # 실행 + 관측 요약
```

## 파일 구성(패턴 관점)
```
schemas.py       도메인 스키마 (엔티티/값 객체)
agent.py         오케스트레이션 (상태 기계) — Subject
tasks.py         커맨드 + 싱글턴 레지스트리
llm.py           전략(LLMBackend) + 팩토리(get_backend) + RetrievalLLM(데코)
decorators.py    데코레이터 (관측/재시도/캐시) = AgentOps 이음새
retrieval.py     전략(ScorerStrategy) + VectorStore
presentation.py  옵서버(FramePresenter)
facade.py        퍼사드(run_complaint_case)
```
