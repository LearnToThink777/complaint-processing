import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, liveApi } from '../api.js'
import { useAsync, Loading, Badge, Empty } from '../components.jsx'

const CRITIC_TONE = { PASS: 'good', ESCALATE: 'warn', BLOCK: 'bad', CONFIRMED: 'info' }
const STATUS_TONE = {
  reviewing: 'info', verdict_generating: 'info', verdict: 'info', negotiating: 'warn', closed: 'good',
}
const MED_TONE = { requested: 'warn', open: 'info', closed: 'good' }
const ACTOR_ICON = { citizen: '🙋', staff: '👤', system: '⚙️' }

// 상태 필터 칩 — key 는 서버가 아는 status 키 또는 프리셋(all/open/attention).
const STATUS_CHIPS = [
  { key: 'all', label: '전체' },
  { key: 'attention', label: '조치 필요' },
  { key: 'reviewing', label: '검토 중' },
  { key: 'verdict', label: '판정 완료' },
  { key: 'negotiating', label: '협의 중' },
  { key: 'closed', label: '종결' },
]

// 정렬 가능한 열. dir 은 그 열을 처음 눌렀을 때의 방향(날짜·기한은 최신/임박이 먼저).
const COLUMNS = [
  { key: 'case_id', label: '사건번호', dir: 'asc' },
  { key: 'customer', label: '고객명', dir: 'asc' },
  { key: 'type', label: '유형', dir: 'asc' },
  { key: 'status', label: '상태', dir: 'asc' },
  { key: 'intake_date', label: '접수일', dir: 'desc' },
  { key: 'due_date', label: '처리 기한', dir: 'asc' },
  { key: 'verdict', label: '판정', dir: 'desc' },
  { key: 'updated_at', label: '최근 처리', dir: 'desc' },
]

function fmtAt(at, withTime = true) {
  if (!at) return '-'
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return '-'
  const p = (n) => String(n).padStart(2, '0')
  const day = `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`
  return withTime ? `${day} ${p(d.getHours())}:${p(d.getMinutes())}` : day
}

