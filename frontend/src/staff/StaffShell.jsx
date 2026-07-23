import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import './staff.css'

const NAV = [
  { to: '/staff', end: true, icon: '🏠', label: '홈' },
  { to: '/staff/intake', icon: '📥', label: '사건접수' },
  { to: '/staff/status', icon: '📊', label: '처리현황' },
  { to: '/staff/history', icon: '🗂️', label: '이력' },
  { to: '/staff/mypage', icon: '👤', label: '마이페이지' },
]

export default function StaffShell() {
  const nav = useNavigate()
  return (
    <div className="staff-root">
      <aside className="staff-sidebar">
        <button className="staff-brand" onClick={() => nav('/')}>
          <span className="staff-brand-logo">🛡️</span>
          <span className="staff-brand-text">
            금융 민원
            <br />
            처리 시스템
          </span>
        </button>
        <nav className="staff-nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `staff-nav-item ${isActive ? 'active' : ''}`}>
              <span className="staff-nav-icon">{n.icon}</span>
              <span>{n.label}</span>
            </NavLink>
          ))}
          <a href="/mediation.html" className="staff-nav-item">
            <span className="staff-nav-icon">🤝</span>
            <span>협상·중재</span>
            <span className="staff-nav-ext">↗</span>
          </a>
        </nav>
        <div className="staff-user">
          <div className="staff-avatar">홍</div>
          <div className="staff-user-meta">
            <strong>홍길동</strong>
            <span>준법감시팀</span>
          </div>
        </div>
      </aside>
      <main className="staff-main">
        <Outlet />
      </main>
    </div>
  )
}
