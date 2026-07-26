import { useEffect, useState } from 'react'

// 비동기 로더 훅 — 로딩/에러/데이터 상태를 한 번에. reload()로 수동 재요청 가능.
// 다시 불러오는 동안 이전 데이터를 지우지 않는다 — 목록을 갱신할 때마다 화면 전체가
// 스피너로 바뀌었다가 돌아오면(=깜빡임) 방금 무엇을 하던 중이었는지 놓치게 된다.
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setState((s) => ({ loading: true, data: s.data, error: null }))
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

// 알림 on/off 스위치.
export function Toggle({ on, onChange }) {
  return <button className={`toggle ${on ? 'on' : ''}`} onClick={() => onChange?.(!on)} aria-pressed={on} />
}

// 내용이 아직 없는 자리 — 왜 비어 있는지와 다음에 할 일을 함께 알려 준다.
export function Empty({ children }) {
  return <p className="muted" style={{ fontSize: 13, margin: 0 }}>{children}</p>
}

// 주격조사 — '분쟁조정위가' / '법원이'. 판단 주체 이름은 LLM 이 만들어 내므로 받침이
// 제각각이다. 문장에 그냥 '가'를 붙이면 '법원가'가 나온다.
export function josa(word) {
  const last = (word || '').slice(-1)
  const code = last.charCodeAt(0)
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 ? '이' : '가'
  return '이(가)'
}
