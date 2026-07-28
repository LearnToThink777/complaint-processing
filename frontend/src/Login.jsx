import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, auth } from './api.js'
import Zikimi from './Zikimi.jsx'
import './styles/landing.css'

// 로그인은 '차단'이 아니라 '신원 판별'이다 — 로그인하지 않아도 두 포털이 그대로 열리고,
// 서버가 시드 계정 기준으로 응답한다. 로그인하면 그 사람 기준으로 바뀐다(활동 로그·담당자 귀속).
// 그래서 이 화면에도 '로그인 없이 둘러보기'를 남겨 둔다.
export default function Login() {
  const nav = useNavigate()
  // 세션 만료로 튕겨 왔으면 이유를 보여 준다(아무 설명 없이 로그인 화면이 뜨면 혼란스럽다).
  const expired = useLocation().state?.expired
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async (e) => {
    e?.preventDefault()
    setBusy(true); setErr(null)
    try {
      const r = await api.login(email.trim(), password)
      nav(r.user_type === 'staff' ? '/staff' : '/app')
    } catch (e2) {
      setErr(String(e2.message || e2))
    } finally {
      setBusy(false)
    }
  }

  const who = auth.user()

  return (
    <div className="landing">
      <div className="landing-inner" style={{ maxWidth: 460 }}>
        <div className="landing-brand">
          <span className="landing-logo"><Zikimi pose="shield" size={56} /></span>
          <div>
            <h1>로그인</h1>
            <p>민원인·직원 모두 같은 창구로 로그인합니다.</p>
          </div>
        </div>

        {expired && <div className="alert warn">⚠ {expired} 다시 로그인해 주세요.</div>}

        {who && (
          <p className="landing-foot" style={{ marginTop: 0 }}>
            현재 <b>{who.name}</b>님으로 로그인되어 있습니다. 다시 로그인하면 계정이 바뀝니다.
          </p>
        )}

        <form className="login-form" onSubmit={submit}>
          <label>
            <span>이메일</span>
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="hong.gildong@internal.com"
              disabled={busy}
            />
          </label>
          <label>
            <span>비밀번호</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
            />
          </label>

          {err && <div className="alert bad">⚠ {err}</div>}

          <button className="btn primary block" type="submit" disabled={busy || !email || !password}>
            {busy ? '확인 중…' : '로그인'}
          </button>
        </form>

        <button className="btn block" style={{ marginTop: 10 }} onClick={() => nav('/')}>
          로그인 없이 둘러보기
        </button>
      </div>
    </div>
  )
}
