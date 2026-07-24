import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'

export default function NewComplaint() {
  const { loading, data: types } = useAsync(() => api.complainantProductTypes(), [])
  const [type, setType] = useState(null)
  const [facts, setFacts] = useState('')
  const [keywords, setKeywords] = useState(null) // 접수 전 AI 쟁점 분석 결과(CaseKeywords)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState('')
  const [newTerm, setNewTerm] = useState('')
  const [result, setResult] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  if (loading || !types) return <Loading />

  // 유형·사실관계가 바뀌면 이전 분석은 낡은 것 → 초기화해 다시 분석하도록 유도.
  const onType = (v) => { setType(v); setKeywords(null); setAnalyzeError('') }
  const onFacts = (v) => { setFacts(v); if (keywords) setKeywords(null) }

  const analyze = async () => {
    if (!type || !facts.trim()) return
    setAnalyzing(true); setAnalyzeError('')
    try {
      const kw = await api.analyzeComplaint(type, facts)
      setKeywords(kw)
    } catch (err) {
      setAnalyzeError('쟁점 분석에 실패했어요. 분석 없이 바로 접수할 수 있습니다.')
    } finally {
      setAnalyzing(false)
    }
  }

  const removeTerm = (t) =>
    setKeywords((k) => ({ ...k, issue_terms: (k.issue_terms || []).filter((x) => x !== t) }))

  const addTerm = () => {
    const t = newTerm.trim()
    if (!t) return
    setKeywords((k) => {
      const cur = k.issue_terms || []
      return cur.includes(t) ? k : { ...k, issue_terms: [...cur, t] }
    })
    setNewTerm('')
  }

  const submit = async () => {
    if (!type || !facts.trim()) return
    setSubmitting(true)
    const res = await api.submitComplaint({ product_type: type, facts, attachments: [], keywords })
    setResult(res)
    setSubmitting(false)
  }

  if (result) {
    return (
      <div className="cx-page cx-narrow" style={{ textAlign: 'center', paddingTop: 60 }}>
        <div style={{ fontSize: 54 }}>✅</div>
        <h2 style={{ marginTop: 16 }}>민원이 접수되었어요</h2>
        <p className="muted">담당자가 곧 검토를 시작합니다.</p>
        <div className="cx-card" style={{ marginTop: 20, textAlign: 'left' }}>
          <div className="row between" style={{ padding: '4px 0' }}>
            <span className="muted">접수번호</span>
            <strong className="mono">{result.case_id}</strong>
          </div>
          <div className="row between" style={{ padding: '4px 0' }}>
            <span className="muted">상태</span>
            <span className="badge info">{result.status_ko}</span>
          </div>
        </div>
        <button className="btn primary block" style={{ marginTop: 20 }} onClick={() => { setResult(null); setType(null); setFacts(''); setKeywords(null); setNewTerm('') }}>
          확인
        </button>
      </div>
    )
  }

  const ready = !!type && !!facts.trim()

  return (
    <div className="cx-narrow">
      <div className="cx-topbar">
        <h1>‹ 민원접수</h1>
        <span style={{ fontSize: 16 }}>❔</span>
      </div>

      <div style={{ padding: '10px 18px 0' }}>
        <div style={{ fontSize: 20, fontWeight: 800 }}>새 민원 신청</div>
        <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>아래 정보를 입력해 주세요.</div>
      </div>

      <div className="cx-label">금융상품 유형</div>
      <select className="cx-select" value={type ?? ''} onChange={(e) => onType(e.target.value || null)}>
        <option value="">상품 유형 선택</option>
        {types.map((t) => (
          <option key={t.key} value={t.key}>{t.label}</option>
        ))}
      </select>
      <div className="cx-chips" style={{ marginTop: 10 }}>
        {types.map((t) => (
          <button key={t.key} className={`cx-chip ${type === t.key ? 'on' : ''}`} onClick={() => onType(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="cx-label">
        사실관계 입력
        <span className="sub">어떤 일이 있었는지 자세히 적어주세요.</span>
      </div>
      <textarea
        className="cx-textarea"
        placeholder="사실관계를 입력해 주세요."
        maxLength={1000}
        value={facts}
        onChange={(e) => onFacts(e.target.value)}
      />
      <div className="cx-count">{facts.length} / 1000</div>

      {/* 접수 전 AI 쟁점 분석 — 민원인이 검색어를 몰라도 AI가 쟁점을 잡아준다 */}
      <div className="cx-label">
        AI 쟁점 분석
        <span className="sub">제출 전에 어떤 쟁점으로 접수되는지 확인·보정할 수 있어요.</span>
      </div>
      {!keywords && (
        <button className="btn block" disabled={!ready || analyzing} onClick={analyze}>
          {analyzing ? '분석 중…' : '🔍 AI로 쟁점 분석하기'}
        </button>
      )}
      {analyzeError && <div className="muted" style={{ fontSize: 12, marginTop: 8, color: '#c0392b' }}>{analyzeError}</div>}

      {keywords && (
        <div className="cx-card" style={{ marginTop: 6 }}>
          {keywords.summary && (
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>“{keywords.summary}”</div>
          )}
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>AI가 파악한 검토 쟁점 (삭제하거나 추가할 수 있어요)</div>
          <div className="cx-chips">
            {(keywords.issue_terms || []).map((t) => (
              <button key={t} className="cx-chip on" onClick={() => removeTerm(t)} title="눌러서 삭제">
                {t} ✕
              </button>
            ))}
            {(keywords.issue_terms || []).length === 0 && (
              <span className="muted" style={{ fontSize: 12 }}>추출된 쟁점이 없어요. 직접 추가해 주세요.</span>
            )}
          </div>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input
              className="cx-select"
              style={{ flex: 1 }}
              placeholder="쟁점 직접 추가 (예: 설명의무 위반)"
              value={newTerm}
              onChange={(e) => setNewTerm(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addTerm() }}
            />
            <button className="btn" onClick={addTerm} disabled={!newTerm.trim()}>추가</button>
          </div>
          {(keywords.entities || []).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>관련 상품·대상</div>
              <div className="cx-chips">
                {keywords.entities.map((t) => <span key={t} className="cx-chip">{t}</span>)}
              </div>
            </div>
          )}
          <button className="btn block" style={{ marginTop: 12 }} disabled={analyzing} onClick={analyze}>
            {analyzing ? '분석 중…' : '↻ 다시 분석'}
          </button>
        </div>
      )}

      <div className="cx-label">
        증빙자료 첨부
        <span className="sub">파일은 최대 10개, 각 10MB까지 첨부 가능</span>
      </div>
      <div className="cx-dropzone">📎 파일 선택 또는 드래그</div>

      <div className="cx-submit">
        <button className="btn primary block" disabled={!ready || submitting} onClick={submit}>
          {submitting ? '제출 중…' : keywords ? '이대로 접수하기' : '제출하기'}
        </button>
      </div>
    </div>
  )
}
