import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading, OutcomeBadge } from '../components.jsx'

export default function History() {
  const [query, setQuery] = useState('')
  // 조회할 고객명(검색 버튼을 눌러야 반영 — 입력할 때마다 요청하지 않는다).
  const [customer, setCustomer] = useState(null)
  const { loading, data } = useAsync(() => api.staffHistory(customer), [customer])
  if (loading) return <Loading />
  if (!data) return <div className="card"><div className="panel-pad"><p className="muted">이력을 찾을 수 없습니다.</p></div></div>

  return (
    <div>
      <div className="page-head">
        <h1>고객 이력 조회</h1>
        <p>같은 고객이 과거에 어떤 민원을 접수했고 각각 어떤 판정이 나왔는지 확인하세요.</p>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <form className="row gap8" onSubmit={(e) => { e.preventDefault(); setCustomer(query.trim() || null) }}>
          <input
            className="chip-select"
            style={{ flex: 1, maxWidth: 340 }}
            placeholder="고객명 입력"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn primary" type="submit">검색</button>
          <div style={{ marginLeft: 'auto' }} className="fg2">
            고객명 <strong style={{ color: 'var(--fg)' }}>{data.customer}</strong>
            <span className="muted" style={{ marginLeft: 8 }}>({data.rows.length}건)</span>
          </div>
        </form>
      </div>

      <div className="card">
        <div className="panel-head"><h2>과거 민원 이력</h2></div>
        <table className="table">
          <thead>
            {/* '일관성 점수'는 계산 규칙 없이 숫자만 그럴듯했던 지표라 뺐다. 대신 그 사건의
                실제 판정 원장 요약(위반 n · 해당없음 m)을 보여준다. */}
            <tr>
              <th>사건번호</th>
              <th>접수일</th>
              <th>유형</th>
              <th>처리 상태</th>
              <th>판정 원장</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.case_id}>
                <td className="mono">{r.case_id}</td>
                <td className="fg2">{r.intake_date}</td>
                <td>{r.type}</td>
                <td><OutcomeBadge value={r.outcome} /></td>
                <td className="fg2">{r.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.repeat_pattern && (
        <div className="alert bad" style={{ marginTop: 18 }}>
          <span style={{ fontSize: 18 }}>⚠️</span>
          <div>
            <div className="alert-title">반복 신고 패턴 감지</div>
            <div style={{ marginTop: 2 }}>
              동일 유형(<strong>{data.repeat_pattern.type}</strong>) 민원이 총 <strong>{data.repeat_pattern.count}회</strong> 접수되었습니다.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
