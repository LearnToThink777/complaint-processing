import { useState } from 'react'
import { api, liveApi, PROVIDERS } from '../api.js'
import { useAsync, Loading, Badge, ProviderSelect, LiveTag } from '../components.jsx'

const CRITIC_TONE = { PASS: 'good', ESCALATE: 'warn', BLOCK: 'bad' }

// 라이브 이중공개 입력으로 쓸 대표 판정(#1 적합성). 실제 LLM이 이 판정을 두 독자용으로 작문한다.
const SAMPLE_VERDICT = {
  code: '금소법 §17',
  verdict: '위반',
  ko: '적합성원칙 위반 확인',
  detail: '안정추구형 고객에게 고위험 ELS 판매 — 투자성향과 상품 위험도 불일치',
}

export default function Status() {
  const { loading, data } = useAsync(() => api.staffCase('C-2024-05130'), [])
  const [provider, setProvider] = useState('mlapi-mini')

  // 라이브 상태
  const [sim, setSim] = useState(null)
  const [simRun, setSimRun] = useState(false)
  const [simErr, setSimErr] = useState(null)
  const [disc, setDisc] = useState(null)
  const [discRun, setDiscRun] = useState(false)
  const [discErr, setDiscErr] = useState(null)

  if (loading || !data) return <Loading />

  const runSimilar = async () => {
    setSimRun(true); setSimErr(null); setSim(null)
    const t0 = performance.now()
    try {
      const r = await liveApi.similarCases('ELS mis-selling', data.due_date, 'ELS 불완전판매 손해배상 적합성 설명의무', provider)
      setSim({ ...r, ms: Math.round(performance.now() - t0) })
    } catch (e) { setSimErr(String(e.message || e)) } finally { setSimRun(false) }
  }

  const runDisclosure = async () => {
    setDiscRun(true); setDiscErr(null); setDisc(null)
    const t0 = performance.now()
    try {
      const r = await liveApi.disclosure(1, SAMPLE_VERDICT, 5, provider)
      setDisc({ ...r, ms: Math.round(performance.now() - t0) })
    } catch (e) { setDiscErr(String(e.message || e)) } finally { setDiscRun(false) }
  }

  return (
    <div>
      <div className="page-head">
        <h1>처리현황</h1>
        <p>사건 원장의 항목별 판정과 AI 신뢰도 검증 결과를 확인하세요.</p>
      </div>

      <div className="case-head">
        <span className="case-id">{data.case_id}</span>
        <Badge tone="info">{data.type}</Badge>
        <Badge tone="warn">처리중</Badge>
        <div className="row gap8" style={{ marginLeft: 'auto' }}>
          <ProviderSelect value={provider} onChange={setProvider} providers={PROVIDERS} />
          <button className="btn" onClick={() => window.open('/mediation.html', '_blank')}>🤝 협상·중재 콘솔 열기</button>
        </div>
      </div>

      <div className="split">
        <div style={{ display: 'grid', gap: 18 }}>
          {/* 사건 원장 */}
          <div className="card">
            <div className="panel-head">
              <h2>사건 원장 (판정 결과)</h2>
              <div className="row gap8">
                <Badge tone="good" solid>PASS {data.critic_summary.PASS}</Badge>
                <Badge tone="warn" solid>ESCALATE {data.critic_summary.ESCALATE}</Badge>
                <Badge tone="bad" solid>BLOCK {data.critic_summary.BLOCK}</Badge>
              </div>
            </div>
            <div style={{ padding: '4px 0' }}>
              <div className="ledger-row" style={{ padding: '8px 20px', color: 'var(--muted)', fontSize: 12 }}>
                <span className="ledger-item">검토 항목</span>
                <span className="ledger-verdict">판정 결과</span>
                <span style={{ width: 96, textAlign: 'center' }}>AI 신뢰도 검증</span>
              </div>
              {data.ledger.map((row, i) => (
                <div key={i} className="ledger-row">
                  <div className="ledger-item">
                    <div className="li-name">{row.item}</div>
                    <span className="li-code">{row.code}</span>
                  </div>
                  <div className="ledger-verdict">{row.verdict}</div>
                  <div style={{ width: 96, textAlign: 'center' }}>
                    <Badge tone={CRITIC_TONE[row.critic]} solid>{row.critic}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 이중 공개 — 라이브 */}
          <div className="card">
            <div className="panel-head">
              <h2>이중 공개 (민원인용 / 감독원용)</h2>
              {disc ? <LiveTag provider={provider} providers={PROVIDERS} ms={disc.ms} /> : <span className="badge muted">미생성</span>}
            </div>
            <div className="panel-pad">
              <div className="live-bar">
                <button className="btn primary" onClick={runDisclosure} disabled={discRun}>
                  {discRun ? '실제 생성 중…' : '⚡ 실제 AI로 이중 공개 생성'}
                </button>
                <span className="muted" style={{ fontSize: 12 }}>같은 판정(적합성 위반)을 두 독자용으로 분리 작문</span>
              </div>
              {discRun && <div className="live-progress"><span className="spinner" /> 실제 LLM이 민원인용·감독원용 문구를 작성하는 중…</div>}
              {discErr && <div className="alert bad">⚠ 실제 호출 실패: {discErr}</div>}
              {disc && (
                <div style={{ display: 'grid', gap: 10 }}>
                  <div className="disc-box u">
                    <div className="disc-h">🙂 민원인용 · {disc.complainant_title}</div>
                    <div className="disc-b">{disc.complainant_body}</div>
                  </div>
                  <div className="disc-box r">
                    <div className="disc-h">🏛️ 감독원용 · {disc.supervisor_title}</div>
                    <div className="disc-b">{disc.supervisor_body}</div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 재협상 자료 */}
          <div className="card">
            <div className="panel-head"><h2>재협상 자료 검토</h2></div>
            <div className="panel-pad">
              {data.renegotiation.attachments.map((f) => (
                <div key={f.name} className="file-row" style={{ marginBottom: 10 }}>
                  <span className="file-icon">📄</span>
                  <div className="file-meta">
                    <div className="file-name">{f.name}</div>
                    <div className="file-sub">{f.size} · 업로드 {f.uploaded_at}</div>
                  </div>
                  <button className="btn">열기</button>
                </div>
              ))}
              <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>{data.renegotiation.note}</p>
            </div>
          </div>
        </div>

        {/* 우측 */}
        <div style={{ display: 'grid', gap: 18 }}>
          {data.over_deadline_risk && (
            <div className="alert bad">
              <span style={{ fontSize: 18 }}>⏱️</span>
              <div>
                <div className="alert-title">기한까지 {data.days_left}일 남음 ({data.due_date} 마감)</div>
                <div style={{ marginTop: 2 }}>예상 완료일이 처리 기한을 초과할 위험이 있습니다.</div>
              </div>
            </div>
          )}

          {/* 유사 과거사례 — 라이브 실검색 */}
          <div className="card">
            <div className="panel-head">
              <h2>유사 과거사례</h2>
              {sim ? <LiveTag provider={provider} providers={PROVIDERS} ms={sim.ms} /> : <span className="badge muted">데모 데이터</span>}
            </div>
            <div className="panel-pad">
              <div className="live-bar">
                <button className="btn primary block" onClick={runSimilar} disabled={simRun}>
                  {simRun ? '실제 검색·분석 중…' : '⚡ 유사사례 실제 검색·분석 (임베딩 RAG)'}
                </button>
              </div>
              {simRun && <div className="live-progress"><span className="spinner" /> 코퍼스 임베딩 검색 + 실제 LLM 분석 중…</div>}
              {simErr && <div className="alert bad">⚠ 실제 호출 실패: {simErr}</div>}

              {sim ? (
                <>
                  {sim.cases.map((c, i) => (
                    <div key={i} className="sim-card">
                      <div className="sim-top">
                        <span className="sim-id">{c.case}</span>
                        <Badge tone="info">{c.business_days}영업일</Badge>
                      </div>
                    </div>
                  ))}
                  <div className={`alert ${sim.over_deadline_risk ? 'bad' : 'warn'}`} style={{ marginTop: 8 }}>
                    <span>🧭</span>
                    <div>
                      <div className="alert-title">예상 완료 {sim.estimated_completion} {sim.over_deadline_risk ? '· 기한 초과 위험' : ''}</div>
                      <div style={{ marginTop: 2, fontSize: 12.5 }}>{sim.reasoning}</div>
                    </div>
                  </div>
                </>
              ) : (
                data.similar_cases.map((s) => (
                  <div key={s.case_id} className="sim-card">
                    <div className="sim-top">
                      <span className="sim-id">{s.case_id}</span>
                      <Badge tone={s.similarity >= 90 ? 'good' : s.similarity >= 80 ? 'info' : 'muted'}>유사도 {s.similarity}%</Badge>
                    </div>
                    <div className="sim-title">{s.title}</div>
                    <div className="sim-foot">{s.closed_at} · {s.outcome_ko}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
