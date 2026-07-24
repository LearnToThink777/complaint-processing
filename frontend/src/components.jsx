import { useEffect, useState } from 'react'

// 비동기 로더 훅 — 로딩/에러/데이터 상태를 한 번에. reload()로 수동 재요청 가능.
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setState({ loading: true, data: null, error: null })
    fn()
      .then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((error) => alive && setState({ loading: false, data: null, error }))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { ...state, reload: () => setTick((t) => t + 1) }
}

export function Loading({ label = '불러오는 중…' }) {
  return <div className="spin">{label}</div>
}

// 상태/톤 배지. solid=강조(색 채움).
export function Badge({ tone = 'muted', solid = false, children }) {
  return <span className={`badge ${tone} ${solid ? 'solid' : ''}`}>{children}</span>
}

// 결정/판정 배지 — {ko, tone} 형태의 객체를 받는다.
export function OutcomeBadge({ value }) {
  if (!value) return <span className="muted">-</span>
  return <Badge tone={value.tone}>{value.ko}</Badge>
}

// 원형 게이지(일관성 점수). value 0~100.
export function Gauge({ value = 0, label }) {
  const tone = value >= 85 ? 'var(--good)' : value >= 75 ? 'var(--warn)' : 'var(--bad)'
  return (
    <div className="gauge">
      <div className="gauge-track" style={{ '--v': value, '--gc': tone, position: 'relative' }}>
        <span className="gauge-val">{value}</span>
      </div>
      {label && <span className="muted" style={{ fontSize: 12 }}>{label}</span>}
    </div>
  )
}

// 토글 스위치(제어형이 아니라 시연용 로컬 상태 토글).
export function Toggle({ on, onChange }) {
  return <button className={`toggle ${on ? 'on' : ''}`} onClick={() => onChange?.(!on)} aria-pressed={on} />
}

// LLM provider 선택 드롭다운(라이브 실행용).
export function ProviderSelect({ value, onChange, providers }) {
  return (
    <select className="chip-select" value={value} onChange={(e) => onChange(e.target.value)} title="실제 LLM provider">
      {providers.map((p) => (
        <option key={p.key} value={p.key}>
          {p.label} · {p.note}
        </option>
      ))}
    </select>
  )
}

// 라이브 실행 상태 태그(모델·소요초).
export function LiveTag({ provider, providers, ms }) {
  const label = providers?.find((p) => p.key === provider)?.label || provider
  return (
    <span className="badge good" title="실제 LLM 호출 결과">
      ⚡ 실제 호출 · {label}
      {ms != null ? ` · ${(ms / 1000).toFixed(1)}s` : ''}
    </span>
  )
}
