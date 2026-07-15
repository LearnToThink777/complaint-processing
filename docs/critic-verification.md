# 출력 검증(Critic) — 설계

작업 agent(`ComplaintAgent`)의 산출물이 **입력 밖의 것을 지어냈는지**(할루시네이션)를,
작업 agent의 추론(CoT)이 아니라 **결과물만** 놓고 독립적으로 대조하는 컴포넌트.
"AgentOps"가 아니라 **출력 검증/가드레일**이다.

## 설계 원칙 (왜 이렇게)
1. **자기채점 금지** — 판정하는 눈은 작업 agent 밖에 둔다. Critic은 작업 agent의 추론을
   보지 않고 `(입력 context, 출력 payload)`만 받아 대조한다.
2. **BLOCK은 100% 확신할 때만** — 인용한 조문이 허용 목록에 없을 때(확정)만 차단한다.
   수치 확인 불가·규범 판단 애매는 전부 ESCALATE(사람)로 보낸다. Critic의 오판이 정상
   출력을 막는 사고를 구조적으로 없앤다.
3. **LLM은 최후에만** — 확정 가능한 검증(조문 실재·수치)은 규칙으로 처리하고, 진짜 규범
   판단만 판단 전략(기본은 어휘겹침, 실제 LLM 앙상블로 교체)에 맡긴다.

## 4단계 라우터 (`critic.py`)
`verify(detail, law, facts)` 한 호출이 다음을 수행한다.

1. **분해(decompose)** — 출력 문장을 claim(원자적 주장) 단위로 쪼갠다.
2. **분류(classify)** — 각 claim을 세 종류로:
   - `structural_law` : 제N조 인용 → 허용 law 목록으로 확정 검증(LLM 불필요)
   - `structural_fact`: 수치 인용 → facts의 수치와 대조(LLM 불필요)
   - `semantic`       : 그 외 규범 판단 → 판단 전략에 위임
3. **검증 라우팅(route)** — 종류별로 다르게 검증한다.
   - law : 인용 (법령명, 조문)이 허용 집합에 있나? 없으면 **확정 실패(하드)**.
   - fact: claim의 수치가 facts 안에 있나? 없으면 **불확실(None)**.
   - semantic: 근거에 함의되나? 불확실이면 **None**.
4. **집계(aggregate)** — 하드 실패가 하나라도 있으면 **BLOCK**, 불확실이 있으면
   **ESCALATE**, 둘 다 없으면 **PASS**.

## 파이프라인 결합 (`decorators.py`의 `CriticLLM`)
`CriticLLM`은 LLM 백엔드를 감싸는 **데코레이터**다(기존 관측/재시도/캐시와 같은 계열).
`structured()` 결과를 받아, context에 근거(law/facts)가 있으면 `verify()`로 대조한다.
- 근거가 없는 task(예: disclosure)는 건너뛴다.
- `enforce=False`(기본): 판정을 기록만 하고 통과(보고 전용).
- `enforce=True`: BLOCK 시 `CriticBlocked` 예외로 산출을 **사용자에게 가기 전에** 막는다.

조립은 `get_backend(critic=True[, critic_enforce=True])`로 켠다. 위치는 산출 직후(base/검색
바로 위), 관측(ObservableLLM)보다 안쪽이라 검증도 계측된다.

## 검증된 예시
- 할루시네이션: `여신전문금융업법 제34조`(허용 목록에 없음) 인용 → `structural_law` 단계에서
  **확정 실패 → BLOCK**. LLM 판단이 개입할 여지가 없어 self-preference bias 문제 자체가 없다.
- 정상 fixtures 6개 판정: mock 실행 시 **BLOCK 0** (PASS 4 · ESCALATE 2 — 배상비율 40%·60%는
  facts로 확인 불가라 에스컬레이트).

## 재현성 메모
유사사례 예상 완료일이 실제 시계(`date.today()`)에 의존해 골든 테스트가 날짜에 따라 깨지던
잠재 버그를 함께 고쳤다. `get_backend(..., today=...)`로 기준일을 주입할 수 있게 하고,
`frames.json`과 골든 테스트를 `today=2026-07-15`로 고정했다.

## 테스트
`pytest complaint_processing/tests` → 8건(골든/중재 4 + critic 4).
`python complaint_processing/run.py --critic` → 실행 + 검증 요약 출력.
