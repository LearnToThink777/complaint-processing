import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import './app.css'

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
    <div className="cx-stage">
      <div className="cx-phone">
        <div className="cx-statusbar">
          <span>9:41</span>
          <span className="cx-exit" onClick={() => nav('/')}>✕ 시연 종료</span>
        </div>
        <div className="cx-scroll">
          <Outlet />
        </div>
        <nav className="cx-tabbar">
          {TABS.map((t) => (
            <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `cx-tab ${isActive ? 'active' : ''}`}>
              <span className="cx-tab-icon">{t.icon}</span>
              <span className="cx-tab-label">{t.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  )
}