// 처리현황 — '지금 처리할 사건'을 찾는 작업 큐(사건 단위)다.
// 고객 단위로 누가 몇 번 접수했는지 보는 화면은 '고객 이력'이고, 여기서는 사건 하나를
// 골라 접수 내용·판정·처리 기록을 확인하고 판정을 확정한다. 협상·중재 진행은 중재 화면.
export default function Status() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('case')

  // 검색·필터·정렬은 서버가 처리한다(목록이 길어져도 화면이 전부 받아 놓고 흉내 내지 않게).
  const [query, setQuery] = useState('')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('all')
  const [dueSoon, setDueSoon] = useState(false)
  const [sort, setSort] = useState('updated_at')
  const [order, setOrder] = useState('desc')

  // 입력할 때마다 요청하지 않고 잠깐 멈추면 보낸다.
  useEffect(() => {
    const t = setTimeout(() => setQ(query.trim()), 300)
    return () => clearTimeout(t)
  }, [query])

  const { data, reload } = useAsync(
    () => api.staffCases({ q, status, due_soon: dueSoon, sort, order }),
    [q, status, dueSoon, sort, order],
  )

  const rows = data?.rows || []
  const facets = data?.facets || {}

  // 아무것도 안 골라져 있을 때만 첫 행을 연다. 필터를 바꿌다고 선택이 튀지는 않게 한다
  // (선택한 사건의 상세는 목록과 별개로 사건번호로 조회한다).
  useEffect(() => {
    if (!selected && rows.length) setParams({ case: rows[0].case_id }, { replace: true })
  }, [rows, selected, setParams])

  const sortBy = (col) => {
    if (sort === col.key) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else { setSort(col.key); setOrder(col.dir) }
  }

  const filtered = q || status !== 'all' || dueSoon

  return (
    <div>
      <div className="page-head">
        <h1>처리현황</h1>
        <p>
          검토계획을 승인한 사건의 작업 큐입니다. 조건으로 찾아 사건을 고르면 접수 내용·AI 판정·처리
          기록을 확인하고 판정을 확정할 수 있습니다. 같은 고객의 과거 접수를 사람 단위로 보려면{' '}
          <Link to="/staff/history">고객 이력</Link>을, 협상·중재 진행은{' '}
          <Link to="/staff/mediation">협상·중재</Link> 화면을 이용하세요.
        </p>
      </div>

      <div className="card queue-card">
        <div className="queue-toolbar">
          <div className="queue-search">
            <span aria-hidden>🔍</span>
            <input
              placeholder="사건번호 · 고객명 · 유형 검색"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && <button className="queue-clear" onClick={() => setQuery('')} title="검색어 지우기">✕</button>}
          </div>
          <div className="queue-chips">
            {STATUS_CHIPS.map((c) => (
              <button
                key={c.key}
                className={status === c.key ? 'on' : ''}
                onClick={() => setStatus(c.key)}
              >
                {c.label}
                <i>{facets[c.key] ?? 0}</i>
              </button>
            ))}
            <button className={`due ${dueSoon ? 'on' : ''}`} onClick={() => setDueSoon((v) => !v)}>
              ⏰ 기한 임박<i>{facets.due_soon ?? 0}</i>
            </button>
          </div>
        </div>

        <div className="queue-meta">
          <span>
            {data ? `${data.total}건` : '불러오는 중…'}
            {filtered && <span className="muted"> · 조건 적용됨</span>}
          </span>
          <div className="row gap8">
            {filtered && (
              <button
                className="btn"
                onClick={() => { setQuery(''); setQ(''); setStatus('all'); setDueSoon(false) }}
              >
                조건 초기화
              </button>
            )}
            <button className="btn" onClick={reload}>새로고침</button>
          </div>
        </div>

        {!data ? (
          <div className="panel-pad"><Loading /></div>
        ) : rows.length === 0 ? (
          <div className="panel-pad">
            <Empty>
              {filtered
                ? '조건에 맞는 사건이 없습니다. 검색어나 상태 필터를 넓혀 보세요.'
                : '아직 검토계획을 승인한 사건이 없습니다. 사건접수에서 검토계획을 승인하면 여기에 나타납니다.'}
            </Empty>
          </div>
        ) : (
          <div className="queue-scroll">
            <table className="table queue-table">
              <thead>
                <tr>
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className={`th-sort ${sort === c.key ? 'on' : ''}`}
                      onClick={() => sortBy(c)}
                      title={`${c.label} 기준 정렬`}
                    >
                      {c.label}
                      <span className="th-arrow">{sort === c.key ? (order === 'asc' ? '▲' : '▼') : '↕'}</span>
                    </th>
                  ))}
                  <th>다음 조치</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr
                    key={c.case_id}
                    className={`clickable ${selected === c.case_id ? 'selected' : ''}`}
                    onClick={() => setParams({ case: c.case_id })}
                  >
                    <td className="mono">{c.case_id}</td>
                    <td style={{ fontWeight: 600 }}>{c.customer}</td>
                    <td className="cell-type" title={c.type}>{c.type}</td>
                    <td><Badge tone={STATUS_TONE[c.status] || 'muted'}>{c.status_ko}</Badge></td>
                    <td className="fg2">{c.intake_date || '-'}</td>
                    <td className={c.over_deadline_risk ? 'due-risk' : 'fg2'}>
                      {c.due_date ? `${c.due_date}${c.days_left != null ? ` (D${c.days_left >= 0 ? '-' : '+'}${Math.abs(c.days_left)})` : ''}` : '-'}
                    </td>
                    <td className="fg2">
                      {c.verdict_status === 'ready'
                        ? (c.verdict_digest || `${c.item_count}건 판정`)
                        : c.verdict_status === 'generating' ? '생성 중…' : '생성 전'}
                    </td>
                    <td className="fg2">{fmtAt(c.last_activity_at || c.updated_at, false)}</td>
                    <td className="fg2">{c.next_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && <CaseDetail key={selected} caseId={selected} onStatusChange={reload} />}
    </div>
  )
}

