import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading, Badge } from '../components.jsx'

// 검토계획 상태 → 화면 배지.
const PLAN_BADGE = {
  pending: { ko: '생성 전', tone: 'muted' },
  generating: { ko: 'AI 생성 중', tone: 'info' },
  ready: { ko: '검토계획 대기', tone: 'warn' },
  approved: { ko: '승인됨', tone: 'good' },
  failed: { ko: '생성 실패', tone: 'bad' },
}

export default function Intake() {
  const { loading, data: cases, reload } = useAsync(() => api.staffIntake(), [])
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

  if (loading || !cases) return <Loading />

  const status = plan?.status
  const items = plan?.items ?? []
  const approved = status === 'approved'
  const badge = PLAN_BADGE[status] || PLAN_BADGE.pending

  return (
    <div>
      <div className="page-head">
        <h1>사건접수</h1>
        <p>신규 이관·제출된 사건 목록입니다. 사건을 선택하면 AI 자동 검토계획을 확인·승인할 수 있어요.</p>
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
            <h2>🤖 AI 자동 검토계획</h2>
            <Badge tone={badge.tone}>{badge.ko}</Badge>
          </div>
          <div className="panel-pad">
            {error && <div className="alert bad" style={{ marginBottom: 12 }}>⚠ {error}</div>}

            {planLoading && !plan ? (
              <Loading label="검토계획 불러오는 중…" />
            ) : status === 'generating' ? (
              <div className="live-progress">
                <span className="spinner" /> 실제 LLM이 사건 사실을 읽고 법령·결정례를 검색해 검토 항목을 도출하는 중… (수십 초 소요)
              </div>
            ) : status === 'pending' ? (
              <>
                <p className="muted" style={{ fontSize: 12.5, marginBottom: 14 }}>
                  아직 검토계획이 없습니다. 실제 AI로 이 사건의 검토 항목을 생성하세요.
                </p>
                <button className="btn primary block" onClick={runGenerate} disabled={busy}>
                  {busy ? '요청 중…' : '⚡ AI 검토계획 생성'}
                </button>
              </>
            ) : (
              <>
                {plan?.reasoning && (
                  <p className="muted" style={{ fontSize: 12.5, marginTop: 4, marginBottom: 14 }}>
                    분류: {plan.classification} · {plan.reasoning}
                    {plan.duration_ms != null && (
                      <span> · 생성 {(plan.duration_ms / 1000).toFixed(1)}초
                        {plan.provider === 'fallback' ? ' (폴백)' : ''}</span>
                    )}
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
                    법률 검토 항목이 없습니다(일반 안내 트랙일 수 있어요).
                  </p>
                )}
                <button
                  className="btn primary block"
                  style={{ marginTop: 16 }}
                  onClick={runApprove}
                  disabled={approved || busy}
                >
                  {approved ? '✓ 검토계획 승인됨 (검토 중)' : busy ? '처리 중…' : '검토계획 승인'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
