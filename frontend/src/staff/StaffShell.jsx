import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import './staff.css'

// 업무 흐름 순서 그대로 — 접수 → 처리 → 중재 → 이력. 협상·중재는 예전처럼 외부 콘솔로
// 튀어 나가지 않고 이 메뉴 안에서 열린다(사건 목록·진행·기록이 모두 한 화면에 있다).
const NAV = [
  { to: '/staff', end: true, icon: '🏠', label: '홈' },
  { to: '/staff/intake', icon: '📥', label: '사건접수' },
  { to: '/staff/status', icon: '📊', label: '처리현황' },
  { to: '/staff/mediation', icon: '🤝', label: '협상·중재' },
  { to: '/staff/history', icon: '🗂️', label: '고객 이력' },
  { to: '/staff/mypage', icon: '👤', label: '마이페이지' },
]

export default function StaffShell() {
  const nav = useNavigate()
  return (
    <div className="staff-root">
      <aside className="staff-sidebar">
        <button className="staff-brand" onClick={() => nav('/staff')}>
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
