from __future__ import annotations

"""국가법령정보 공동활용 Open API(law.go.kr) 클라이언트 — 법령 조문을 평문으로 조회.

인증은 OC(Open API 신청 시 등록한 이메일의 '@' 앞부분)로 한다. .env 의 LAWGOKR_OC 에서 읽는다.

흐름: lawSearch.do(법령명 검색 → MST 확보) → lawService.do(MST로 본문 XML 조회) →
<조문단위>를 순회해 "제N조(제목) ... 항/호/목" 평문으로 재조립한다.

반환 형식은 retrieval.chunk_statute(raw, ...) 가 그대로 받는 원문 문자열이다 —
'제N조' 경계로 청킹하므로, 조문 순서만 지키면 청킹 로직은 그대로 재사용된다.
"""

import math
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

ENV_PATH = Path(__file__).with_name(".env")
BASE_URL = "https://www.law.go.kr/DRF"


def _load_oc() -> str:
    load_dotenv(ENV_PATH)
    oc = os.environ.get("LAWGOKR_OC")
    if not oc:
        raise RuntimeError(
            f".env 에 LAWGOKR_OC 가 없습니다. {ENV_PATH} 에 'LAWGOKR_OC=본인이메일아이디' "
            "로 넣으세요 (law.go.kr Open API 신청 시 등록한 이메일의 '@' 앞부분)."
        )
    return oc


def _get_bytes(path: str, params: dict[str, str]) -> bytes:
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = resp.read()
    head = data.lstrip()[:15].lower()
    if head.startswith(b"<html") or head.startswith(b"<!doctype"):
        # law.go.kr 는 잘못된 OC/파라미터 오류를 HTTP 200 + HTML 페이지로 돌려준다.
        raise RuntimeError(f"law.go.kr 가 XML 대신 HTML을 반환 (OC/파라미터 오류 가능성): {url}")
    return data


def _get_xml(path: str, params: dict[str, str]) -> ET.Element:
    return ET.fromstring(_get_bytes(path, params))


def search_law(name: str, *, oc: str | None = None) -> dict[str, str]:
    """법령명으로 검색해 첫 번째(현행) 결과의 {law_name, mst, law_id} 를 반환한다."""
    oc = oc or _load_oc()
    root = _get_xml("lawSearch.do", {"OC": oc, "target": "law", "type": "XML", "query": name})
    law = root.find("law")
    if law is None:
        raise ValueError(f"law.go.kr 검색 결과 없음: '{name}'")
    return {
        "law_name": law.findtext("법령명한글") or name,
        "mst": law.findtext("법령일련번호") or "",
        "law_id": law.findtext("법령ID") or "",
    }


def _article_text(jo: ET.Element) -> str | None:
    """<조문단위> 1개 → 평문 한 덩어리 ('제N조(제목) 본문 / ① .. / 1. .. / 가. ..')."""
    if jo.findtext("조문여부") != "조문":
        return None
    lines = []
    content = (jo.findtext("조문내용") or "").strip()
    if content:
        lines.append(content)
    for hang in jo.findall("항"):
        hang_content = (hang.findtext("항내용") or "").strip()
        if hang_content:
            lines.append(hang_content)
        for ho in hang.findall("호"):
            ho_content = (ho.findtext("호내용") or "").strip()
            if ho_content:
                lines.append(ho_content)
            for mok in ho.findall("목"):
                mok_content = (mok.findtext("목내용") or "").strip()
                if mok_content:
                    lines.append(mok_content)
    return "\n".join(lines) if lines else None


