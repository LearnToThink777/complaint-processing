# 성능 기록 지침 (응답시간·성능 테스트)

> 목적: "검토계획 생성이 왜 수십 초 걸리나?" 같은 질문에 **근거(숫자)로** 답할 수 있게,
> LLM 호출의 소요시간을 한 곳에서 자동으로 남기고, 수동 성능 테스트 결과도 같은 틀에 쌓는다.

관련: [README](../README.md) · [ARCHITECTURE](ARCHITECTURE.md) · [SKILLS](SKILLS.md)

---

## 어디에 기록되나 (2중 기록)

`perf.record()` 한 번 호출로 두 곳에 동시에 남는다.

| 저장소 | 무엇 | 용도 |
|---|---|---|
| **DB** `performance_logs` 테이블 ([models.py](../models.py) `PerformanceLog`) | 기계가 읽는 원본. task/case_id/provider/duration_ms/tool_calls/item_count/outcome/error/created_at | 집계·조회(`GET /api/perf/summary`), 회귀 비교 |
| **`PERFORMANCE_LOG.md`** (저장소 루트, "디지털 공책") | 사람이 바로 훑는 마크다운 표. 최신 기록이 아래로 계속 덧붙는다 | 눈으로 빠르게 확인, PR/보고 캡처 |

> `PERFORMANCE_LOG.md` 는 **자동 생성·자동 추가** 파일이다. 손으로 편집하지 말 것(헤더가 없으면
> 자동으로 다시 만든다). DB 파일(`data/complaint.db`)과 이 공책은 모두 `.gitignore` 대상이라
> 각자 로컬에 쌓인다 — 커밋되지 않는다.

---

## 무엇이 자동으로 기록되나

1. **AI 검토계획 생성** — `task="checklist_plan_agentic"`.
   [agentic_plan.py](../agentic_plan.py) `run_plan_generation()` 이 생성 끝나면 항상 기록.
   `duration_ms`(도구 호출 왕복 포함 전체), `tool_calls`(LLM이 실제로 부른 검색 도구 횟수),
   `item_count`, `outcome`(ok/fallback), 실패 사유(`error`)까지.
2. **LLM 스킬 5종** — `task="skill:checklist_plan"`, `"skill:verdict"` 등.
   [api.py](../api.py) `_run_skill()` 이 성공/실패 모두 기록.

### 왜 느린가 (기록으로 확인되는 것)

- **콜드스타트**: 첫 생성은 `corpus_index.json`(74MB) + 로컬 임베딩 모델(e5-base) 최초 적재가 겹친다.
- **순차 LLM 왕복**: tool-calling 루프는 `invoke → 도구 실행 → 재invoke` → 최종 구조화 출력까지
  LLM 호출이 여러 번 순차로 나간다. `tool_calls` 값이 클수록 총 시간이 늘어난다.
  → `GET /api/perf/summary?task=checklist_plan_agentic` 의 `tool_calls` 와 `duration_ms` 상관을 보면 된다.

### 개선 이력 — 2026-07-24: 60s → 28s (53%↓)

perf 기록으로 병목을 특정해 두 가지를 고쳤다([agentic_plan.py](../agentic_plan.py), [api.py](../api.py)).

1. **낭비되는 LLM 왕복 제거**: 예전 루프는 도구 실행 후 "더 부를 도구가 있는지"를 확인하려고
   빈 답이 나올 걸 알면서도 재invoke를 했다(최대 4라운드). `_MAX_TOOL_ROUNDS=1`로 바꿔 도구
   1라운드 실행 직후 곧장 최종 구조화 출력으로 넘어간다 — LLM 호출 3회 → **2회**(하한).
2. **콜드스타트를 요청 밖으로 이동**: `corpus_index.json` + e5 임베딩 모델 적재를 첫 사용자
   요청이 아니라 **서버 기동 시 백그라운드 스레드**(`api.py`의 `@app.on_event("startup")` →
   `agentic_plan.warm_store()`)에서 미리 끝낸다. 사용자 요청은 이미 데워진 스토어를 쓴다.
3. (부수) LLM 호출에 `timeout=90s, max_retries=0` — 멈춘 호출이 응답을 무한정 지연시키지 않고
   빠르게 fallback으로 강등되게.

**측정(같은 사건 사실, mlapi-nano)**:

| 시점 | 조건 | duration_ms | tool_calls |
|---|---|---|---|
| 개선 전 | 4라운드 상한, 요청 안에서 콜드스타트 | 59,962 / 95,538 | 2 |
| 개선 후 | 1라운드 상한, 사전 예열(warm_store) | 28,095(실서버 재현) · 벤치 평균 28,014(n=3) | 2 |

실서버(uvicorn, `--reload` 없이 정상 기동) 기준 검증 — 제출 응답은 0.12s(비동기 정상), 백그라운드
생성이 폴링으로 16초 만에 `ready` 확인, 응답의 `duration_ms=28095`. 재현성 확인을 위해
`benchmark:checklist_agentic_v2` task로 3회 반복 측정(21.9s~33.8s, p50 28.3s) — 자세한 원본은
`PERFORMANCE_LOG.md` 참고.

**남은 병목**: 여전히 LLM 호출 2회(≈각 10~17s)가 지배적이다. 더 줄이려면 (a) 최종 구조화 출력을
tool-calling 응답과 한 번에 받도록 프롬프트를 바꿔 1회로 합치거나, (b) 더 빠른 모델/스트리밍으로
체감 지연을 낮추는 방향이 남아있다 — 다음 개선 후보.

---

## 조회 방법

```bash
# 전체 최근 기록 + 통계(평균/최소/최대/p50/p95)
curl http://127.0.0.1:8000/api/perf/summary

# 검토계획 생성만
curl "http://127.0.0.1:8000/api/perf/summary?task=checklist_plan_agentic&limit=100"
```

또는 `PERFORMANCE_LOG.md` 를 그냥 열어본다.

---

## 수동 성능 테스트를 기록하려면

같은 `perf.record()` 를 쓰면 자동 기록과 한 공책·한 테이블에 섞여 쌓인다. `task` 이름만
구분되게 지어라(예: `"benchmark:checklist_nano_vs_mini"`).

```python
import time
from complaint_processing.db import SessionLocal
from complaint_processing import perf

with SessionLocal() as s:
    t0 = time.perf_counter()
    # ... 측정 대상 호출 ...
    perf.record(
        s,
        task="benchmark:checklist_nano",   # 벤치마크는 task 접두사 'benchmark:' 로 통일 권장
        provider="mlapi-nano",
        duration_ms=(time.perf_counter() - t0) * 1000,
        tool_calls=2,          # 알면 채우고, 모르면 0
        item_count=4,
        outcome="ok",
        note="cold start 포함, 반복 1회차",
    )
```

### 기록 컨벤션

- **task 접두사**: 자동 실사용은 `checklist_plan_agentic` / `skill:*`, 수동 벤치는 `benchmark:*`.
- **cold vs warm**: 첫 호출(콜드스타트)과 이후를 `note` 에 반드시 구분해 적는다 — 안 그러면 평균이 왜곡된다.
- **반복 횟수**: 벤치는 최소 3회 반복해 p50/p95 가 의미 있게 한다.
- **환경 메모**: provider·모델·네트워크 상태가 결과를 좌우하므로 `note` 에 남긴다.

---

## 초기화

기록을 리셋하려면 노트북 파일과 DB 를 지운다(다음 기동 때 자동 재생성/재시드):

```bash
rm complaint_processing/PERFORMANCE_LOG.md
rm complaint_processing/data/complaint.db   # 사건 데이터까지 함께 초기화됨에 주의
```
