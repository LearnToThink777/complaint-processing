import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading, Toggle } from '../components.jsx'

export default function MyPage() {
  const nav = useNavigate()
  const { loading, data } = useAsync(() => api.staffMe(), [])
  const [noti, setNoti] = useState(null)
  if (loading || !data) return <Loading />
  const notifications = noti ?? data.notifications
  const acc = data.account

  return (
    <div>
      <div className="page-head">
        <h1>마이페이지</h1>
        <p>계정 정보와 알림 설정, 최근 활동 내역을 관리하세요.</p>
      </div>

      <div className="split">
        {/* 좌: 계정 정보 + 알림 설정 */}
        <div style={{ display: 'grid', gap: 18 }}>
          <div className="card">
            <div className="panel-head"><h2>계정 정보</h2></div>
            <div className="panel-pad">
              <div className="kv"><span className="k">이름</span><span className="v">{acc.name} {acc.verified && '✅'}</span></div>
              <div className="kv"><span className="k">소속</span><span className="v">{acc.team}</span></div>
              <div className="kv"><span className="k">직급</span><span className="v">{acc.rank}</span></div>
              <div className="kv"><span className="k">이메일</span><span className="v">{acc.email}</span></div>
              <div className="kv"><span className="k">휴대폰</span><span className="v">{acc.phone}</span></div>
              <button className="btn block" style={{ marginTop: 14 }}>정보 수정</button>
            </div>
          </div>

          <div className="card">
            <div className="panel-head"><h2>알림 설정</h2></div>
            <div className="panel-pad" style={{ paddingTop: 4 }}>
              {notifications.map((n, i) => (
                <div key={n.key} className="noti-row">
                  <div className="noti-label">{n.label}</div>
                  <Toggle
                    on={n.enabled}
                    onChange={(v) => {
                      const next = notifications.map((x, j) => (j === i ? { ...x, enabled: v } : x))
                      setNoti(next)
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 우: 계정 관리 + 활동 로그 + 세션 */}
        <div style={{ display: 'grid', gap: 18 }}>
          <div className="card">
            <div className="panel-head"><h2>계정 관리</h2></div>
            <div className="panel-pad row gap12">
              <button className="btn" style={{ flex: 1 }}>🔒 비밀번호 변경</button>
              <button className="btn danger" style={{ flex: 1 }} onClick={() => nav('/')}>↪ 로그아웃</button>
            </div>
          </div>

          <div className="card">
            <div className="panel-head"><h2>최근 활동 로그</h2></div>
            <table className="table">
              <thead>
                <tr><th>일시</th><th>활동</th><th>상세</th><th>IP</th></tr>
              </thead>
              <tbody>
                {data.activity_log.map((a, i) => (
                  <tr key={i}>
                    <td className="fg2 mono">{a.at}</td>
                    <td style={{ fontWeight: 600 }}>{a.action}</td>
                    <td className="fg2">{a.detail}</td>
                    <td className="mono">{a.ip}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="panel-head"><h2>세션 정보</h2></div>
            <div className="panel-pad">
              <div className="kv"><span className="k">현재 접속 IP</span><span className="v mono">{data.session.current_ip}</span></div>
              <div className="kv"><span className="k">최근 접속</span><span className="v">{data.session.last_login}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
