import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading, Toggle } from '../components.jsx'

const NOTI_ICON = { progress: '📨', notice: '💬', event: '🔍' }
const MENU_ICON = { faq: '❓', support: '🎧', about: 'ℹ️' }

export default function MyPage() {
  const { loading, data } = useAsync(() => api.complainantMe(), [])
  const [noti, setNoti] = useState(null)
  if (loading || !data) return <Loading />
  const notifications = noti ?? data.notifications

  return (
    <div>
      <div className="cx-topbar">
        <h1>마이페이지</h1>
        <span style={{ fontSize: 17 }}>⚙️</span>
      </div>

      <div className="cx-profile">
        <div className="avatar">🧑</div>
        <div style={{ flex: 1 }}>
          <div className="p-name">{data.name}님 ›</div>
          <div className="p-email">{data.email}</div>
          {data.verified && <span className="cx-verified">🔒 본인 인증 완료</span>}
        </div>
      </div>

      <div className="cx-section"><h3>알림 설정</h3></div>
      <div className="cx-card">
        {notifications.map((n, i) => (
          <div key={n.key} className="cx-noti">
            <div className="n-ico">{NOTI_ICON[n.key] || '🔔'}</div>
            <div className="n-main">
              <div className="n-l">{n.label}</div>
              {n.hint && <div className="n-h">{n.hint}</div>}
            </div>
            <Toggle
              on={n.enabled}
              onChange={(v) => setNoti(notifications.map((x, j) => (j === i ? { ...x, enabled: v } : x)))}
            />
          </div>
        ))}
      </div>

      <div className="cx-section"><h3>고객 지원</h3></div>
      {data.menu.map((m) => (
        <div key={m.key} className="cx-menu-row">
          <span className="m-ico">{MENU_ICON[m.key] || '•'}</span>
          <span>{m.label}</span>
          <span className="arrow">{m.value ? <span className="muted">{m.value}</span> : '›'}</span>
        </div>
      ))}
    </div>
  )
}
