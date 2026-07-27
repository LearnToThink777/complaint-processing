import { useNavigate } from 'react-router-dom'
import Zikimi from './Zikimi.jsx'
import './styles/landing.css'

// 첫 화면은 '어느 쪽으로 들어갈지' 고르는 자리다. 이 시스템의 사용자는 민원인과 기관
// 직원 둘뿐이므로 입구도 둘이다 — 협상·중재는 별도 입구가 아니라 각 포털 안의 기능이다.
export default function Landing() {
  const nav = useNavigate()
  return (
    <div className="landing">
      <div className="landing-inner">
        <div className="landing-brand">
          <span className="landing-logo"><Zikimi pose="shield" size={56} /></span>
          <div>
            <h1>금융 민원 처리 시스템</h1>
            <p>민원 접수부터 검토·판정, 협상·중재까지 한 곳에서 처리합니다.</p>
          </div>
        </div>

        <div className="landing-cards">
          <button className="landing-card" onClick={() => nav('/app')}>
            <div className="lc-icon cx"><Zikimi pose="wave" size={42} /></div>
            <h2>민원인 포털</h2>
            <p>민원을 접수하고 처리 진행 상황을 확인합니다.<br />민원접수 · 진행현황 · 협상·중재 · 이력</p>
            <span className="lc-cta">민원인으로 들어가기 &rarr;</span>
          </button>

          <button className="landing-card" onClick={() => nav('/staff')}>
            <div className="lc-icon staff"><Zikimi pose="docs" size={42} /></div>
            <h2>직원 포털</h2>
            <p>배정된 사건을 검토하고 판정·중재를 진행합니다.<br />사건접수 · 처리현황 · 협상·중재 · 고객 이력</p>
            <span className="lc-cta">직원으로 들어가기 &rarr;</span>
          </button>
        </div>

        <p className="landing-foot">
          접수하신 민원의 처리 단계와 결과는 민원인 포털 진행현황에서 언제든 확인하실 수 있습니다.
        </p>
      </div>
    </div>
  )
}
