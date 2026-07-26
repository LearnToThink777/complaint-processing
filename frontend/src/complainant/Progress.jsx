import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
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

// 진행현황 — 민원 1건의 처리 과정. ?case= 로 어떤 민원을 볼지 지정한다(없으면 최근 민원).
// 여러 건을 접수한 민원인은 이력에서 카드를 눌러 각 민원의 기록으로 들어온다.
export default function Progress() {
  const [params] = useSearchParams()
  const caseId = params.get('case')
  const { loading, data, error } = useAsync(() => api.complainantProgress(caseId), [caseId])
  const nav = useNavigate()

  if (loading && !data) return <Loading />
  if (error) {
    return (
      <div className="cx-narrow">
        <div className="cx-topbar"><h1>진행현황</h1></div>
        <div className="cx-card" style={{ textAlign: 'center', padding: '26px 18px' }}>
          <div style={{ fontSize: 30 }}>🔍</div>
          <div className="cx-case-title" style={{ marginTop: 8 }}>민원을 찾을 수 없어요</div>
          <div className="cx-case-sub" style={{ marginTop: 4 }}>
            접수번호를 다시 확인해 주세요. 이력에서 민원을 선택하면 바로 열 수 있어요.
          </div>
          <button className="cx-btn primary" style={{ marginTop: 14 }} onClick={() => nav('/app/history')}>
            이력에서 고르기
          </button>
        </div>
      </div>
    )
  }
  if (!data) return <Loading />
  return <Tracker data={data} />
}

