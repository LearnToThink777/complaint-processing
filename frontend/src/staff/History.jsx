import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading, Badge, OutcomeBadge, Gauge } from '../components.jsx'

export default function History() {
  const [query, setQuery] = useState('')
  const { loading, data } = useAsync(() => api.staffHistory(), [])
  if (loading || !data) return <Loading />

  return (
    <div>
      <div className="page-head">
        <h1>고객 이력 조회</h1>
        <p>고객별 과거 민원 이력과 이번 판정의 일관성을 확인하세요.</p>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <div className="row gap8">
          <input
            className="chip-select"
            style={{ flex: 1, maxWidth: 340 }}
            placeholder="고객명 또는 고객번호 입력"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn primary">검색</button>
          <div style={{ marginLeft: 'auto' }} className="fg2">
            고객명 <strong style={{ color: 'var(--fg)' }}>{data.customer}</strong>
            <span className="muted" style={{ marginLeft: 8 }}>(고객번호: {data.customer_no})</span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="panel-head"><h2>과거 민원 이력</h2></div>
        <table className="table">
          <thead>
            <tr>
              <th>사건번호</th>
              <th>접수일</th>
              <th>유형</th>
              <th>판정 결과</th>
              <th>처리 결과</th>
              <th>반복 패턴</th>
              <th>일관성 점수 <span className="muted" style={{ fontWeight: 400 }}>(이번 판정 대비)</span></th>
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
                <td>{r.repeat ? <Badge tone="bad">{r.repeat}</Badge> : <span className="muted">-</span>}</td>
                <td><Gauge value={r.consistency} label="점" /></td>
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
