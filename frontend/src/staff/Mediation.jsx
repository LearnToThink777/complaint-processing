import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading, Badge, Empty } from '../components.jsx'

// 협상·중재 콘솔 — 직원 포털에서 중재를 보고 진행하는 유일한 자리.
// 예전에는 ① 사이드바 바깥 콘솔(mediation.html) ② 처리현황 안 패널 ③ 첫 화면 카드로
// 입구가 셋이라 어디가 '진짜'인지 알 수 없었다. 이제 진행(개시·발언)은 여기서만 하고,
// 처리현황은 사건별 상태 요약과 이 화면으로 오는 링크만 갖는다.

const MED_TONE = { requested: 'warn', open: 'info', closed: 'good', none: 'muted' }
const ISSUE_TONE = { 미확정: 'muted', 확인중: 'info', 자료대기: 'warn', 정리완료: 'good' }
const LOG_KIND = { 발언: { cls: 'say', icon: '💬' }, 자문: { cls: 'advice', icon: '⚖️' }, 서기: { cls: 'note', icon: '📝' } }

const FILTERS = [
  { key: 'all', label: '전체', match: () => true },
  { key: 'open', label: '진행 중', match: (r) => r.med_status === 'open' },
  { key: 'requested', label: '요청됨', match: (r) => r.med_status === 'requested' },
  { key: 'closed', label: '종결', match: (r) => r.med_status === 'closed' },
  { key: 'none', label: '미개시', match: (r) => r.med_status === 'none' },
]

// 응답이 {mediation: …} 로 감싸져 오기도 하고 payload 그대로 오기도 한다 — 한 모양으로.
const unwrap = (r) => (r && typeof r === 'object' && 'mediation' in r ? r.mediation : r)

