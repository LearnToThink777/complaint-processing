import { useEffect, useRef, useState } from 'react'
import { api, liveApi, PROVIDERS } from '../api.js'
import { useAsync, Loading, Badge, ProviderSelect, LiveTag } from '../components.jsx'

const CRITIC_TONE = { PASS: 'good', ESCALATE: 'warn', BLOCK: 'bad', CONFIRMED: 'info' }
const STATUS_TONE = {
  reviewing: 'info', verdict_generating: 'info', verdict: 'info', negotiating: 'warn', closed: 'good',
}

// 처리현황 — 검토계획을 승인한 사건들을 DB 에서 목록으로 받아 고르고, 그 사건의 접수 내용(SSOT)과
// AI 판정 원장·유사사례를 확인한다. (예전엔 단일 사건이 하드코딩돼 있었다.)
export default function Status() {
  const { loading, data: cases, reload } = useAsync(() => api.staffCases(), [])
  const [selected, setSelected] = useState(null)
  const [provider, setProvider] = useState('mlapi-nano')

  useEffect(() => {
    if (cases && cases.length && !cases.some((c) => c.case_id === selected)) {
      setSelected(cases[0].case_id)
    }
  }, [cases, selected])

  if (loading || !cases) return <Loading />

  return (
    <div>
      <div className="page-head">
        <h1>처리현황</h1>
        <p>검토계획을 승인한 사건을 선택하면 접수 내용과 AI 판정 결과(사건 원장)를 확인할 수 있어요.</p>
      </div>

      <div className="split">
        <div className="card">
          <div className="panel-head">
            <h2>처리 중 사건</h2>
            <span className="muted" style={{ fontSize: 12.5 }}>{cases.length}건</span>
          </div>
          {cases.length === 0 ? (
            <div className="panel-pad">
              <p className="muted" style={{ fontSize: 13 }}>
                아직 검토계획을 승인한 사건이 없습니다. <b>사건접수</b>에서 검토계획을 승인하면 여기에 나타나요.
              </p>
            </div>
          ) : (
            <table className="table">
              <thead>
                <tr><th>사건번호</th><th>고객명</th><th>유형</th><th>상태</th></tr>
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
                    <td>{c.type}</td>
                    <td><Badge tone={STATUS_TONE[c.status] || 'muted'}>{c.status_ko}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected ? (
          <CaseDetail key={selected} caseId={selected} provider={provider} setProvider={setProvider} onStatusChange={reload} />
        ) : (
          <div className="card"><div className="panel-pad"><p className="muted">사건을 선택하세요.</p></div></div>
        )}
      </div>
    </div>
  )
}

function CaseDetail({ caseId, provider, setProvider, onStatusChange }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const pollRef = useRef(null)

  const fetchDetail = async () => {
    try {
      const d = await api.staffCase(caseId)
      setData(d)
      return d
    } catch (e) { setErr(String(e.message || e)); return null }
  }

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }
  const startPoll = () => {
    stopPoll()
    pollRef.current = setInterval(async () => {
      const d = await fetchDetail()
      if (!d || d.verdict_status !== 'generating') { stopPoll(); onStatusChange?.() }
    }, 3000)
  }

  useEffect(() => {
    setData(null); setErr(null)
    fetchDetail().then((d) => { if (d && d.verdict_status === 'generating') startPoll() })
    return stopPoll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  const runVerdict = async () => {
    setBusy(true); setErr(null)
    try {
      const d = await api.staffGenerateVerdict(caseId)
      setData(d)
      if (d.verdict_status === 'generating') startPoll()
      onStatusChange?.()
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  // 검토 항목이 0개라 판정을 낼 수 없는 사건을 되살린다: 검토계획부터 다시 세운다.
  // 완료되면 사건접수 화면에서 승인 → 여기서 판정 생성으로 이어진다.
  const regeneratePlan = async () => {
    setBusy(true); setErr(null)
    try {
      await api.staffGeneratePlan(caseId)
      setErr(null)
      await fetchDetail()
      onStatusChange?.()
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  if (!data) return <div className="card"><div className="panel-pad">{err ? <div className="alert bad">⚠ {err}</div> : <Loading />}</div></div>

  const vs = data.verdict_status
  const kw = data.keywords || {}
  const chips = [...(kw.issue_terms || []), ...(kw.entities || [])].slice(0, 8)

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      {/* 사건 헤더 */}
      <div className="card">
        <div className="panel-head">
          <div className="row gap8" style={{ alignItems: 'center' }}>
            <span className="mono" style={{ fontWeight: 700 }}>{data.case_id}</span>
            <Badge tone="info">{data.type}</Badge>
            <Badge tone={STATUS_TONE[data.status] || 'muted'}>{data.status_ko}</Badge>
          </div>
          <ProviderSelect value={provider} onChange={setProvider} providers={PROVIDERS} />
        </div>
        <div className="panel-pad" style={{ display: 'grid', gap: 6 }}>
          <div className="kv"><span className="k">고객명</span><span className="v">{data.customer}</span></div>
          <div className="kv"><span className="k">접수일</span><span className="v">{data.intake_date || '-'}</span></div>
          {data.due_date && (
            <div className="kv">
              <span className="k">처리 기한</span>
              <span className="v">{data.due_date} · D-{data.days_left}{data.over_deadline_risk ? ' ⚠' : ''}</span>
            </div>
          )}
        </div>
      </div>

      {/* 접수 내용(SSOT) */}
      <div className="card">
        <div className="panel-head"><h2>접수 내용</h2><span className="muted" style={{ fontSize: 12 }}>{data.channel === 'citizen' ? '민원인 제출' : '이관 접수'}</span></div>
        <div className="panel-pad">
          <p style={{ fontSize: 13.5, lineHeight: 1.7, margin: '0 0 12px', whiteSpace: 'pre-wrap' }}>{data.facts || '접수 내용이 없습니다.'}</p>
          {chips.length > 0 && (
            <div className="row gap8" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
              {chips.map((t, i) => <span key={i} className="law-tag">{t}</span>)}
            </div>
          )}
          {(data.attachments || []).length > 0 && (
            <div style={{ display: 'grid', gap: 6 }}>
              {data.attachments.map((f, i) => (
                <div key={i} className="file-row"><span className="file-icon">📄</span><div className="file-meta"><div className="file-name">{typeof f === 'string' ? f : f.name}</div></div></div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 사건 원장 (판정 결과) */}
      <div className="card">
        <div className="panel-head">
          <h2>사건 원장 (AI 판정 결과)</h2>
          {vs === 'ready' && (
            <div className="row gap8">
              <Badge tone="good" solid>PASS {data.critic_summary.PASS}</Badge>
              <Badge tone="warn" solid>ESCALATE {data.critic_summary.ESCALATE}</Badge>
              <Badge tone="bad" solid>BLOCK {data.critic_summary.BLOCK}</Badge>
            </div>
          )}
        </div>
        <div className="panel-pad">
          {err && <div className="alert bad" style={{ marginBottom: 12 }}>⚠ {err}</div>}

          {vs === 'none' && (
            <>
              <p className="muted" style={{ fontSize: 12.5, marginTop: 0, marginBottom: 14 }}>
                검토계획이 승인되었습니다. 실제 AI로 검토 항목별 규정 판정을 생성하세요.
                {data.classification ? ` (분류: ${data.classification})` : ''}
              </p>
              <button className="btn primary block" onClick={runVerdict} disabled={busy}>
                {busy ? '요청 중…' : '⚡ AI 판정 생성'}
              </button>
            </>
          )}

          {vs === 'generating' && (
            <div className="live-progress"><span className="spinner" /> 실제 LLM이 검토 항목을 사건 사실에 대조해 규정 판정을 내리는 중… (수십 초 소요)</div>
          )}

          {vs === 'ready' && (
            <>
              <div className="ledger-row" style={{ padding: '4px 0 10px', color: 'var(--muted)', fontSize: 12 }}>
                <span className="ledger-item">검토 항목</span>
                <span className="ledger-verdict">판정 결과</span>
                <span style={{ width: 150, textAlign: 'center' }}>검증 / 수정</span>
              </div>
              {/* 검토 항목이 0개인 사건 — 예전 생성 로직에서 근거를 못 찾으면 항목을 비운 채
                  일반 안내 트랙으로 빠져나가는 바람에 판정이 영영 안 나오던 상태다.
                  지금은 금융상품 사건이면 공통 판매원칙 검토축이 자동으로 붙으므로,
                  여기서 검토계획을 다시 세우면 판정을 낼 수 있다. */}
              {data.ledger.length === 0 && (
                <div className="alert warn" style={{ marginBottom: 12 }}>
                  <span>ℹ️</span>
                  <div style={{ flex: 1 }}>
                    <div className="alert-title">판정할 검토 항목이 없습니다</div>
                    <div style={{ fontSize: 12.5, marginTop: 2 }}>
                      검토계획이 항목 없이 수립되어 판정을 생성할 수 없습니다.
                      검토계획을 다시 세우면 금융소비자보호법 공통 판매원칙을 축으로 최소 검토 항목이 잡힙니다.
                    </div>
                    <button className="btn" style={{ marginTop: 10 }} onClick={regeneratePlan} disabled={busy}>
                      {busy ? '재생성 요청 중…' : '↻ 검토계획 다시 생성'}
                    </button>
                  </div>
                </div>
              )}
              {data.ledger.map((row) => (
                <LedgerRow
                  key={row.seq}
                  caseId={caseId}
                  row={row}
                  options={data.verdict_options || []}
                  onSaved={(d) => { setData(d); onStatusChange?.() }}
                />
              ))}
              <p className="muted" style={{ fontSize: 12, margin: '12px 0 0' }}>
                AI 판정은 제안입니다 — <b>수정</b>으로 담당자가 직접 확정할 수 있고, 확정한 행은 재생성해도 덮어쓰지 않습니다.
              </p>
              <button className="btn block" style={{ marginTop: 10 }} onClick={runVerdict} disabled={busy}>
                {busy ? '재생성 중…' : '↻ 판정 재생성'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 유사 과거사례 — 이 사건의 접수 내용으로 실검색 */}
      <SimilarCases caseId={caseId} />

      {/* 협상·중재 — 요청 접수 / 세션 진행 / 쟁점 원장 */}
      <MediationPanel
        caseId={caseId}
        mediation={data.mediation}
        provider={provider}
        onChange={(m) => { setData({ ...data, mediation: m }); onStatusChange?.() }}
      />

      {/* 검토 결과 공개(직원·감독원용) — 원장이 있을 때만 */}
      {vs === 'ready' && data.ledger.length > 0 && (
        <Disclosure caseId={caseId} ledger={data.ledger} provider={provider} />
      )}
    </div>
  )
}

// 원장 한 행 — AI 판정을 그대로 보여주되, 담당자가 그 자리에서 고쳐 확정할 수 있다.
// (AI 판정은 제안이고 확정은 사람이 한다는 전제인데 그동안 화면에 고칠 통로가 없었다.)
function LedgerRow({ caseId, row, options, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const openEditor = () => {
    setForm({ verdict: row.verdict === '—' ? (options[0] || '') : row.verdict,
              ko: row.ko || '', detail: row.detail || '', reason: '' })
    setErr(null)
    setEditing(true)
  }

  const save = async () => {
    setBusy(true); setErr(null)
    try {
      onSaved(await api.staffOverrideVerdict(caseId, row.seq, form))
      setEditing(false)
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  const revert = async () => {
    setBusy(true); setErr(null)
    try {
      onSaved(await api.staffRevertVerdict(caseId, row.seq))
      setEditing(false)
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  const ai = row.ai_original || {}
  return (
    <div className="ledger-row" style={{ alignItems: 'flex-start' }}>
      <div className="ledger-item">
        <div className="li-name">
          {row.item}
          {row.source === 'baseline' && (
            <span className="badge muted" style={{ marginLeft: 6, fontSize: 10.5 }}
                  title="검색에서 이 분야 직접 근거를 못 찾아 금융소비자보호법 공통 판매원칙으로 세운 항목">
              공통 원칙
            </span>
          )}
        </div>
        <span className="li-code">{row.code}</span>
        {row.ko && <div className="fg2" style={{ fontSize: 12, marginTop: 4 }}>{row.ko}</div>}
        {row.detail && <div className="muted" style={{ fontSize: 11.5, marginTop: 3, lineHeight: 1.6 }}>{row.detail}</div>}

        {row.edited && (
          <div className="alert warn" style={{ marginTop: 8, fontSize: 11.5, padding: '7px 10px' }}>
            <span>✏️</span>
            <div>
              <b>담당자 수정</b> · AI 원안 「{ai.verdict || '—'}{ai.ko ? ` · ${ai.ko}` : ''}」
              <div style={{ marginTop: 2 }}>사유: {row.override_reason}</div>
              <div className="muted" style={{ marginTop: 1 }}>
                {row.overridden_by}{row.overridden_at ? ` · ${row.overridden_at.slice(0, 16).replace('T', ' ')}` : ''}
              </div>
            </div>
          </div>
        )}

        {editing && (
          <div className="card" style={{ marginTop: 10, padding: 12, display: 'grid', gap: 8 }}>
            <label className="muted" style={{ fontSize: 11.5 }}>판정 라벨</label>
            <select className="chip-select" value={form.verdict}
                    onChange={(e) => setForm({ ...form, verdict: e.target.value })}>
              {options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <label className="muted" style={{ fontSize: 11.5 }}>한 줄 요지</label>
            <input className="chip-select" value={form.ko}
                   onChange={(e) => setForm({ ...form, ko: e.target.value })} />
            <label className="muted" style={{ fontSize: 11.5 }}>판정 근거 상세</label>
            <textarea className="chip-select" rows={3} value={form.detail}
                      onChange={(e) => setForm({ ...form, detail: e.target.value })} />
            <label className="muted" style={{ fontSize: 11.5 }}>수정 사유 (감사 기록에 남습니다 · 필수)</label>
            <textarea className="chip-select" rows={2} value={form.reason}
                      placeholder="예: 녹취 확인 결과 위험 고지가 이루어져 위반으로 볼 수 없음"
                      onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            {err && <div className="alert bad" style={{ fontSize: 12 }}>⚠ {err}</div>}
            <div className="row gap8">
              <button className="btn primary" onClick={save} disabled={busy || !form.reason.trim()}>
                {busy ? '저장 중…' : '판정 확정'}
              </button>
              <button className="btn" onClick={() => setEditing(false)} disabled={busy}>취소</button>
              {row.edited && (
                <button className="btn" onClick={revert} disabled={busy} style={{ marginLeft: 'auto' }}>
                  ↺ AI 원안으로
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="ledger-verdict">{row.verdict}</div>

      <div style={{ width: 150, display: 'grid', gap: 6, justifyItems: 'center' }}>
        {row.critic
          ? <Badge tone={CRITIC_TONE[row.critic]} solid>{row.critic_meta?.ko || row.critic}</Badge>
          : <span className="muted">-</span>}
        {!editing && (
          <button className="btn" style={{ fontSize: 11.5, padding: '3px 10px' }} onClick={openEditor}>
            ✏️ 수정
          </button>
        )}
      </div>
    </div>
  )
}

function SimilarCases({ caseId }) {
  const { loading, data, error } = useAsync(() => api.staffCaseSimilar(caseId), [caseId])
  return (
    <div className="card">
      <div className="panel-head">
        <h2>유사 과거사례</h2>
        {data && <span className="badge good" title="접수 내용 기반 실검색">⚡ 실검색 · 임베딩 RAG</span>}
      </div>
      <div className="panel-pad">
        {loading && <div className="live-progress"><span className="spinner" /> 접수 사실·키워드로 결정례 검색 중…</div>}
        {error && <div className="alert bad">⚠ 검색 실패: {String(error.message || error)}</div>}
        {data && (
          <>
            {data.cases.length === 0 ? (
              <p className="muted" style={{ fontSize: 12.5 }}>유사 결정례를 찾지 못했습니다.</p>
            ) : (
              data.cases.map((c, i) => (
                <div key={i} className="sim-card">
                  <div className="sim-top">
                    <span className="sim-id">{c.case}</span>
                    <Badge tone={c.similarity >= 70 ? 'good' : c.similarity >= 40 ? 'info' : 'muted'}>유사도 {c.similarity}%</Badge>
                  </div>
                  <div className="sim-foot">
                    {c.kind ? <span className="law-tag" style={{ marginRight: 6 }}>{c.kind}</span> : null}
                    {/* 소요 영업일·배상비율은 분쟁조정 결정례에만 있다 — 없으면 0으로 우기지 않고 생략. */}
                    {c.business_days ? `${c.business_days}영업일 소요` : '처리 소요일 기록 없음'}
                    {c.award_ratio != null ? ` · 배상비율 ${c.award_ratio}%` : ''}
                    {c.product_en ? ` · ${c.product_en}` : ''}
                    {c.org ? ` · ${c.org}` : ''}
                  </div>
                </div>
              ))
            )}
            {!data.product_matched && data.cases.length > 0 && (
              <div className="alert warn" style={{ marginTop: 8 }}>
                <span>ℹ️</span>
                <div style={{ fontSize: 12.5 }}>
                  {data.corpus_widened
                    ? '같은 상품유형의 분쟁조정 결정례가 없어 금융위 검사·제재 결정례까지 넓혀 검색했습니다.'
                    : '같은 상품유형의 결정례가 코퍼스에 없어, 의미상 가장 가까운 선례로 대체했습니다.'}
                </div>
              </div>
            )}
            <div className={`alert ${data.over_deadline_risk ? 'bad' : 'warn'}`} style={{ marginTop: 8 }}>
              <span>🧭</span>
              <div>
                <div className="alert-title">예상 완료 {data.estimated_completion}{data.over_deadline_risk ? ' · 기한 초과 위험' : ''}</div>
                <div style={{ marginTop: 2, fontSize: 12.5 }}>{data.reasoning}</div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const MED_TONE = { requested: 'warn', open: 'info', closed: 'good' }
const ISSUE_TONE = { 미확정: 'muted', 확인중: 'info', 자료대기: 'warn', 정리완료: 'good' }
const LEAN_KO = { A: '민원인 측', B: '회사·감독원 측', neutral: '중립' }

// 협상·중재 패널 — '요청은 했는데 아무 데도 안 보인다'를 없애는 자리.
// 요청 접수 → 세션 개시 → 한 발언씩 진행. 진행 결과(쟁점 원장·공유 처리이력·중립성
// 밸런스)는 서버가 사건에 스냅샷하므로 민원인 진행현황에도 같은 사본이 나타난다.
function MediationPanel({ caseId, mediation, provider, onChange }) {
  const [busy, setBusy] = useState(null) // 'request' | 'start' | 'turn'
  const [err, setErr] = useState(null)
  const [reason, setReason] = useState('')

  const run = async (kind, fn) => {
    setBusy(kind); setErr(null)
    try { onChange(await fn()) } catch (e) { setErr(String(e.message || e)) } finally { setBusy(null) }
  }

  const m = mediation
  const issues = m?.issues || []
  const log = m?.log || []
  const entries = m?.balance?.entries || []
  const leanA = entries.filter((e) => e.leans === 'A').length
  const leanB = entries.filter((e) => e.leans === 'B').length

  return (
    <div className="card">
      <div className="panel-head">
        <h2>협상·중재</h2>
        <div className="row gap8">
          {m && <Badge tone={MED_TONE[m.status] || 'muted'} solid>{m.status_ko}</Badge>}
          {m?.sid && (
            <a className="badge muted" href={`/mediation.html?bind=${encodeURIComponent(caseId)}`}
               target="_blank" rel="noreferrer" title="전체 중재 콘솔에서 이 사건을 이어서 진행">
              중재 콘솔 ↗
            </a>
          )}
        </div>
      </div>
      <div className="panel-pad">
        {err && <div className="alert bad" style={{ marginBottom: 10 }}>⚠ {err}</div>}

        {!m && (
          <>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
              아직 협상·중재 요청이 없습니다. 민원인이 요청하거나, 담당자가 여기서 중재를 열 수 있어요.
            </p>
            <textarea className="chip-select" rows={2} value={reason} style={{ width: '100%', marginBottom: 8 }}
                      placeholder="중재를 요청하는 사유(선택)"
                      onChange={(e) => setReason(e.target.value)} />
            <button className="btn primary block" disabled={busy === 'request'}
                    onClick={() => run('request', () => api.staffRequestMediation(caseId, reason))}>
              {busy === 'request' ? '요청 중…' : '🤝 협상·중재 요청'}
            </button>
          </>
        )}

        {m && (
          <div style={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'grid', gap: 5 }}>
              <div className="kv"><span className="k">요청자</span><span className="v">{m.requested_by_ko}</span></div>
              {m.reason && <div className="kv"><span className="k">요청 사유</span><span className="v" style={{ whiteSpace: 'pre-wrap' }}>{m.reason}</span></div>}
              {m.sid && <div className="kv"><span className="k">진행</span><span className="v">{m.turn_index}/{m.max_turns} 발언</span></div>}
              {m.domain && <div className="kv"><span className="k">중재 주제</span><span className="v">{m.domain}</span></div>}
            </div>

            {!m.sid ? (
              <button className="btn primary block" disabled={busy === 'start'}
                      onClick={() => run('start', () => api.staffStartMediation(caseId, provider))}>
                {busy === 'start' ? '개시 중…' : '▶ 중재 세션 개시'}
              </button>
            ) : (
              <div className="live-bar">
                <button className="btn primary" disabled={busy === 'turn' || m.done}
                        onClick={() => run('turn', () => api.staffMediationTurn(caseId))}>
                  {busy === 'turn' ? '진행 중…' : m.done ? '중재 종료됨' : '▶ 다음 발언 진행'}
                </button>
                <span className="muted" style={{ fontSize: 12 }}>
                  진행 내용은 민원인 진행현황에도 같은 사본으로 표시됩니다.
                </span>
              </div>
            )}
            {busy === 'turn' && <div className="live-progress"><span className="spinner" /> LLM이 양측을 롤플레이하며 원장을 쓰는 중…</div>}

            {m.boundary && (
              <div className="alert warn" style={{ fontSize: 12 }}>
                <span>⚖️</span><div>{m.boundary}</div>
              </div>
            )}

            {/* 쟁점 원장 — 쟁점마다 양측 유리·불리를 대칭으로 기록(중립성의 근거) */}
            <div>
              <div className="panel-head" style={{ padding: 0, marginBottom: 6, border: 0 }}>
                <h2 style={{ fontSize: 13 }}>쟁점 원장 {issues.length > 0 && <span className="muted">({issues.length})</span>}</h2>
                {entries.length > 0 && (
                  <span className="muted" style={{ fontSize: 11.5 }}>
                    중립성 밸런스 · 민원인 유리 {leanA} / 회사·감독원 유리 {leanB}
                  </span>
                )}
              </div>
              {issues.length === 0 ? (
                <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
                  아직 정리된 쟁점이 없습니다. 발언을 진행하면 쟁점이 하나씩 세워져요.
                </p>
              ) : issues.map((it, i) => (
                <div key={i} className="sim-card" style={{ display: 'grid', gap: 6 }}>
                  <div className="sim-top">
                    <span className="sim-id">{it.title}</span>
                    <Badge tone={ISSUE_TONE[it.status] || 'muted'}>{it.status}</Badge>
                  </div>
                  <span className="li-code">{it.code}</span>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12 }}>
                    <div><b className="fg2">민원인 측 유리</b><div>{it.for_a}</div></div>
                    <div><b className="fg2">민원인 측 불리</b><div>{it.against_a}</div></div>
                    <div><b className="fg2">회사·감독원 유리</b><div>{it.for_b}</div></div>
                    <div><b className="fg2">회사·감독원 제한</b><div>{it.against_b}</div></div>
                  </div>
                  <div className="muted" style={{ fontSize: 11.5 }}>
                    중재 자문: {it.agent_note} · <b>최종 판단 주체: {it.decider}</b>
                  </div>
                </div>
              ))}
            </div>

            {/* 공유 처리이력 — 양측이 같은 사본을 본다 */}
            {log.length > 0 && (
              <div>
                <div className="panel-head" style={{ padding: 0, marginBottom: 6, border: 0 }}>
                  <h2 style={{ fontSize: 13 }}>공유 처리이력 <span className="muted">({log.length})</span></h2>
                </div>
                <div style={{ display: 'grid', gap: 5, maxHeight: 260, overflowY: 'auto' }}>
                  {log.map((l, i) => (
                    <div key={i} className="file-row" style={{ alignItems: 'flex-start' }}>
                      <span className="file-icon">{l.kind === '발언' ? '💬' : l.kind === '자문' ? '⚖️' : '📝'}</span>
                      <div className="file-meta">
                        <div className="file-name" style={{ fontSize: 12 }}>
                          [{l.seq}] {l.kind} · {l.speaker}
                        </div>
                        <div className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>{l.text}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {entries.length > 0 && (
              <div className="alert good" style={{ fontSize: 12 }}>
                <span>⚖️</span>
                <div>
                  <div className="alert-title">중립성 소명</div>
                  <div style={{ marginTop: 2 }}>{m.balance?.note}</div>
                  <div className="muted" style={{ marginTop: 4 }}>
                    {entries.map((e, i) => (
                      <div key={i}>· [{e.ref}] {LEAN_KO[e.leans] || e.leans} — {e.summary}</div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Disclosure({ caseId, ledger, provider }) {
  const [disc, setDisc] = useState(null)
  const [run, setRun] = useState(false)
  const [err, setErr] = useState(null)
  const [published, setPublished] = useState(false)

  const runDisclosure = async () => {
    setRun(true); setErr(null); setDisc(null); setPublished(false)
    const t0 = performance.now()
    // 원장의 대표 판정(첫 행)을 이중공개의 원천으로 삼는다 — 실제 판정 기반 작문.
    const top = ledger[0]
    const verdict = { code: top.code, verdict: top.verdict, ko: top.ko || top.verdict, detail: top.detail || '' }
    try {
      const r = await liveApi.disclosure(1, verdict, Math.max(0, ledger.length - 1), provider)
      setDisc({ ...r, ms: Math.round(performance.now() - t0) })
      try {
        await api.publishDisclosure({ disclosure: r, stage_key: 'verdict', case_id: caseId })
        setPublished(true)
      } catch { /* 게시 실패는 생성 표시를 막지 않는다 */ }
    } catch (e) { setErr(String(e.message || e)) } finally { setRun(false) }
  }

  return (
    <div className="card">
      <div className="panel-head">
        <h2>검토 결과 공개 (직원·감독원용)</h2>
        {disc ? <LiveTag provider={provider} providers={PROVIDERS} ms={disc.ms} /> : <span className="badge muted">미생성</span>}
      </div>
      <div className="panel-pad">
        <div className="live-bar">
          <button className="btn primary" onClick={runDisclosure} disabled={run}>
            {run ? '실제 생성 중…' : '⚡ 실제 AI로 검토 결과 공개 생성'}
          </button>
          <span className="muted" style={{ fontSize: 12 }}>민원인용 안내는 이 사건의 진행현황에 게시됩니다.</span>
        </div>
        {run && <div className="live-progress"><span className="spinner" /> 실제 LLM이 직원·감독원용 문구를 작성하는 중…</div>}
        {err && <div className="alert bad">⚠ 실제 호출 실패: {err}</div>}
        {disc && (
          <div style={{ display: 'grid', gap: 10 }}>
            <div className="disc-box r">
              <div className="disc-h">🏛️ 직원·감독원용 · {disc.supervisor_title}</div>
              <div className="disc-b">{disc.supervisor_body}</div>
            </div>
            {published && (
              <div className="alert good"><span>✓</span><div>민원인용 안내가 <b>민원인 진행현황(판정 완료 단계)</b>에 게시되었습니다.</div></div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
