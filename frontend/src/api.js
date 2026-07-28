// API 클라이언트 — /api/* 라이브 호출을 우선 시도하고, 실패하면 내장 폴백으로.
// (기존 viewer.html 의 "API 우선 → 정적 폴백" 패턴을 그대로 계승한다.)
import { FALLBACK } from './fallback.js'

// ---- 토큰 ------------------------------------------------------------------
// 로그인은 '차단'이 아니라 '신원 판별'용이다 — 토큰이 없어도 모든 화면이 그대로 동작하고,
// 서버가 시드 계정으로 응답한다. 토큰이 있으면 그 사람 기준으로 바뀐다.

const TOKEN_KEY = 'cp.access'
const REFRESH_KEY = 'cp.refresh'
const USER_KEY = 'cp.user'

export const auth = {
  token: () => localStorage.getItem(TOKEN_KEY),
  user: () => {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
  },
  save: ({ access_token, refresh_token, user_type, name }) => {
    localStorage.setItem(TOKEN_KEY, access_token)
    if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token)
    localStorage.setItem(USER_KEY, JSON.stringify({ user_type, name }))
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
  },
}

// 인증 오류는 네트워크 장애와 구분해야 한다 — 아래 폴백 규칙이 이 타입에 의존한다.
export class AuthError extends Error {
  constructor(message) {
    super(message)
    this.name = 'AuthError'
  }
}

// 토큰이 만료·위조된 경우. 화면마다 에러를 그리게 하면 처리를 빠뜨린 화면이 무한 스피너에
// 걸리므로(useAsync 의 error 를 안 보는 화면이 많다) 한 곳에서 알리고 로그인으로 보낸다.
// 조용히 비로그인으로 강등하지는 않는다 — 그러면 왜 남의 이름으로 보이는지 알 수 없다.
export const AUTH_EXPIRED_EVENT = 'cp:auth-expired'

function authFailure(detail) {
  auth.clear()
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail }))
  return new AuthError(detail)
}

function headers(extra) {
  const h = { Accept: 'application/json', ...extra }
  const t = auth.token()
  if (t) h.Authorization = `Bearer ${t}`
  return h
}

// access 토큰이 만료되면 refresh 로 한 번만 재발급하고 원 요청을 재시도한다.
// 재발급도 실패하면 토큰을 버린다 — 남겨 두면 매 요청이 401 을 맞는다.
async function tryRefresh() {
  const rt = localStorage.getItem(REFRESH_KEY)
  if (!rt) return false
  try {
    const res = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!res.ok) throw new Error('refresh 실패')
    const j = await res.json()
    localStorage.setItem(TOKEN_KEY, j.access_token)
    return true
  } catch {
    auth.clear()
    return false
  }
}

async function request(path, init, { retry = true } = {}) {
  const res = await fetch(path, { ...init, headers: headers(init && init.headers) })
  if (res.status === 401 && retry && (await tryRefresh())) {
    return request(path, init, { retry: false })
  }
  return res
}

async function detailOf(res) {
  try {
    const j = await res.json()
    if (j.detail) return j.detail
  } catch { /* 본문이 JSON 이 아닐 수 있다 */ }
  return `HTTP ${res.status}`
}

async function get(path, fallbackKey) {
  let res
  try {
    res = await request(path, { method: 'GET' })
  } catch (err) {
    // fetch 자체가 실패 = 서버에 닿지 못함. 이때만 폴백이 정당하다.
    if (fallbackKey && FALLBACK[fallbackKey] !== undefined) {
      console.warn(`[api] ${path} 연결 실패 → 폴백(${fallbackKey}) 사용:`, err.message)
      return structuredClone(FALLBACK[fallbackKey])
    }
    throw err
  }
  if (res.ok) return res.json()
  // 401 은 폴백으로 덮지 않는다. 예전엔 여기서도 폴백이 나가서, 토큰이 만료돼도
  // '서버 연결 실패' 가짜 데이터가 조용히 보였다 — 로그인이 풀린 걸 알 방법이 없었다.
  if (res.status === 401) {
    throw authFailure(await detailOf(res))
  }
  if (fallbackKey && FALLBACK[fallbackKey] !== undefined) {
    console.warn(`[api] ${path} 실패(HTTP ${res.status}) → 폴백(${fallbackKey}) 사용`)
    return structuredClone(FALLBACK[fallbackKey])
  }
  throw new Error(await detailOf(res))
}

