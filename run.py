from __future__ import annotations

"""민원 처리 에이전트 실행기.

    python run.py                        # 더미(MockLLM)로 전체 시퀀스 실행
    python run.py --llm                  # 프록시 LLM(PROXY_TOKEN 필요, CHONNAM_CLONE_REPO 필요)
    python run.py --json out.json        # 프레임을 콘솔 호환 JSON으로 저장

콘솔(민원 처리 콘솔.html)이 상수로 보여주던 20여 스텝을,
에이전트가 LLM 호출로 '실제로' 만들어내는 것을 확인합니다.
"""

import argparse
import json
import sys
from pathlib import Path

# Windows 콘솔(cp949)에서도 한글/기호가 깨지지 않도록 UTF-8로.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 이 폴더 자체를 path에 넣어 `python run.py`로 바로 실행 가능하게.
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from complaint_processing.agent import ComplaintAgent
from complaint_processing.llm import get_backend
from complaint_processing.schemas import ComplaintCase

FIXTURES = json.loads((Path(__file__).with_name("fixtures.json")).read_text(encoding="utf-8"))


def build_agent(use_llm: bool, retrieval_index: str | None = None) -> ComplaintAgent:
    case = ComplaintCase.model_validate(FIXTURES["case"])
    # 검토 항목은 여기서 만들지 않는다 — 이관 시 LLM #0(plan_checklist)이 사건 사실만 보고 도출한다.
    backend = get_backend(use_llm=use_llm, retrieval_index=retrieval_index, facts=case.facts)
    return ComplaintAgent(case, llm=backend)


def print_timeline(frames: list[dict]) -> None:
    print(f"\n총 {len(frames)} 프레임 생성\n" + "=" * 72)
    for i, f in enumerate(frames):
        print(f"[STEP {i:02d}] {f['phase_ko']:<8} | 상태={f['status']:<6} | {f['hop']}")
        u, r = f["disclose_u"], f["disclose_r"]
        print(f"         ├─ 민원인용 : {u['body']}")
        print(f"         └─ 감독원용 : {r['body']}")
        if f["vector"]:
            cases = ", ".join(f"{v['case']}({v['dur']})" for v in f["vector"])
            print(f"            └ 사례 DB : {cases}  {'⚠초과위험' if f['risk'] else ''}")
    print("=" * 72)
    final = frames[-1]
    print(f"최종 상태: {final['status']} · 원장 {len(final['ledger'])}건 확정 · 처리 기한 {final['due_date']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="프록시 LLM 사용 (기본: 더미)")
    ap.add_argument("--json", metavar="PATH", help="프레임을 JSON 파일로 저장")
    ap.add_argument("--retrieval", metavar="INDEX", nargs="?", const="corpus_index.json",
                    help="#3 유사사례를 실검색으로 (기본 색인: corpus_index.json). build_index.py 먼저 실행.")
    args = ap.parse_args()

    index = None
    if args.retrieval:
        p = Path(args.retrieval)
        index = str(p if p.is_absolute() else Path(__file__).with_name(args.retrieval))

    agent = build_agent(use_llm=args.llm, retrieval_index=index)
    backend = type(agent.llm).__name__
    src = "실제 LLM" if args.llm else "더미 JSON"
    if index:
        src += " + 실검색(RetrievalLLM)"
    print(f"백엔드: {backend}  ({src})")

    frames = agent.run()
    print_timeline(frames)

    # AgentOps 이음새: 관측 데코레이터가 붙어 있으면 호출 계측 요약을 출력한다.
    if hasattr(agent.llm, "summary"):
        s = agent.llm.summary()
        print(f"관측(Observability): LLM 호출 {s['calls']}건 "
              f"(성공 {s['ok']} · 실패 {s['failed']}) · 총 {s['total_ms']}ms")

    if args.json:
        Path(args.json).write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n프레임 저장: {args.json}")


if __name__ == "__main__":
    main()
