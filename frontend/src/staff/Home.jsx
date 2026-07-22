import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading, OutcomeBadge } from '../components.jsx'

const TONE_COLOR = {
  info: 'var(--info)',
  good: 'var(--good)',
  warn: 'var(--warn)',
  bad: 'var(--bad)',
}

export default function Home() {
  const nav = useNavigate()
  const { loading, data } = useAsync(() => api.staffSummary(), [])
  if (loading || !data) return <Loading />
  const { summary, recent } = data

  return (
    <div>
      <div className="page-head">
        <h1>홈</h1>
        <p>{summary.team} · {summary.officer}님, 오늘 처리할 사건을 확인하세요.</p>
      </div>

      <div className="stat-grid">
        {summary.cards.map((c) => (
          <div key={c.key} className="card stat-card">
            <div className="stat-label">
              <span className="stat-dot" style={{ background: TONE_COLOR[c.tone] }} />
              {c.label}
            </div>
            <div className="stat-value" style={{ color: c.tone === 'bad' ? 'var(--bad)' : 'var(--fg)' }}>
              {c.value}
              <span className="unit">{c.unit}</span>
            </div>
            <div className="stat-hint">{c.hint}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="panel-head">
          <h2>최근 처리한 사건</h2>
          <span className="link-more" onClick={() => nav('/staff/status')} style={{ cursor: 'pointer' }}>
            더보기 &rsaquo;
          </span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>사건번호</th>
              <th>고객명</th>
              <th>유형</th>
              <th>판정 결과</th>
              <th>처리일시</th>
              <th>담당자</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((r) => (
              <tr key={r.case_id} className="clickable" onClick={() => nav('/staff/status')}>
                <td className="mono">{r.case_id}</td>
                <td style={{ fontWeight: 600 }}>{r.customer}</td>
                <td>{r.type}</td>
                <td><OutcomeBadge value={r.outcome} /></td>
                <td className="fg2">{r.processed_at}</td>
                <td className="fg2">{r.officer}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
