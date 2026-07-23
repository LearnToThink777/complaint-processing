import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'

const NOTICE_ICON = { megaphone: '📢', document: '📄' }

export default function Home() {
  const nav = useNavigate()
  const { loading, data } = useAsync(() => api.complainantHome(), [])
  if (loading || !data) return <Loading />
  const c = data.current_case

  return (
    <div>
      <div className="cx-topbar">
        <h1>금융지킴이</h1>
        <span style={{ fontSize: 18 }}>🔔</span>
      </div>

      <div className="cx-hero">
        <div className="wave">👋 안녕하세요</div>
        <h2>{data.greeting_name}님</h2>
        <p>오늘도 금융지킴이가 함께할게요</p>
        <span className="mascot">🛡️</span>
      </div>

      <div className="cx-section">
        <h3>현재 진행 중인 민원</h3>
        <span className="more" onClick={() => nav('/app/history')}>전체보기 &rsaquo;</span>
      </div>

      <div className="cx-card cx-progress-card" onClick={() => nav('/app/progress')} style={{ cursor: 'pointer' }}>
        <div className="cx-case-row">
          <div className="cx-case-icon">📈</div>
          <div style={{ flex: 1 }}>
            <div className="cx-case-title">{c.title}</div>
            <div className="cx-case-sub">접수일 {c.intake_date}</div>
          </div>
          <span className="badge info">{c.status_ko}</span>
        </div>
        <div className="row between" style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <span className="cx-case-sub">예상 완료일 {c.expected_completion}</span>
          <span className="cx-dday">D-{c.days_left}</span>
        </div>
      </div>

      <div className="cx-section">
        <h3>최근 안내</h3>
      </div>
      <div className="cx-grid">
        {data.notices.map((n, i) => (
          <div key={i} className="cx-notice">
            <div className="cx-notice-icon">{NOTICE_ICON[n.icon] || 'ℹ️'}</div>
            <div style={{ flex: 1 }}>
              <div className="n-title">
                <span>{n.title}</span>
                <span className="n-at">{n.at}</span>
              </div>
              <div className="n-body">{n.body}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
