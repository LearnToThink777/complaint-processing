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

import math
import re
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any, Callable, Sequence

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """색인 단위 1개. text(원문 조각) + metadata(파싱) + labels(LLM 생성)."""

    chunk_id: str = Field(description="청크 식별자. 예: '금융소비자보호법#제17조'.")
    source_type: str = Field(description="'statute'(법령) | 'decision'(분쟁조정 결정문) | 'admin_decision'(행정기관 결정문·재결례) | 'law_interp'(법령해석례).")
    text: str = Field(description="자른 원문 조각.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="파싱으로 뽑은 정형 태그.")
    labels: dict[str, Any] = Field(default_factory=dict, description="ChunkLabels.model_dump() — LLM 생성.")
    embedding: list[float] | None = Field(default=None, description="색인 시 사전계산한 임베딩 벡터(선택). 없으면 검색 시 계산 또는 어휘 겹침 폴백.")

    @property
    def search_text(self) -> str:
        """임베딩/검색 대상 텍스트 = 원문 + 정형 메타 + 일상어 라벨(비대칭 해소분)."""
        meta = [str(self.metadata.get(k, "")) for k in ("law_name", "article", "case_display", "product_en", "title", "org_name")]
        parts = [self.text, *meta, self.labels.get("issue_summary", "")]
        parts += self.labels.get("keywords", []) or []
        parts += self.labels.get("everyday_questions", []) or []
        return " ".join(p for p in parts if p)


# ---- 코퍼스 스코프: 무엇을 근거로 삼을지 -------------------------------------
# 코퍼스는 종류(source_type)와 발급기관(metadata["org"])이 섞여 있다. '무엇을 뒤질지'를
# 검색 호출부마다 따로 정하면 경로별로 답이 갈리므로(실제로 갈렸다) 여기 한 곳에 둔다.

# 법령 근거로 인용할 수 있는 종류. statute 는 코퍼스에 4청크뿐이라 조문만 뒤지면
# 예금·보험·대출처럼 조문 시드가 없는 분야에서 근거가 0건이 된다 — 같은 성격의
# 법제처 법령해석례를 함께 후보에 놓는다.
STATUTE_SOURCES = ("statute", "law_interp")

# 선례로 인용할 수 있는 종류. 분쟁조정 결정례(12청크)에 금융위 검사·제재 결정례를 더한다.
PRECEDENT_SOURCES = ("decision", "admin_decision")

# 금융 규제·해석 권한이 있는 발급기관만 근거로 삼는다.
#
# corpus_index.json(6,524청크)의 구성과 이 필터가 남기는 것:
#
#   [검색에 쓰는 것 · 2,339]
#      2,100  admin_decision  금융위원회 검사·제재 결정례        (org=fsc)
#        147  law_interp      법제처 법령해석례                 (org=expc)
#         57  admin_decision  공정거래위원회                    (org=ftc)
#         23  statute         금융 6법 조문(build_index.STATUTE_TARGETS)
#         12  decision        금융분쟁조정위 결정례
#
#   [의도적으로 제외 · 4,185]
#      2,141  국민권익위원회 일반 행정심판      (org=acr)
#      1,053  조세심판원 조세 재결              (org=ttSpecialDecc)
#        600  관세청 법령해석례                 (org=kcsCgmExpc)
#        341  국민권익위원회(특별행정심판)      (org=acrSpecialDecc)
#         50  행정안전부 법령해석례             (org=moisCgmExpc)
#
# 제외분이 코퍼스에 들어 있는 이유는 선별이 아니라 수집 방식 때문이다 — collect_corpus.py
# 가 law.go.kr 의 8개 target 을 통째로 받아왔다(lawgokr_targets.TARGET_SPECS 참고).
#
# 버리지 않고 필터로 가리기만 하는 이유: 지금 금융 민원에 쓸모가 없을 뿐 코퍼스 자체는
# 멀쩡하고(조세·행정 도메인으로 넓힐 여지), 색인 재수집 비용이 크다. 대신 검색에서는
# 반드시 걸러야 한다 — 이들은 임베딩상 '거절·환수 분쟁'으로 가까워 보여서, 필터가 없으면
# 보험금 지급거절 질의에 '부당이득금환수고지처분취소청구'(권익위)가 1순위로 잡힌다(실측).
# 확인해 보면 제외분에 금융상품 민원은 실제로 없다: 권익위 660문서 중 '금융' 키워드가
# 걸리는 29건도 건강보험료·고용산재보험료·내일배움카드 같은 사회보험이고, 조세심판원
# 300문서는 전부 취득세·익금산입 분쟁에서 금융기관을 언급할 뿐이다.
#
# 근거 수를 늘리는 것보다 잘못된 권위를 인용하지 않는 것이 먼저다.
FINANCE_ORGS = {"fsc", "ftc", "expc"}


def finance_scoped(chunk: "Chunk") -> bool:
    """금융 관련 발급기관 문서만 통과. org 메타가 없는 코퍼스(법령 조문·분쟁조정 결정례)는 통과."""
    org = chunk.metadata.get("org")
    return org is None or org in FINANCE_ORGS


def doc_key(chunk: "Chunk") -> str:
    """청크가 속한 '문서' 식별자. 같은 결정문의 여러 섹션을 한 건으로 묶는 데 쓴다."""
    return chunk.chunk_id.split("#")[0]


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


_MAX_SECTION_CHARS = 6000   # 이보다 긴 섹션은 문단 경계에서 분할(임베딩 입력 한도 보호)


def chunk_sections(
    sections: list[tuple[str, str]],
    *,
    doc_id: str,
    source_type: str,
    meta: dict[str, Any],
) -> list[Chunk]:
    """(섹션명, 텍스트) 목록 → 섹션 1개 = 청크 1개. law.go.kr 결정문·해석례용.

    chunk_statute 의 '제N조' 정규식과 달리 재분할이 없다 — 섹션 경계는 XML 태그로
    이미 확정돼 있고, 본문 속 '제N조' 인용 때문에 오분할될 여지를 원천 차단한다.
    지나치게 긴 섹션만 문단(빈 줄) 경계에서 나눠 #2, #3 접미를 붙인다.
    """
    chunks: list[Chunk] = []
    for name, text in sections:
        parts = [text]
        if len(text) > _MAX_SECTION_CHARS:
            # 문단(빈 줄) 경계 우선, 문단 하나가 한도를 넘으면 개행→고정폭 순으로 강제 분할
            paras: list[str] = []
            for para in text.split("\n\n"):
                while len(para) > _MAX_SECTION_CHARS:
                    cut = para.rfind("\n", 0, _MAX_SECTION_CHARS)
                    cut = cut if cut > 0 else _MAX_SECTION_CHARS
                    paras.append(para[:cut])
                    para = para[cut:]
                paras.append(para)
            parts, buf = [], ""
            for para in paras:
                if buf and len(buf) + len(para) > _MAX_SECTION_CHARS:
                    parts.append(buf)
                    buf = para
                else:
                    buf = f"{buf}\n\n{para}" if buf else para
            if buf:
                parts.append(buf)
        for i, part in enumerate(parts):
            suffix = f"#{i + 1}" if len(parts) > 1 else ""
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#{name}{suffix}",
                    source_type=source_type,
                    text=part.strip(),
                    metadata={**meta, "section": name},
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

    def score_many(self, query: str, chunks: list[Chunk]) -> list[float]:
        """청크 여러 개를 한 번에 채점한다. 기본 구현은 score() 를 그대로 반복한다.

        후보군이 수천 건인 코퍼스(행정 결정례·법령해석례)를 검색하면서 생긴 훅이다.
        벡터 연산으로 한 번에 계산할 수 있는 전략(EmbeddingScorer)은 이 메서드를
        재정의해 파이썬 루프를 벗어난다 — VectorStore 는 무엇이 오는지 모른 채
        score_many 만 부른다(Strategy 경계 유지).
        """
        return [self.score(query, c) for c in chunks]


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


# ---- 임베딩 호출: 교체 가능한 '함수' (튜닝 지점) -------------------------------
# 임베딩 호출을 함수로 빼두는 이유는 프롬프트를 build_prompt 함수로 뺀 것과 같다:
# 모델·차원·정규화 방식을 상황에 따라 바꿔가며 튜닝하려면, 호출 지점이 한 함수여야
# 한다. EmbeddingScorer 는 이 함수에만 의존하고 '무엇으로' 임베딩하는지는 모른다.

# (texts, is_query) -> 각 text의 임베딩 벡터. is_query 로 질의/문서를 구분해
# task_type(RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT)을 달리 준다(비대칭 검색 최적화).
EmbedFn = Callable[[list[str], bool], list[list[float]]]

# 색인·질의가 반드시 같은 차원을 써야 cosine 이 성립한다. 한 곳에서 관리하는 기준 차원.
# gemini-embedding-001 은 3072차원이 기본이지만 MRL(Matryoshka) 학습이라 앞 N차원만
# 잘라 써도 품질이 유지된다. 768로 잘라 색인 JSON 비대화를 막는다(3072면 ~4배).
EMBED_DIMS = 768


def _truncate_normalize(vec: list[float], dims: int) -> list[float]:
    """MRL 임베딩을 앞 dims 차원으로 자르고 L2 정규화한다(자른 뒤엔 재정규화 권장)."""
    v = vec[:dims]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def default_gemini_embed_fn(
    model: str = "models/gemini-embedding-001",
    *,
    dimensions: int | None = EMBED_DIMS,
) -> EmbedFn:
    """Gemini 임베딩(무료 티어)을 쓰는 기본 EmbedFn 을 만든다.

    LLM과 같은 GEMINI_API_KEY 하나를 쓴다(별도 키 불필요). model·dimensions 를 바꾸면
    다른 임베딩으로 튜닝된다. 완전히 다른 제공자로 갈아끼우려면 이 함수 대신 같은
    시그니처(EmbedFn)의 함수를 만들어 EmbeddingScorer 에 주입하면 된다.

    dimensions 를 주면(기본 EMBED_DIMS=768) 반환 벡터를 그 차원으로 맞춘다. langchain
    버전에 따라 output_dimensionality 요청이 무시되고 3072차원이 그대로 오기도 하므로,
    받은 뒤 클라이언트에서 한 번 더 잘라(_truncate_normalize) 색인·질의 차원을 보장한다.
    """
    from .llm import _load_gemini_api_key

    api_key = _load_gemini_api_key()
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "langchain-google-genai 가 설치돼 있지 않습니다. pip install -r requirements.txt 하세요."
        ) from exc
    kwargs: dict[str, Any] = {"model": model, "google_api_key": api_key}
    if dimensions is not None:
        kwargs["output_dimensionality"] = dimensions
    client = GoogleGenerativeAIEmbeddings(**kwargs)

    def embed(texts: list[str], is_query: bool) -> list[list[float]]:
        # langchain 이 질의/문서에 맞는 task_type 을 자동 지정한다
        # (embed_query→RETRIEVAL_QUERY, embed_documents→RETRIEVAL_DOCUMENT).
        if is_query:
            raw = [client.embed_query(t) for t in texts]
        else:
            raw = client.embed_documents(texts)
        # 라이브러리가 output_dimensionality 를 무시해 3072차원을 돌려줘도 여기서 맞춘다.
        if dimensions is not None:
            raw = [_truncate_normalize(v, dimensions) for v in raw]
        return raw

    return embed


