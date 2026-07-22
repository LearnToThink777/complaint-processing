import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'

const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'reviewing', label: '진행중' },
  { key: 'closed', label: '종결' },
]
const TYPE_ICON = (t) =>
  t.includes('ELS') ? '📈' : t.includes('펀드') ? '💹' : t.includes('대출') ? '💳' : t.includes('보험') ? '🛡️' : '📄'

export default function History() {
  const [filter, setFilter] = useState('all')
  const { loading, data } = useAsync(() => api.complainantHistory(), [])
  if (loading || !data) return <Loading />

  const rows = data.filter((r) => filter === 'all' || r.status === filter)

  return (
    <div>
      <div className="cx-topbar"><h1>이력</h1></div>

      <div className="cx-filter" style={{ marginTop: 12 }}>
        {FILTERS.map((f) => (
          <button key={f.key} className={filter === f.key ? 'on' : ''} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      {rows.map((r) => (
        <div key={r.case_id} className="cx-card cx-hist-card">
          <div className="cx-hist-icon">{TYPE_ICON(r.type)}</div>
          <div style={{ flex: 1 }}>
            <div className="cx-case-title" style={{ fontSize: 13.5 }}>{r.type}</div>
            <div className="cx-case-sub">접수일 {r.intake_date}</div>
            <div className="cx-case-sub" style={{ marginTop: 4 }}>
              {r.status === 'closed' ? `종결 · ${r.closed_at} 완료` : `검토 중 · 예상 완료일 ${r.expected_completion}`}
            </div>
          </div>
          <span className={`badge ${r.status === 'closed' ? 'good' : 'info'}`}>{r.status_ko}</span>
        </div>
      ))}
    </div>
  )
}
