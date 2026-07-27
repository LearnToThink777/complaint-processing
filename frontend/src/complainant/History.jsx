import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'
import Zikimi from '../Zikimi.jsx'

const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'open', label: '진행중' },
  { key: 'closed', label: '종결' },
]
const TYPE_ICON = (t) =>
  t.includes('ELS') ? '📈' : t.includes('펀드') ? '💹' : t.includes('대출') ? '💳' : t.includes('보험') ? '🛡️' : '📄'

function fmtAt(at) {
  if (!at) return null
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return null
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`
}

// 이력 — 내가 접수한 민원 목록. 카드를 누르면 그 민원의 진행현황(처리 기록)으로 들어간다.
// 예전에는 유형·접수일만 적힌 정적 카드여서, 민원 하나하나가 어떻게 처리됐는지 볼 방법이
// 없었다(진행현황은 가장 최근 민원 하나만 열렸다).
export default function History() {
  const nav = useNavigate()
  const [filter, setFilter] = useState('all')
  const { loading, data } = useAsync(() => api.complainantHistory(), [])
  if (loading || !data) return <Loading />

  const rows = data.filter((r) =>
    filter === 'all' ? true : filter === 'closed' ? r.status === 'closed' : r.status !== 'closed')

  return (
    <div>
      <div className="cx-topbar"><h1>이력</h1></div>
      <p className="cx-case-sub" style={{ margin: '0 0 4px' }}>
        접수한 민원 {data.length}건이에요. 민원을 누르면 접수부터 지금까지의 처리 기록을 볼 수 있어요.
      </p>

      <div className="cx-filter" style={{ marginTop: 12 }}>
        {FILTERS.map((f) => (
          <button key={f.key} className={filter === f.key ? 'on' : ''} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="cx-card" style={{ textAlign: 'center', padding: '26px 18px' }}>
          <Zikimi pose="search" size={68} style={{ margin: '0 auto' }} />
          <div className="cx-case-title" style={{ marginTop: 8 }}>해당하는 민원이 없어요</div>
          <div className="cx-case-sub" style={{ marginTop: 4 }}>다른 조건을 선택해 보세요.</div>
        </div>
      ) : (
        <div className="cx-grid">
          {rows.map((r) => {
            const last = fmtAt(r.last_activity_at)
            return (
              <button
                key={r.case_id}
                className="cx-card cx-hist-card"
                onClick={() => nav(`/app/progress?case=${encodeURIComponent(r.case_id)}`)}
              >
                <div className="cx-hist-icon">{TYPE_ICON(r.type)}</div>
                <div className="cx-hist-main">
                  <div className="cx-case-title" style={{ fontSize: 13.5 }}>{r.type}</div>
                  <div className="cx-case-sub">접수번호 {r.case_id} · 접수일 {r.intake_date}</div>

                  {/* 지금 몇 번째 단계까지 왔는지 — 카드에서 바로 보이게. */}
                  <div className="cx-hist-steps" aria-label={`${r.step_total}단계 중 ${r.step + 1}단계`}>
                    {Array.from({ length: r.step_total || 5 }, (_, i) => (
                      <i key={i} className={i < r.step ? 'done' : i === r.step ? 'on' : ''} />
                    ))}
                    <span>{r.step_title}</span>
                  </div>

                  <div className="cx-case-sub" style={{ marginTop: 4 }}>
                    {r.status === 'closed'
                      ? `종결 · ${r.closed_at || '완료'}`
                      : `예상 완료일 ${r.expected_completion || '-'} (D-${r.days_left ?? 0})`}
                  </div>
                  <div className="cx-hist-foot">
                    <span>📄 처리 기록 {r.entry_count ?? 0}건</span>
                    {r.mediation_status_ko && <span>🤝 {r.mediation_status_ko}</span>}
                    {last && <span>최근 {last}</span>}
                  </div>
                </div>
                <div className="cx-hist-right">
                  <span className={`badge ${r.status === 'closed' ? 'good' : 'info'}`}>{r.status_ko}</span>
                  <span className="cx-hist-arrow">›</span>
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
