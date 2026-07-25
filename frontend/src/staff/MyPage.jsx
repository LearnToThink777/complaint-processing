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

          {/* 활동 로그는 실제 처리 이력(stage_events)에서 온다 — 예전엔 '자료 다운로드
              재협상_안_20240521.pdf' 같은 있지도 않은 활동이 박혀 있었다. IP 열은 로그인·
              세션 추적 기능이 없어 뺐다(빈 값을 채워 넣지 않는다). */}
          <div className="card">
            <div className="panel-head">
              <h2>최근 처리 활동</h2>
              <span className="muted" style={{ fontSize: 12 }}>{data.activity_log.length}건</span>
            </div>
            {data.activity_log.length === 0 ? (
              <div className="panel-pad"><p className="muted" style={{ fontSize: 13 }}>아직 기록된 처리 활동이 없습니다.</p></div>
            ) : (
              <table className="table">
                <thead>
                  <tr><th>일시</th><th>활동</th><th>사건번호</th></tr>
                </thead>
                <tbody>
                  {data.activity_log.map((a, i) => (
                    <tr key={i}>
                      <td className="fg2 mono">{a.at}</td>
                      <td style={{ fontWeight: 600 }}>{a.action}</td>
                      <td className="fg2 mono">{a.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
