from __future__ import annotations

"""검색(RAG) 코어 — 청킹 · 메타데이터 · 벡터 스토어 · 유사사례 조립.

이 파일이 커버하는 것은 앞서 정리한 2단 구조 중 'LLM이 필요 없는' 뼈대입니다.

  [청킹]     구조 규칙으로 자르기            ← 여기 (chunk_statute / chunk_decision)
  [라벨링a]  정형 메타데이터 추출(파싱)      ← 여기 (각 chunk 함수가 metadata 채움)
  [라벨링b]  일상어 라벨 생성                ← build_index.py 가 LLM으로 (ChunkLabels)
  [검색]     메타 필터 + 유사도             ← 여기 (VectorStore.search)

임베딩은 외부 의존성을 피하려고 '어휘 겹침(lexical overlap)'으로 근사했습니다.
실제로는 _score()를 임베딩 코사인 유사도로 갈아끼우면 되고, 그 자리에 주석을 달아뒀습니다.
"""

import re
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """색인 단위 1개. text(원문 조각) + metadata(파싱) + labels(LLM 생성)."""

    chunk_id: str = Field(description="청크 식별자. 예: '금융소비자보호법#제17조'.")
    source_type: str = Field(description="'statute'(법령) | 'decision'(분쟁조정 결정문).")
    text: str = Field(description="자른 원문 조각.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="파싱으로 뽑은 정형 태그.")
    labels: dict[str, Any] = Field(default_factory=dict, description="ChunkLabels.model_dump() — LLM 생성.")

    @property
    def search_text(self) -> str:
        """임베딩/검색 대상 텍스트 = 원문 + 정형 메타 + 일상어 라벨(비대칭 해소분)."""
        meta = [str(self.metadata.get(k, "")) for k in ("law_name", "article", "case_display", "product_en")]
        parts = [self.text, *meta, self.labels.get("issue_summary", "")]
        parts += self.labels.get("keywords", []) or []
        parts += self.labels.get("everyday_questions", []) or []
        return " ".join(p for p in parts if p)


# ---- 청킹: 구조 규칙만, LLM 없음 ----------------------------------------------

_ARTICLE = re.compile(r"(?=제\d+조)")   # '제N조' 경계에서 자른다
_ARTICLE_NO = re.compile(r"제(\d+)조")


def chunk_statute(raw: str, *, law_name: str, sector: str) -> list[Chunk]:
    """법령 원문 → '조(條) 1개 = 청크 1개'. 법령은 이미 조-항-호로 쪼개져 있다."""
    chunks: list[Chunk] = []
    for part in _ARTICLE.split(raw.strip()):
        part = part.strip()
        m = _ARTICLE_NO.match(part)
        if not m:
            continue
        art = f"제{m.group(1)}조"
        chunks.append(
            Chunk(
                chunk_id=f"{law_name}#{art}",
                source_type="statute",
                text=part,
                metadata={"law_name": law_name, "article": art, "sector": sector},
            )
        )
    return chunks


_SECTION = re.compile(r"(?=【)")        # '【사건개요】' 같은 섹션 머리에서 자른다
_SECTION_NAME = re.compile(r"【([^】]+)】")


def chunk_decision(raw: str, *, meta: dict[str, Any]) -> list[Chunk]:
    """분쟁조정 결정문 → 섹션(사건개요/당사자주장/판단/결정) 단위 청크.

    섹션별로 자르되, 각 청크에 부모 결정문의 정형 메타(사건번호·상품유형·
    배상비율·소요영업일)를 그대로 복사해 붙인다. 검색은 섹션 단위로 하고,
    결과 조립 때 사건번호로 묶어 '사례 1건'으로 되돌린다.
    """
    chunks: list[Chunk] = []
    for part in _SECTION.split(raw.strip()):
        part = part.strip()
        m = _SECTION_NAME.match(part)
        if not m:
            continue
        section = m.group(1)
        chunks.append(
            Chunk(
                chunk_id=f"{meta['case_no']}#{section}",
                source_type="decision",
                text=part,
                metadata={**meta, "section": section},
            )
        )
    return chunks


# ---- 유사도 점수: 전략(Strategy) 패턴 -----------------------------------------
# 점수 계산 '방식'을 갈아끼우는 축. 지금은 어휘 겹침(LexicalScorer)이지만, 진짜
# 임베딩을 넣을 때는 EmbeddingScorer 를 새로 구현해 VectorStore(scorer=...)로 주입만
# 하면 된다 — VectorStore 와 검색 호출부(agent/llm)는 한 줄도 바뀌지 않는다.


class ScorerStrategy(ABC):
    """질의–청크 유사도 점수 전략의 인터페이스(Strategy 역할)."""

    @abstractmethod
    def score(self, query: str, chunk: Chunk) -> float:
        ...


class LexicalScorer(ScorerStrategy):
    """어휘 겹침(Jaccard)으로 임베딩을 근사하는 기본 전략. 외부 의존성 0.

    NOTE: 진짜 임베딩으로 바꾸려면 score()를 cosine(embed(query),
          embed(chunk.search_text)) 로 계산하는 EmbeddingScorer 를 새로 만들어
          VectorStore(scorer=EmbeddingScorer(...)) 로 주입하면 된다.
    """

    _TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")

    @classmethod
    def _tokens(cls, s: str) -> set[str]:
        return {t for t in cls._TOKEN.findall(s) if len(t) >= 2}

    def score(self, query: str, chunk: Chunk) -> float:
        q, d = self._tokens(query), self._tokens(chunk.search_text)
        if not q or not d:
            return 0.0
        return len(q & d) / len(q | d)   # Jaccard (코사인 대용)


# ---- 벡터 스토어: 메타 필터 + 유사도(전략 주입) -------------------------------


class VectorStore:
    """색인된 청크 위에서 hybrid 검색을 수행한다 (메타 필터 + 유사도).

    점수 계산은 ScorerStrategy 에 위임한다(기본 LexicalScorer). 필터·정렬 로직은
    점수 방식과 무관하게 고정이라, 임베딩 도입 시 이 클래스는 손대지 않는다.
    """

    def __init__(self, chunks: list[Chunk], scorer: ScorerStrategy | None = None) -> None:
        self.chunks = chunks
        self.scorer = scorer or LexicalScorer()

    def search(
        self,
        query: str,
        *,
        source_type: str | None = None,
        filters: dict[str, Any] | None = None,
        k: int = 5,
    ) -> list[tuple[float, Chunk]]:
        """filters(메타 완전일치)로 먼저 좁히고, 유사도 상위 k개를 반환.

        점수 0(=어휘 겹침 전무)도 포함해 반환한다. 데모 코퍼스가 작아서, 자연어
        사건 사실과 격식체 법령 원문 사이의 어휘 겹침이 낮아도 필터(메타)로 이미
        좁혀진 후보군 안에서는 '가장 그나마 가까운' 항목을 보여주는 게 맞다.
        (실제 임베딩으로 교체하면 저점 매칭 자체가 줄어들 것.)
        """
        pool = self.chunks
        if source_type:
            pool = [c for c in pool if c.source_type == source_type]
        if filters:
            pool = [c for c in pool if all(c.metadata.get(kk) == vv for kk, vv in filters.items())]
        scored = [(self.scorer.score(query, c), c) for c in pool]
        scored.sort(key=lambda sc: sc[0], reverse=True)
        return scored[:k]


# ---- 유사사례 조립: 검색 결과 → SimilarCasesResult payload --------------------

def add_business_days(start: date, n: int) -> date:
    """start 로부터 영업일(월~금) n일 뒤 날짜."""
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def assemble_similar_cases(
    store: VectorStore,
    *,
    query: str,
    product_en: str,
    due_date: str,
    today: date,
    k: int = 3,
) -> dict[str, Any]:
    """검색된 결정문 청크 → SimilarCasesResult 로 넣을 dict 를 만든다.

    같은 사건번호의 여러 섹션이 잡히므로 사건 단위로 합치고, 소요영업일 평균으로
    예상 완료일을 추정한 뒤 처리 기한과 비교해 초과 위험을 판정한다.
    """
    hits = store.search(query, source_type="decision", filters={"product_en": product_en}, k=k * 4)

    seen: dict[str, dict[str, Any]] = {}
    for _, c in hits:
        no = c.metadata["case_no"]
        if no not in seen:
            seen[no] = {"case": c.metadata["case_display"], "business_days": c.metadata["business_days"]}
        if len(seen) == k:
            break

    cases = list(seen.values())
    if not cases:
        return {
            "cases": [],
            "estimated_completion": due_date,
            "due_date": due_date,
            "over_deadline_risk": False,
            "reasoning": f"'{product_en}' 유형의 유사 결정문을 찾지 못해 위험 판정을 보류합니다.",
        }

    avg = round(sum(c["business_days"] for c in cases) / len(cases))
    est = add_business_days(today, avg)
    est_iso = est.isoformat()
    risk = est_iso > due_date
    return {
        "cases": cases,
        "estimated_completion": est_iso,
        "due_date": due_date,
        "over_deadline_risk": risk,
        "reasoning": (
            f"유사 {len(cases)}건 평균 약 {avg}영업일 소요. 오늘({today.isoformat()}) 기준 "
            f"예상 완료 {est_iso} vs 처리 기한 {due_date} → "
            f"{'초과 위험' if risk else '기한 내 가능'}."
        ),
    }
