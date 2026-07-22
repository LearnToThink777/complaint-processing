import { Routes, Route, Navigate } from 'react-router-dom'
import Landing from './Landing.jsx'
import DemoTour from './DemoTour.jsx'

import StaffShell from './staff/StaffShell.jsx'
import StaffHome from './staff/Home.jsx'
import StaffIntake from './staff/Intake.jsx'
import StaffStatus from './staff/Status.jsx'
import StaffHistory from './staff/History.jsx'
import StaffMyPage from './staff/MyPage.jsx'

import AppShell from './complainant/AppShell.jsx'
import CxHome from './complainant/Home.jsx'
import CxNew from './complainant/NewComplaint.jsx'
import CxProgress from './complainant/Progress.jsx'
import CxHistory from './complainant/History.jsx'
import CxMyPage from './complainant/MyPage.jsx'

export default function App() {
  return (
    <>
      <DemoTour />
      <Routes>
      <Route path="/" element={<Landing />} />

      {/* 직원 데스크탑 대시보드 */}
      <Route path="/staff" element={<StaffShell />}>
        <Route index element={<StaffHome />} />
        <Route path="intake" element={<StaffIntake />} />
        <Route path="status" element={<StaffStatus />} />
        <Route path="history" element={<StaffHistory />} />
        <Route path="mypage" element={<StaffMyPage />} />
      </Route>

      {/* 민원인 모바일 앱 */}
      <Route path="/app" element={<AppShell />}>
        <Route index element={<CxHome />} />
        <Route path="new" element={<CxNew />} />
        <Route path="progress" element={<CxProgress />} />
        <Route path="history" element={<CxHistory />} />
        <Route path="mypage" element={<CxMyPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
