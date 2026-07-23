import { useNavigate } from 'react-router-dom'
import './styles/landing.css'

export default function Landing() {
  const nav = useNavigate()
  return (
    <div className="landing">
      <div className="landing-inner">
        <div className="landing-brand">
          <span className="landing-logo">🛡️</span>
          <div>
            <h1>금융 민원 처리 시스템</h1>
            <p>AI 검토 · 이중 공개 · 소비자 권익 보호 — 시연 프로토타입</p>
          </div>
        </div>

        <div className="landing-cards">
          <button className="landing-card" onClick={() => nav('/staff')}>
            <div className="lc-icon staff">🗂️</div>
            <h2>직원 대시보드</h2>
            <p>사건 접수 · 처리현황 · AI 신뢰도 검증 · 이력 · 마이페이지</p>
            <span className="lc-cta">데스크탑 백오피스 &rarr;</span>
          </button>

          <button className="landing-card" onClick={() => nav('/app')}>
            <div className="lc-icon cx">🌐</div>
            <h2>민원인 포털</h2>
            <p>민원 접수 · 진행현황 · 이력 · 알림 설정</p>
            <span className="lc-cta">웹 포털 &rarr;</span>
          </button>

          <button className="landing-card" onClick={() => { window.location.href = '/mediation.html' }}>
            <div className="lc-icon med">🤝</div>
            <h2>협상·중재 콘솔</h2>
            <p>쟁점 원장 · 중립성 밸런스 · 실시간 LLM 중재 시뮬레이션</p>
            <span className="lc-cta">중재 콘솔 &rarr;</span>
          </button>
        </div>

        <p className="landing-foot">
          동일한 FastAPI 백엔드(<code>/api/*</code>)를 두 화면이 함께 사용합니다.
        </p>
      </div>
    </div>
  )
}
