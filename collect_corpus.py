from __future__ import annotations

"""law.go.kr 결정문·법령해석례 수집 CLI — 원본 XML 을 로컬에 캐시한다.

    python collect_corpus.py                          # 8개 target 전부, spec 기본값
    python collect_corpus.py --targets fsc,expc       # 일부만
    python collect_corpus.py --query 보험 --cap 200   # spec 기본값 오버라이드
    python collect_corpus.py --probe                  # target당 2건만 받아 태그 구조 덤프

수집(네트워크 바운드)과 색인(LLM/임베딩 바운드)을 분리하는 경계가 이 스크립트다:
원본 응답을 data/raw/{target}/{doc_id}.xml 에 무가공 저장하고, build_index.py 는
그 캐시만 읽는다 — 재색인·어댑터 수정 시 API 재호출이 없다.

재실행 안전: {doc_id}.xml 이 이미 있으면 건너뛴다(재실행 = 이어받기).
목록(manifest.json)도 재사용하며 --refresh-list 로만 강제 갱신한다.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from complaint_processing.lawgokr import fetch_service_xml, iter_search
from complaint_processing.lawgokr_targets import TARGET_SPECS, TargetSpec, extract_doc_id, parse_doc

DATA_DIR = _HERE / "data" / "raw"


def _atomic_write(path: Path, data: bytes) -> None:
    """임시파일 + os.replace 로 원자적 쓰기(중단돼도 반쪽 파일이 남지 않게)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass
class CollectStats:
    target: str
    listed: int = 0
    fetched: int = 0
    cached: int = 0     # 이미 있어 건너뜀
    skipped: dict[str, str] = field(default_factory=dict)  # doc_id → 이유


def _load_manifest(tdir: Path) -> list[dict[str, str]] | None:
    mf = tdir / "manifest.json"
    if mf.exists():
        return json.loads(mf.read_text(encoding="utf-8"))["rows"]
    return None


def _fetch_with_retry(target: str, doc_id: str, sleep: float) -> bytes:
    """지수 백오프 2회 재시도. 최종 실패는 예외를 그대로 올린다(호출부가 기록)."""
    delay = sleep
    for attempt in range(3):
        try:
            return fetch_service_xml(target, doc_id)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(delay * (2 ** (attempt + 1)))
    raise AssertionError("unreachable")


def collect_target(
    spec: TargetSpec,
    *,
    query: str | None,
    cap: int | None,
    sleep: float,
    data_dir: Path,
    refresh_list: bool = False,
) -> CollectStats:
    tdir = data_dir / spec.target
    tdir.mkdir(parents=True, exist_ok=True)
    stats = CollectStats(target=spec.target)

    rows = None if refresh_list else _load_manifest(tdir)
    if rows is None:
        rows = list(iter_search(spec.target, query=query, max_items=cap, sleep=sleep))
        _atomic_write(
            tdir / "manifest.json",
            json.dumps({"query": query, "cap": cap, "rows": rows}, ensure_ascii=False, indent=1).encode("utf-8"),
        )
    stats.listed = len(rows)

    for row in rows:
        doc_id = extract_doc_id(spec, row)
        if not doc_id:
            stats.skipped[str(row)[:80]] = "no_id"
            continue
        out = tdir / f"{doc_id}.xml"
        if out.exists():
            stats.cached += 1
            continue
        try:
            body = _fetch_with_retry(spec.target, doc_id, sleep)
        except Exception as exc:
            stats.skipped[doc_id] = f"fetch_error: {exc}"
            continue
        _atomic_write(out, body)
        stats.fetched += 1
        time.sleep(sleep)

    if stats.skipped:
        _atomic_write(
            tdir / "_skipped.json",
            json.dumps(stats.skipped, ensure_ascii=False, indent=1).encode("utf-8"),
        )
    return stats


def probe_target(spec: TargetSpec, *, sleep: float) -> None:
    """target당 목록 1페이지+본문 2건을 받아 태그 구조를 덤프 — TARGET_SPECS 확정용."""
    print(f"\n=== {spec.target} ({spec.org_name}) ===")
    try:
        rows = list(iter_search(spec.target, query=spec.default_query, max_items=2, sleep=sleep))
    except Exception as exc:
        print(f"  목록 실패: {exc}")
        return
    if not rows:
        print("  목록 0건")
        return
    print(f"  목록 태그: {list(rows[0].keys())}")
    for row in rows:
        doc_id = extract_doc_id(spec, row)
        if not doc_id:
            print(f"  !! ID 추출 실패: {row}")
            continue
        try:
            body = _fetch_with_retry(spec.target, doc_id, sleep)
        except Exception as exc:
            print(f"  본문 {doc_id} 실패: {exc}")
            continue
        import xml.etree.ElementTree as ET

        root = ET.fromstring(body)
        from complaint_processing.lawgokr_targets import clean_text

        leaves = [(c.tag, len(clean_text(c.text or ""))) for c in root if not len(c)]
        print(f"  본문 {doc_id} 루트=<{root.tag}> leaf(태그,정제길이): {leaves}")
        doc = parse_doc(spec, doc_id, body)
        if doc is None:
            print("    → parse_doc: 폐기(텍스트 부족)")
        else:
            print(f"    → parse_doc: 섹션 {[(n, len(t)) for n, t in doc.sections]} · meta {list(doc.metadata)}")
        time.sleep(sleep)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=",".join(TARGET_SPECS), help="쉼표 구분 target 목록 (기본: 전부)")
    ap.add_argument("--query", default=None, help="검색어 오버라이드 (기본: spec의 default_query)")
    ap.add_argument("--cap", type=int, default=None, help="타겟당 상한 오버라이드 (기본: spec의 default_cap)")
    ap.add_argument("--sleep", type=float, default=0.5, help="요청 간 대기(초)")
    ap.add_argument("--data-dir", default=str(DATA_DIR), help="캐시 디렉터리")
    ap.add_argument("--refresh-list", action="store_true", help="manifest 무시하고 목록 재조회")
    ap.add_argument("--probe", action="store_true", help="수집 대신 태그 구조만 덤프(타겟당 2건)")
    args = ap.parse_args()

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    unknown = [t for t in targets if t not in TARGET_SPECS]
    if unknown:
        ap.error(f"모르는 target: {unknown} (가능: {list(TARGET_SPECS)})")

    if args.probe:
        for t in targets:
            probe_target(TARGET_SPECS[t], sleep=args.sleep)
        return

    data_dir = Path(args.data_dir)
    grand_fetched = 0
    for t in targets:
        spec = TARGET_SPECS[t]
        query = args.query if args.query is not None else spec.default_query
        cap = args.cap if args.cap is not None else spec.default_cap
        stats = collect_target(
            spec, query=query, cap=cap, sleep=args.sleep,
            data_dir=data_dir, refresh_list=args.refresh_list,
        )
        grand_fetched += stats.fetched
        print(
            f"{t}: 목록 {stats.listed}건 → 신규 {stats.fetched} · 캐시 {stats.cached}"
            f" · 스킵 {len(stats.skipped)}"
            + (f" (쿼리={query!r}, 상한={cap})" if query or cap else "")
        )
    print(f"완료 — 신규 수집 {grand_fetched}건, 캐시: {data_dir}")


if __name__ == "__main__":
    main()
