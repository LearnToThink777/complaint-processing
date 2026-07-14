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


def build_chunks() -> list[Chunk]:
    """청킹 + 정형 메타 추출 (LLM 없음)."""
    chunks: list[Chunk] = []
    for s in RAW_STATUTES:
        chunks += chunk_statute(s["raw"], law_name=s["law_name"], sector=s["sector"])
    for d in RAW_DECISIONS:
        chunks += chunk_decision(d["raw"], meta=d["meta"])
    return chunks


def label_chunks(chunks: list[Chunk], use_llm: bool) -> None:
    """각 청크에 일상어 라벨 부착 (LLM, 색인 때 1회). chunks 를 제자리 수정."""
    backend = get_backend(use_llm=use_llm)
    for c in chunks:
        labels = backend.structured(
            "chunk_label",
            ChunkLabels,
            {"source_type": c.source_type, "text": c.text, "metadata": c.metadata},
        )
        c.labels = labels.model_dump()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="실제 프록시 LLM으로 라벨 생성 (기본: 더미)")
    ap.add_argument("--out", metavar="PATH", default=str(INDEX_PATH), help="색인 저장 경로")
    args = ap.parse_args()

    chunks = build_chunks()
    print(f"청킹 완료: {len(chunks)} 청크 "
          f"(법령 {sum(c.source_type == 'statute' for c in chunks)} · "
          f"결정문 {sum(c.source_type == 'decision' for c in chunks)})")

    label_chunks(chunks, use_llm=args.llm)
    print(f"라벨링 완료: {'프록시 LLM' if args.llm else '더미'} 로 일상어 라벨 부착")

    payload = [c.model_dump() for c in chunks]
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"색인 저장: {args.out}")


if __name__ == "__main__":
    main()