def default_local_embed_fn(model_name: str = "intfloat/multilingual-e5-base") -> EmbedFn:
    """API 키·쿼터 없이 로컬에서 도는 임베딩(sentence-transformers). Gemini 429 대안.

    intfloat/multilingual-e5-base: Microsoft 개발, 다국어(한국어 포함) 검색 특화,
    네이티브 768차원(EMBED_DIMS와 자연히 일치 — 트렁케이션 불필요). E5 계열 관례상
    질의는 "query: ", 문서는 "passage: " 접두사를 붙여야 검색 품질이 나온다.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "sentence-transformers 가 설치돼 있지 않습니다. pip install sentence-transformers 하세요."
        ) from exc
    model = SentenceTransformer(model_name)

    def embed(texts: list[str], is_query: bool) -> list[list[float]]:
        prefix = "query: " if is_query else "passage: "
        vecs = model.encode([prefix + t for t in texts], normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    return embed


def cosine(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도. 표준 라이브러리만 사용(외부 의존성 0)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class EmbeddingScorer(ScorerStrategy):
    """임베딩 코사인 유사도로 점수를 내는 전략(LexicalScorer 대체).

    NOTE 주석이 예고한 그대로의 교체 지점이다: VectorStore(scorer=EmbeddingScorer())
    로 주입하면 VectorStore·검색 호출부는 한 줄도 바뀌지 않는다.

    ScorerStrategy.score(query, chunk) 는 청크마다 호출되므로, 같은 텍스트를 반복
    임베딩하지 않도록 결과를 캐시한다(질의는 질의끼리, 문서는 chunk_id 로). 임베딩
    '방법'은 EmbedFn 함수에 위임하므로, 이 클래스는 무슨 모델을 쓰는지 모른다.
    """

    def __init__(self, embed_fn: EmbedFn | None = None) -> None:
        self._embed_fn = embed_fn
        self._qcache: dict[str, list[float]] = {}
        self._dcache: dict[str, list[float]] = {}
        # score_many 의 numpy 경로용 행렬 캐시: 같은 후보군을 반복 검색할 때 재사용한다.
        # key = 후보군 chunk_id 튜플의 해시(같은 source_type/필터면 항상 같은 후보군).
        self._matrix_cache: dict[int, Any] = {}

    @property
    def embed_fn(self) -> EmbedFn:
        # 지연 생성: 실제 검색이 일어날 때만 임베딩 클라이언트를 만든다(키 없으면 그때 실패).
        if self._embed_fn is None:
            self._embed_fn = default_gemini_embed_fn()
        return self._embed_fn

    def _query_vec(self, query: str) -> list[float]:
        if query not in self._qcache:
            self._qcache[query] = self.embed_fn([query], True)[0]
        return self._qcache[query]

    def _doc_vec(self, chunk: Chunk) -> list[float]:
        if chunk.chunk_id not in self._dcache:
            # 색인 시 사전계산된 벡터가 있으면 그대로 사용 — 문서 임베딩 API 호출 0회,
            # 검색 1회당 질의 임베딩 1회만 남는다.
            if chunk.embedding:
                self._dcache[chunk.chunk_id] = chunk.embedding
            else:
                self._dcache[chunk.chunk_id] = self.embed_fn([chunk.search_text], False)[0]
        return self._dcache[chunk.chunk_id]

    def score(self, query: str, chunk: Chunk) -> float:
        return cosine(self._query_vec(query), self._doc_vec(chunk))

    def score_many(self, query: str, chunks: list[Chunk]) -> list[float]:
        """후보군 전체를 행렬 한 번으로 채점한다(numpy 있으면). 없으면 기본 루프.

        코퍼스가 6천 청크 규모라 파이썬 루프 코사인은 검색 1회당 1초 안팎을 먹는다.
        검색은 검토계획 1건에 여러 번 일어나므로 여기서 벡터화해 둔다 — 결과값은
        score() 와 동일한 코사인이다(임베딩은 L2 정규화돼 있어 내적 = 코사인).
        """
        if not chunks:
            return []
        try:
            import numpy as np
        except ModuleNotFoundError:
            return super().score_many(query, chunks)

        key = hash(tuple(c.chunk_id for c in chunks))
        mat = self._matrix_cache.get(key)
        if mat is None:
            mat = np.asarray([self._doc_vec(c) for c in chunks], dtype="float32")
            # 정규화 상태를 보장해야 내적을 코사인으로 쓸 수 있다(색인 임베딩은 정규화돼 있지만
            # 외부에서 주입된 벡터가 섞일 수 있으므로 한 번 맞춰 둔다).
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            mat = mat / np.where(norms == 0, 1.0, norms)
            self._matrix_cache[key] = mat
        q = np.asarray(self._query_vec(query), dtype="float32")
        qn = float(np.linalg.norm(q)) or 1.0
        return (mat @ (q / qn)).tolist()


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
        source_types: Sequence[str] | None = None,
        filters: dict[str, Any] | None = None,
        where: Callable[[Chunk], bool] | None = None,
        k: int = 5,
    ) -> list[tuple[float, Chunk]]:
        """filters(메타 완전일치)로 먼저 좁히고, 유사도 상위 k개를 반환.

        점수 0(=어휘 겹침 전무)도 포함해 반환한다. 데모 코퍼스가 작아서, 자연어
        사건 사실과 격식체 법령 원문 사이의 어휘 겹침이 낮아도 필터(메타)로 이미
        좁혀진 후보군 안에서는 '가장 그나마 가까운' 항목을 보여주는 게 맞다.
        (실제 임베딩으로 교체하면 저점 매칭 자체가 줄어들 것.)

        source_type 은 단일 종류, source_types 는 여러 종류를 한 후보군으로 묶는다.
        후자는 '법령 조문(statute)이 4건뿐이라 특정 분야에선 근거가 0건'인 문제를
        푼다 — 같은 성격의 코퍼스(법령해석례·행정 결정례)를 함께 후보로 놓는다.
        둘 다 주면 합집합. 둘 다 없으면 전체 코퍼스가 후보다.

        where 는 메타 완전일치로 표현되지 않는 후보군 제약(예: '금융 규제기관이 발급한
        문서만')을 걸기 위한 술어다. filters 와 함께 쓰면 둘 다 만족하는 청크만 남는다.
        """
        wanted: set[str] = set()
        if source_type:
            wanted.add(source_type)
        if source_types:
            wanted.update(source_types)
        pool = self.chunks
        if wanted:
            pool = [c for c in pool if c.source_type in wanted]
        if filters:
            pool = [c for c in pool if all(c.metadata.get(kk) == vv for kk, vv in filters.items())]
        if where is not None:
            pool = [c for c in pool if where(c)]
        scores = self.scorer.score_many(query, pool)
        scored = list(zip(scores, pool))
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

    상품유형이 맞는 분쟁조정 결정례를 먼저 찾고, 없으면 금융위 검사·제재 결정례까지
    넓혀 다시 찾는다 — product_en 메타는 분쟁조정 결정례 12청크에만 붙어 있어, 필터만
    걸면 보험·대출·예금 사건은 언제나 0건이 되기 때문이다(case_ai 와 같은 규칙).
    """
    hits = store.search(query, source_type="decision", filters={"product_en": product_en}, k=k * 4)
    widened = False
    if not hits:
        hits = store.search(query, source_types=PRECEDENT_SOURCES, where=finance_scoped, k=k * 8)
        widened = bool(hits)

    seen: dict[str, dict[str, Any]] = {}
    for _, c in hits:
        m = c.metadata
        # 분쟁조정 결정례는 case_no, 행정 결정례는 doc_id 로 사건을 식별한다.
        no = m.get("case_no") or m.get("doc_id") or doc_key(c)
        if no not in seen:
            seen[no] = {
                "case": m.get("case_display") or m.get("title") or str(no),
                # 소요 영업일은 분쟁조정 결정례에만 기록돼 있다. 없으면 0 으로 채워 두되
                # 아래 평균 계산에서는 제외한다(0영업일 = 오늘 완료로 우기지 않기 위해).
                "business_days": m.get("business_days") or 0,
            }
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

    lead = (f"'{product_en}' 유형의 분쟁조정 결정례가 없어 금융위 검사·제재 결정례까지 넓혀 검색한 "
            f"{len(cases)}건" if widened else f"유사 {len(cases)}건")
    timed = [c["business_days"] for c in cases if c["business_days"] > 0]
    if not timed:
        return {
            "cases": cases,
            "estimated_completion": due_date,
            "due_date": due_date,
            "over_deadline_risk": False,
            "reasoning": f"{lead}을 찾았으나 처리 소요일 기록이 없어 완료일 추정은 보류합니다.",
        }

    avg = round(sum(timed) / len(timed))
    est = add_business_days(today, avg)
    est_iso = est.isoformat()
    risk = bool(due_date) and est_iso > due_date
    return {
        "cases": cases,
        "estimated_completion": est_iso,
        "due_date": due_date,
        "over_deadline_risk": risk,
        "reasoning": (
            f"{lead} 중 소요일이 기록된 {len(timed)}건 평균 약 {avg}영업일. "
            f"오늘({today.isoformat()}) 기준 예상 완료 {est_iso} vs 처리 기한 {due_date} → "
            f"{'초과 위험' if risk else '기한 내 가능'}."
        ),
    }
