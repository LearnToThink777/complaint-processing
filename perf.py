from __future__ import annotations

"""성능/응답시간 기록 — "얼마나 걸렸는지"를 어딘가에 남기기 위한 최소 계측 계층.

record() 한 곳만 부르면 두 군데에 동시에 남는다:
  1) DB(models.PerformanceLog)   — API(/api/perf/summary)로 조회·집계 가능한 원본.
  2) PERFORMANCE_LOG.md(저장소 루트) — 사람이 바로 훑어볼 수 있는 "디지털 공책".
     자동 기록(실사용) 뿐 아니라 수동 성능 테스트 결과도 이 함수로 그대로 쌓으면 된다.

사용법(지침은 docs/PERFORMANCE.md 참고):
    t0 = time.perf_counter()
    ... (LLM 호출 등) ...
    record(task="checklist_plan_agentic", case_id=case_id, provider="mlapi-nano",
           duration_ms=(time.perf_counter() - t0) * 1000, tool_calls=2, item_count=4, outcome="ok")

기록 실패(디스크 권한 등)가 본 기능을 절대 막지 않도록 record() 내부는 전부 방어적으로 짜여 있다.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PerformanceLog

_PKG_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = _PKG_DIR / "PERFORMANCE_LOG.md"

_HEADER = (
    "# 성능 기록 노트\n\n"
    "이 파일은 `perf.record()`가 자동으로 한 줄씩 덧붙이는 **디지털 공책**이다. 손으로 편집하지 말고,\n"
    "기록 지침은 [docs/PERFORMANCE.md](docs/PERFORMANCE.md)를 참고할 것. 원본 데이터는 DB\n"
    "`performance_logs` 테이블에 있고(`GET /api/perf/summary`로 집계 조회), 이 파일은 그중 최신 순\n"
    "요약을 사람이 바로 훑어보기 위한 사본이다.\n\n"
    "| 시각(UTC) | task | case_id | provider | 소요(ms) | tool_calls | items | outcome | 비고 |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)


def _ensure_header() -> None:
    if not NOTEBOOK_PATH.exists():
        NOTEBOOK_PATH.write_text(_HEADER, encoding="utf-8")


def _append_row(
    *,
    task: str,
    case_id: str | None,
    provider: str,
    duration_ms: float,
    tool_calls: int,
    item_count: int | None,
    outcome: str,
    note: str,
) -> None:
    try:
        _ensure_header()
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        row = (
            f"| {ts} | {task} | {case_id or '-'} | {provider or '-'} | "
            f"{duration_ms:.0f} | {tool_calls} | {item_count if item_count is not None else '-'} | "
            f"{outcome} | {note} |\n"
        )
        with NOTEBOOK_PATH.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        pass  # 노트북 파일 기록 실패는 무시 — DB 기록/본 기능에 영향 주지 않는다.


def record(
    session: Session,
    *,
    task: str,
    duration_ms: float,
    case_id: str | None = None,
    provider: str = "",
    tool_calls: int = 0,
    item_count: int | None = None,
    outcome: str = "ok",
    error: str = "",
    note: str = "",
) -> None:
    """성능 기록 1건을 DB + 노트북 파일에 남긴다. 실패해도 예외를 던지지 않는다."""
    try:
        session.add(PerformanceLog(
            task=task, case_id=case_id, provider=provider, duration_ms=duration_ms,
            tool_calls=tool_calls, item_count=item_count, outcome=outcome, error=error, note=note,
        ))
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    _append_row(task=task, case_id=case_id, provider=provider, duration_ms=duration_ms,
               tool_calls=tool_calls, item_count=item_count, outcome=outcome, note=note or error[:80])


def summary(session: Session, *, task: str | None = None, limit: int = 50) -> dict[str, Any]:
    """최근 기록 + 기본 통계(평균/최소/최대/p50/p95)를 반환. task 지정 시 그 task만."""
    q = select(PerformanceLog).order_by(PerformanceLog.id.desc()).limit(limit)
    if task:
        q = q.where(PerformanceLog.task == task)
    rows = list(session.execute(q).scalars().all())
    durations = sorted(r.duration_ms for r in rows)
    n = len(durations)

    def _pct(p: float) -> float | None:
        if not n:
            return None
        idx = min(n - 1, int(round(p * (n - 1))))
        return durations[idx]

    stats = {
        "count": n,
        "avg_ms": round(sum(durations) / n, 1) if n else None,
        "min_ms": durations[0] if n else None,
        "max_ms": durations[-1] if n else None,
        "p50_ms": _pct(0.50),
        "p95_ms": _pct(0.95),
    }
    entries = [
        {
            "task": r.task, "case_id": r.case_id, "provider": r.provider,
            "duration_ms": r.duration_ms, "tool_calls": r.tool_calls, "item_count": r.item_count,
            "outcome": r.outcome, "error": r.error, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return {"stats": stats, "entries": entries}
