from __future__ import annotations

"""(a) 오프라인 색인 스크립트 — 데이터 넣을 때 '한 번만' 도는 전처리.

    python build_index.py                 # 더미(MockLLM)로 일상어 라벨 생성
    python build_index.py --llm           # 실제 프록시 LLM으로 라벨 생성
    python build_index.py --out corpus_index.json

흐름 (앞서 정리한 2단 구조 그대로):

    원본 문서
      ├─[청킹]     구조 규칙으로 자르기          ← retrieval.chunk_* (LLM X)
      ├─[라벨링a]  정형 메타데이터 추출          ← chunk 함수가 metadata 채움 (LLM X)
      ├─[라벨링b]  일상어 라벨 생성              ← llm.structured("chunk_label", ...) (LLM O, 1회)
      └─→ corpus_index.json  (라벨 붙은 청크)   ← RetrievalLLM 이 검색 때 읽음

여기서 코퍼스는 데모용 소량 샘플입니다. 실제로는 이 자리에 법령 XML/HTML,
결정문 PDF 파서를 물려 RAW_STATUTES / RAW_DECISIONS 를 채우면 됩니다.
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from complaint_processing.llm import get_backend
from complaint_processing.retrieval import Chunk, chunk_decision, chunk_statute
from complaint_processing.schemas import ChunkLabels

INDEX_PATH = _HERE / "corpus_index.json"


# ---- 데모용 샘플 코퍼스 (실제로는 파서 출력으로 대체) --------------------------

RAW_STATUTES = [
    {
        "law_name": "금융소비자보호법",
        "sector": "공통",
        "raw": """
제17조(적합성원칙) ① 금융상품판매업자등은 일반금융소비자의 재산상황, 투자경험,
투자성향 등에 비추어 적합하지 아니하다고 인정되는 금융상품 계약 체결을 권유해서는 아니 된다.
② 금융상품판매업자등은 계약 체결을 권유하기 전에 소비자의 정보를 파악하고 확인받아야 한다.

제19조(설명의무) ① 금융상품판매업자등은 일반금융소비자에게 계약 체결을 권유하는 경우
그 상품의 중요한 사항을 이해할 수 있도록 설명하여야 한다. 원금 손실이 발생할 수 있다는 사실과
그 위험의 내용은 특히 중요한 사항으로 본다.
""",
    },
    {
        "law_name": "자본시장법",
        "sector": "증권",
        "raw": """
제49조(부당권유의 금지) 금융투자업자는 투자권유를 할 때 다음 각 호의 행위를 하여서는 아니 된다.
1. 거짓의 내용을 알리는 행위
2. 불확실한 사항에 대하여 단정적 판단을 제공하거나 확실하다고 오인하게 할 소지가 있는 내용을 알리는 행위
3. 손실의 전부 또는 일부를 보전하여 줄 것을 사전에 약속하는 행위
""",
    },
]

RAW_DECISIONS = [
    {
        "meta": {"case_no": "2023-0942", "case_display": "분쟁조정 2023-0942 ELS",
                 "product_en": "ELS mis-selling", "sector": "증권", "business_days": 42, "award_ratio": 45},
        "raw": """
【사건개요】 안정추구형으로 분류된 신청인에게 원금 비보장 고위험 ELS를 권유·판매한 건.
【당사자주장】 신청인은 원금 손실 위험을 제대로 설명받지 못했고 투자성향과 맞지 않았다고 주장.
【판단】 적합성원칙 및 설명의무 위반이 인정되며, 손실 위험 고지가 불충분하였다고 판단.
【결정】 과실상계를 반영하여 배상비율 45%로 조정한다.
""",
    },
    {
        "meta": {"case_no": "2024-0175", "case_display": "분쟁조정 2024-0175 DLF",
                 "product_en": "DLF mis-selling", "sector": "은행", "business_days": 38, "award_ratio": 40},
        "raw": """