function CaseDetail({ caseId, onStatusChange }) {
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

  if (!data) {
    return (
      <div className="card" style={{ marginTop: 18 }}>
        <div className="panel-pad">{err ? <div className="alert bad">⚠ {err}</div> : <Loading />}</div>
      </div>
    )
  }

  const vs = data.verdict_status
  const kw = data.keywords || {}
  const chips = [...(kw.issue_terms || []), ...(kw.entities || [])].slice(0, 8)

  return (
    <div className="case-detail">
      {/* 선택한 사건의 머리글 — 목록 위에서 고른 사건이 무엇인지 한 줄로 붙잡아 둔다. */}
      <div className="card cd-head">
        <div className="cd-head-top">
          <div className="row gap8" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="mono" style={{ fontWeight: 700, fontSize: 15 }}>{data.case_id}</span>
            <Badge tone="info">{data.type}</Badge>
            <Badge tone={STATUS_TONE[data.status] || 'muted'}>{data.status_ko}</Badge>
            {data.over_deadline_risk && <Badge tone="bad" solid>기한 임박</Badge>}
          </div>
          <div className="row gap8">
            {data.customer_case_count > 1 && (
              <Link
                className="btn"
                to={`/staff/history?customer=${encodeURIComponent(data.customer)}`}
                title="이 고객이 접수한 다른 민원을 사람 단위로 확인"
              >
                🗂️ 이 고객의 민원 {data.customer_case_count}건
              </Link>
            )}
          </div>
        </div>
        <div className="cd-head-grid">
          <div className="kv"><span className="k">고객명</span><span className="v">{data.customer}</span></div>
          <div className="kv"><span className="k">접수 경로</span><span className="v">{data.channel === 'citizen' ? '민원인 직접 접수' : '타 기관 이관'}</span></div>
          <div className="kv"><span className="k">접수일</span><span className="v">{data.intake_date || '-'}</span></div>
          <div className="kv">
            <span className="k">처리 기한</span>
            <span className="v">
              {data.due_date ? `${data.due_date} · ${data.days_left}일 남음` : '기한 없음'}
            </span>
          </div>
          <div className="kv"><span className="k">다음 조치</span><span className="v">{data.next_action}</span></div>
        </div>
      </div>

      <div className="cd-grid">
        <div className="cd-col">
          {/* 접수 내용 */}
          <div className="card">
            <div className="panel-head">
              <h2>접수 내용</h2>
              <span className="muted" style={{ fontSize: 12 }}>{data.channel === 'citizen' ? '민원인 직접 접수' : '타 기관 이관'}</span>
            </div>
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

          {/* AI 판정 결과 */}
          <div className="card">
            <div className="panel-head">
              <h2>AI 판정 결과</h2>
              {vs === 'ready' && (
                <div className="row gap8">
                  <Badge tone="good" solid>근거 확인 {data.critic_summary.PASS}</Badge>
                  <Badge tone="warn" solid>확인 필요 {data.critic_summary.ESCALATE}</Badge>
                  <Badge tone="bad" solid>근거 부족 {data.critic_summary.BLOCK}</Badge>
                </div>
              )}
            </div>
            <div className="panel-pad">
              {err && <div className="alert bad" style={{ marginBottom: 12 }}>⚠ {err}</div>}

              {vs === 'none' && (
                <>
                  <p className="muted" style={{ fontSize: 12.5, marginTop: 0, marginBottom: 14 }}>
                    검토계획이 승인되었습니다. 검토 항목별 법령 판정을 생성하세요.
                    {data.classification ? ` (분류: ${data.classification})` : ''}
                  </p>
                  <button className="btn primary block" onClick={runVerdict} disabled={busy}>
                    {busy ? '요청 중…' : 'AI 판정 생성'}
                  </button>
                </>
              )}

              {vs === 'generating' && (
                <div className="live-progress">
                  <span className="spinner" /> AI가 검토 항목을 사건 사실과 대조해 판정하고 있습니다. 잠시만 기다려 주세요.
                </div>
              )}

              {vs === 'ready' && (
                <>
                  <div className="ledger-row" style={{ padding: '4px 0 10px', color: 'var(--muted)', fontSize: 12 }}>
                    <span className="ledger-item">검토 항목</span>
                    <span className="ledger-verdict">판정</span>
                    <span style={{ width: 150, textAlign: 'center' }}>AI 검증 · 수정</span>
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
                          {busy ? '재생성 요청 중…' : '검토계획 다시 세우기'}
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
                    AI 판정은 담당자를 돕기 위한 제안입니다. <b>수정</b>으로 직접 확정할 수 있고, 확정한 항목은 판정을 다시 생성해도 유지됩니다.
                  </p>
                  <button className="btn block" style={{ marginTop: 10 }} onClick={runVerdict} disabled={busy}>
                    {busy ? '재생성 중…' : '판정 다시 생성'}
                  </button>
                </>
              )}
            </div>
          </div>

          {/* 검토 결과 안내문(내부·감독기관용) — 판정이 있을 때만 */}
          {vs === 'ready' && data.ledger.length > 0 && (
            <Disclosure
              caseId={caseId}
              ledger={data.ledger}
              published={data.staff_messages || []}
              onPublished={fetchDetail}
            />
          )}
        </div>

        <div className="cd-col">
          {/* 처리 기록 — 이 사건이 어떤 과정을 거쳤는지(민원인 화면의 기록과 같은 원천). */}
          <ProcessLog events={data.events || []} />

          {/* 유사 과거사례 — 이 사건의 접수 내용으로 검색 */}
          <SimilarCases caseId={caseId} />

          {/* 협상·중재 — 상태 요약만. 진행은 협상·중재 화면에서 한다. */}
          <MediationSummary caseId={caseId} mediation={data.mediation} />

          {/* 종결 처리 — 사건을 닫고 사람이 내린 결정을 남기는 마지막 단계. */}
          <CaseClosure
            caseId={caseId}
            detail={data}
            onClosed={async () => { await fetchDetail(); onStatusChange?.() }}
          />
        </div>
      </div>
    </div>
  )
}

