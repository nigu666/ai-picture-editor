import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import AuthStatus from '@/components/AuthStatus'
import { errorMessage, useAuthActions, useCurrentUser } from '@/hooks/useAuth'

export default function AuthPage() {
  const current = useCurrentUser()
  const { login, register } = useAuthActions()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const action = mode === 'login' ? login : register

  if (current.isPending) return <AuthStatus />
  if (current.isError) return <AuthStatus onRetry={() => { void current.refetch() }} />
  if (current.data) return <Navigate to="/editor" replace />

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    action.mutate({ username, password })
  }

  function switchMode() {
    login.reset()
    register.reset()
    setPassword('')
    setMode(mode === 'login' ? 'register' : 'login')
  }

  return (
    <main className="auth-shell">
      <section className="auth-story" aria-label="AI 修图智能体">
        <div className="wordmark"><span className="brand-mark" aria-hidden="true">✦</span> AI 修图智能体</div>
        <div className="story-content">
          <p className="eyebrow">把想法，留在画面里</p>
          <h1>下一次编辑，<br />从这里开始。</h1>
          <p className="story-description">登录你的账号，进入图片创作工作区。</p>
          <div className="composition" aria-hidden="true">
            <svg viewBox="0 0 440 290" fill="none">
              <rect x="44" y="35" width="326" height="220" rx="8" fill="#fff" stroke="#c6d4e6" />
              <rect x="58" y="49" width="298" height="192" rx="3" fill="#dbe8f4" />
              <circle cx="292" cy="93" r="23" fill="#f9fbfe" />
              <path d="M58 193L146 112L223 182L283 139L356 209V241H58Z" fill="#afc5dc" />
              <path d="M58 218L128 172L222 221L298 176L356 218V241H58Z" fill="#87a8c7" />
              <rect x="133" y="74" width="132" height="174" rx="4" stroke="#2869d8" strokeWidth="2" strokeDasharray="6 5" />
              <circle cx="199" cy="128" r="24" fill="#315979" />
              <path d="M157 221V200C157 177 176 159 199 159C222 159 241 177 241 200V221" fill="#315979" />
              <path d="M125 94V66H153M245 66H273V94M273 228V256H245M153 256H125V228" stroke="#2869d8" strokeWidth="3" />
            </svg>
          </div>
        </div>
        <p className="story-footnote">每一幅画面，都从一个想法开始。</p>
      </section>
      <section className="auth-form-panel">
        <div className="auth-card">
          <p className="eyebrow">你的创作空间</p>
          <h2>{mode === 'login' ? '欢迎回来' : '创建账号'}</h2>
          <p className="form-description">{mode === 'login' ? '登录后继续你的图片创作。' : '创建账号，开启你的图片创作。'}</p>
          <form onSubmit={submit}>
            <label htmlFor="username">用户名</label>
            <input id="username" name="username" autoComplete="username" value={username}
              onChange={(event) => setUsername(event.target.value)} required minLength={3} maxLength={32}
              placeholder="输入用户名" aria-describedby="username-help" disabled={action.isPending} />
            <p className="field-help" id="username-help">3–32 位字母、数字或下划线</p>
            <label htmlFor="password">密码</label>
            <input id="password" name="password" type="password" value={password}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              onChange={(event) => setPassword(event.target.value)} required minLength={6} maxLength={64}
              placeholder="输入密码" disabled={action.isPending} />
            <p className="field-help">6–64 位；中文等字符还需符合编码长度限制</p>
            {action.isError && <p className="error-message" role="alert">{errorMessage(action.error)}</p>}
            <button className="primary submit" disabled={action.isPending}>
              {action.isPending ? '正在处理…' : mode === 'login' ? '登录工作区' : '注册并进入'}
              <span aria-hidden="true">↗</span>
            </button>
          </form>
          <button className="text-button switch-mode" onClick={switchMode} disabled={action.isPending}>
            {mode === 'login' ? '还没有账号？创建账号' : '已有账号？返回登录'}
          </button>
          <p className="auth-note">账号密码用于验证身份，请妥善保管。</p>
        </div>
      </section>
    </main>
  )
}