【사건개요】 예금 상담을 위해 방문한 고객에게 고위험 DLF를 권유한 건.
【당사자주장】 신청인은 예금과 유사한 안전 상품으로 오인하였다고 주장.
【판단】 설명의무 위반 및 부적합 권유가 인정된다.
【결정】 배상비율 40%로 결정한다.
""",
    },
    {
        "meta": {"case_no": "2024-1187", "case_display": "금융감독원 조정 2024-1187",
                 "product_en": "ELS mis-selling", "sector": "증권", "business_days": 51, "award_ratio": 40},
        "raw": """
【사건개요】 고령 신청인에게 원금손실 가능성이 큰 ELS를 반복 권유한 건.
【당사자주장】 손실보전을 약속받았다고 주장하며 녹취 일부를 제출.
【판단】 부당권유 정황과 설명의무 미이행이 확인된다.
【결정】 배상비율 40%를 인용한다.
""",
    },
]


# --live-law 로 law.go.kr에서 실제로 가져올 조문 — 법령 하나가 수백 조문이라
# 민원 검토에 실제 쓰는 조문만 지정한다(전체 법령 색인은 build_index 1회 비용이 너무 큼).
# 자본시장법 제49조(부당권유의 금지)는 2020년 금융소비자보호법 제정으로 폐지·통합됐다 —
# 그래서 부당권유는 자본시장법이 아니라 금융소비자보호법 제21조에서 가져온다.
# 접수 폼의 상품유형(예금·적금 / 펀드 / ELS·DLS / 보험 / 대출 / 기타)을 전부 덮도록 고른다.
# 예전엔 4개 조문(금소법 17·19·21 + 자본시장법 71)뿐이라, 보험·대출·예금 민원은 검색해도
# 근거가 0건이었다 — 그게 "특정 분야는 판정을 아예 안 한다"의 뿌리였다.
STATUTE_TARGETS = [
    # 6대 판매원칙 + 소비자 구제수단. 상품 종류를 가리지 않고 모든 민원에 걸린다.
    {"law_name": "금융소비자보호법", "sector": "공통",
     "articles": [17, 18, 19, 20, 21, 22, 28, 36, 44, 45, 46, 47]},
    # 투자성 상품(펀드·ELS·DLS)
    {"law_name": "자본시장과 금융투자업에 관한 법률", "sector": "증권", "articles": [55, 64, 71]},
    # 보장성 상품(보험) — 모집 규제와 보험회사의 사용자책임
    {"law_name": "보험업법", "sector": "보험", "articles": [95, 97, 102]},
    # 예금성 상품 — 은행 불공정영업, 예금 보호
    {"law_name": "은행법", "sector": "은행", "articles": [52]},
    {"law_name": "예금자보호법", "sector": "은행", "articles": [31, 32]},
    # 대출성 상품 — 카드·대부 포함
    {"law_name": "여신전문금융업법", "sector": "여신", "articles": [24, 50]},
    {"law_name": "대부업 등의 등록 및 금융이용자 보호에 관한 법률", "sector": "대부", "articles": [6, 8]},
]


def build_chunks(live_law: bool = False) -> list[Chunk]:
    """청킹 + 정형 메타 추출 (LLM 없음)."""
    chunks: list[Chunk] = []
    if live_law:
        from complaint_processing.lawgokr import fetch_law_articles

        for t in STATUTE_TARGETS:
            for art_no, text in fetch_law_articles(t["law_name"], t["articles"]):
                art = f"제{art_no}조"
                chunks.append(Chunk(
                    chunk_id=f"{t['law_name']}#{art}",
                    source_type="statute",
                    text=text,
                    metadata={"law_name": t["law_name"], "article": art, "sector": t["sector"]},
                ))
    else:
        for s in RAW_STATUTES:
            chunks += chunk_statute(s["raw"], law_name=s["law_name"], sector=s["sector"])
    for d in RAW_DECISIONS:
        chunks += chunk_decision(d["raw"], meta=d["meta"])
    return chunks


def build_admin_chunks(corpus_dir: Path, targets: list[str] | None = None) -> list[Chunk]:
    """collect_corpus.py 가 캐시한 원본 XML → 결정문·해석례 청크 (API 호출 없음)."""
    from complaint_processing.lawgokr_targets import TARGET_SPECS, parse_doc
    from complaint_processing.retrieval import chunk_sections

    chunks: list[Chunk] = []
    dropped = 0
    for name, spec in TARGET_SPECS.items():
        if targets is not None and name not in targets:
            continue
        tdir = corpus_dir / name
        if not tdir.is_dir():
            continue
        n_before = len(chunks)
        for xml_path in sorted(tdir.glob("*.xml")):
            doc_id = xml_path.stem
            doc = parse_doc(spec, doc_id, xml_path.read_bytes())
            if doc is None:   # 스캔 이미지 전용 등 텍스트 없는 문서
                dropped += 1
                continue
            meta = {
                "org": name, "org_name": spec.org_name,
                "doc_id": doc_id, "title": doc.title,
                **doc.metadata,
            }
            chunks += chunk_sections(
                doc.sections, doc_id=f"{name}:{doc_id}",
                source_type=spec.source_type, meta=meta,
            )
        print(f"  {name}: {len(chunks) - n_before} 청크")
    if dropped:
        print(f"  (텍스트 없는 문서 {dropped}건 폐기 — 스캔 이미지 전용 등)")
    return chunks


# ---- 체크포인트: 라벨·임베딩의 중단·재개 --------------------------------------
# 청크 구성은 원본 캐시로부터 결정적(같은 XML → 같은 chunk_id)이므로, chunk_id 키의
# 부분 결과 사전 하나면 충분하다. 어느 단계에서 죽어도 같은 명령 재실행 = 재개.

def load_checkpoint(path: Path) -> dict[str, dict]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_checkpoint(path: Path, ckpt: dict[str, dict]) -> None:
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ckpt, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _label_one(backend, fallback_backend, c: Chunk) -> tuple[dict, bool]:
    """청크 1개 라벨링 — (labels_dict, used_fallback). 스레드에서 호출된다(순수 호출, 공유 상태 없음)."""
    context = {"source_type": c.source_type, "text": c.text, "metadata": c.metadata}
    try:
        return backend.structured("chunk_label", ChunkLabels, context).model_dump(), False
    except Exception:
        # 실LLM이 스키마를 어긴 응답(예: 필드명 hallucination)을 줄 때가 있다 — 청크 하나
        # 때문에 수천 건짜리 라벨링 전체가 죽으면 안 되므로 더미로 대체하고 계속.
        return fallback_backend.structured("chunk_label", ChunkLabels, context).model_dump(), True


def label_chunks(
    chunks: list[Chunk],
    use_llm: bool,
    *,
    ckpt: dict[str, dict] | None = None,
    ckpt_path: Path | None = None,
    mode: str = "chunk",
    every: int = 20,
    concurrency: int = 1,
) -> None:
    """각 청크에 일상어 라벨 부착 (LLM, 색인 때 1회). chunks 를 제자리 수정.

    ckpt 에 라벨이 있는 청크는 건너뛰고, every 건마다 체크포인트를 저장한다.
    mode="doc": 문서(doc_id)당 첫 청크만 LLM 호출하고 형제 청크에 라벨을 복사
                (결정문은 섹션들이 같은 사건이라 라벨 공유가 타당 — 호출 수 ~1/3).
    mode="none": admin_decision/law_interp 라벨 생략(statute/decision 은 항상 라벨).
    concurrency>1: LLM 호출은 I/O 대기가 대부분이라 스레드풀로 동시에 여러 건 보낸다.
                   체크포인트 쓰기·doc_labels 갱신은 메인 스레드에서만 하므로 락이 불필요하다
                   (워커는 순수 호출만 하고 결과를 as_completed로 메인 스레드가 수거).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    backend = get_backend(use_llm=use_llm)
    fallback_backend = get_backend(use_llm=False)  # 실LLM 스키마 위반 시 더미 라벨로 대체
    ckpt = ckpt if ckpt is not None else {}
    doc_labels: dict[str, dict] = {}   # mode="doc"용: doc_id → labels
    done = 0
    failed = 0

    # 1단계: 캐시·mode=none·doc 중복은 미리 걸러 '실제로 호출해야 하는 청크'만 추린다.
    #
    # 주의: 대표 청크가 '이전 실행에서' 이미 라벨링돼 ckpt 에 있는 경우(재시작 흔한 이 환경 —
    # 세션이 자주 죽는다), 그 라벨을 doc_labels 에 미리 심어둬야 형제 청크가 재호출 없이
    # 복사를 받는다. 안 그러면 seen_doc_keys/doc_labels 가 이번 실행에서 비어 있어서
    # 형제가 '대표 청크'로 오인되어 불필요한 LLM 재호출이 난다(실측: ckpt 라벨 수가
    # 예상 호출 수를 넘어서는 현상으로 발견).
    todo: list[Chunk] = []
    seen_doc_keys: set[str] = set()
    for c in chunks:
        cached = ckpt.get(c.chunk_id, {}).get("labels")
        doc_key = str(c.metadata.get("doc_id", c.chunk_id))
        is_new_corpus = c.source_type in ("admin_decision", "law_interp")
        if cached:
            c.labels = cached
            if is_new_corpus:
                doc_labels.setdefault(doc_key, cached)
                seen_doc_keys.add(doc_key)
            continue
        if mode == "none" and is_new_corpus:
            continue
        if mode == "doc" and is_new_corpus and doc_key in seen_doc_keys:
            continue  # 대표 청크가 todo 에 있거나 이미 캐시됨 — 3단계에서 형제로 채워진다
        if mode == "doc" and is_new_corpus:
            seen_doc_keys.add(doc_key)
        todo.append(c)

    def _checkpoint_tick() -> None:
        nonlocal done
        done += 1
        if ckpt_path and done % every == 0:
            save_checkpoint(ckpt_path, ckpt)
            print(f"  라벨링 {done}/{len(todo)}건 (체크포인트 저장{f', 실패 {failed}건 더미 대체' if failed else ''})")

    def _apply(c: Chunk, labels: dict, used_fallback: bool) -> None:
        nonlocal failed
        c.labels = labels
        doc_labels[str(c.metadata.get("doc_id", c.chunk_id))] = labels
        ckpt.setdefault(c.chunk_id, {})["labels"] = labels
        if used_fallback:
            failed += 1
            print(f"  !! 라벨링 실패 → 더미로 대체: {c.chunk_id}")
        _checkpoint_tick()

    # 2단계: 실제 호출(동시성 적용) — 순서는 무관, 완료되는 대로 처리.
    if concurrency <= 1:
        for c in todo:
            labels, used_fallback = _label_one(backend, fallback_backend, c)
            _apply(c, labels, used_fallback)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_label_one, backend, fallback_backend, c): c for c in todo}
            for fut in as_completed(futures):
                c = futures[fut]
                labels, used_fallback = fut.result()
                _apply(c, labels, used_fallback)

    # 3단계: mode="doc" 형제 청크에 대표 라벨 복사(호출 없이).
    for c in chunks:
        if c.labels:
            continue
        doc_key = str(c.metadata.get("doc_id", c.chunk_id))
        if mode == "doc" and c.source_type in ("admin_decision", "law_interp") and doc_key in doc_labels:
            c.labels = doc_labels[doc_key]
            ckpt.setdefault(c.chunk_id, {})["labels"] = c.labels

    if ckpt_path:
        save_checkpoint(ckpt_path, ckpt)
    if ckpt_path:
        save_checkpoint(ckpt_path, ckpt)