// 처리 기록 — stage_events 를 시간 역순으로. '이 사건이 지금 상태에 어떻게 도달했는지'가
// 화면 어디에도 없어서, 정적인 카드만 보이고 진행 과정은 확인할 수 없었다.
function ProcessLog({ events }) {
  const [all, setAll] = useState(false)
  const rows = useMemo(() => [...events].reverse(), [events])
  const shown = all ? rows : rows.slice(0, 6)

  return (
    <div className="card">
      <div className="panel-head">
        <h2>처리 기록</h2>
        <span className="muted" style={{ fontSize: 12 }}>{rows.length}건</span>
      </div>
      <div className="panel-pad">
        {rows.length === 0 ? (
          <Empty>아직 기록된 처리 이력이 없습니다.</Empty>
        ) : (
          <>
            <div className="log-list">
              {shown.map((e, i) => (
                <div key={i} className={`log-row ${e.kind}`}>
                  <span className="log-icon" aria-hidden>{ACTOR_ICON[e.actor] || '•'}</span>
                  <div className="log-body">
                    <div className="log-top">
                      <span className="log-title">
                        {e.kind === 'transition'
                          ? `${e.from_ko ? `${e.from_ko} → ` : ''}${e.to_ko}`
                          : `${e.to_ko} 처리`}
                      </span>
                      <span className="log-at">{fmtAt(e.at)}</span>
                    </div>
                    {e.note && <div className="log-note">{e.note}</div>}
                    <div className="log-actor">{e.actor_ko}</div>
                  </div>
                </div>
              ))}
            </div>
            {rows.length > 6 && (
              <button className="btn block" style={{ marginTop: 10 }} onClick={() => setAll((v) => !v)}>
                {all ? '최근 6건만 보기' : `전체 ${rows.length}건 보기`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// 원장 한 행 — AI 판정을 그대로 보여주되, 담당자가 그 자리에서 고쳐 확정할 수 있다.
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
                  title="이 분야의 직접 근거를 찾지 못해 금융소비자보호법 공통 판매원칙으로 세운 항목">
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
              <b>담당자 확정</b> · AI 판정 「{ai.verdict || '—'}{ai.ko ? ` · ${ai.ko}` : ''}」에서 수정
              <div style={{ marginTop: 2 }}>사유: {row.override_reason}</div>
              <div className="muted" style={{ marginTop: 1 }}>
                {row.overridden_by}{row.overridden_at ? ` · ${row.overridden_at.slice(0, 16).replace('T', ' ')}` : ''}
              </div>
            </div>
          </div>
        )}

        {editing && (
          <div className="card" style={{ marginTop: 10, padding: 12, display: 'grid', gap: 8 }}>
            <label className="muted" style={{ fontSize: 11.5 }}>판정</label>
            <select className="chip-select" value={form.verdict}
                    onChange={(e) => setForm({ ...form, verdict: e.target.value })}>
              {options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <label className="muted" style={{ fontSize: 11.5 }}>한 줄 요지</label>
            <input className="chip-select" value={form.ko}
                   onChange={(e) => setForm({ ...form, ko: e.target.value })} />
            <label className="muted" style={{ fontSize: 11.5 }}>판정 근거</label>
            <textarea className="chip-select" rows={3} value={form.detail}
                      onChange={(e) => setForm({ ...form, detail: e.target.value })} />
            <label className="muted" style={{ fontSize: 11.5 }}>수정 사유 (처리 기록에 남습니다 · 필수)</label>
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
                  AI 판정으로 되돌리기
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="ledger-verdict">{row.verdict}</div>

      <div style={{ width: 150, display: 'grid', gap: 6, justifyItems: 'center' }}>
        {row.critic
          ? <Badge tone={CRITIC_TONE[row.critic]} solid={row.critic !== 'CONFIRMED'}>{row.critic_meta?.ko || row.critic}</Badge>
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
        {data && <span className="muted" style={{ fontSize: 12 }}>접수 내용 기준 {data.cases.length}건</span>}
      </div>
      <div className="panel-pad">
        {loading && <div className="live-progress"><span className="spinner" /> 비슷한 과거 결정례를 찾는 중…</div>}
        {error && <div className="alert bad">⚠ 검색에 실패했습니다: {String(error.message || error)}</div>}
        {data && (
          <>
            {data.cases.length === 0 ? (
              <Empty>유사한 과거 결정례를 찾지 못했습니다.</Empty>
            ) : (
              data.cases.map((c, i) => (
                <div key={i} className="sim-card">
                  <div className="sim-top">
                    <span className="sim-id">{c.case}</span>
                    <Badge tone={c.similarity >= 70 ? 'good' : c.similarity >= 40 ? 'info' : 'muted'}>유사도 {c.similarity}%</Badge>
                  </div>
                  <div className="sim-foot">
                    {c.kind ? <span className="law-tag" style={{ marginRight: 6 }}>{c.kind}</span> : null}
                    {/* 소요 영업일·배상비율은 분쟁조정 결정례에만 있다 — 없으면 0으로 우기지 않고 생략.
                        product_en 은 코퍼스 내부 코드(영문)라 화면에는 내보내지 않는다. */}
                    {c.business_days ? `${c.business_days}영업일 소요` : '처리 소요일 기록 없음'}
                    {c.award_ratio != null ? ` · 배상비율 ${c.award_ratio}%` : ''}
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
                    ? '같은 상품유형의 분쟁조정 결정례가 없어 검사·제재 결정례까지 범위를 넓혀 검색했습니다.'
                    : '같은 상품유형의 결정례가 없어 내용상 가장 가까운 선례로 대체했습니다.'}
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

// 협상·중재 상태 요약 — 진행 버튼은 두지 않는다. 중재를 여는 것도, 발언을 진행하는 것도
// 협상·중재 화면에서만 한다(예전엔 같은 조작이 이 패널과 외부 콘솔 두 곳에 있었다).
function MediationSummary({ caseId, mediation }) {
  const nav = useNavigate()
  const m = mediation
  const goConsole = () => nav(`/staff/mediation?case=${encodeURIComponent(caseId)}`)

  return (
    <div className="card">
      <div className="panel-head">
        <h2>협상·중재</h2>
        {m ? <Badge tone={MED_TONE[m.status] || 'muted'}>{m.status_ko}</Badge> : <Badge tone="muted">요청 없음</Badge>}
      </div>
      <div className="panel-pad">
        {m ? (
          <div style={{ display: 'grid', gap: 4, marginBottom: 12 }}>
            <div className="kv"><span className="k">요청자</span><span className="v">{m.requested_by_ko}</span></div>
            <div className="kv">
              <span className="k">진행</span>
              <span className="v">
                {m.sid ? `${m.turn_index}/${m.max_turns} 발언 · 쟁점 ${(m.issues || []).length}건` : '아직 개시 전'}
              </span>
            </div>
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 12.5, margin: '0 0 12px' }}>
            이 사건에는 아직 협상·중재 요청이 없습니다. 민원인이 요청하거나 담당자가 직접 열 수 있습니다.
          </p>
        )}
        <button className="btn primary block" onClick={goConsole}>
          {m ? '협상·중재 화면에서 이어보기' : '협상·중재 열기'}
        </button>
      </div>
    </div>
  )
}

// 종결 처리 — 그동안 '종결'은 상태 라벨·필터·집계에만 있고 사건을 그 상태로 보내는 통로가
// 어디에도 없었다(사건이 종결에 도달할 수 없었다). 여기가 그 통로다.
// AI 판정과 달리 이건 사람의 결정이므로, 무엇을 근거로 닫는지(남은 판정)를 먼저 보여준다.
function CaseClosure({ caseId, detail, onClosed }) {
  const [outcome, setOutcome] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const closed = detail.status === 'closed'
  const left = detail.remaining_verdicts || 0
  const options = detail.outcome_options || []

  const submit = async () => {
    setBusy(true); setErr(null)
    try {
      await api.staffCloseCase(caseId, outcome, note.trim())
      await onClosed?.()
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  return (
    <div className="card">
      <div className="panel-head">
        <h2>종결 처리</h2>
        {closed
          ? <Badge tone={detail.outcome?.tone || 'good'}>{detail.outcome?.ko || '종결'}</Badge>
          : <Badge tone="muted">진행 중</Badge>}
      </div>
      <div className="panel-pad">
        {closed ? (
          <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
            이 사건은 <b>{detail.outcome?.ko}</b>(으)로 종결되었습니다. 처리 기록에서 종결 시점을 확인할 수 있습니다.
          </p>
        ) : !detail.can_close ? (
          <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
            {left > 0
              ? `아직 판정이 나지 않은 검토 항목이 ${left}건 있습니다. 판정을 마친 뒤 종결할 수 있습니다.`
              : '판정이 나온 뒤에 종결할 수 있습니다.'}
          </p>
        ) : (
          <>
            <p className="muted" style={{ fontSize: 12.5, margin: '0 0 10px' }}>
              검토 항목 {detail.ledger?.length || 0}건의 판정이 모두 끝났습니다. 최종 결정을 선택해 종결하세요.
            </p>
            <div className="row gap8" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
              {options.map((o) => (
                <button
                  key={o.code}
                  className={`btn${outcome === o.code ? ' primary' : ''}`}
                  onClick={() => setOutcome(o.code)}
                  disabled={busy}
                >
                  {o.ko}
                </button>
              ))}
            </div>
            <input
              className="chip-select"
              placeholder="처리 기록에 남길 메모(선택)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={busy}
              style={{ width: '100%', marginBottom: 10, boxSizing: 'border-box' }}
            />
            <button className="btn primary block" onClick={submit} disabled={busy || !outcome}>
              {busy ? '종결 처리 중…' : '종결 처리'}
            </button>
          </>
        )}
        {err && <div className="alert bad" style={{ marginTop: 10 }}>⚠ {err}</div>}
      </div>
    </div>
  )
}

// 검토 결과 안내문 — 같은 판정을 청중별로 다르게 쓴다. 민원인용은 진행현황에 게시되고,
// 내부·감독기관용은 이 화면에서만 보인다. 게시한 안내문은 사건에 남아 다시 열어도 보인다.
function Disclosure({ caseId, ledger, published, onPublished }) {
  const [disc, setDisc] = useState(null)
  const [run, setRun] = useState(false)
  const [err, setErr] = useState(null)
  const [ok, setOk] = useState(false)

  const runDisclosure = async () => {
    setRun(true); setErr(null); setDisc(null); setOk(false)
    // 원장의 대표 판정(첫 행)을 안내문의 원천으로 삼는다.
    const top = ledger[0]
    const verdict = { code: top.code, verdict: top.verdict, ko: top.ko || top.verdict, detail: top.detail || '' }
    try {
      const r = await liveApi.disclosure(1, verdict, Math.max(0, ledger.length - 1))
      setDisc(r)
      try {
        await api.publishDisclosure({ disclosure: r, stage_key: 'verdict', case_id: caseId })
        setOk(true)
        await onPublished?.()
      } catch { /* 게시 실패가 생성 결과 표시를 막지는 않는다 */ }
    } catch (e) { setErr(String(e.message || e)) } finally { setRun(false) }
  }

  return (
    <div className="card">
      <div className="panel-head">
        <h2>검토 결과 안내문</h2>
        <span className="muted" style={{ fontSize: 12 }}>게시 {published.length}건</span>
      </div>
      <div className="panel-pad">
        <div className="live-bar">
          <button className="btn primary" onClick={runDisclosure} disabled={run}>
            {run ? '생성 중…' : '안내문 생성'}
          </button>
          <span className="muted" style={{ fontSize: 12 }}>
            민원인용 안내는 민원인 진행현황에 게시되고, 내부·감독기관용은 아래에 표시됩니다.
          </span>
        </div>
        {run && <div className="live-progress"><span className="spinner" /> 판정 내용을 바탕으로 안내 문구를 작성하는 중…</div>}
        {err && <div className="alert bad">⚠ 생성에 실패했습니다: {err}</div>}
        {ok && (
          <div className="alert good"><span>✓</span><div>민원인용 안내를 <b>민원인 진행현황(판정 완료 단계)</b>에 게시했습니다.</div></div>
        )}
        {disc && (
          <div className="disc-box r" style={{ marginTop: 10 }}>
            <div className="disc-h">🏛️ 방금 생성 · {disc.supervisor_title}</div>
            <div className="disc-b">{disc.supervisor_body}</div>
          </div>
        )}
        {published.length === 0 ? (
          !disc && <Empty>아직 게시한 안내문이 없습니다.</Empty>
        ) : (
          <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
            {published.map((m, i) => (
              <div key={i} className="disc-box r">
                <div className="disc-h">🏛️ 내부·감독기관용 · {m.title || '안내문'}</div>
                <div className="disc-b">{m.body}</div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 6 }}>{fmtAt(m.at)} · {m.sender}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
