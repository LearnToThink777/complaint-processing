import { useState } from 'react'
import { api } from '../api.js'
import { useAsync, Loading } from '../components.jsx'

export default function NewComplaint() {
  const { loading, data: types } = useAsync(() => api.complainantProductTypes(), [])
  const [type, setType] = useState(null)
  const [facts, setFacts] = useState('')
  const [result, setResult] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  if (loading || !types) return <Loading />

  const submit = async () => {
    if (!type || !facts.trim()) return
    setSubmitting(true)
    const res = await api.submitComplaint({ product_type: type, facts, attachments: [] })
    setResult(res)
    setSubmitting(false)
  }

  if (result) {
    return (
      <div className="cx-page" style={{ textAlign: 'center', paddingTop: 60 }}>
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
        <button className="btn primary block" style={{ marginTop: 20 }} onClick={() => { setResult(null); setType(null); setFacts('') }}>
          확인
        </button>
      </div>
    )
  }

  return (
    <div>
      <div className="cx-topbar">
        <h1>‹ 민원접수</h1>
        <span style={{ fontSize: 16 }}>❔</span>
      </div>

      <div style={{ padding: '10px 18px 0' }}>
        <div style={{ fontSize: 20, fontWeight: 800 }}>새 민원 신청</div>
        <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>아래 정보를 입력해 주세요.</div>
      </div>

      <div className="cx-label">금융상품 유형</div>
      <select className="cx-select" value={type ?? ''} onChange={(e) => setType(e.target.value || null)}>
        <option value="">상품 유형 선택</option>
        {types.map((t) => (
          <option key={t.key} value={t.key}>{t.label}</option>
        ))}
      </select>
      <div className="cx-chips" style={{ marginTop: 10 }}>
        {types.map((t) => (
          <button key={t.key} className={`cx-chip ${type === t.key ? 'on' : ''}`} onClick={() => setType(t.key)}>
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
        onChange={(e) => setFacts(e.target.value)}
      />
      <div className="cx-count">{facts.length} / 1000</div>

      <div className="cx-label">
        증빙자료 첨부
        <span className="sub">파일은 최대 10개, 각 10MB까지 첨부 가능</span>
      </div>
      <div className="cx-dropzone">📎 파일 선택 또는 드래그</div>

      <div className="cx-submit">
        <button className="btn primary block" disabled={!type || !facts.trim() || submitting} onClick={submit}>
          {submitting ? '제출 중…' : '제출하기'}
        </button>
      </div>
    </div>
  )
}
