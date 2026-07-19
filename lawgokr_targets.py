from __future__ import annotations

"""law.go.kr target별 어댑터 — 응답 태그 차이를 데이터(TargetSpec)로 선언.

lawgokr.py 의 범용 함수는 "행 dict / 본문 bytes"만 돌려주고 태그 이름을 모른다.
target 마다 다른 것(목록의 ID 필드명, 본문의 섹션 태그, 메타 필드)을 여기서
TargetSpec 하나로 선언하고, 파싱(parse_doc)·정제(clean_text)도 여기서 담당한다.

새 target 을 추가하려면 TARGET_SPECS 에 스펙 한 줄을 넣으면 끝이다 — 코드 수정 없음.
section_fields 를 모르면 None 으로 두면 자동 탐지(긴 leaf 텍스트)로 동작하고,
collect_corpus.py --probe 로 실제 태그를 확인해 확정하면 된다.
"""

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

# 계열 2종 — 기존 'statute'/'decision' 검색 경로(checklist_plan·similar_cases)와
# 절대 겹치지 않는 새 source_type. 기관 구분은 metadata["org"] 로 한다.
ADMIN_DECISION = "admin_decision"   # 행정기관 결정문·재결례
LAW_INTERP = "law_interp"           # 법령해석례


@dataclass(frozen=True)
class TargetSpec:
    target: str                          # API target 파라미터 값
    org_name: str                        # 기관 표시명
    source_type: str                     # ADMIN_DECISION | LAW_INTERP
    id_fields: tuple[str, ...]           # 목록 행에서 ID 를 찾을 태그 후보(순서대로)
    title_fields: tuple[str, ...] = ("안건명",)
    section_fields: tuple[str, ...] | None = None   # 본문 섹션 태그(순서 보존). None=자동 탐지
    meta_fields: tuple[str, ...] = ()    # 본문에서 정형 메타로 복사할 태그
    default_query: str | None = None     # 대형 target 의 기본 검색어
    default_cap: int | None = None       # 타겟당 기본 수집 상한. None=전량


TARGET_SPECS: dict[str, TargetSpec] = {
    "fsc": TargetSpec(
        target="fsc", org_name="금융위원회", source_type=ADMIN_DECISION,
        id_fields=("결정문일련번호",),
        section_fields=("안건명", "조치내용", "조치이유"),
        meta_fields=("의결번호",),
    ),
    "acr": TargetSpec(
        target="acr", org_name="국민권익위원회", source_type=ADMIN_DECISION,
        id_fields=("결정문일련번호",),
        title_fields=("제목",),
        section_fields=("주문", "이유", "결정요지"),  # 본문은 <의결서> 래퍼 안에 있음
        meta_fields=("의안번호", "민원표시", "피신청인", "의결일"),
    ),
    "acrSpecialDecc": TargetSpec(
        target="acrSpecialDecc", org_name="국민권익위원회(특별행정심판)", source_type=ADMIN_DECISION,
        id_fields=("특별행정심판재결례일련번호", "재결례일련번호"),
        title_fields=("사건명",),
        section_fields=("재결요지", "주문", "청구취지", "이유"),
        meta_fields=("사건번호", "의결일자", "처분청", "재결청"),
    ),
    "ftc": TargetSpec(
        target="ftc", org_name="공정거래위원회", source_type=ADMIN_DECISION,
        id_fields=("결정문일련번호",),
        title_fields=("사건명",),
        section_fields=("주문", "신청취지", "이유", "결정요지"),  # 별지는 부속물이라 제외
        meta_fields=("사건번호", "결정번호", "결정일자"),
        default_query="금융", default_cap=300,
    ),
    "ttSpecialDecc": TargetSpec(
        target="ttSpecialDecc", org_name="조세심판원", source_type=ADMIN_DECISION,
        id_fields=("특별행정심판재결례일련번호", "재결례일련번호"),
        title_fields=("사건명",),
        section_fields=("재결요지", "주문", "청구취지", "이유"),
        meta_fields=("청구번호", "의결일자", "처분청", "재결청", "세목"),
        default_query="금융", default_cap=300,   # 14만 건 — 전량 수집 금지
    ),
    "expc": TargetSpec(
        target="expc", org_name="법제처", source_type=LAW_INTERP,
        id_fields=("법령해석례일련번호",),
        section_fields=("질의요지", "회답", "이유"),
        meta_fields=("안건번호", "해석일자", "질의기관명"),
        default_query="금융", default_cap=500,
    ),
    "moisCgmExpc": TargetSpec(
        target="moisCgmExpc", org_name="행정안전부", source_type=LAW_INTERP,
        id_fields=("법령해석일련번호", "법령해석례일련번호"),
        section_fields=("질의요지", "회답", "이유"),
        meta_fields=("안건번호", "해석일자", "질의기관명"),
        default_query="금융", default_cap=300,
    ),
    "kcsCgmExpc": TargetSpec(
        target="kcsCgmExpc", org_name="관세청", source_type=LAW_INTERP,
        id_fields=("법령해석일련번호", "법령해석례일련번호"),
        section_fields=("질의요지", "회답", "이유"),
        meta_fields=("해석일자", "질의기관명"),
        default_query=None, default_cap=300,   # 관세청엔 "금융" 검색이 0건 — 전체에서 최신순 상한
    ),
}

