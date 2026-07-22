from __future__ import annotations

"""Task 정의 — 커맨드(Command) 패턴 + 레지스트리(싱글턴).

LLM 호출 '종류' 하나(task)를 객체 하나(TaskSpec)로 캡슐화한다.
예전에는 task 문자열이 세 군데에 흩어져 있었다:
  1) MockLLM.structured 의 if/elif 라우팅 (더미 payload 조립)
  2) ProxyLLM._system_prompt 의 guides dict (실제 LLM 지시문)
  3) 호출부(agent.py)의 self.llm.structured("task이름", ...)

그래서 task 하나를 추가/수정하려면 파일 두 곳(1·2)을 동시에 고쳐야 했다.
이제 TaskSpec 하나(프롬프트 빌더 build_prompt + 더미 빌더 build_mock)를 레지스트리에
등록하면 백엔드 코드는 손대지 않는다 — 백엔드는 task 이름으로 레지스트리를 조회할 뿐이다.

실제 LLM 지시문은 정적 문자열이 아니라 build_prompt(context) '함수'다. 그래서 사건
사실·판정·유사사례 같은 context를 프롬프트 본문에 자유롭게 녹이고, few-shot 예시나
출력 규칙을 task별로 손봐가며 프롬프트 엔지니어링을 할 수 있다.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

# 트리아지 키워드 휴리스틱 — 더미(MockLLM)·검색(RetrievalLLM)이 공유한다.
# 실제 LLM은 프롬프트(_prompt_checklist_plan)로 더 정교하게 판정하고, 오프라인 모드에서는
# 이 키워드 겹침으로 근사한다(임베딩 없이 결정론적). 애매하면 법률(legal)로 — 안전측.
_LEGAL_SIGNALS = (
    "불완전판매", "손실", "손해", "배상", "위반", "설명의무", "적합성", "부당", "피해",
    "분쟁", "사기", "보이스피싱", "약관", "환불 거부", "손실보전", "미이행", "하자", "위법",
)
_GENERAL_SIGNALS = (
    "조회", "발급", "재발급", "변경", "한도", "비밀번호", "이체", "가입 방법", "절차", "문의",
    "영업시간", "위치", "앱 오류", "로그인", "명세서", "해지 방법", "수수료 안내",
)


def classify_track(facts: str) -> str:
    """사건 사실로 처리 트랙을 판정 — 'legal'(법률 분쟁) 또는 'general'(일반 안내).

    법률 신호와 일반 신호 출현 수를 세어 더 많은 쪽으로. 동수·둘 다 0이면 legal(안전측: 법률
    분쟁을 일반 안내로 흘려보내지 않는다). 실제 LLM 모드는 프롬프트로 판정하므로 여기 안 탄다.
    """
    text = facts or ""
    legal = sum(1 for s in _LEGAL_SIGNALS if s in text)
    general = sum(1 for s in _GENERAL_SIGNALS if s in text)
    return "general" if general > legal else "legal"


# (context, fixtures) -> payload dict. 더미(MockLLM)가 스키마에 넣을 값을 조립하는 함수.
MockBuilder = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

# context -> 자연어 프롬프트(str). 실제 LLM(ProxyLLM)에게 줄 지시문을 '조립'하는 함수.
# 정적 문자열이 아니라 함수인 이유: context(사건 사실·판정·유사사례 등)를 프롬프트 본문에
# 자유롭게 녹이고, few-shot 예시·조건 분기 등 프롬프트 엔지니어링을 task별로 하기 위함.
PromptBuilder = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class TaskSpec:
    """LLM 호출 한 종류를 캡슐화한 커맨드.

    - name         : task 식별자
    - build_prompt : 실제 LLM(ProxyLLM)에게 줄 지시문을 context로 조립하는 함수
                     (프롬프트 엔지니어링은 전부 이 함수 안에서 한다)
    - build_mock   : 더미(MockLLM)가 fixtures/context로 payload를 조립하는 함수
    출력 스키마는 호출부가 structured(task, schema, ...)로 넘겨주므로 여기 두지 않는다.
    """

    name: str
    build_prompt: PromptBuilder
    build_mock: MockBuilder


# ---- 각 task 의 더미 payload 빌더 (예전 MockLLM.structured 의 if/elif 분기) --------

def _mock_verdict(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    n = context["item_no"]
    hit = fx["verdict"].get(str(n))
    if hit:
        return dict(hit)
    # fixtures 는 데모 6항목분만 있다. 검토 계획(#0)이 실검색으로 더 많은 항목을
    # 도출하면(RetrievalLLM + MockLLM 조합) 초과분은 context로 일반 판정을 합성한다.
    return {
        "code": context.get("law", f"검토 항목 #{n}"),
        "verdict": "해당없음",
        "ko": f"{context.get('item', f'항목 #{n}')} — 더미 판정",
        "detail": "fixtures 데모 범위 밖 항목이라 더미 백엔드가 일반 판정을 반환했습니다(실제 LLM 모드에서 실판정).",
    }


def _mock_disclosure(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    n = context["item_no"]
    d = fx["disclosure"].get(str(n)) or {
        "complainant_body": f"{n}번째 검토 항목 처리가 끝났어요. 다음 단계로 진행 중입니다.",
        "supervisor_body": f"검토 항목 #{n} 처리 완료.",
    }
    remaining = context.get("remaining", 0)
    return {
        "complainant_title": f"진행 안내 #{n} · 민원인용 / Complainant",
        "complainant_body": d["complainant_body"],
        "supervisor_title": f"검토 결과 #{n} · 회사·감독원용 / Supervisor",
        # 남은 검토 건수는 오케스트레이터가 세어서 넘겨준 값을 반영(=콘솔과 동일 문구).
        "supervisor_body": f"{d['supervisor_body']} 남은 검토 {remaining}건 · 전체 근거 원장 반영.",
    }


def _mock_verdict_batch(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 항목별 더미(_mock_verdict)를 그대로 재사용해 배치 결과를 조립한다.
    # → 배칭 전(항목별 N회 호출)과 오프라인 출력이 한 글자도 다르지 않다(골든 보존).
    items = context.get("items", [])
    return {
        "verdicts": [
            _mock_verdict({"item_no": it["n"], "item": it.get("item", ""), "law": it.get("law", "")}, fx)
            for it in items
        ]
    }


def _mock_disclosure_batch(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 항목별 더미(_mock_disclosure)를 그대로 재사용. remaining 은 호출부가 항목별로 계산해 넘긴다.
    items = context.get("items", [])
    return {
        "disclosures": [
            _mock_disclosure({"item_no": it["n"], "remaining": it.get("remaining", 0)}, fx)
            for it in items
        ]
    }


def _mock_similar_cases(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    return dict(fx["similar_cases"])


def _mock_renegotiation(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    return dict(fx["renegotiation"])


def _mock_closing_disclosure(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 종결 문구는 미리 정해둘 수 없다 — 실제 원장(ledger)의 판정을 읽고 나서야
    # '무슨 문제가 확인됐고 배상비율이 얼마인지' 알 수 있다.
    ledger = context.get("ledger", [])
    issues = [l for l in ledger if l["verdict"] in ("위반", "미이행", "하자", "해당")]
    award = next((l for l in ledger if l["verdict"] == "산정"), None)
    detail = award["detail"] if award else "배상비율 산정 결과 없음"
    found = bool(issues)
    return {
        "complainant_title": "처리 결과 안내 / To complainant",
        "complainant_body": (
            f"검토 결과 {'문제가 확인되어 배상이 산정되었습니다' if found else '문제가 확인되지 않았습니다'}"
            f"({detail}). 이후 절차와 제출 서류를 쉽게 안내드릴게요."
        ),
        "supervisor_title": "사건 종결 리포트 / To supervisor",
        "supervisor_body": f"{len(ledger)}개 항목 전부 ② 원장 반영. {detail}. 처리 이력 로그 종료.",
    }


def _mock_checklist_plan(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 더미는 실제 검색 없이 fixtures의 데모 항목을 '이 사건에서 도출한 것처럼' 되돌린다
    # (사실을 읽어 코퍼스를 검색하는 버전은 RetrievalLLM).
    facts = context.get("facts", "")
    track = classify_track(facts)
    if track == "general":
        # 비법률 일반 민원 — 검토 항목(법령 대조) 자체가 필요 없다. 트랙만 정하고 항목은 비운다.
        return {
            "classification": f"{context.get('product_en', '일반 문의')} · 일반 안내",
            "track": "general",
            "items": [],
            "reasoning": "사건 사실에 법률 분쟁 신호가 없고 안내·행정 문의 신호가 우세해 일반 안내 트랙으로 분류했습니다.",
        }
    items = fx["checklist"]
    return {
        "classification": f"{fx['case']['product']} 의심",
        "track": "legal",
        "items": [{"item": c["item"], "law": c["law"], "source": c["law"]} for c in items],
        "reasoning": "사건 사실에서 쟁점 키워드를 추출해 유형을 분류하고 관련 법령·절차 항목을 구성했습니다.",
    }


def _mock_general_guidance(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 일반 안내도 미리 못 박아둘 순 없지만, 오프라인 더미는 fixtures의 데모 안내를 돌려준다
    # (사건별 실질 안내는 실제 LLM이 facts를 읽고 생성).
    return dict(fx["general_guidance"])


def _mock_rights_guide(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 권익 안내도 종결 문구처럼 미리 못 박아둘 수 없다 — 원장(ledger)에 위반이 쌓였는지에 따라
    # 안내가 달라진다. 더미는 fixtures의 데모 안내를 기본으로 돌려주되, 원장에 위반/미이행/하자/
    # 해당이 하나도 없으면(무혐의) 권리·서류 안내를 접고 무혐의 안내로 바꿔 '개인화'를 흉내낸다.
    base = dict(fx["rights_guide"])
    ledger = context.get("ledger", [])
    has_violation = any(l.get("verdict") in ("위반", "미이행", "하자", "해당") for l in ledger)
    if not has_violation:
        return {
            "summary": "검토 결과 규정 위반이 확인되지 않았습니다. 참고하실 일반 대응 경로만 안내드려요.",
            "rights": [],
            "documents": [],
            "escalation": base["escalation"],
            "disclaimer": base["disclaimer"],
        }
    return base


def _mock_chunk_label(context: dict[str, Any], fx: dict[str, Any]) -> dict[str, Any]:
    # 색인용 일상어 라벨. 더미는 텍스트에서 순진하게 파생시킨다(요지=첫 구절, 키워드=명사 후보).
    text = context.get("text", "")
    head = re.split(r"[。.\n]", text.strip(), maxsplit=1)[0][:40]
    kws = list(dict.fromkeys(re.findall(r"[가-힣]{2,}", text)))[:5]
    return {
        "issue_summary": head,
        "keywords": kws,
        "everyday_questions": [f"{k} 관련해서 문제가 있어요" for k in kws[:3]],
    }


# ---- 각 task 의 프롬프트 빌더 (실제 LLM 에게 줄 지시문을 context로 조립) ------------
# 프롬프트 엔지니어링은 여기서 한다. context 필드를 자연어 본문에 녹이고, 필요하면
# few-shot 예시·출력 규칙·조건 분기를 함수 안에서 자유롭게 덧붙이면 된다.
# (공통 지시문 _BASE_GUIDE 는 백엔드가 이 함수 결과 앞에 붙이므로 여기서 반복하지 않는다.)

def _dump(value: Any) -> str:
    """context 값(list/dict)을 프롬프트에 넣기 좋은 한글 JSON 문자열로."""
    return json.dumps(value, ensure_ascii=False, indent=2)


def _prompt_checklist_plan(ctx: dict[str, Any]) -> str:
    return (
        "방금 이관받은 사건이다. 먼저 처리 트랙을 판정하라(track): 규정 위반·손해배상 등 "
        "법률 분쟁이면 'legal', 단순 조회·발급·변경·절차 문의 등 비법률 안내·행정 민원이면 "
        "'general'. general이면 검토 항목(items)은 비워도 된다. legal이면 사건 유형을 "
        "분류하고(classification) 어떤 법령·절차 위반 여부를 검토해야 하는지 스스로 도출해 "
        "각 항목의 근거 법령·절차와 함께 밝혀라. 사실에 없는 근거를 지어내지 않는다. "
        "애매하면 legal로 둔다(법률 분쟁을 일반 안내로 흘려보내지 않는다).\n\n"
        f"[상품 유형] {ctx.get('product_en', '')}\n"
        f"[사건 사실]\n{ctx.get('facts', '')}"
    )


def _prompt_general_guidance(ctx: dict[str, Any]) -> str:
    return (
        "비법률 일반 민원(안내·행정 문의)이다. 규정 판정 없이, 사용자의 구체 상황에 맞춰 "
        "실질적으로 답하라 — 직접 답변(answer), 밟을 절차(steps), 앱/웹 셀프처리 가능 여부"
        "(self_service), 추가 문의처(contact). 만약 사실관계에 규정 위반·피해·손해배상 등 "
        "법률 분쟁 소지가 보이면 escalation_hint에 정식 민원(분쟁)으로 전환 안내를 적고, "
        "아니면 빈 문자열로 둬라. 사실에 없는 내용을 지어내지 않는다.\n\n"
        f"[사건 유형] {ctx.get('classification', '')}\n"
        f"[사건 사실]\n{ctx.get('facts', '')}"
    )


def _prompt_verdict(ctx: dict[str, Any]) -> str:
    return (
        "주어진 검토 항목 1건을 사건 사실에 대조해 규정 판정을 내려라. "
        "판정 근거로 조문을 인용하되, 사건 사실에 없는 조문·수치는 지어내지 마라. "
        "애매하면 단정하지 마라.\n\n"
        f"[검토 항목 #{ctx.get('item_no', '')}] {ctx.get('item', '')}\n"
        f"[근거 법령] {ctx.get('law', '')}\n"
        f"[사건 사실]\n{ctx.get('facts', '')}"
    )


def _prompt_disclosure(ctx: dict[str, Any]) -> str:
    return (
        "같은 판정을 두 독자에게 나눠 써라. 민원인용(complainant)은 법률 용어 없이 쉽고 "
        "공감적으로, 회사·감독원용(supervisor)은 법조문·판정·근거를 포함해 기술적으로. "
        "두 글의 사실 내용은 동일하게 유지한다. 제목에는 반드시 검토 항목 번호를 "
        f"'#{ctx.get('item_no', '')}' 형식으로 포함하라(예: '진행 안내 #{ctx.get('item_no', '')} · 민원인용').\n\n"
        f"[검토 항목 번호] {ctx.get('item_no', '')}\n"
        f"[판정 결과]\n{_dump(ctx.get('verdict', {}))}\n"
        f"[남은 검토 항목 수] {ctx.get('remaining', 0)}건"
    )


def _prompt_verdict_batch(ctx: dict[str, Any]) -> str:
    items = ctx.get("items", [])
    lines = "\n".join(f"[검토 항목 #{it['n']}] {it.get('item','')} (근거 법령: {it.get('law','')})" for it in items)
    return (
        "아래 검토 항목 전부를 사건 사실에 대조해 각각 규정 판정을 내려라. "
        "항목마다 하나씩, 입력 순서 그대로 배열(verdicts)로 반환하라 — 항목 수와 판정 수가 같아야 한다. "
        "판정 근거로 조문을 인용하되 사건 사실에 없는 조문·수치는 지어내지 마라. 애매하면 단정하지 마라.\n\n"
        f"[검토 항목 목록]\n{lines}\n\n"
        f"[사건 사실]\n{ctx.get('facts', '')}"
    )


def _prompt_disclosure_batch(ctx: dict[str, Any]) -> str:
    items = ctx.get("items", [])
    blocks = "\n".join(
        f"[항목 #{it['n']}] 판정={_dump(it.get('verdict', {}))} · 남은 검토 {it.get('remaining', 0)}건"
        for it in items
    )
    return (
        "아래 각 판정을 두 독자용으로 나눠 써라 — 민원인용(complainant)은 법률 용어 없이 쉽고 공감적으로, "
        "회사·감독원용(supervisor)은 법조문·판정·근거를 포함해 기술적으로. 두 글의 사실 내용은 동일하게 유지한다. "
        "제목에는 반드시 항목 번호를 '#n' 형식으로 포함하라. 입력 순서 그대로 배열(disclosures)로 반환하라 — "
        "항목 수와 공개 수가 같아야 한다.\n\n"
        f"[항목별 판정]\n{blocks}"
    )


def _prompt_similar_cases(ctx: dict[str, Any]) -> str:
    return (
        "유사 과거 분쟁 사례를 근거로 예상 완료일을 추정하고 처리 기한 초과 위험을 판정하라.\n\n"
        f"[상품 유형] {ctx.get('product_en', '')}\n"
        f"[현재 처리 기한] {ctx.get('due_date', '')}"
    )


def _prompt_renegotiation(ctx: dict[str, Any]) -> str:
    return (
        "기한 재협상 '재료'만 초안한다. 너는 자문·중재자이며 새 기한을 확정하지 않는다 — "
        "결정은 사람(민원인·감독원)이 한다. 아래 유사사례별 소요 영업일과 그로 추정한 "
        "완료일을 근거로 evidence_for_supervisor와 recommended_new_due_date를 작성하라. "
        "근거에 없는 수치를 지어내지 않는다.\n\n"
        f"[미완 검토 항목] {', '.join(ctx.get('blocking', []))}\n"
        f"[현재 처리 기한] {ctx.get('due_date', '')}\n"
        f"[추정 완료일] {ctx.get('estimated_completion', '')}\n"
        f"[유사 사례]\n{_dump(ctx.get('similar_cases', []))}"
    )


def _prompt_closing_disclosure(ctx: dict[str, Any]) -> str:
    return (
        "사건이 종결됐다. 미리 정해둔 결과를 말하지 말고, 아래 원장(ledger)의 실제 판정들을 "
        "읽어 무슨 문제가 확인됐는지와 배상비율을 반영해 종결 안내를 작성하라. "
        "민원인용은 쉽고 공감적으로, 감독원용은 기술적으로.\n\n"
        f"[적용 법률 원장]\n{_dump(ctx.get('ledger', []))}"
    )


def _prompt_rights_guide(ctx: dict[str, Any]) -> str:
    return (
        "사건이 종결됐다. 아래 원장(ledger)의 실제 판정에 근거해 이 소비자가 지금 행사할 수 있는 "
        "권리·대응 절차를 안내하라. 일반 FAQ가 아니라 '이 사건'에 맞춘 안내여야 한다 — 위반이 "
        "확인된 항목이 있으면 그에 맞는 권리(위법계약해지·손해배상·분쟁조정 등)를, 무혐의면 그에 맞게. "
        "각 권리에는 근거 법령과 행사 기한(제척기간)을 밝히고, 준비 서류와 확대 경로(금감원 "
        "분쟁조정·소비자원·소액소송)를 정리하라. 사실·근거에 없는 조문·수치는 지어내지 마라. "
        "너는 정보 제공·안내까지만 한다 — 권리 행사 여부는 본인이 결정한다.\n\n"
        f"[사건 유형] {ctx.get('classification', '')}\n"
        f"[적용 법률 원장]\n{_dump(ctx.get('ledger', []))}"
    )


def _prompt_chunk_label(ctx: dict[str, Any]) -> str:
    return (
        "색인 대상 텍스트 조각(법령 조문 또는 분쟁조정 결정문 섹션)을 읽고, 검색이 잘 되도록 "
        "쟁점 한 줄 요약·키워드·'일상어 질문'을 생성하라. 일상어 질문은 법률어를 모르는 "
        "민원인이 실제로 던질 법한 문장이어야 한다(예: '원금 다 잃었어요', '설명 못 들었어요').\n\n"
        f"[대상 텍스트]\n{ctx.get('text', '')}"
    )


# ---- task 정의(커맨드 목록) — 프롬프트 빌더(build_prompt) + 더미 빌더 --------------

_BASE_GUIDE = (
    "너는 금융 민원 처리 에이전트다. 사건 사실관계와 적용 법률에 근거해서만 판단하고, "
    "사실을 지어내지 않는다. 애매하면 단정하지 않는다."
)

_ALL_SPECS: list[TaskSpec] = [
    TaskSpec("checklist_plan", _prompt_checklist_plan, _mock_checklist_plan),
    TaskSpec("verdict", _prompt_verdict, _mock_verdict),
    TaskSpec("verdict_batch", _prompt_verdict_batch, _mock_verdict_batch),
    TaskSpec("disclosure", _prompt_disclosure, _mock_disclosure),
    TaskSpec("disclosure_batch", _prompt_disclosure_batch, _mock_disclosure_batch),
    TaskSpec("similar_cases", _prompt_similar_cases, _mock_similar_cases),
    TaskSpec("renegotiation", _prompt_renegotiation, _mock_renegotiation),
    TaskSpec("closing_disclosure", _prompt_closing_disclosure, _mock_closing_disclosure),
    TaskSpec("rights_guide", _prompt_rights_guide, _mock_rights_guide),
    TaskSpec("general_guidance", _prompt_general_guidance, _mock_general_guidance),
    TaskSpec("chunk_label", _prompt_chunk_label, _mock_chunk_label),
]


# ---- 레지스트리(싱글턴) — 프로세스 전체가 하나의 task 목록을 공유 -----------------


class TaskRegistry:
    """등록된 TaskSpec들을 보관하는 싱글턴. task 이름 → TaskSpec 조회 담당.

    싱글턴(Singleton): 프로세스 안에서 인스턴스가 하나만 존재하도록 보장한다.
    백엔드(MockLLM/ProxyLLM)는 각자 목록을 들고 있지 않고 이 하나를 조회한다.
    """

    _instance: "TaskRegistry | None" = None

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSpec] = {}

    def register(self, spec: TaskSpec) -> None:
        self._tasks[spec.name] = spec

    def get(self, name: str) -> TaskSpec:
        try:
            return self._tasks[name]
        except KeyError:
            raise ValueError(f"알 수 없는 task: {name}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._tasks

    @property
    def base_guide(self) -> str:
        """모든 task 프롬프트 앞에 붙는 공통 지시문."""
        return _BASE_GUIDE


def task_registry() -> TaskRegistry:
    """싱글턴 인스턴스를 돌려준다(최초 호출 때 _ALL_SPECS로 채워 1회 생성)."""
    if TaskRegistry._instance is None:
        reg = TaskRegistry()
        for spec in _ALL_SPECS:
            reg.register(spec)
        TaskRegistry._instance = reg
    return TaskRegistry._instance
