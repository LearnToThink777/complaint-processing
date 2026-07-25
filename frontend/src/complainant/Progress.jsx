import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'

// 발신자별 말풍선 스타일/아이콘 — 담당자·민원인·AI·시스템을 색으로 구분한다.
const SENDER_META = {
  담당자: { cls: 'by-staff', icon: '📋' },
  민원인: { cls: 'by-citizen', icon: '🙋' },
  'AI 분석': { cls: 'by-ai', icon: '🤖' },
  시스템: { cls: 'by-system', icon: '🔔' },
}

function fmtAt(at) {
  if (!at) return ''
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function Progress() {
  const { loading, data, reload } = useAsync(() => api.complainantProgress(), [])
  if (loading || !data) return <Loading />
  return <Tracker data={data} onReload={reload} />
}

function Tracker({ data, onReload }) {
  // 현재 단계는 기본 펼침. 나머지는 접어두고 클릭으로 펼친다(인터랙티브 트래커).
  const [open, setOpen] = useState(() => new Set([data.current]))
  const toggle = (i) =>
    setOpen((prev) => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  const stepClass = (i) => (i < data.current ? 'done' : i === data.current ? 'current' : 'pending')

  return (
    <div className="cx-narrow">
      <div className="cx-topbar"><h1>진행현황</h1></div>

      <div className="cx-dday-banner">
        <span className="icon">⏱️</span>
        <div style={{ flex: 1 }}>
          <div className="label">예상 완료일까지 {data.days_left}일 남았어요</div>
          <div className="big">D-{data.days_left}</div>
        </div>
        {data.risk && <span className="badge warn">지연 위험</span>}
      </div>

      <div className="cx-card" style={{ marginTop: 14 }}>
        <div className="cx-case-title">{data.title}</div>
        <div className="cx-case-sub">접수일 {data.intake_date}</div>
      </div>

      <div className="cx-timeline">
        {data.steps.map((s, i) => {
          const messages = s.messages || []
          const count = s.message_count ?? messages.length
          const hasMsg = count > 0
          const isOpen = open.has(i)
          const cls = stepClass(i)
          return (
            <div key={s.no} className={`cx-step ${cls} ${hasMsg ? 'has-msg' : ''} ${isOpen ? 'open' : ''}`}>
              <div className="cx-step-dot">{i < data.current ? '✓' : s.no}</div>
              <div className="cx-step-body">
                <button
                  type="button"
                  className="cx-step-toggle"
                  onClick={() => hasMsg && toggle(i)}
                  aria-expanded={hasMsg ? isOpen : undefined}
                  disabled={!hasMsg}
                >
                  <span className="cx-step-title">{String(s.no).padStart(2, '0')} {s.title}</span>
                  {hasMsg && <span className="cx-step-count">💬 {count}</span>}
                  {s.date && <span className="cx-step-date">{s.date}</span>}
                  {hasMsg && <span className="cx-chevron" aria-hidden>⌄</span>}
                </button>

                <div className="cx-step-desc">{s.body}</div>

                {hasMsg && isOpen && (
                  <div className="cx-msg-list">
                    {messages.map((m, k) => {
                      const meta = SENDER_META[m.sender] || { cls: 'by-system', icon: '💬' }
                      return (
                        <div key={k} className={`cx-msg ${meta.cls}`}>
                          <div className="cx-msg-head">
                            <span className="cx-msg-sender">{meta.icon} {m.sender}</span>
                            {m.at && <span className="cx-msg-at">{fmtAt(m.at)}</span>}
                          </div>
                          {m.title && <div className="cx-msg-title">{m.title}</div>}
                          <div className="cx-msg-body">{m.body}</div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {data.case_id && <Mediation mediation={data.mediation} onReload={onReload} />}
    </div>
  )
}

const MED_STATUS_TONE = { requested: 'warn', open: 'info', closed: 'good' }
const ISSUE_TONE = { 미확정: 'muted', 확인중: 'info', 자료대기: 'warn', 정리완료: 'good' }
const LOG_ICON = { 발언: '💬', 자문: '⚖️', 서기: '📝' }

// 협상·중재 — 민원인이 직접 요청하고, 진행 내역을 직원과 '같은 사본'으로 본다.
// (중재 기록은 이중공개와 달리 청중별로 다르게 쓰지 않는다 — 양측이 동일한 것을 보는 게 핵심.)
function Mediation({ mediation, onReload }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [openLog, setOpenLog] = useState(false)

  const request = async () => {
    setBusy(true); setErr(null)
    try {
      await api.complainantRequestMediation(reason)
      setReason('')
      onReload?.()
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  const m = mediation
  const issues = m?.issues || []
  const log = m?.log || []
  const partyName = (key) => (m?.parties || []).find((p) => p.key === key)?.role || (key === 'C' ? '중재자' : key)

  if (!m) {
    return (
      <div className="cx-card cx-med" style={{ marginTop: 16 }}>
        <div className="cx-med-head">
          <span className="cx-med-icon">🤝</span>
          <div style={{ flex: 1 }}>
            <div className="cx-case-title">협상·중재 요청</div>
            <div className="cx-case-sub">
              검토 결과에 대해 금융회사와 조율이 필요하면 중재를 요청할 수 있어요.
              중재자가 양측 이야기를 같은 기록으로 정리해 드려요.
            </div>
          </div>
        </div>
        <textarea
          className="cx-med-input" rows={2} value={reason}
          placeholder="어떤 점을 조율하고 싶은지 적어주세요 (선택)"
          onChange={(e) => setReason(e.target.value)}
        />
        {err && <div className="alert bad" style={{ fontSize: 12.5 }}>⚠ {err}</div>}
        <button className="cx-btn primary" onClick={request} disabled={busy}>
          {busy ? '요청 중…' : '협상·중재 요청하기'}
        </button>
      </div>
    )
  }

  return (
    <div className="cx-card cx-med" style={{ marginTop: 16 }}>
      <div className="cx-med-head">
        <span className="cx-med-icon">🤝</span>
        <div style={{ flex: 1 }}>
          <div className="cx-case-title">협상·중재 진행</div>
          <div className="cx-case-sub">
            {m.requested_by_subject || m.requested_by_ko} 요청 · {m.domain || '조율 진행 중'}
          </div>
        </div>
        <span className={`badge ${MED_STATUS_TONE[m.status] || 'muted'}`}>{m.status_ko}</span>
      </div>

      {m.reason && (
        <div className="cx-med-reason">
          <b>요청 내용</b>
          <div style={{ whiteSpace: 'pre-wrap' }}>{m.reason}</div>
        </div>
      )}

      {m.boundary && <div className="cx-med-note">⚖️ {m.boundary}</div>}

      {issues.length === 0 ? (
        <div className="cx-med-empty">
          아직 정리된 쟁점이 없어요. 중재가 진행되면 어떤 점이 쟁점인지, 각 쟁점에서
          어느 쪽에 유리·불리한 사실이 있는지 여기에 정리해 드릴게요.
        </div>
      ) : (
        <div className="cx-med-issues">
          <div className="cx-med-subhead">쟁점별 정리 ({issues.length}건)</div>
          {issues.map((it, i) => (
            <div key={i} className="cx-med-issue">
              <div className="cx-med-issue-top">
                <span className="cx-med-issue-title">{it.title}</span>
                <span className={`badge ${ISSUE_TONE[it.status] || 'muted'}`}>{it.status}</span>
              </div>
              <div className="cx-med-issue-code">{it.code}</div>
              <div className="cx-med-pair">
                <div className="pro"><b>고객님께 유리</b><span>{it.for_a}</span></div>
                <div className="con"><b>고객님께 불리</b><span>{it.against_a}</span></div>
              </div>
              <div className="cx-med-decider">이 쟁점의 최종 판단은 <b>{it.decider}</b>가 합니다.</div>
            </div>
          ))}
        </div>
      )}

      {log.length > 0 && (
        <>
          <button className="cx-med-toggle" onClick={() => setOpenLog((v) => !v)}>
            진행 기록 {log.length}건 {openLog ? '접기 ⌃' : '펼치기 ⌄'}
          </button>
          {openLog && (
            <div className="cx-med-log">
              {log.map((l, i) => (
                <div key={i} className="cx-med-log-row">
                  <span className="cx-med-log-icon">{LOG_ICON[l.kind] || '•'}</span>
                  <div>
                    <div className="cx-med-log-who">{partyName(l.speaker)} · {l.kind}</div>
                    <div className="cx-med-log-text">{l.text}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {err && <div className="alert bad" style={{ fontSize: 12.5, marginTop: 8 }}>⚠ {err}</div>}
      <details className="cx-med-more">
        <summary>추가로 조율하고 싶은 점 전달하기</summary>
        <textarea className="cx-med-input" rows={2} value={reason}
                  placeholder="추가로 전달할 내용을 적어주세요"
                  onChange={(e) => setReason(e.target.value)} />
        <button className="cx-btn" onClick={request} disabled={busy || !reason.trim()}>
          {busy ? '전달 중…' : '전달하기'}
        </button>
      </details>
    </div>
  )
}
