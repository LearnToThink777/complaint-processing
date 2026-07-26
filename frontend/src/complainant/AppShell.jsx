import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import './app.css'

// 상단 탭은 민원인이 자주 쓰는 다섯 가지로 고정한다. 협상·중재는 별도 탭이 아니라
// 진행현황 안의 진입 카드에서 열린다 — 내 민원의 맥락에서만 의미가 있는 기능이라서.
const TABS = [
  { to: '/app', end: true, icon: '🏠', label: '홈' },
  { to: '/app/new', icon: '📝', label: '민원접수' },
  { to: '/app/progress', icon: '📈', label: '진행현황' },
  { to: '/app/history', icon: '📋', label: '이력' },
  { to: '/app/mypage', icon: '👤', label: '마이페이지' },
]

export default function AppShell() {
  const nav = useNavigate()
  return (
    <div className="cx-web">
      <header className="cx-appbar">
        <div className="cx-appbar-inner">
          <button className="cx-brand" onClick={() => nav('/app')}>
            <span className="cx-brand-logo">🛡️</span>
            <span className="cx-brand-text">금융지킴이</span>
          </button>
          <nav className="cx-topnav">
            {TABS.map((t) => (
              <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `cx-tab ${isActive ? 'active' : ''}`}>
                <span className="cx-tab-icon">{t.icon}</span>
                <span className="cx-tab-label">{t.label}</span>
              </NavLink>
            ))}
          </nav>
          <button className="cx-exit" onClick={() => nav('/')}>로그아웃</button>
        </div>
      </header>
      <main className="cx-main">
        <div className="cx-container">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