MIN_DOC_CHARS = 50    # 전 섹션 합산 정제 텍스트가 이보다 짧으면 문서 폐기(스캔 이미지 전용)
MIN_SECTION_CHARS = 80  # 섹션 자동 탐지 시 '본문 섹션'으로 인정할 최소 길이


def extract_doc_id(spec: TargetSpec, row: dict[str, str]) -> str | None:
    """목록 행에서 문서 ID 추출 — id_fields 순차 시도, '일련번호' 접미 태그 폴백."""
    for f in spec.id_fields:
        if row.get(f):
            return row[f]
    for k, v in row.items():
        if k.endswith("일련번호") and v:
            return v
    return None


_TAG_IMG = re.compile(r"<img[^>]*>(?:</img>)?", re.IGNORECASE)
_TAG_BREAK = re.compile(r"</?(?:br|p|div|tr|li)[^>]*>", re.IGNORECASE)
_TAG_ANY = re.compile(r"<[^>]+>")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(s: str) -> str:
    """CDATA 안에 섞여 오는 HTML 조각·이미지 참조·엔티티를 걷어내고 공백을 정규화."""
    s = _TAG_IMG.sub("", s)
    s = _TAG_BREAK.sub("\n", s)
    s = _TAG_ANY.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = _CTRL.sub("", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*", "\n\n", s)
    return s.strip()


_META_SUFFIXES = ("일자", "번호", "기관명", "기관코드", "일시")


@dataclass
class ParsedDoc:
    doc_id: str
    title: str
    sections: list[tuple[str, str]] = field(default_factory=list)  # (섹션명, 정제 텍스트)
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_doc(spec: TargetSpec, doc_id: str, xml_bytes: bytes) -> ParsedDoc | None:
    """본문 XML → ParsedDoc. 텍스트가 사실상 없으면(스캔 이미지 전용) None.

    루트 태그명은 target 마다 달라(FscService/ExpcService...) 검증하지 않고,
    루트 직속 leaf 요소만 순회한다.
    """
    root = ET.fromstring(xml_bytes)
    # 일부 target(acr)은 본문 전체를 <의결서> 같은 래퍼 하나로 감싼다 — 단일 비-leaf
    # 자식만 있으면 그 안으로 내려간다(태그명 무관, 구조 규칙만).
    while len(root) == 1 and len(root[0]):
        root = root[0]

    title = ""
    for f in spec.title_fields:
        t = root.findtext(f)
        if t and t.strip():
            title = clean_text(t)
            break

    metadata: dict[str, Any] = {}
    for f in spec.meta_fields:
        v = root.findtext(f)
        if v and v.strip():
            metadata[f] = v.strip()

    sections: list[tuple[str, str]] = []
    if spec.section_fields is not None:
        for name in spec.section_fields:
            text = clean_text(root.findtext(name) or "")
            if text:
                sections.append((name, text))
    else:
        # 자동 탐지: 루트 직속 leaf 중 정제 후 충분히 긴 태그를 문서 순서대로 섹션으로.
        # 짧은 것 중 메타성 접미(일자/번호/기관명...)를 가진 태그는 메타로 분류.
        for child in root:
            if len(child):
                continue
            text = clean_text(child.text or "")
            if not text:
                continue
            if len(text) >= MIN_SECTION_CHARS:
                sections.append((child.tag, text))
            elif child.tag.endswith(_META_SUFFIXES):
                metadata.setdefault(child.tag, text)

    if sum(len(t) for _, t in sections) < MIN_DOC_CHARS:
        return None
    return ParsedDoc(doc_id=doc_id, title=title, sections=sections, metadata=metadata)
