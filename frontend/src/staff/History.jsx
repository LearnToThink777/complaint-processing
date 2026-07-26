import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading, OutcomeBadge, Empty } from '../components.jsx'

function fmtAt(at) {
  if (!at) return '-'
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return '-'
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// 고객 이력 — 사람 단위 조회다. 처리현황(사건 단위 작업 큐)과 목적이 다르다:
// 여기서는 '이 민원인이 그동안 몇 건을, 어떤 유형으로 접수했고 각 사건이 어떻게 끝났는지'를
// 보고, 처리할 사건을 발견하면 그 사건의 처리현황으로 건너간다(행 클릭).
export default function History() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  // 조회 대상 고객은 URL 에 둔다 — 사건 상세의 '이 고객의 민원 n건' 링크로 바로 들어올 수 있게.
  const customer = params.get('customer')
  const [query, setQuery] = useState(customer || '')

  useEffect(() => { setQuery(customer || '') }, [customer])

  const { loading, data } = useAsync(() => api.staffHistory(customer), [customer])

  const search = (name) => {
    const v = (name ?? query).trim()
    setParams(v ? { customer: v } : {})
  }

  if (loading && !data) return <Loading />
  if (!data) {
    return (
      <div className="card"><div className="panel-pad">
        <Empty>접수된 사건이 없어 조회할 고객 이력이 없습니다.</Empty>
      </div></div>
    )
  }

  const s = data.summary || {}
  const candidates = (data.candidates || []).slice(0, 6)

  return (
    <div>
      <div className="page-head">
        <h1>고객 이력</h1>
        <p>
          한 민원인이 여러 건을 접수할 수 있습니다. 이 화면은 <b>사람 단위</b>로 접수 이력과 반복
          패턴을 확인하는 곳이고, 사건을 처리하는 곳은 <Link to="/staff/status">처리현황</Link>입니다.
          아래 표에서 사건을 누르면 그 사건의 처리현황으로 이동합니다.
        </p>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <form className="row gap8" style={{ flexWrap: 'wrap' }}
              onSubmit={(e) => { e.preventDefault(); search() }}>
          <input
            className="chip-select"
            style={{ flex: 1, minWidth: 200, maxWidth: 340 }}
            placeholder="고객명 입력 (일부만 입력해도 됩니다)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn primary" type="submit">검색</button>
          {customer && <button className="btn" type="button" onClick={() => setParams({})}>초기화</button>}
        </form>
        {candidates.length > 0 && (
          <div className="row gap8" style={{ flexWrap: 'wrap', marginTop: 12 }}>
            <span className="muted" style={{ fontSize: 12 }}>접수 많은 고객</span>
            {candidates.map((c) => (
              <button
                key={c.customer}
                className={`btn ${c.customer === data.customer ? 'primary' : ''}`}
                style={{ fontSize: 12, padding: '4px 10px' }}
                onClick={() => search(c.customer)}
              >
                {c.customer} {c.count}건
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 고객 요약 — 사람 단위 화면이므로 '이 사람에 대한' 숫자를 먼저 보여준다. */}
      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <div className="card stat-card">
          <div className="stat-label">조회 고객</div>
          <div className="stat-value" style={{ fontSize: 22 }}>{data.customer}</div>
          <div className="stat-hint">최근 접수 {s.last_intake || '-'}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">총 접수</div>
          <div className="stat-value">{s.total ?? 0}<span className="unit">건</span></div>
          <div className="stat-hint">첫 접수 {s.first_intake || '-'}</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">진행 중</div>
          <div className="stat-value">{s.open ?? 0}<span className="unit">건</span></div>
          <div className="stat-hint">종결 {s.closed ?? 0}건</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">접수 유형</div>
          <div className="stat-value">{s.types ?? 0}<span className="unit">종</span></div>
          <div className="stat-hint">{data.repeat_pattern ? '반복 패턴 감지됨' : '반복 패턴 없음'}</div>
        </div>
      </div>

      {data.repeat_pattern && (
        <div className="alert bad" style={{ marginBottom: 18 }}>
          <span style={{ fontSize: 18 }}>⚠️</span>
          <div>
            <div className="alert-title">반복 신고 패턴 감지</div>
            <div style={{ marginTop: 2 }}>
              동일 유형(<strong>{data.repeat_pattern.type}</strong>) 민원이 총{' '}
              <strong>{data.repeat_pattern.count}회</strong> 접수되었습니다. 같은 원인이 반복되는지,
              앞선 사건의 판정과 어긋나지 않는지 함께 확인하세요.
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="panel-head">
          <h2>접수 이력</h2>
          <span className="muted" style={{ fontSize: 12.5 }}>{data.rows.length}건 · 최신 접수순</span>
        </div>
        {data.rows.length === 0 ? (
          <div className="panel-pad"><Empty>이 고객의 접수 이력이 없습니다.</Empty></div>
        ) : (
          <div className="queue-scroll">
            {/* '일관성 점수'는 계산 규칙 없이 숫자만 그럴듯했던 지표라 뺐다. 대신 그 사건의
                실제 판정 원장 요약(위반 n · 해당없음 m)과 처리 기록 건수를 보여준다. */}
            <table className="table queue-table" style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <th>사건번호</th>
                  <th>접수일</th>
                  <th>유형</th>
                  <th>접수 경로</th>
                  <th>처리 상태</th>
                  <th>판정 결과</th>
                  <th>처리 기록</th>
                  <th>최근 처리</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr
                    key={r.case_id}
                    className="clickable"
                    onClick={() => nav(`/staff/status?case=${encodeURIComponent(r.case_id)}`)}
                    title="처리현황에서 이 사건 열기"
                  >
                    <td className="mono">{r.case_id}</td>
                    <td className="fg2">{r.intake_date}</td>
                    <td className="cell-type" title={r.type}>{r.type}</td>
                    <td className="fg2">{r.channel === 'citizen' ? '직접 접수' : '이관'}</td>
                    <td>
                      <OutcomeBadge value={r.outcome} />
                      {r.mediation_status_ko && (
                        <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>🤝 {r.mediation_status_ko}</div>
                      )}
                    </td>
                    <td className="fg2">{r.result}</td>
                    <td className="fg2">{r.event_count ?? 0}건</td>
                    <td className="fg2">{fmtAt(r.last_activity_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
