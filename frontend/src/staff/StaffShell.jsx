import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import Zikimi from '../Zikimi.jsx'
import { auth } from '../api.js'
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
  const who = auth.user()
  return (
    <div className="staff-root">
      <aside className="staff-sidebar">
        <button className="staff-brand" onClick={() => nav('/staff')}>
          <span className="staff-brand-logo"><Zikimi pose="shield" size={30} /></span>
          <span className="staff-brand-text">
            금융 민원
            <br />
            처리 시스템
          </span>
        </button>
        {/* 직원 포털에는 지금까지 바깥으로 나가는 길이 없었다 — 포털 홈(랜딩)으로 돌아가야
            민원인 화면으로 전환할 수 있으므로 사이드바 맨 위에 출구를 둔다. */}
        <button className="staff-portal-home" onClick={() => nav('/')} title="포털 홈 — 민원인 화면으로 전환할 수 있어요">
          <Zikimi pose="base" size={22} />
          <span>포털 홈</span>
        </button>
        <nav className="staff-nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `staff-nav-item ${isActive ? 'active' : ''}`}>
              <span className="staff-nav-icon">{n.icon}</span>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        {/* 이름이 '홍길동'으로 박혀 있어서 누가 로그인해도 같은 사람으로 보였다. 로그인한
            계정을 보여주고, 로그인하지 않았으면 시연 계정임을 밝힌다(지어내지 않는다). */}
        <div className="staff-user" onClick={() => nav(who ? '/staff/mypage' : '/login')}
             role="button" title={who ? '마이페이지' : '로그인'}>
          <div className="staff-avatar">{(who?.name || '홍길동').slice(0, 1)}</div>
          <div className="staff-user-meta">
            <strong>{who?.name || '홍길동'}</strong>
            <span>{who ? '준법감시팀' : '로그인 안 함 · 시연 계정'}</span>
          </div>
        </div>
      </aside>
      <main className="staff-main">
        <Outlet />
      </main>
    </div>
  )
}