export default function Mediation() {
  const [params, setParams] = useSearchParams()
  const { data: rows, reload } = useAsync(() => api.staffMediations(), [])
  const [filter, setFilter] = useState('all')
  const selected = params.get('case')

  const list = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter) || FILTERS[0]
    return (rows || []).filter(f.match)
  }, [rows, filter])

  // 고른 사건이 없거나 지금 목록에 없으면 첫 사건으로 맞춘다(URL 에 남겨 두고 새로고침·
  // 처리현황에서 넘어온 딥링크가 그대로 살아 있게).
  useEffect(() => {
    if (!list.length) return
    if (!selected || !list.some((r) => r.case_id === selected)) {
      setParams({ case: list[0].case_id }, { replace: true })
    }
  }, [list, selected, setParams])

  if (!rows) return <Loading />

  const row = rows.find((r) => r.case_id === selected) || null

  return (
    <div>
      <div className="page-head">
        <h1>협상·중재</h1>
        <p>사건별로 중재를 열고 발언을 진행합니다. 여기서 정리된 쟁점과 기록은 민원인 화면에도 같은 내용으로 보입니다.</p>
      </div>

      {rows.length === 0 ? (
        <div className="card"><div className="panel-pad">
          <Empty>처리 중인 사건이 없습니다. 사건접수에서 검토계획을 승인하면 그 사건부터 중재를 열 수 있습니다.</Empty>
        </div></div>
      ) : (
        <div className="med-layout">
          <div className="card">
            <div className="panel-head">
              <h2>사건 목록</h2>
              <span className="muted" style={{ fontSize: 12.5 }}>{list.length}건</span>
            </div>
            <div className="med-filter">
              {FILTERS.map((f) => {
                const n = rows.filter(f.match).length
                return (
                  <button key={f.key} className={filter === f.key ? 'on' : ''} onClick={() => setFilter(f.key)}>
                    {f.label} {n}
                  </button>
                )
              })}
            </div>
            <div className="med-list">
              {list.length === 0 && <div className="panel-pad"><Empty>해당하는 사건이 없습니다.</Empty></div>}
              {list.map((r) => (
                <button
                  key={r.case_id}
                  className={`med-list-item ${selected === r.case_id ? 'on' : ''}`}
                  onClick={() => setParams({ case: r.case_id })}
                >
                  <div className="med-list-top">
                    <span className="mono" style={{ fontWeight: 700 }}>{r.case_id}</span>
                    <Badge tone={MED_TONE[r.med_status]}>{r.med_status_ko}</Badge>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{r.customer} · {r.type}</div>
                  <div className="muted" style={{ fontSize: 11.5 }}>
                    {r.med_status === 'none'
                      ? '중재 요청 없음'
                      : `${r.requested_by_ko} 요청${r.max_turns ? ` · ${r.turn_index}/${r.max_turns} 발언` : ''}${r.issue_count ? ` · 쟁점 ${r.issue_count}건` : ''}`}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {row ? (
            <Console key={row.case_id} row={row} onChanged={reload} />
          ) : (
            <div className="card"><div className="panel-pad"><Empty>왼쪽에서 사건을 선택하세요.</Empty></div></div>
          )}
        </div>
      )}
    </div>
  )
}

function Console({ row, onChanged }) {
  const nav = useNavigate()
  const [med, setMed] = useState(undefined) // undefined=로딩 전, null=중재 없음
  const [busy, setBusy] = useState(null)    // 'start' | 'turn'
  const [err, setErr] = useState(null)
  const [reason, setReason] = useState('')
  const [view, setView] = useState('shared')

  useEffect(() => {
    let alive = true
    setMed(undefined); setErr(null); setView('shared')
    api.staffMediation(row.case_id)
      .then((r) => alive && setMed(unwrap(r) || null))
      .catch((e) => alive && setErr(String(e.message || e)))
    return () => { alive = false }
  }, [row.case_id])

  const run = async (kind, fn) => {
    setBusy(kind); setErr(null)
    try {
      setMed(unwrap(await fn()))
      onChanged?.()
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(null) }
  }

  const open = () => run('start', async () => {
    // 사유를 적었으면 '요청'으로 먼저 남긴다 — 민원인 화면에도 요청 사실이 안내로 뜬다.
    if (reason.trim()) await api.staffRequestMediation(row.case_id, reason.trim())
    setReason('')
    return api.staffStartMediation(row.case_id)
  })

  if (med === undefined && !err) return <div className="card"><div className="panel-pad"><Loading label="중재 내역 불러오는 중…" /></div></div>

  const issues = med?.issues || []
  const log = med?.log || []
  const entries = med?.balance?.entries || []
  const parties = med?.parties || []
  const roleOf = (side) => parties.find((p) => p.side === side)?.role || (side === 'A' ? '민원인 측' : '회사·감독원 측')
  const keyOf = (side) => parties.find((p) => p.side === side)?.key
  // 기록의 speaker 는 내부 키('complainant'/'company')다 — 화면에는 역할 이름으로 옮긴다.
  const nameOf = (key) => parties.find((p) => p.key === key)?.role || (key === 'C' ? '중재자' : key)
  const progress = med?.max_turns ? Math.round((med.turn_index / med.max_turns) * 100) : 0

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      {/* 사건·중재 개요 + 진행 컨트롤 */}
      <div className="card">
        <div className="panel-head">
          <div className="row gap8" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="mono" style={{ fontWeight: 700 }}>{row.case_id}</span>
            <Badge tone="info">{row.type}</Badge>
            <Badge tone={MED_TONE[med?.status || 'none']} solid={!!med}>{med?.status_ko || '중재 없음'}</Badge>
          </div>
          <span className="link-more" style={{ cursor: 'pointer' }}
                onClick={() => nav(`/staff/status?case=${encodeURIComponent(row.case_id)}`)}>
            사건 상세 &rsaquo;
          </span>
        </div>
        <div className="panel-pad">
          <div className="kv"><span className="k">고객명</span><span className="v">{row.customer}</span></div>
          <div className="kv"><span className="k">사건 상태</span><span className="v">{row.case_status_ko}</span></div>
          {med && <div className="kv"><span className="k">요청자</span><span className="v">{med.requested_by_ko}</span></div>}
          {med?.domain && <div className="kv"><span className="k">중재 주제</span><span className="v">{med.domain}</span></div>}
          {med?.reason && (
            <div className="kv" style={{ alignItems: 'flex-start' }}>
              <span className="k">요청 사유</span>
              <span className="v" style={{ whiteSpace: 'pre-wrap', textAlign: 'right', maxWidth: '70%' }}>{med.reason}</span>
            </div>
          )}

          {err && <div className="alert bad" style={{ marginTop: 12 }}>⚠ {err}</div>}

          {med?.boundary && (
            <div className="alert warn" style={{ marginTop: 12, fontSize: 12.5 }}>
              <span>⚖️</span><div><div className="alert-title">권한 경계</div>{med.boundary}</div>
            </div>
          )}

          {/* 진행 컨트롤 — 중재를 여는 것도, 발언을 진행하는 것도 이 화면에서만 한다. */}
          <div style={{ marginTop: 14 }}>
            {!med || !med.sid ? (
              <>
                <p className="muted" style={{ fontSize: 12.5, margin: '0 0 8px' }}>
                  {med
                    ? '중재 요청이 접수되었습니다. 세션을 개시하면 쟁점 정리가 시작됩니다.'
                    : '아직 협상·중재 요청이 없습니다. 담당자가 여기서 바로 열 수 있습니다.'}
                </p>
                {!med && (
                  <textarea className="chip-select" rows={2} value={reason} style={{ width: '100%', marginBottom: 8 }}
                            placeholder="중재를 여는 사유 (선택 · 민원인에게도 안내됩니다)"
                            onChange={(e) => setReason(e.target.value)} />
                )}
                <button className="btn primary block" disabled={busy === 'start'} onClick={open}>
                  {busy === 'start' ? '여는 중…' : '협상·중재 열기'}
                </button>
              </>
            ) : (
              <>
                <div className="row between" style={{ fontSize: 12.5, marginBottom: 6 }}>
                  <span className="fg2">진행 {med.turn_index}/{med.max_turns} 발언</span>
                  <span className="muted">쟁점 {issues.length}건 · 기록 {log.length}건</span>
                </div>
                <div className="med-progress"><i style={{ width: `${progress}%` }} /></div>
                <div className="live-bar" style={{ marginTop: 12, marginBottom: 0 }}>
                  <button className="btn primary" disabled={busy === 'turn' || med.done}
                          onClick={() => run('turn', () => api.staffMediationTurn(row.case_id))}>
                    {busy === 'turn' ? '진행 중…' : med.done ? '중재 종료됨' : '다음 발언 진행'}
                  </button>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {med.done
                      ? '중재가 종료되었습니다. 기록은 양측 화면에 그대로 남습니다.'
                      : '한 번에 한 발언씩 진행되며, 진행 즉시 민원인 화면에도 같은 기록이 보입니다.'}
                  </span>
                </div>
                {busy === 'turn' && (
                  <div className="live-progress" style={{ marginTop: 10, marginBottom: 0 }}>
                    <span className="spinner" /> 양측의 주장을 정리해 쟁점 기록을 쓰는 중…
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {med?.sid && (
        <>
          {/* 쟁점 원장 — 쟁점마다 양측 유리·불리를 대칭으로 적는다(중립성의 근거). */}
          <div className="card">
            <div className="panel-head">
              <h2>쟁점 정리 {issues.length > 0 && <span className="muted" style={{ fontWeight: 500 }}>({issues.length}건)</span>}</h2>
              <div className="med-viewsw">
                <button className={view === 'shared' ? 'on' : ''} onClick={() => setView('shared')}>양측 공통</button>
                <button className={view === 'A' ? 'on' : ''} onClick={() => setView('A')}>{roleOf('A')} 관점</button>
                <button className={view === 'B' ? 'on' : ''} onClick={() => setView('B')}>{roleOf('B')} 관점</button>
              </div>
            </div>
            <div className="panel-pad">
              {issues.length === 0 ? (
                <Empty>아직 정리된 쟁점이 없습니다. 발언을 진행하면 쟁점이 하나씩 세워집니다.</Empty>
              ) : (
                issues.map((it, i) => (
                  <div key={i} className="med-issue">
                    <div className="sim-top">
                      <span style={{ fontWeight: 700, fontSize: 13.5 }}>{it.title}</span>
                      <Badge tone={ISSUE_TONE[it.status] || 'muted'}>{it.status}</Badge>
                    </div>
                    <span className="li-code">{it.code}</span>
                    <div className="med-sides">
                      <div className={`med-side a ${view === 'B' ? 'dim' : ''}`}>
                        <div className="who">{roleOf('A')}</div>
                        <div className="med-fact"><span className="k pro">유리</span><span>{it.for_a}</span></div>
                        <div className="med-fact"><span className="k con">불리</span><span>{it.against_a}</span></div>
                      </div>
                      <div className={`med-side b ${view === 'A' ? 'dim' : ''}`}>
                        <div className="who">{roleOf('B')}</div>
                        <div className="med-fact"><span className="k pro">유리</span><span>{it.for_b}</span></div>
                        <div className="med-fact"><span className="k con">불리</span><span>{it.against_b}</span></div>
                      </div>
                    </div>
                    <div className="med-note"><b>중재 자문</b> · {it.agent_note}</div>
                    <div className="med-decider">이 쟁점의 최종 판단 주체: <b>{it.decider}</b></div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* 중립성 밸런스 — '누구 편이냐'는 물음에 숫자로 답하는 자리. */}
          <div className="card">
            <div className="panel-head">
              <h2>중립성 확인</h2>
              <span className="muted" style={{ fontSize: 12 }}>자문 {entries.length}건 집계</span>
            </div>
            <div className="panel-pad">
              {entries.length === 0 ? (
                <Empty>중재 자문이 쌓이면 어느 쪽에 유리하게 작용했는지 집계해 보여 드립니다.</Empty>
              ) : (
                <>
                  <Balance entries={entries} roleA={roleOf('A')} roleB={roleOf('B')} />
                  <div style={{ marginTop: 12 }}>
                    {entries.map((e, i) => (
                      <div key={i} className="med-bal-row">
                        <span className="mono" style={{ fontSize: 11 }}>[{e.ref}]</span>
                        <span className={`med-lean ${e.leans}`}>
                          {e.leans === 'A' ? `${roleOf('A')} 유리` : e.leans === 'B' ? `${roleOf('B')} 유리` : '중립'}
                        </span>
                        <span>{e.summary}</span>
                      </div>
                    ))}
                  </div>
                  {med.balance?.note && (
                    <p className="muted" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>{med.balance.note}</p>
                  )}
                </>
              )}
            </div>
          </div>

          {/* 공유 처리이력 — 민원인과 직원이 같은 사본을 본다. */}
          <div className="card">
            <div className="panel-head">
              <h2>진행 기록</h2>
              <span className="muted" style={{ fontSize: 12 }}>{log.length}건 · 양측 공유</span>
            </div>
            <div className="panel-pad">
              {log.length === 0 ? (
                <Empty>아직 진행된 발언이 없습니다.</Empty>
              ) : (
                <div className="med-tl">
                  {log.map((l, i) => {
                    const meta = LOG_KIND[l.kind] || { cls: 'note', icon: '•' }
                    const mine = view !== 'shared' && l.speaker === keyOf(view)
                    return (
                      <div key={i} className={`med-tl-row ${meta.cls} ${mine ? 'mine' : ''}`}>
                        <div className="med-tl-head">
                          <span className="mono" style={{ fontSize: 11 }}>[{l.seq}]</span>
                          <span className={`med-tl-kind ${meta.cls}`}>{meta.icon} {l.kind}</span>
                          <span className="muted" style={{ fontSize: 11.5 }}>{nameOf(l.speaker)}</span>
                        </div>
                        <div className="med-tl-text">{l.text}</div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Balance({ entries, roleA, roleB }) {
  const cA = entries.filter((e) => e.leans === 'A').length
  const cB = entries.filter((e) => e.leans === 'B').length
  const cN = entries.length - cA - cB
  return (
    <>
      <div className="med-bal">
        <span className="sa" style={{ flex: cA }}>{cA || ''}</span>
        <span className="sn" style={{ flex: cN }}>{cN || ''}</span>
        <span className="sb" style={{ flex: cB }}>{cB || ''}</span>
      </div>
      <div className="row gap12" style={{ fontSize: 11.5, color: 'var(--muted)', flexWrap: 'wrap' }}>
        <span><i className="med-dot sa" /> {roleA} 유리 {cA}</span>
        <span><i className="med-dot sn" /> 중립 {cN}</span>
        <span><i className="med-dot sb" /> {roleB} 유리 {cB}</span>
      </div>
    </>
  )
}
