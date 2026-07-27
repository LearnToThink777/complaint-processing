import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'
import Zikimi from '../Zikimi.jsx'

const NOTICE_ICON = { megaphone: '📢', document: '📄' }

export default function Home() {
  const nav = useNavigate()
  const { loading, data } = useAsync(() => api.complainantHome(), [])
  if (loading || !data) return <Loading />
  const c = data.current_case

  return (
    <div>
      <div className="cx-hero">
        <div className="wave">👋 안녕하세요</div>
        <h2>{data.greeting_name}님</h2>
        <p>오늘도 금융지킴이가 함께할게요</p>
        <span className="mascot"><Zikimi pose="wave" size={84} /></span>
      </div>

      <div className="cx-section">
        <h3>현재 진행 중인 민원</h3>
        {c && <span className="more" onClick={() => nav('/app/history')}>전체보기 &rsaquo;</span>}
      </div>

      {c ? (
        <div
          className="cx-card cx-progress-card"
          onClick={() => nav(`/app/progress?case=${encodeURIComponent(c.case_id)}`)}
          style={{ cursor: 'pointer' }}
        >
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
      ) : (
        // 진행 중인 민원이 없을 때 빈 화면을 남기지 않는다 — 다음에 할 일을 바로 안내한다.
        <div className="cx-card" style={{ textAlign: 'center', padding: '26px 18px' }}>
          <Zikimi pose="base" size={72} style={{ margin: '0 auto' }} />
          <div className="cx-case-title" style={{ marginTop: 8 }}>진행 중인 민원이 없어요</div>
          <div className="cx-case-sub" style={{ marginTop: 4 }}>
            금융상품 이용 중 불편한 점이 있으면 민원을 접수해 주세요.
          </div>
          <button className="cx-btn primary" style={{ marginTop: 14 }} onClick={() => nav('/app/new')}>
            민원 접수하기
          </button>
        </div>
      )}

      <div className="cx-section">
        <h3>최근 안내</h3>
      </div>
      {data.notices.length === 0 ? (
        <div className="cx-card">
          <div className="cx-case-sub">아직 도착한 안내가 없어요. 담당자 안내가 오면 여기에 표시해 드릴게요.</div>
        </div>
      ) : (
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
      )}
    </div>
  )
}
