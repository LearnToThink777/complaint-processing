import { useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import Landing from './Landing.jsx'
import Login from './Login.jsx'
import { AUTH_EXPIRED_EVENT } from './api.js'

import StaffShell from './staff/StaffShell.jsx'
import StaffHome from './staff/Home.jsx'
import StaffIntake from './staff/Intake.jsx'
import StaffStatus from './staff/Status.jsx'
import StaffMediation from './staff/Mediation.jsx'
import StaffHistory from './staff/History.jsx'
import StaffMyPage from './staff/MyPage.jsx'

import AppShell from './complainant/AppShell.jsx'
import CxHome from './complainant/Home.jsx'
import CxNew from './complainant/NewComplaint.jsx'
import CxProgress from './complainant/Progress.jsx'
import CxMediation from './complainant/Mediation.jsx'
import CxHistory from './complainant/History.jsx'
import CxMyPage from './complainant/MyPage.jsx'

export default function App() {
  const nav = useNavigate()
  // 토큰이 만료·위조되면 어느 화면에 있든 로그인으로 보낸다. 화면마다 에러를 그리게 하면
  // useAsync 의 error 를 안 보는 화면(대부분)이 '불러오는 중…'에서 멈춘다.
  useEffect(() => {
    const onExpired = (e) => {
      nav('/login', { replace: true, state: { expired: e.detail || '로그인이 만료되었습니다.' } })
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [nav])

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />

      {/* 직원 포털 — 사건 처리 백오피스. 협상·중재는 여기 한 곳(콘솔)에서만 진행한다. */}
      <Route path="/staff" element={<StaffShell />}>
        <Route index element={<StaffHome />} />
        <Route path="intake" element={<StaffIntake />} />
        <Route path="status" element={<StaffStatus />} />
        <Route path="mediation" element={<StaffMediation />} />
        <Route path="history" element={<StaffHistory />} />
        <Route path="mypage" element={<StaffMyPage />} />
      </Route>

      {/* 민원인 포털 — 협상·중재는 진행현황의 진입 카드에서 이 화면으로 들어온다. */}
      <Route path="/app" element={<AppShell />}>
        <Route index element={<CxHome />} />
        <Route path="new" element={<CxNew />} />
        <Route path="progress" element={<CxProgress />} />
        <Route path="mediation" element={<CxMediation />} />
        <Route path="history" element={<CxHistory />} />
        <Route path="mypage" element={<CxMyPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
