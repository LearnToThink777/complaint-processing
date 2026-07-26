import { Routes, Route, Navigate } from 'react-router-dom'
import Landing from './Landing.jsx'

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
  return (
    <Routes>
      <Route path="/" element={<Landing />} />

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
