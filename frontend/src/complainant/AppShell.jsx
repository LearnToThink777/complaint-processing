import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import Zikimi from '../Zikimi.jsx'
import { api, auth } from '../api.js'
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
  const who = auth.user()
  return (
    <div className="cx-web">
      <header className="cx-appbar">
        <div className="cx-appbar-inner">
          <button className="cx-brand" onClick={() => nav('/app')}>
            <span className="cx-brand-logo"><Zikimi pose="shield" size={28} /></span>
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
          {/* 포털 홈(랜딩)이 민원인↔직원을 오가는 유일한 통로다 — 각 포털 안에는 반대편으로
              가는 길이 없어서, 상단에 항상 보이는 출구를 둔다. */}
          <div className="cx-appbar-actions">
            <button className="cx-portal-home" onClick={() => nav('/')} title="포털 홈 — 직원 화면으로 전환할 수 있어요">
              <Zikimi pose="base" size={22} />
              <span>포털 홈</span>
            </button>
            {/* 예전엔 첫 화면으로 이동만 하고 토큰은 남았다. 로그인 상태면 실제로 로그아웃하고,
                안 했으면 로그인 화면으로 안내한다(무엇을 누른 건지 헷갈리지 않게 라벨도 바꾼다). */}
            {who ? (
              <button className="cx-exit" onClick={async () => { await api.logout(); nav('/login') }}>
                로그아웃 ({who.name})
              </button>
            ) : (
              <button className="cx-exit" onClick={() => nav('/login')}>로그인</button>
            )}
          </div>
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
