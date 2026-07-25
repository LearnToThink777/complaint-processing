// API 클라이언트 — /api/* 라이브 호출을 우선 시도하고, 실패하면 내장 폴백으로.
// (기존 viewer.html 의 "API 우선 → 정적 폴백" 패턴을 그대로 계승한다.)
import { FALLBACK } from './fallback.js'

async function get(path, fallbackKey) {
  try {
    const res = await fetch(path, { headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } catch (err) {
    if (fallbackKey && FALLBACK[fallbackKey] !== undefined) {
      console.warn(`[api] ${path} 실패 → 폴백(${fallbackKey}) 사용:`, err.message)
      return structuredClone(FALLBACK[fallbackKey])
    }
    throw err
  }
}

async function post(path, body, fallbackKey) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } catch (err) {
    if (fallbackKey && FALLBACK[fallbackKey]) {
      console.warn(`[api] POST ${path} 실패 → 폴백 사용:`, err.message)
      return FALLBACK[fallbackKey](body)
    }
    throw err
  }
}

// 상태를 바꾸는 호출(판정 수정·중재 요청 등) — 폴백 없이 서버 결과만. 실패 시 서버가 준
// detail 을 그대로 예외 메시지로 올려 화면이 이유를 보여줄 수 있게 한다.
async function mutate(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      if (j.detail) detail = j.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

// 라이브(실제 LLM) 호출 — 폴백 없이 실제 서버 결과만. 실패 시 예외를 던진다.
async function live(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      if (j.detail) detail = j.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

// 실제 파이프라인 스킬(기존 백엔드 /api/skills/*)을 그대로 호출한다.
// provider 기본은 gpt-5-mini(mlapi-mini). 화면에서 gpt-5-nano(mlapi-nano)로 전환 가능.
export const liveApi = {
  checklistPlan: (facts, product_en, provider = 'mlapi-mini') =>
    live('/api/skills/checklist-plan', {
      facts,
      product_en,
      options: { use_llm: true, provider, retrieval: true, critic: false },
    }),
  similarCases: (product_en, due_date, facts, provider = 'mlapi-mini') =>
    live('/api/skills/similar-cases', {
      product_en,
      due_date,
      facts,
      options: { use_llm: true, provider, retrieval: true, critic: false },
    }),
  verdict: (item_no, item, law, facts, provider = 'mlapi-mini') =>
    live('/api/skills/verdict', {
      item_no,
      item,
      law,
      facts,
      options: { use_llm: true, provider, retrieval: false, critic: false },
    }),
  disclosure: (item_no, verdict, remaining, provider = 'mlapi-mini') =>
    live('/api/skills/disclosure', {
      item_no,
      verdict,
      remaining,
      options: { use_llm: true, provider, retrieval: false, critic: false },
    }),
}

export const PROVIDERS = [
  { key: 'mlapi-mini', label: 'GPT-5 mini', note: '실제 · ~20초' },
  { key: 'mlapi-nano', label: 'GPT-5 nano', note: '실제 · 빠름' },
]

export const api = {
  // 직원
  staffSummary: () => get('/api/staff/summary', 'staffSummary'),
  staffIntake: () => get('/api/staff/intake', 'staffIntake'),
  // 검토계획은 서버 폴링이 핵심(plan_generating → plan_ready). 폴백을 주지 않아야
  // 서버 정상 중 정적 픽스처로 새어 '생성 중'이 안 뜨는 일을 막는다.
  staffChecklistPlan: (id) => get(`/api/staff/checklist-plan/${id}`),
  staffGeneratePlan: (id) => live(`/api/staff/checklist-plan/${id}/generate`, {}),
  staffApprovePlan: (id) => live(`/api/staff/checklist-plan/${id}/approve`, {}),
  // 처리현황 — 처리 단계 사건 목록(승인 이후). 직원이 골라 원장을 본다.
  staffCases: () => get('/api/staff/cases', 'staffCases'),
  staffCase: (id) => get(`/api/staff/cases/${id}`, 'staffCase'),
  // 판정(원장) 생성 트리거 — 실제 LLM. 폴백 없이 서버 결과만(실패 시 예외).
  staffGenerateVerdict: (id) => live(`/api/staff/cases/${id}/verdict`, {}),
  // AI 판정을 담당자가 직접 고쳐 확정 / AI 원안으로 되돌리기. 응답은 갱신된 사건 상세.
  staffOverrideVerdict: (id, seq, body) =>
    mutate(`/api/staff/cases/${id}/ledger/${seq}`, 'PATCH', body),
  staffRevertVerdict: (id, seq) =>
    mutate(`/api/staff/cases/${id}/ledger/${seq}/revert`, 'POST', {}),
  // 협상·중재(사건 스코프) — 요청 / 세션 개시 / 한 발언 진행. 응답은 중재 내역 payload.
  staffMediation: (id) => get(`/api/staff/cases/${id}/mediation`),
  staffRequestMediation: (id, reason) =>
    mutate(`/api/staff/cases/${id}/mediation/request`, 'POST', { reason }),
  staffStartMediation: (id, provider = 'mlapi-nano') =>
    mutate(`/api/staff/cases/${id}/mediation/start`, 'POST', { use_llm: true, provider }),
  staffMediationTurn: (id) => mutate(`/api/staff/cases/${id}/mediation/turn`, 'POST', {}),
  // 이 사건의 접수 내용으로 유사사례 실검색. 서버 없으면 폴백.
  staffCaseSimilar: (id) => get(`/api/staff/cases/${id}/similar-cases`, 'staffCaseSimilar'),
  // 이중공개를 청중별로 분리 게시(민원인용→진행현황, 직원용→직원 화면). 서버 없으면 폴백 스텁.
  publishDisclosure: (body) => post('/api/staff/disclosure/publish', body, 'publishDisclosure'),
  staffHistory: (customer) =>
    get(`/api/staff/history${customer ? `?customer=${encodeURIComponent(customer)}` : ''}`, 'staffHistory'),
  staffMe: () => get('/api/staff/me', 'staffMe'),
  // 민원인
  complainantHome: () => get('/api/complainant/home', 'complainantHome'),
  complainantProgress: () => get('/api/complainant/progress', 'complainantProgress'),
  complainantHistory: () => get('/api/complainant/history', 'complainantHistory'),
  complainantMe: () => get('/api/complainant/me', 'complainantMe'),
  complainantProductTypes: () => get('/api/complainant/product-types', 'complainantProductTypes'),
  // 민원인이 자기 사건에 협상·중재를 요청 / 그 내역 조회.
  complainantRequestMediation: (reason) =>
    mutate('/api/complainant/mediation/request', 'POST', { reason }),
  complainantMediation: () => get('/api/complainant/mediation'),
  // 접수 전 AI 쟁점 분석 — 폴백 없이 실제 서버 결과만(LLM 필요). 실패 시 예외 → 화면이 안내.
  analyzeComplaint: (product_type, facts) => live('/api/complainant/analyze', { product_type, facts }),
  submitComplaint: (body) => post('/api/complainant/complaints', body, 'submitComplaint'),
}