def embed_chunks(
    chunks: list[Chunk],
    *,
    ckpt: dict[str, dict],
    ckpt_path: Path,
    dims: int = 768,
    batch: int = 20,
    sleep: float = 1.5,
) -> None:
    """search_text 를 Gemini 로 배치 임베딩해 Chunk.embedding 에 저장 (중단·재개 가능).

    무료 티어 쿼터 보호: 배치 사이 sleep, 실패 시 백오프 재시도 2회, 그래도 실패면
    체크포인트 저장 후 명확히 종료(같은 명령 재실행 = 이어서).
    """
    import time

    from complaint_processing.retrieval import default_gemini_embed_fn

    todo = [c for c in chunks if not ckpt.get(c.chunk_id, {}).get("embedding")]
    for c in chunks:
        cached = ckpt.get(c.chunk_id, {}).get("embedding")
        if cached:
            c.embedding = cached
    if not todo:
        print("  임베딩: 전부 체크포인트에 있음 (호출 0회)")
        return

    embed_fn = default_gemini_embed_fn(dimensions=dims)
    print(f"  임베딩 대상 {len(todo)}청크 (배치 {batch}, {dims}차원)")
    for i in range(0, len(todo), batch):
        group = todo[i:i + batch]
        texts = [c.search_text for c in group]
        for attempt in range(3):
            try:
                vectors = embed_fn(texts, False)
                break
            except Exception as exc:
                if attempt == 2:
                    save_checkpoint(ckpt_path, ckpt)
                    raise RuntimeError(
                        f"임베딩 실패(3회 시도): {exc} — 체크포인트 저장됨. "
                        "같은 명령을 재실행하면 이어서 진행합니다."
                    ) from exc
                time.sleep(sleep * (2 ** (attempt + 1)))
        for c, v in zip(group, vectors):
            c.embedding = [round(x, 6) for x in v]
            ckpt.setdefault(c.chunk_id, {})["embedding"] = c.embedding
        save_checkpoint(ckpt_path, ckpt)
        print(f"  임베딩 {min(i + batch, len(todo))}/{len(todo)}")
        time.sleep(sleep)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="실제 프록시 LLM으로 라벨 생성 (기본: 더미)")
    ap.add_argument("--live-law", action="store_true",
                     help="법령 원문을 하드코딩 대신 law.go.kr Open API로 실조회 (.env의 LAWGOKR_OC 필요)")
    ap.add_argument("--corpus-dir", metavar="DIR", default=None,
                     help="collect_corpus.py 캐시 디렉터리(예: data/raw) — 지정 시 결정문·해석례 코퍼스 색인")
    ap.add_argument("--corpus-targets", default=None,
                     help="--corpus-dir 중 일부 target만 (쉼표 구분)")
    ap.add_argument("--label-mode", choices=["chunk", "doc", "none"], default="chunk",
                     help="신규 코퍼스 라벨링: chunk=청크마다 · doc=문서당 1회 복사 · none=생략")
    ap.add_argument("--concurrency", type=int, default=1,
                     help="라벨링 LLM 호출 동시 실행 수(스레드풀). I/O 대기 위주라 3~8 정도면 크게 단축됨")
    ap.add_argument("--embed", action="store_true", help="Gemini 임베딩 사전계산(기본 꺼짐, Jaccard 폴백 유지)")
    ap.add_argument("--embed-dims", type=int, default=768, help="임베딩 차원(기본 768 — JSON 비대화 방지)")
    ap.add_argument("--checkpoint", metavar="PATH", default=str(_HERE / "data" / "index_checkpoint.json"),
                     help="라벨·임베딩 체크포인트 파일")
    ap.add_argument("--out", metavar="PATH", default=str(INDEX_PATH), help="색인 저장 경로")
    args = ap.parse_args()

    chunks = build_chunks(live_law=args.live_law)
    if args.corpus_dir:
        targets = args.corpus_targets.split(",") if args.corpus_targets else None
        chunks += build_admin_chunks(Path(args.corpus_dir), targets)

    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk_id 중복 발견"
    by_type = {t: sum(c.source_type == t for c in chunks) for t in
               ("statute", "decision", "admin_decision", "law_interp")}
    print(f"청킹 완료: {len(chunks)} 청크 {by_type}"
          + (" [법령: law.go.kr 실조회]" if args.live_law else ""))

    ckpt_path = Path(args.checkpoint)
    ckpt = load_checkpoint(ckpt_path)

    label_chunks(chunks, use_llm=args.llm, ckpt=ckpt, ckpt_path=ckpt_path, mode=args.label_mode,
                 concurrency=args.concurrency)
    print(f"라벨링 완료: {'프록시 LLM' if args.llm else '더미'} (mode={args.label_mode})")

    if args.embed:
        embed_chunks(chunks, ckpt=ckpt, ckpt_path=ckpt_path, dims=args.embed_dims)
        print("임베딩 완료")

    payload = [c.model_dump(exclude_none=True) for c in chunks]
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"색인 저장: {args.out} ({len(chunks)} 청크)")


if __name__ == "__main__":
    main()