async function post(path, body, fallbackKey) {
  let res
  try {
    res = await request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (err) {
    if (fallbackKey && FALLBACK[fallbackKey]) {
      console.warn(`[api] POST ${path} 연결 실패 → 폴백 사용:`, err.message)
      return FALLBACK[fallbackKey](body)
    }
    throw err
  }
  if (res.ok) return res.json()
  if (res.status === 401) {
    throw authFailure(await detailOf(res))
  }
  if (fallbackKey && FALLBACK[fallbackKey]) {
    console.warn(`[api] POST ${path} 실패(HTTP ${res.status}) → 폴백 사용`)
    return FALLBACK[fallbackKey](body)
  }
  throw new Error(await detailOf(res))
}

// 상태를 바꾸는 호출(판정 수정·중재 요청 등) — 폴백 없이 서버 결과만. 실패 시 서버가 준
// detail 을 그대로 예외 메시지로 올려 화면이 이유를 보여줄 수 있게 한다.
async function mutate(path, method, body) {
  const res = await request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    if (res.status === 401) {
      throw authFailure(await detailOf(res))
    }
    throw new Error(await detailOf(res))
  }
  // 204 No Content(로그아웃 등)는 본문이 없다 — res.json() 이 터지므로 빈 객체로.
  if (res.status === 204) return {}
  return res.json()
}

// 라이브(실제 LLM) 호출 — 폴백 없이 실제 서버 결과만. 실패 시 예외를 던진다.
async function live(path, body) {
  const res = await request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    if (res.status === 401) {
      throw authFailure(await detailOf(res))
    }
    throw new Error(await detailOf(res))
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
  // 인증 — 민원인·직원 공통 창구. 성공하면 토큰을 저장하고 이후 모든 호출에 실린다.
  login: async (email, password) => {
    const r = await post('/api/auth/login', { email, password })
    auth.save(r)
    return r
  },
  logout: async () => {
    try { await mutate('/api/auth/logout', 'POST', {}) } catch { /* 토큰 정리는 무조건 한다 */ }
    auth.clear()
  },
  authMe: () => get('/api/auth/me'),

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
  // 사건 종결 — 사람이 내린 결정(accepted|partial|rejected)을 남긴다. 응답은 갱신된 사건 상세.
  // 판정이 안 끝난 항목이 남아 있으면 서버가 409(상세의 can_close 로 미리 막는다).
  staffCloseCase: (id, outcome, note = '') =>
    mutate(`/api/staff/cases/${id}/close`, 'POST', { outcome, note }),
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
  staffSetNotification: (key, enabled) =>
    mutate('/api/staff/me/notifications', 'PATCH', { key, enabled }),
  // 민원인
  complainantHome: () => get('/api/complainant/home', 'complainantHome'),
  // 진행현황은 사건 단위 — 사건번호를 주면 그 민원의 처리 기록을 연다(없으면 최근 사건).
  complainantProgress: (caseId) =>
    get(`/api/complainant/progress${qs({ case: caseId })}`, 'complainantProgress'),
  complainantHistory: () => get('/api/complainant/history', 'complainantHistory'),
  complainantMe: () => get('/api/complainant/me', 'complainantMe'),
  // 알림 설정 저장 — 예전엔 토글이 화면 상태만 바꾸고 아무 곳에도 남지 않았다.
  complainantSetNotification: (key, enabled) =>
    mutate('/api/complainant/me/notifications', 'PATCH', { key, enabled }),
  complainantProductTypes: () => get('/api/complainant/product-types', 'complainantProductTypes'),
  // 민원인이 자기 사건에 협상·중재를 요청 / 그 내역 조회.
  complainantRequestMediation: (reason, caseId) =>
    mutate(`/api/complainant/mediation/request${qs({ case: caseId })}`, 'POST', { reason }),
  complainantMediation: (caseId) => get(`/api/complainant/mediation${qs({ case: caseId })}`),
  // 접수 전 AI 쟁점 분석 — 폴백 없이 실제 서버 결과만(LLM 필요). 실패 시 예외 → 화면이 안내.
  analyzeComplaint: (product_type, facts) => live('/api/complainant/analyze', { product_type, facts }),
  submitComplaint: (body) => post('/api/complainant/complaints', body, 'submitComplaint'),
}
