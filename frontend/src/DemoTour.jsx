import { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import './styles/tour.css'

// 자동 시연 스크립트 — 경로 · 자막 · 머무는 시간(ms)
const SCRIPT = [
  { path: '/staff', cap: '직원 홈 — 담당 사건 요약과 최근 처리 내역', ms: 4500 },
  { path: '/staff/intake', cap: '사건접수 — 신규 이관 목록 + AI 자동 검토계획 (⚡ 실제 LLM 생성 가능)', ms: 5000 },
  { path: '/staff/status', cap: '처리현황 — 판정 원장 · AI 신뢰도 검증(PASS/ESCALATE/BLOCK) · 유사사례 RAG · 협상/중재', ms: 6000 },
  { path: '/staff/history', cap: '이력 — 반복 신고 패턴 감지 · 판정 일관성 점수', ms: 4500 },
  { path: '/staff/mypage', cap: '마이페이지 — 계정 · 알림 설정 · 활동 로그', ms: 4000 },
  { path: '/app', cap: '민원인 포털 · 홈 — 진행 중 민원과 예상 완료 D-day', ms: 4500 },
  { path: '/app/new', cap: '민원접수 — 상품유형 · 사실관계 · 증빙 첨부', ms: 4500 },
  { path: '/app/progress', cap: '진행현황 — 접수 → 검토 → 판정 → 협의 → 종결 타임라인', ms: 4500 },
  { path: '/app/history', cap: '이력 — 전체 / 진행중 / 종결 필터', ms: 4000 },
  { path: '/app/mypage', cap: '마이페이지 — 본인 인증 · 알림 설정', ms: 4000 },
]

export default function DemoTour() {
  const nav = useNavigate()
  const loc = useLocation()
  const [playing, setPlaying] = useState(false)
  const [idx, setIdx] = useState(0)
  const timer = useRef(null)

  // 랜딩(/)에서는 숨김 — 시연은 화면 안에서만.
  const hidden = loc.pathname === '/'

  useEffect(() => {
    if (!playing) return
    const step = SCRIPT[idx]
    nav(step.path)
    timer.current = setTimeout(() => {
      if (idx + 1 < SCRIPT.length) {
        setIdx(idx + 1)
      } else {
        setPlaying(false)
        setIdx(0)
      }
    }, step.ms)
    return () => clearTimeout(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, idx])

  const start = () => { setIdx(0); setPlaying(true) }
  const stop = () => { setPlaying(false); clearTimeout(timer.current) }

  if (hidden) return null

  return (
    <div className={`tour ${playing ? 'on' : ''}`}>
      {playing ? (
        <>
          <span className="tour-dot" />
          <span className="tour-step">{idx + 1}/{SCRIPT.length}</span>
          <span className="tour-cap">{SCRIPT[idx].cap}</span>
          <button className="tour-btn" onClick={stop}>⏸ 정지</button>
        </>
      ) : (
        <button className="tour-btn play" onClick={start}>▶ 자동 시연 재생</button>
      )}
    </div>
  )
}
