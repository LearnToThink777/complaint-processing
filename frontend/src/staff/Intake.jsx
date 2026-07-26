import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading, Badge } from '../components.jsx'

// 검토계획 상태 → 화면 배지.
const PLAN_BADGE = {
  pending: { ko: '수립 전', tone: 'muted' },
  generating: { ko: 'AI 수립 중', tone: 'info' },
  ready: { ko: '승인 대기', tone: 'warn' },
  approved: { ko: '승인 완료', tone: 'good' },
  failed: { ko: '수립 실패', tone: 'bad' },
}

export default function Intake() {
  const { data: cases, reload } = useAsync(() => api.staffIntake(), [])
  const [selected, setSelected] = useState(null)
  const [plan, setPlan] = useState(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [busy, setBusy] = useState(false) // 생성/승인 요청 진행 중
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    if (cases && cases.length && !selected) setSelected(cases[0].case_id)
  }, [cases, selected])

  // 선택된 사건의 검토계획을 불러오고, 생성 중이면 폴링한다.
  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const fetchPlan = async (id) => {
    try {
      const p = await api.staffChecklistPlan(id)
      setPlan(p)
      return p
    } catch (e) {
      setError(String(e.message || e))
      return null
    }
  }

  useEffect(() => {
    stopPoll()
    setPlan(null)
    setError(null)
    if (!selected) return
    setPlanLoading(true)
    fetchPlan(selected).then((p) => {
      setPlanLoading(false)
      if (p && p.status === 'generating') startPolling(selected)
    })
    return stopPoll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])

  const startPolling = (id) => {
    stopPoll()
    pollRef.current = setInterval(async () => {
      const p = await fetchPlan(id)
      if (!p || p.status !== 'generating') stopPoll()
    }, 3000)
  }

  const runGenerate = async () => {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      const p = await api.staffGeneratePlan(selected)
      setPlan(p)
      if (p.status === 'generating') startPolling(selected)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const runApprove = async () => {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      const p = await api.staffApprovePlan(selected)
      setPlan(p)
      reload() // 목록에서 검토 착수한 사건이 접수 목록을 빠지도록 갱신
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  if (!cases) return <Loading />

  const status = plan?.status
  const items = plan?.items ?? []
  const approved = status === 'approved'
  const badge = PLAN_BADGE[status] || PLAN_BADGE.pending

  return (
    <div>
      <div className="page-head">
        <h1>사건접수</h1>
        <p>새로 접수·이관된 사건입니다. 사건을 선택하면 AI가 세운 검토계획을 확인하고 승인할 수 있습니다.</p>
      </div>

      <div className="split">
        <div className="card">
          <div className="panel-head">
            <h2>신규 사건</h2>
            <span className="muted" style={{ fontSize: 12.5 }}>{cases.length}건</span>
          </div>
          <table className="table">
            <thead>
              <tr><th>사건번호</th><th>고객명</th><th>유형</th><th>접수일</th></tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr
                  key={c.case_id}
                  className={`clickable ${selected === c.case_id ? 'selected' : ''}`}
                  onClick={() => setSelected(c.case_id)}
                >
                  <td className="mono">{c.case_id}</td>
                  <td style={{ fontWeight: 600 }}>{c.customer}</td>
                  <td>
                    {c.type}{' '}
                    <Badge tone={c.track === 'general' ? 'muted' : 'info'}>
                      {c.track === 'general' ? '일반' : '법률'}
                    </Badge>
                  </td>
                  <td className="fg2">{c.intake_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="panel-head">
            <h2>AI 검토계획</h2>
            <Badge tone={badge.tone}>{badge.ko}</Badge>
          </div>
          <div className="panel-pad">
            {error && <div className="alert bad" style={{ marginBottom: 12 }}>⚠ {error}</div>}

            {planLoading && !plan ? (
              <Loading label="검토계획 불러오는 중…" />
            ) : status === 'generating' ? (
              <div className="live-progress">
                <span className="spinner" /> AI가 사건 내용을 읽고 관련 법령·결정례를 찾아 검토 항목을 정리하고 있습니다. 잠시만 기다려 주세요.
              </div>
            ) : status === 'pending' ? (
              <>
                <p className="muted" style={{ fontSize: 12.5, marginBottom: 14 }}>
                  아직 검토계획이 없습니다. 이 사건에서 확인해야 할 검토 항목을 AI가 정리하도록 요청하세요.
                </p>
                <button className="btn primary block" onClick={runGenerate} disabled={busy}>
                  {busy ? '요청 중…' : 'AI 검토계획 세우기'}
                </button>
              </>
            ) : (
              <>
                {plan?.reasoning && (
                  <p className="muted" style={{ fontSize: 12.5, marginTop: 4, marginBottom: 14 }}>
                    분류: {plan.classification} · {plan.reasoning}
                  </p>
                )}
                {items.map((it, i) => (
                  <div key={i} className="checklist-item">
                    <span className={`check-box ${it.status === 'approved' ? 'checked' : ''}`}>
                      {it.status === 'approved' ? '✓' : ''}
                    </span>
                    <span className="check-item-name">{it.item}</span>
                    <span className="law-tag">{it.law}</span>
                  </div>
                ))}
                {items.length === 0 && (
                  <p className="muted" style={{ fontSize: 12.5 }}>
                    법률 검토가 필요한 항목이 없습니다. 일반 안내로 처리할 수 있는 사건입니다.
                  </p>
                )}
                <button
                  className="btn primary block"
                  style={{ marginTop: 16 }}
                  onClick={runApprove}
                  disabled={approved || busy}
                >
                  {approved ? '✓ 승인 완료 — 처리현황에서 이어서 진행' : busy ? '처리 중…' : '검토계획 승인'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