function Tracker({ data }) {
  const nav = useNavigate()
  // 현재 단계는 기본 펼침. 나머지는 접어두고 클릭으로 펼친다(인터랙티브 트래커).
  const [open, setOpen] = useState(() => new Set([data.current]))
  const toggle = (i) =>
    setOpen((prev) => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  const stepClass = (i) => (i < data.current ? 'done' : i === data.current ? 'current' : 'pending')
  const cases = data.cases || []
  const total = data.steps.reduce((n, s) => n + (s.entry_count ?? 0), 0)

  return (
    <div className="cx-narrow">
      <div className="cx-topbar"><h1>진행현황</h1></div>

      {/* 접수한 민원이 여러 건이면 여기서 바로 바꿘 볼 수 있게 한다. */}
      {cases.length > 1 && (
        <div className="cx-caseswitch">
          <span className="cx-caseswitch-label">내 민원 {cases.length}건</span>
          <div className="cx-caseswitch-list">
            {cases.map((c) => (
              <button
                key={c.case_id}
                className={c.current ? 'on' : ''}
                onClick={() => nav(`/app/progress?case=${encodeURIComponent(c.case_id)}`)}
                title={`${c.title} · ${c.status_ko}`}
              >
                {c.intake_date} · {c.title.length > 14 ? `${c.title.slice(0, 14)}…` : c.title}
              </button>
            ))}
          </div>
        </div>
      )}

      {data.case_id && (
        <div className="cx-dday-banner">
          <span className="icon">⏱️</span>
          <div style={{ flex: 1 }}>
            <div className="label">
              {data.status === 'closed' ? '처리가 끝난 민원이에요' : `예상 완료일까지 ${data.days_left}일 남았어요`}
            </div>
            <div className="big">{data.status === 'closed' ? '종결' : `D-${data.days_left}`}</div>
          </div>
          {data.risk && <span className="badge warn">지연 위험</span>}
        </div>
      )}

      <div className="cx-card" style={{ marginTop: 14 }}>
        <div className="cx-case-title">{data.title}</div>
        <div className="cx-case-sub">
          {data.case_id ? `접수번호 ${data.case_id} · 접수일 ${data.intake_date}` : '접수한 민원이 아직 없어요'}
        </div>
        {data.case_id && (
          <div className="cx-case-sub" style={{ marginTop: 4 }}>
            현재 <b>{data.status_ko}</b> · 처리 기록 {total}건
          </div>
        )}
      </div>

      <div className="cx-timeline">
        {data.steps.map((s, i) => {
          const entries = s.entries || []
          const count = s.entry_count ?? entries.length
          const hasLog = count > 0
          const isOpen = open.has(i)
          const cls = stepClass(i)
          return (
            <div key={s.no} className={`cx-step ${cls} ${hasLog ? 'has-msg' : ''} ${isOpen ? 'open' : ''}`}>
              <div className="cx-step-dot">{i < data.current ? '✓' : s.no}</div>
              <div className="cx-step-body">
                <button
                  type="button"
                  className="cx-step-toggle"
                  onClick={() => hasLog && toggle(i)}
                  aria-expanded={hasLog ? isOpen : undefined}
                  disabled={!hasLog}
                >
                  <span className="cx-step-title">{String(s.no).padStart(2, '0')} {s.title}</span>
                  {hasLog && <span className="cx-step-count">🗂 {count}</span>}
                  {s.date && <span className="cx-step-date">{s.date}</span>}
                  {hasLog && <span className="cx-chevron" aria-hidden>⌄</span>}
                </button>

                <div className="cx-step-desc">{s.body}</div>

                {hasLog && isOpen && (
                  <div className="cx-msg-list">
                    {entries.map((e, k) =>
                      // 같은 단계 안에서 '실제로 일어난 일(처리 기록)'과 '받은 안내(메시지)'를
                      // 시간순으로 섞어 보여준다 — 정적 카드가 아니라 사건이 어떻게 흘렀는지가 보이게.
                      e.kind === 'event' ? (
                        <div key={k} className="cx-event">
                          <span className="cx-event-dot" aria-hidden>✓</span>
                          <div className="cx-event-body">
                            <div className="cx-event-head">
                              <span className="cx-event-title">{e.title}</span>
                              {e.at && <span className="cx-msg-at">{fmtAt(e.at)}</span>}
                            </div>
                            <div className="cx-event-text">{e.body}</div>
                          </div>
                        </div>
                      ) : (
                        <Bubble key={k} m={e} />
                      ),
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {data.case_id && <MediationEntry caseId={data.case_id} mediation={data.mediation} />}
    </div>
  )
}

function Bubble({ m }) {
  const meta = SENDER_META[m.sender] || { cls: 'by-system', icon: '💬' }
  return (
    <div className={`cx-msg ${meta.cls}`}>
      <div className="cx-msg-head">
        <span className="cx-msg-sender">{meta.icon} {m.sender}</span>
        {m.at && <span className="cx-msg-at">{fmtAt(m.at)}</span>}
      </div>
      {m.title && <div className="cx-msg-title">{m.title}</div>}
      <div className="cx-msg-body">{m.body}</div>
    </div>
  )
}

const MED_TONE = { requested: 'warn', open: 'info', closed: 'good' }

// 협상·중재 진입 카드 — 내용은 담지 않고 '들어가는 문'만 둔다.
// (예전엔 진행현황 안에 중재 화면 전체가 들어 있어, 같은 내용이 직원 콘솔과 두 벌로 있었다.)
function MediationEntry({ caseId, mediation }) {
  const nav = useNavigate()
  const m = mediation
  const issues = (m?.issues || []).length

  return (
    <button
      className="cx-card cx-med-entry"
      onClick={() => nav(`/app/mediation?case=${encodeURIComponent(caseId)}`)}
    >
      <span className="cx-med-icon">🤝</span>
      <span className="cx-med-entry-main">
        <span className="cx-case-title">협상·중재</span>
        <span className="cx-case-sub">
          {m
            ? issues
              ? `쟁점 ${issues}건이 정리되어 있어요 — 눌러서 확인하세요`
              : '중재 진행 내용을 확인하세요'
            : '검토 결과에 대해 금융회사와 조율이 필요하면 중재를 요청할 수 있어요'}
        </span>
      </span>
      {m && <span className={`badge ${MED_TONE[m.status] || 'muted'}`}>{m.status_ko}</span>}
      <span className="cx-med-entry-arrow">›</span>
    </button>
  )
}
