import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'
import Zikimi from '../Zikimi.jsx'

const MAX_FILES = 10

export default function NewComplaint() {
  const nav = useNavigate()
  const { loading, data: types } = useAsync(() => api.complainantProductTypes(), [])
  const [type, setType] = useState(null)
  const [facts, setFacts] = useState('')
  const [files, setFiles] = useState([])
  const [keywords, setKeywords] = useState(null) // 접수 전 AI 쟁점 확인 결과
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState('')
  const [newTerm, setNewTerm] = useState('')
  const [result, setResult] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const fileRef = useRef(null)

  if (loading || !types) return <Loading />

  // 유형·내용이 바뀌면 이전 분석은 낡은 것 → 초기화해 다시 확인하도록 유도.
  const onType = (v) => { setType(v); setKeywords(null); setAnalyzeError('') }
  const onFacts = (v) => { setFacts(v); if (keywords) setKeywords(null) }

  const pickFiles = (list) => {
    const picked = Array.from(list || []).map((f) => f.name)
    setFiles((prev) => [...prev, ...picked.filter((n) => !prev.includes(n))].slice(0, MAX_FILES))
    if (fileRef.current) fileRef.current.value = ''
  }

  const analyze = async () => {
    if (!type || !facts.trim()) return
    setAnalyzing(true); setAnalyzeError('')
    try {
      setKeywords(await api.analyzeComplaint(type, facts))
    } catch {
      setAnalyzeError('지금은 쟁점을 확인하지 못했어요. 확인 없이 그대로 접수하셔도 됩니다.')
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
    const res = await api.submitComplaint({ product_type: type, facts, attachments: files, keywords })
    setResult(res)
    setSubmitting(false)
  }

  if (result) {
    return (
      <div className="cx-narrow" style={{ textAlign: 'center', paddingTop: 50 }}>
        <Zikimi pose="done" size={96} style={{ margin: '0 auto' }} />
        <h2 style={{ marginTop: 16 }}>민원이 접수되었어요</h2>
        <p className="muted">담당자가 확인 후 검토를 시작하고, 진행 상황은 진행현황에서 알려 드려요.</p>
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
        <button className="cx-btn primary" style={{ width: '100%', marginTop: 20 }} onClick={() => nav('/app/progress')}>
          진행현황 보기
        </button>
        <button
          className="cx-btn" style={{ width: '100%', marginTop: 8 }}
          onClick={() => { setResult(null); setType(null); setFacts(''); setFiles([]); setKeywords(null); setNewTerm('') }}
        >
          새 민원 접수하기
        </button>
      </div>
    )
  }

  const ready = !!type && !!facts.trim()

  return (
    <div className="cx-narrow">
      <div className="cx-topbar"><h1>민원접수</h1></div>
      <p className="cx-case-sub" style={{ margin: '0 2px 6px' }}>
        어떤 상품에서 어떤 일이 있었는지 알려 주시면 담당자가 검토를 시작해요.
      </p>

      <div className="cx-label">금융상품 유형</div>
      <div className="cx-chips">
        {types.map((t) => (
          <button key={t.key} className={`cx-chip ${type === t.key ? 'on' : ''}`} onClick={() => onType(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="cx-label">
        어떤 일이 있었나요?
        <span className="sub">가입·상담 시점, 들으신 설명, 확인하고 싶은 점을 적어주세요.</span>
      </div>
      <textarea
        className="cx-textarea"
        placeholder="예: 2023년 3월 지점에서 원금이 보장된다는 설명만 듣고 가입했는데, 만기에 원금 손실이 발생했습니다."
        maxLength={1000}
        value={facts}
        onChange={(e) => onFacts(e.target.value)}
      />
      <div className="cx-count">{facts.length} / 1000</div>

      {/* 접수 전 쟁점 확인 — 민원인은 법률 용어를 모른다. 어떤 쟁점으로 접수되는지 먼저 보여주고
          직접 빼거나 더할 수 있게 한다(여기서 고른 쟁점이 담당자 검토의 출발점이 된다). */}
      <div className="cx-label">
        검토 쟁점 미리 확인 <span className="sub">선택 · 어떤 쟁점으로 접수되는지 미리 보고 고칠 수 있어요.</span>
      </div>
      {!keywords && (
        <button className="cx-btn" style={{ width: '100%' }} disabled={!ready || analyzing} onClick={analyze}>
          {analyzing ? '확인 중…' : '쟁점 확인하기'}
        </button>
      )}
      {analyzeError && <div className="cx-case-sub" style={{ marginTop: 8 }}>{analyzeError}</div>}

      {keywords && (
        <div className="cx-card" style={{ marginTop: 6 }}>
          {keywords.summary && (
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>“{keywords.summary}”</div>
          )}
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>이렇게 이해했어요 (눌러서 삭제하거나 아래에서 추가하세요)</div>
          <div className="cx-chips">
            {(keywords.issue_terms || []).map((t) => (
              <button key={t} className="cx-chip on" onClick={() => removeTerm(t)} title="눌러서 삭제">
                {t} ✕
              </button>
            ))}
            {(keywords.issue_terms || []).length === 0 && (
              <span className="muted" style={{ fontSize: 12 }}>확인된 쟁점이 없어요. 직접 추가해 주세요.</span>
            )}
          </div>
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input
              className="cx-select"
              style={{ flex: 1 }}
              placeholder="쟁점 직접 추가 (예: 위험 설명을 듣지 못함)"
              value={newTerm}
              onChange={(e) => setNewTerm(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addTerm() }}
            />
            <button className="cx-btn" onClick={addTerm} disabled={!newTerm.trim()}>추가</button>
          </div>
          {(keywords.entities || []).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>관련 상품·대상</div>
              <div className="cx-chips">
                {keywords.entities.map((t) => <span key={t} className="cx-chip">{t}</span>)}
              </div>
            </div>
          )}
          <button className="cx-btn" style={{ width: '100%', marginTop: 12 }} disabled={analyzing} onClick={analyze}>
            {analyzing ? '확인 중…' : '다시 확인하기'}
          </button>
        </div>
      )}

      <div className="cx-label">
        증빙자료
        <span className="sub">최대 {MAX_FILES}개 · 파일 목록이 담당자에게 전달되고, 원본은 담당자 요청 시 제출하시면 돼요.</span>
      </div>
      <button className="cx-dropzone" onClick={() => fileRef.current?.click()}>📎 파일 선택하기</button>
      <input ref={fileRef} type="file" multiple hidden onChange={(e) => pickFiles(e.target.files)} />
      {files.length > 0 && (
        <div className="cx-files">
          {files.map((n) => (
            <div key={n} className="cx-file-row">
              <span>📄</span>
              <span className="cx-file-name">{n}</span>
              <button className="cx-file-del" onClick={() => setFiles(files.filter((x) => x !== n))}>✕</button>
            </div>
          ))}
        </div>
      )}

      <div className="cx-submit">
        <button className="cx-btn primary" style={{ width: '100%' }} disabled={!ready || submitting} onClick={submit}>
          {submitting ? '제출 중…' : '민원 접수하기'}
        </button>
        {!ready && (
          <div className="cx-case-sub" style={{ textAlign: 'center', marginTop: 8 }}>
            상품 유형과 내용을 입력하시면 접수할 수 있어요.
          </div>
        )}
      </div>
    </div>
  )
}
