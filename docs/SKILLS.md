# LLM 스킬 레퍼런스 (#0 ~ #7)

에이전트가 LLM에게 구조화 출력을 받아내는 모든 지점. 각 스킬은 **task 이름 하나**로 식별되고,
`self.llm.structured(task, schema, context)` 한 시그니처로 호출된다. 프롬프트/더미는
[`tasks.py`](../tasks.py)의 `TaskSpec`(커맨드)가, 출력 계약은 [`schemas.py`](../schemas.py)가,
호출 시점은 [`agent.py`](../agent.py)가, HTTP 노출은 [`api.py`](../api.py)가 담당한다.

> 배경/데이터 플로우는 [ARCHITECTURE](ARCHITECTURE.md), 왜 이렇게 나눴는지는
> [DIFFERENTIATION](DIFFERENTIATION.md) 참조. 백엔드 옵션(`use_llm`/`provider`/`retrieval`/`critic`)은
> 모든 스킬 요청 body의 `options`로 전달되며 기본은 오프라인 더미(MockLLM)라 키 없이 즉시 응답한다.

## 한눈에

| # | task | agent 메서드 | 입력 context 키 | 출력 스키마 | API 엔드포인트 |
|---|---|---|---|---|---|
| 0 | `checklist_plan` | `plan_checklist()` | `facts`, `product_en` | `ChecklistPlan`(+`track`) | `POST /api/skills/checklist-plan` |
| 1 | `verdict` | `review_item(n)` | `item_no`, `item`, `law`, `facts` | `RegulatoryVerdict` | `POST /api/skills/verdict` |
| 2 | `disclosure` | `dual_disclose()` | `item_no`, `verdict`, `remaining` | `DualDisclosure` | `POST /api/skills/disclosure` |
| 3 | `similar_cases` | `retrieve_similar_cases()` | `product_en`, `due_date` | `SimilarCasesResult` | `POST /api/skills/similar-cases` |
| 4 | `renegotiation` | `draft_renegotiation(sim)` | `blocking`, `due_date`, `similar_cases`, `estimated_completion`, `facts` | `RenegotiationDraft` | `POST /api/skills/renegotiation` |
| 5 | `closing_disclosure` | `close_disclose()` | `ledger`, `checklist` | `DualDisclosure` | *(미노출 — 파이프라인 내부)* |
| 6 | `rights_guide` | `guide_rights()` | `ledger`, `classification`, `facts` | `ConsumerRightsGuide` | `POST /api/skills/rights-guide` |
| 7 | `general_guidance` | `general_guide()` | `classification`, `facts` | `GeneralGuidance` | `POST /api/skills/general-guidance` |
| 색인 | `chunk_label` | `build_index.py` | `text` | `ChunkLabels` | *(오프라인 색인 — 미노출)* |

`#5`(종결 작문)·`chunk_label`(색인 라벨)은 파이프라인/색인 내부 전용이라 HTTP로 열지 않았다.

---

## #0 `checklist_plan` — 검토 계획 수립 + 트리아지
접수 시 사건 사실만 읽고 **트랙(legal/general)** 을 판정하고, legal이면 검토 항목을 도출한다.
`--retrieval`이면 법령 코퍼스를 질의해 항목을 실제로 찾고, 아니면 fixtures 데모를 되돌린다.
- **출력** `ChecklistPlan`: `classification`, `track`(legal/general), `items[]`(`item`/`law`/`source`), `reasoning`
- **트리아지**: `tasks.classify_track(facts)`(오프라인 키워드 근사) / 실제 LLM 프롬프트가 판정. 애매하면 legal.
```bash
curl -X POST localhost:8000/api/skills/checklist-plan -H "Content-Type: application/json" \
  -d '{"facts":"안정추구형 고객에 고위험 ELS 판매, 원금손실 고지 불충분","product_en":"ELS mis-selling"}'
```

