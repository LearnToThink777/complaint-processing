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

// 쿼리스트링 조립 — 빈 값·false 는 빼고 보낸다(서버 기본값을 덮지 않게).
function qs(params) {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '' || v === false) continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// 파이프라인 스킬(백엔드 /api/skills/*) 직접 호출.
// 어떤 모델로 도느냐는 운영 설정이지 사용자가 고를 값이 아니다 — 화면에서 모델 선택을
// 없애고 여기서 한 곳으로 고정한다.
const MODEL = 'mlapi-mini'

export const liveApi = {
  disclosure: (item_no, verdict, remaining) =>
    live('/api/skills/disclosure', {
      item_no,
      verdict,
      remaining,
      options: { use_llm: true, provider: MODEL, retrieval: false, critic: false },
    }),
}

export const api = {
  // 직원
  staffSummary: () => get('/api/staff/summary', 'staffSummary'),
  staffIntake: () => get('/api/staff/intake', 'staffIntake'),
  // 검토계획은 서버 폴링이 핵심(plan_generating → plan_ready). 폴백을 주지 않아야
  // 서버 정상 중 정적 픽스처로 새어 '생성 중'이 안 뜨는 일을 막는다.
  staffChecklistPlan: (id) => get(`/api/staff/checklist-plan/${id}`),
  staffGeneratePlan: (id) => live(`/api/staff/checklist-plan/${id}/generate`, {}),
  staffApprovePlan: (id) => live(`/api/staff/checklist-plan/${id}/approve`, {}),
  // 처리현황 — 처리 단계 사건 목록(승인 이후). 검색·정렬은 서버가 한다(목록이 길어져도
  // 화면이 전부 받아 놓고 흉내 내지 않게). params: {q, status, due_soon, sort, order}
  staffCases: (params = {}) => get(`/api/staff/cases${qs(params)}`, 'staffCases'),
  staffCase: (id) => get(`/api/staff/cases/${id}`, 'staffCase'),
  // 판정(원장) 생성 트리거 — 실제 LLM. 폴백 없이 서버 결과만(실패 시 예외).
  staffGenerateVerdict: (id) => live(`/api/staff/cases/${id}/verdict`, {}),
  // AI 판정을 담당자가 직접 고쳐 확정 / AI 원안으로 되돌리기. 응답은 갱신된 사건 상세.
  staffOverrideVerdict: (id, seq, body) =>
    mutate(`/api/staff/cases/${id}/ledger/${seq}`, 'PATCH', body),
  staffRevertVerdict: (id, seq) =>
    mutate(`/api/staff/cases/${id}/ledger/${seq}/revert`, 'POST', {}),
  // 협상·중재 콘솔 — 사건별 중재 진행 목록(콘솔 좌측 목록의 원천).
  staffMediations: () => get('/api/staff/mediations', 'staffMediations'),
  // 협상·중재(사건 스코프) — 요청 / 세션 개시 / 한 발언 진행. 응답은 중재 내역 payload.
  staffMediation: (id) => get(`/api/staff/cases/${id}/mediation`),
  staffRequestMediation: (id, reason) =>
    mutate(`/api/staff/cases/${id}/mediation/request`, 'POST', { reason }),
  staffStartMediation: (id) =>
    mutate(`/api/staff/cases/${id}/mediation/start`, 'POST', { use_llm: true }),
  staffMediationTurn: (id) => mutate(`/api/staff/cases/${id}/mediation/turn`, 'POST', {}),
  // 이 사건의 접수 내용으로 유사사례 실검색. 서버 없으면 폴백.
  staffCaseSimilar: (id) => get(`/api/staff/cases/${id}/similar-cases`, 'staffCaseSimilar'),
  // 이중공개를 청중별로 분리 게시(민원인용→진행현황, 직원용→직원 화면). 서버 없으면 폴백 스텁.
  publishDisclosure: (body) => post('/api/staff/disclosure/publish', body, 'publishDisclosure'),
  staffHistory: (customer) => get(`/api/staff/history${qs({ customer })}`, 'staffHistory'),
  staffMe: () => get('/api/staff/me', 'staffMe'),
  // 민원인
  complainantHome: () => get('/api/complainant/home', 'complainantHome'),
  // 진행현황은 사건 단위 — 사건번호를 주면 그 민원의 처리 기록을 연다(없으면 최근 사건).
  complainantProgress: (caseId) =>
    get(`/api/complainant/progress${qs({ case: caseId })}`, 'complainantProgress'),
  complainantHistory: () => get('/api/complainant/history', 'complainantHistory'),
  complainantMe: () => get('/api/complainant/me', 'complainantMe'),
  complainantProductTypes: () => get('/api/complainant/product-types', 'complainantProductTypes'),
  // 민원인이 자기 사건에 협상·중재를 요청 / 그 내역 조회.
  complainantRequestMediation: (reason, caseId) =>
    mutate(`/api/complainant/mediation/request${qs({ case: caseId })}`, 'POST', { reason }),
  complainantMediation: (caseId) => get(`/api/complainant/mediation${qs({ case: caseId })}`),
  // 접수 전 AI 쟁점 분석 — 폴백 없이 실제 서버 결과만(LLM 필요). 실패 시 예외 → 화면이 안내.
  analyzeComplaint: (product_type, facts) => live('/api/complainant/analyze', { product_type, facts }),
  submitComplaint: (body) => post('/api/complainant/complaints', body, 'submitComplaint'),
}
