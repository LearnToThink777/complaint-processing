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
              <th>처리 상태</th>
              <th>판정 원장</th>
              <th>최근 갱신</th>
              <th>담당자</th>
            </tr>
          </thead>
          <tbody>
            {recent.length === 0 && (
              <tr><td colSpan={7} className="muted" style={{ padding: 16 }}>
                아직 처리 단계에 들어간 사건이 없습니다. <b>사건접수</b>에서 검토계획을 승인해 보세요.
              </td></tr>
            )}
            {recent.map((r) => (
              <tr key={r.case_id} className="clickable" onClick={() => nav('/staff/status')}>
                <td className="mono">{r.case_id}</td>
                <td style={{ fontWeight: 600 }}>{r.customer}</td>
                <td>{r.type}</td>
                <td><OutcomeBadge value={r.outcome} /></td>
                {/* 판정 라벨 분포(예: '위반 2 · 해당없음 1') — 판정 전이면 비어 있다. */}
                <td className="fg2">{r.verdict_digest || <span className="muted">판정 전</span>}</td>
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