## #1 `verdict` — 규정 판정
검토 항목 1건을 사건 사실에 대조해 조항·위반 여부·근거를 낸다(워크플로우의 핵심 법률 추론).
- **출력** `RegulatoryVerdict`: `code`, `verdict`(위반/미이행/해당/하자/선례/산정/해당없음), `ko`, `detail`
```json
// 요청
{"item_no":1,"item":"적합성 원칙 위반 여부","law":"금융소비자보호법 제17조",
 "facts":"안정추구형 고객에게 고위험 ELS를 판매함.","options":{"use_llm":false}}
// 응답
{"code":"제17조 적합성","verdict":"위반","ko":"적합성원칙 위반 확인","detail":"안정추구형 고객에 고위험 ELS 판매"}
```

## #2 `disclosure` — 이중 공개
같은 판정을 **민원인용(법률어 없이 공감적)** / **감독원용(법조문·수치 포함)** 으로 나눠 쓴다. 사실은 동일, 표현 수위만 다름.
- **출력** `DualDisclosure`: `complainant_title`/`complainant_body`, `supervisor_title`/`supervisor_body`
- 제목에 검토 항목 번호(`#n`)를 포함. `verdict`는 #1 결과(dict)를 그대로 넘긴다.

## #3 `similar_cases` — 유사사례 검색 + 완료일 추정
유사 과거 분쟁으로 예상 완료일을 추정하고 처리 기한 초과 위험을 판정(RAG). `--retrieval`이면 상품유형 필터로 결정문 조회.
- **출력** `SimilarCasesResult`: `cases[]`(`case`/`business_days`), `estimated_completion`, `due_date`, `over_deadline_risk`, `reasoning`

## #4 `renegotiation` — 재협상 재료 초안
기한 재협상 '재료'만 초안한다. **에이전트는 새 기한을 확정하지 않는다**(자문·중재). #3 결과를 근거로 넘겨야 함의가 검증된다.
- **출력** `RenegotiationDraft`: `blocking_items[]`, `reason_for_complainant`, `evidence_for_supervisor`, `recommended_new_due_date`, `note`

## #5 `closing_disclosure` — 종결 이중 공개 *(내부)*
종결 시 **실제 원장(ledger)의 판정을 읽고** 결과를 재작문한다(무슨 문제가 확인됐고 배상비율이 얼마인지는 원장을 봐야 안다). 출력은 `DualDisclosure`. 파이프라인 내부에서만 호출.

## #6 `rights_guide` — 소비자 권익 보호 안내
종결 시 **이 사건 원장에 근거한 개인화 안내** — 위반 사안이면 위법계약해지·손해배상·분쟁조정 권리를, 무혐의면 접는다.
- **출력** `ConsumerRightsGuide`: `summary`, `rights[]`(`RightsAction`: `title`/`basis`/`deadline`/`how`), `documents[]`, `escalation[]`, `disclaimer`
```json
// 요청 (위반 원장)
{"ledger":[{"code":"제19조","verdict":"미이행","ko":"설명의무 미이행","detail":"고지 불충분"}],
 "classification":"ELS 불완전판매 의심","options":{"use_llm":false}}
// 응답(발췌): rights=[위법계약해지권 행사(제47조)·손해배상 청구(제44·45조)·분쟁조정 신청(제33~36조)]
```
> 개인화 증거: `ledger`에 위반이 없으면(무혐의) `rights`가 빈 배열로 접힌다 — 모두에게 동일 답변이 아님.

## #7 `general_guidance` — 비법률 일반 민원 안내
트리아지(#0)가 `general`로 분류한 사건에서만 호출. 규정 판정 없이 사용자 상황에 맞춘 실질 안내.
- **출력** `GeneralGuidance`: `answer`, `steps[]`, `self_service`, `contact`, `escalation_hint`
- **안전망**: 안내 중 법률 소지가 보이면 `escalation_hint`에 정식 민원 전환 안내를 채운다.
```bash
curl -X POST localhost:8000/api/skills/general-guidance -H "Content-Type: application/json" \
  -d '{"facts":"이체한도 변경 절차와 OTP 재발급 방법이 궁금합니다."}'
```

## 색인 `chunk_label` — 일상어 라벨 *(오프라인)*
`build_index.py`가 코퍼스 청크마다 붙이는 파생 라벨. 문서의 법률어("채무불이행 손해배상")와 민원인 생활어("돈 떼였어요") 비대칭을 색인 때 메운다.
- **출력** `ChunkLabels`: `issue_summary`, `keywords[]`, `everyday_questions[]`
