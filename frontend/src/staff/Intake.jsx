import { useEffect, useState } from 'react'
import { api, liveApi, PROVIDERS } from '../api.js'
import { useAsync, Loading, Badge, ProviderSelect, LiveTag } from '../components.jsx'

// 접수 목록의 유형 → 검색 질의로 쓸 사실관계(라이브 검토계획 생성 입력).
const FACTS_BY_CASE = {
  'C-2024-05130': '안정추구형으로 분류된 개인 고객에게 원금 비보장 고위험 ELS를 판매. 원금손실 위험 고지가 불충분했고, 판매 녹취 일부 누락 및 서명 불일치.',
}

export default function Intake() {
  const { loading, data: cases } = useAsync(() => api.staffIntake(), [])
  const [selected, setSelected] = useState(null)
  const [plan, setPlan] = useState(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [approved, setApproved] = useState(false)

  // 라이브(실제 LLM) 상태
  const [provider, setProvider] = useState('mlapi-mini')
  const [live, setLive] = useState(null) // {items, classification, reasoning, ms}
  const [liveRunning, setLiveRunning] = useState(false)
  const [liveError, setLiveError] = useState(null)

  useEffect(() => {
    if (cases && cases.length && !selected) setSelected(cases[0].case_id)
  }, [cases, selected])

  useEffect(() => {
    if (!selected) return
    setPlanLoading(true)
    setApproved(false)
    setLive(null)
    setLiveError(null)
    api.staffChecklistPlan(selected).then((p) => {
      setPlan(p)
      setPlanLoading(false)
    })
  }, [selected])

  const runLive = async () => {
    if (!selected) return
    const sel = cases.find((c) => c.case_id === selected)
    const facts = FACTS_BY_CASE[selected] || `${sel?.type} 관련 민원. 사실관계를 검토한다.`
    setLiveRunning(true)
    setLiveError(null)
    setLive(null)
    const t0 = performance.now()
    try {
      const res = await liveApi.checklistPlan(facts, 'ELS mis-selling', provider)
      setLive({ ...res, ms: Math.round(performance.now() - t0) })
    } catch (e) {
      setLiveError(String(e.message || e))
    } finally {
      setLiveRunning(false)
    }
  }

  if (loading || !cases) return <Loading />

  // 라이브 결과가 있으면 그걸, 없으면 시드 계획을 렌더
  const shownItems = live?.items ?? plan?.items ?? []

  return (
    <div>
      <div className="page-head">
        <h1>사건접수</h1>
        <p>신규 이관된 사건 목록입니다. 사건을 선택하면 AI 자동 검토계획을 확인할 수 있어요.</p>
      </div>

      <div className="split">
        <div className="card">
          <div className="panel-head">
            <h2>신규 이관 사건</h2>
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
            {live ? <LiveTag provider={provider} providers={PROVIDERS} ms={live.ms} /> : <span className="badge muted">데모 데이터</span>}
          </div>
          <div className="panel-pad">
            {/* 라이브 실행 컨트롤 */}
            <div className="live-bar">
              <ProviderSelect value={provider} onChange={setProvider} providers={PROVIDERS} />
              <button className="btn primary" onClick={runLive} disabled={liveRunning}>
                {liveRunning ? '실제 AI 검토 중…' : '⚡ 실제 AI로 검토계획 생성'}
              </button>
            </div>

            {liveRunning && (
              <div className="live-progress">
                <span className="spinner" /> 실제 LLM이 사건 사실관계를 읽고 검토 항목을 도출하는 중… (수십 초 소요)
              </div>
            )}
            {liveError && <div className="alert bad" style={{ marginBottom: 12 }}>⚠ 실제 호출 실패: {liveError}</div>}

            {planLoading && !live ? (
              <Loading label="검토계획 불러오는 중…" />
            ) : (
              <>
                {(live?.reasoning || plan?.reasoning) && (
                  <p className="muted" style={{ fontSize: 12.5, marginTop: 4, marginBottom: 14 }}>
                    {live ? `분류: ${live.classification} · ` : ''}
                    {live?.reasoning || plan?.reasoning}
                  </p>
                )}
                {shownItems.map((it, i) => (
                  <div key={i} className="checklist-item">
                    <span className={`check-box ${approved ? 'checked' : ''}`}>{approved ? '✓' : ''}</span>
                    <span className="check-item-name">{it.item}</span>
                    <span className="law-tag">{it.law}</span>
                  </div>
                ))}
                <button
                  className="btn primary block"
                  style={{ marginTop: 16 }}
                  onClick={() => setApproved(true)}
                  disabled={approved}
                >
                  {approved ? '✓ 검토계획 승인됨' : '검토계획 승인'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