def fetch_law_articles(
    name_or_mst: str,
    article_nos: list[int] | None = None,
    *,
    oc: str | None = None,
    is_mst: bool = False,
) -> list[tuple[int, str]]:
    """법령 조문을 조회해 [(조번호, 평문), ...] 로 반환한다(조 경계가 이미 확정된 형태).

    article_nos 를 주면 해당 조번호만(예: [17, 19, 21]) 골라 반환 — 법령 하나가
    수백 조문이라 민원 검토에 쓸 조문만 지정하는 게 기본 사용법이다. None 이면 전체.

    조문 본문에는 다른 법령/조문을 인용하는 "제N조" 문구가 섞여 있을 수 있어
    (예: 「보험업법」 제108조제1항제3호에 따른...), 문자열을 합쳐서 '제N조' 정규식으로
    재분리하면(retrieval.chunk_statute의 방식) 그 인용문에서 잘못 잘린다. 그래서 여기서는
    조문단위 XML 요소 단위로 이미 확정된 경계를 그대로 (조번호, 텍스트) 쌍으로 반환한다.
    """
    oc = oc or _load_oc()
    mst = name_or_mst if is_mst else search_law(name_or_mst, oc=oc)["mst"]
    root = _get_xml("lawService.do", {"OC": oc, "target": "law", "MST": mst, "type": "XML"})

    wanted = set(article_nos) if article_nos is not None else None
    results: list[tuple[int, str]] = []
    for jo in root.iter("조문단위"):
        no = jo.findtext("조문번호")
        if no is None or (wanted is not None and int(no) not in wanted):
            continue
        if jo.findtext("조문가지번호"):  # "제N조의2" 같은 가지조문 — 명시 요청 없으면 제외
            continue
        text = _article_text(jo)
        if text:
            results.append((int(no), text))
    return results


# ---- 범용 목록/본문 API (결정문·법령해석례 등 law 외 target) --------------------
# 모든 target 이 같은 2단 구조를 쓴다: lawSearch.do(목록, totalCnt+행들) →
# lawService.do?ID=(본문). target 마다 다른 것은 응답의 태그 이름뿐이라, 여기서는
# 태그 해석 없이 "행 = 태그명→텍스트 dict / 본문 = 원본 bytes" 로만 돌려준다.
# 태그 해석(ID 필드·섹션 매핑)은 lawgokr_targets.py 의 TargetSpec 이 담당.


def _row_to_dict(el: ET.Element) -> dict[str, str]:
    """목록 응답의 행 요소(<fsc>·<expc>...) → {태그명: 텍스트}."""
    return {child.tag: (child.text or "").strip() for child in el}


def search_list(
    target: str,
    *,
    query: str | None = None,
    page: int = 1,
    display: int = 100,
    oc: str | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """lawSearch.do 1페이지 조회 → (totalCnt, [행 dict, ...]).

    행 요소는 target 과 같은 이름의 자식(<fsc>...)이 관례지만 예외가 있어
    (ttSpecialDecc 는 <decc>), '자식이 또 자식을 가진 요소'를 전부 행으로 취급한다.
    """
    oc = oc or _load_oc()
    params = {"OC": oc, "target": target, "type": "XML", "display": str(display), "page": str(page)}
    if query:
        params["query"] = query
    root = _get_xml("lawSearch.do", params)
    total = int(root.findtext("totalCnt") or 0)
    rows = [_row_to_dict(el) for el in root if len(el)]
    return total, rows


def iter_search(
    target: str,
    *,
    query: str | None = None,
    max_items: int | None = None,
    display: int = 100,
    sleep: float = 0.5,
    oc: str | None = None,
) -> Iterator[dict[str, str]]:
    """목록 전 페이지 순회 제너레이터. max_items 도달·빈 페이지·totalCnt 소진 시 종료.

    display 는 요청값일 뿐이고 서버가 더 적게 줄 수 있어, 첫 페이지의 실반환 건수로
    실효 페이지 크기를 감지해 페이지 상한을 다시 계산한다(무한 루프 방지).
    """
    oc = oc or _load_oc()
    yielded = 0
    page = 1
    max_page: int | None = None
    while max_page is None or page <= max_page:
        total, rows = search_list(target, query=query, page=page, display=display, oc=oc)
        if not rows:
            break
        if max_page is None:
            effective = max(len(rows), 1)  # 서버의 실효 페이지 크기
            max_page = math.ceil(total / effective) + 1
        for row in rows:
            yield row
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return
        if yielded >= total:
            break
        page += 1
        time.sleep(sleep)


def fetch_service_xml(target: str, doc_id: str, *, oc: str | None = None) -> bytes:
    """lawService.do 본문을 원본 bytes 그대로 반환한다(수집 캐시에 무가공 저장용)."""
    oc = oc or _load_oc()
    params = {"OC": oc, "target": target, "ID": str(doc_id), "type": "XML"}
    return _get_bytes("lawService.do", params)
