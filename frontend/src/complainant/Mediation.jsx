import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading, josa } from '../components.jsx'

// 협상·중재(민원인 화면) — 진행현황의 진입 카드에서 들어온다.
// 직원 콘솔과 '같은 기록'을 보되, 표현만 민원인 쪽으로 옮긴다(A/B 대칭 표기 대신
// '고객님께 유리/불리'). 진행(발언 순서 등)은 중재자가 맡으므로 여기엔 조작이 없다.

const MED_TONE = { requested: 'warn', open: 'info', closed: 'good' }
const ISSUE_TONE = { 미확정: 'muted', 확인중: 'info', 자료대기: 'warn', 정리완료: 'good' }
const LOG_ICON = { 발언: '💬', 자문: '⚖️', 서기: '📝' }

export default function Mediation() {
  const nav = useNavigate()
  // 어떤 민원의 중재인지는 진행현황에서 넘겨받는다(민원이 여러 건일 수 있으므로).
  const [params] = useSearchParams()
  const caseId = params.get('case')
  const { loading, data, reload } = useAsync(() => api.complainantMediation(caseId), [caseId])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [openLog, setOpenLog] = useState(false)

  if (loading) return <Loading />

  const m = data?.mediation || null
  const issues = m?.issues || []
  const log = m?.log || []
  const partyName = (key) => (m?.parties || []).find((p) => p.key === key)?.role || (key === 'C' ? '중재자' : key)

  const send = async () => {
    setBusy(true); setErr(null)
    try {
      await api.complainantRequestMediation(reason, caseId)
      setReason('')
      reload()
    } catch (e) {
      setErr('요청을 전달하지 못했어요. 잠시 후 다시 시도해 주세요.')
    } finally { setBusy(false) }
  }

  return (
    <div className="cx-narrow">
      <div className="cx-topbar">
        <button
          className="cx-back"
          onClick={() => nav(caseId ? `/app/progress?case=${encodeURIComponent(caseId)}` : '/app/progress')}
        >
          ‹ 진행현황
        </button>
        <h1>협상·중재</h1>
      </div>

      {/* 이 기능이 무엇인지부터 — 민원인은 '중재'가 무엇을 해 주는지 모른 채 들어온다. */}
      <div className="cx-card cx-med-intro">
        <div className="cx-med-icon">🤝</div>
        <div>
          <div className="cx-case-title">중재자가 양측 이야기를 같은 기록으로 정리해요</div>
          <div className="cx-case-sub">
            검토 결과에 대해 금융회사와 조율이 필요할 때 이용하실 수 있어요. 쟁점마다 고객님께
            유리한 사실과 불리한 사실을 함께 정리해 드리고, 같은 기록을 담당자도 봅니다.
            <b> 최종 판단은 중재자가 아니라 각 쟁점의 판단 주체가 합니다.</b>
          </div>
        </div>
      </div>

      {!m ? (
        <div className="cx-card" style={{ marginTop: 14 }}>
          <div className="cx-case-title">협상·중재 요청하기</div>
          <div className="cx-case-sub" style={{ marginTop: 4 }}>
            어떤 점을 조율하고 싶으신지 적어 주시면 담당자에게 함께 전달돼요.
          </div>
          <textarea
            className="cx-med-input" rows={3} value={reason}
            placeholder="예: 가입 당시 위험 설명을 듣지 못했다는 점을 다시 확인받고 싶어요."
            onChange={(e) => setReason(e.target.value)}
          />
          {err && <div className="alert bad" style={{ fontSize: 12.5 }}>⚠ {err}</div>}
          <button className="cx-btn primary" onClick={send} disabled={busy}>
            {busy ? '요청 중…' : '협상·중재 요청하기'}
          </button>
        </div>
      ) : (
        <>
          <div className="cx-card" style={{ marginTop: 14 }}>
            <div className="row between">
              <div>
                <div className="cx-case-title">{m.domain || '조율 진행 중'}</div>
                <div className="cx-case-sub">{m.requested_by_subject || m.requested_by_ko} 요청</div>
              </div>
              <span className={`badge ${MED_TONE[m.status] || 'muted'}`}>{m.status_ko}</span>
            </div>
            {m.reason && (
              <div className="cx-med-reason">
                <b>요청 내용</b>
                <div style={{ whiteSpace: 'pre-wrap' }}>{m.reason}</div>
              </div>
            )}
            {m.boundary && <div className="cx-med-note">⚖️ {m.boundary}</div>}
          </div>

          <div className="cx-section"><h3>쟁점별 정리</h3></div>
          {issues.length === 0 ? (
            <div className="cx-card">
              <div className="cx-med-empty">
                아직 정리된 쟁점이 없어요. 중재가 진행되면 어떤 점이 쟁점인지, 각 쟁점에서
                어느 쪽에 유리·불리한 사실이 있는지 여기에 정리해 드릴게요.
              </div>
            </div>
          ) : (
            <div className="cx-med-issues">
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
                  <div className="cx-med-decider">
                    이 쟁점의 최종 판단은 <b>{it.decider}</b>{josa(it.decider)} 합니다.
                  </div>
                </div>
              ))}
            </div>
          )}

          {log.length > 0 && (
            <>
              <div className="cx-section"><h3>진행 기록</h3></div>
              <div className="cx-card">
                <button className="cx-med-toggle" onClick={() => setOpenLog((v) => !v)}>
                  전체 {log.length}건 {openLog ? '접기 ⌃' : '펼치기 ⌄'}
                </button>
                <div className="cx-med-log">
                  {(openLog ? log : log.slice(-3)).map((l, i) => (
                    <div key={i} className="cx-med-log-row">
                      <span className="cx-med-log-icon">{LOG_ICON[l.kind] || '•'}</span>
                      <div>
                        <div className="cx-med-log-who">{partyName(l.speaker)} · {l.kind}</div>
                        <div className="cx-med-log-text">{l.text}</div>
                      </div>
                    </div>
                  ))}
                </div>
                {!openLog && log.length > 3 && (
                  <div className="cx-case-sub" style={{ textAlign: 'center' }}>최근 3건만 표시하고 있어요</div>
                )}
              </div>
            </>
          )}

          <div className="cx-section"><h3>추가로 전달하기</h3></div>
          <div className="cx-card">
            <div className="cx-case-sub">조율하고 싶은 내용을 더 알려 주시면 기록에 함께 남겨 드려요.</div>
            <textarea className="cx-med-input" rows={3} value={reason}
                      placeholder="추가로 전달할 내용을 적어주세요"
                      onChange={(e) => setReason(e.target.value)} />
            {err && <div className="alert bad" style={{ fontSize: 12.5 }}>⚠ {err}</div>}
            <button className="cx-btn primary" onClick={send} disabled={busy || !reason.trim()}>
              {busy ? '전달 중…' : '전달하기'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
