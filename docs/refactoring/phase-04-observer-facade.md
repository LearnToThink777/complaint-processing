# Phase 4 — 옵서버(Observer) · 퍼사드(Facade)

> **적용 디자인 패턴: 행위 - 옵서버(Observer), 구조 - 퍼사드(Facade).**
> 목표는 (1) 오케스트레이션에서 '뷰 포맷 지식'을 떼어내고, (2) 사건 처리 배선을 한 진입점 뒤로
> 숨기는 것. 겉보기 동작 불변(골든 테스트 4건 통과, run.py 실행 결과 동일).

## 1. 프레임 조립 → 옵서버(Observer)
- `agent.py`의 `emit()`(구 57~81번째 줄)이 viewer.html용 프레임 dict(키 17개·라벨)를
  **직접 조립·`copy.deepcopy`해서 `self.frames`에 append**하던 부분을, **옵서버 패턴**으로 분리했다.
- 이제 `emit()`은 등록된 옵서버들에게 "상태가 바뀌었다"고 통지만 한다(`obs.capture(self, phase, hop)`).
  프레임 dict 조립(뷰 포맷)은 `presentation.py`의 `FramePresenter`(옵서버)가 담당한다.
- `ComplaintAgent.__init__`에 `observers` 인자를 추가해, 기본 프레젠터 외에 다른 옵서버(예: 향후
  AgentOps 이벤트 수집기)를 붙일 수 있게 했다. `self.frames`는 프레젠터가 모은 목록을 돌려주는
  프로퍼티로 바뀌었다.
- 부수 효과: `agent.py`에서 `import copy`가 사라지고(프레젠터로 이동), `emit()`이 24줄 → 3줄.

## 2. 사건 처리 배선 → 퍼사드(Facade)
- `run.py`의 `build_agent()`가 하던 "케이스 검증 → `get_backend` → `ComplaintAgent` 생성 → 실행"의
  다단계 배선을, **퍼사드 패턴**으로 `facade.py`의 `run_complaint_case(case, ...) -> (frames, backend)`
  한 함수 뒤로 숨겼다.
- `run.py`의 `main()`은 이제 `build_agent`+`agent.run()`을 직접 엮지 않고 이 퍼사드만 호출한다.
  백엔드를 함께 돌려받아 관측 요약(Phase 3의 ObservableLLM)을 그대로 출력한다.
- 향후 웹 API(FastAPI 등)도 같은 퍼사드를 호출하면 되므로 진입점이 통일된다.

## 확인
- `pytest complaint_processing/tests` → 4건 통과(frames.json 재생성 불변).
- `python run.py --retrieval corpus_index.json` 정상 실행 — 12프레임 + 관측 16콜 요약 출력.
