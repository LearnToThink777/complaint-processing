import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'

export default function Progress() {
  const { loading, data } = useAsync(() => api.complainantProgress(), [])
  if (loading || !data) return <Loading />

  const stepClass = (i) => {
    if (i < data.current) return 'done'
    if (i === data.current) return 'current'
    return 'pending'
  }

  return (
    <div>
      <div className="cx-topbar"><h1>진행현황</h1></div>

      <div className="cx-dday-banner">
        <span className="icon">⏱️</span>
        <div style={{ flex: 1 }}>
          <div className="label">예상 완료일까지 {data.days_left}일 남았어요</div>
          <div className="big">D-{data.days_left}</div>
        </div>
        {data.risk && <span className="badge warn">지연 위험</span>}
      </div>

      <div className="cx-card" style={{ marginTop: 14 }}>
        <div className="cx-case-title">{data.title}</div>
        <div className="cx-case-sub">접수일 {data.intake_date}</div>
      </div>

      <div className="cx-timeline">
        {data.steps.map((s, i) => (
          <div key={s.no} className={`cx-step ${stepClass(i)}`}>
            <div className="cx-step-dot">{i < data.current ? '✓' : s.no}</div>
            <div className="cx-step-body">
              <div className="cx-step-head">
                <span className="cx-step-title">{String(s.no).padStart(2, '0')} {s.title}</span>
                {s.date && <span className="cx-step-date">{s.date}</span>}
              </div>
              {(i <= data.current) && <div className="cx-step-desc">{s.body}</div>}
              {i > data.current && <div className="cx-step-desc">{s.body}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
