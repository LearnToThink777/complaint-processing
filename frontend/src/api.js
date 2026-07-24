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
  staffCase: (id) => get(`/api/staff/cases/${id}`, 'staffCase'),
  staffHistory: (customer) =>
    get(`/api/staff/history${customer ? `?customer=${encodeURIComponent(customer)}` : ''}`, 'staffHistory'),
  staffMe: () => get('/api/staff/me', 'staffMe'),
  // 민원인
  complainantHome: () => get('/api/complainant/home', 'complainantHome'),
  complainantProgress: () => get('/api/complainant/progress', 'complainantProgress'),
  complainantHistory: () => get('/api/complainant/history', 'complainantHistory'),
  complainantMe: () => get('/api/complainant/me', 'complainantMe'),
  complainantProductTypes: () => get('/api/complainant/product-types', 'complainantProductTypes'),
  // 접수 전 AI 쟁점 분석 — 폴백 없이 실제 서버 결과만(LLM 필요). 실패 시 예외 → 화면이 안내.
  analyzeComplaint: (product_type, facts) => live('/api/complainant/analyze', { product_type, facts }),
  submitComplaint: (body) => post('/api/complainant/complaints', body, 'submitComplaint'),
}
