import { BASE_URL } from '../api/client'
import { useState } from 'react'

const ROLE_COLOR = {
  commander:  '#ff4d1a',
  dispatcher: '#38bdf8',
  viewer:     '#8b9bb0',
}
const ROLE_DESC = {
  commander:  'Full access — dispatch, briefings, all actions',
  dispatcher: 'Can view and approve dispatches',
  viewer:     'Read-only — no dispatch actions',
}

export default function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const loginCardStyle = {
    position: 'relative',
    zIndex: 1,
    background: 'linear-gradient(180deg, rgba(24,31,43,0.9) 0%, rgba(18,24,35,0.94) 100%)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '20px',
    padding: '28px',
    backdropFilter: 'blur(16px)',
    boxShadow: '0 28px 68px rgba(0,0,0,0.44), inset 0 1px 0 rgba(255,255,255,0.05)',
  }

  const ambientOrbStyle = (background, width, height, top, left, right, bottom, animationDelay = '0s') => ({
    position: 'absolute',
    width,
    height,
    top,
    left,
    right,
    bottom,
    borderRadius: '999px',
    background,
    filter: 'blur(80px)',
    opacity: 0.7,
    animation: 'ambient-drift 16s ease-in-out infinite',
    animationDelay,
    pointerEvents: 'none',
  })

  async function handleLogin(e) {
    e.preventDefault()
    if (!username || !password) return
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${BASE_URL}/api/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        let detail = `Login failed (${res.status})`
        try { const d = await res.json(); detail = d.detail || detail } catch (_) {}
        throw new Error(detail)
      }
      onLogin(await res.json())
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  const canSubmit = !loading && username && password

  return (
    <div style={{
      height: '100vh', width: '100vw',
      position: 'relative',
      overflow: 'hidden',
      background: 'linear-gradient(180deg, #18212e 0%, #121a25 44%, #0e151e 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'var(--font-sans)',
    }}>
      <div style={ambientOrbStyle('radial-gradient(circle, rgba(255,115,56,0.32) 0%, rgba(255,115,56,0.12) 38%, rgba(255,115,56,0) 72%)', '420px', '420px', '-120px', '-90px', 'auto', 'auto')} />
      <div style={ambientOrbStyle('radial-gradient(circle, rgba(56,189,248,0.2) 0%, rgba(56,189,248,0.08) 42%, rgba(56,189,248,0) 74%)', '420px', '420px', 'auto', 'auto', '-120px', '-140px', '-5s')} />
      <div style={ambientOrbStyle('radial-gradient(circle, rgba(255,207,84,0.16) 0%, rgba(255,207,84,0.06) 36%, rgba(255,207,84,0) 72%)', '300px', '300px', 'auto', '12%', 'auto', '10%', '-9s')} />
      <div style={{
        position: 'absolute',
        inset: 0,
        backgroundImage: 'radial-gradient(rgba(255,255,255,0.035) 1px, transparent 1px)',
        backgroundSize: '34px 34px',
        maskImage: 'linear-gradient(180deg, rgba(0,0,0,0.95), rgba(0,0,0,0.7))',
        opacity: 0.55,
        pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute',
        inset: 0,
        background: 'linear-gradient(180deg, rgba(10,14,20,0.04) 0%, rgba(10,14,20,0.18) 100%)',
        pointerEvents: 'none',
      }} />
      <div style={{ width: 'min(400px, 90vw)', padding: '0 16px', animation: 'fade-up 0.45s ease-out', position: 'relative', zIndex: 1 }}>

        {/* Logo + wordmark */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '40px', animation: 'panel-float 10s ease-in-out infinite' }}>
          <div style={{
            width: '44px', height: '44px', borderRadius: '10px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            boxShadow: '0 0 28px rgba(245,110,15,0.34), inset 0 1px 0 rgba(255,255,255,0.08)',
          }}>
            <img
              src="/pyra-logo.svg"
              alt="Pyra logo"
              style={{
                width: '26px',
                height: '26px',
                display: 'block',
                filter: 'drop-shadow(0 0 16px rgba(245,110,15,0.55))',
              }}
            />
          </div>
          <div>
            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '24px', color: '#edf2f7', letterSpacing: '0.08em', lineHeight: 1 }}>
              PYRA
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#7a8ba0', letterSpacing: '0.14em', marginTop: '3px' }}>
              WILDFIRE COMMAND INTELLIGENCE
            </div>
          </div>
        </div>

        {/* Login card */}
        <div style={{ ...loginCardStyle, marginBottom: '12px', animation: 'panel-float 11s ease-in-out infinite', animationDelay: '-1.2s' }}>
          <div style={{ fontWeight: 700, fontSize: '15px', color: '#d4dce8', marginBottom: '5px' }}>
            Sign in to Pyra
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#7a8ba0', letterSpacing: '0.06em', marginBottom: '24px' }}>
            AUTHENTICATED ACCESS REQUIRED
          </div>

          <form onSubmit={handleLogin}>
            {['username', 'password'].map((field) => (
              <div key={field} style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 600, color: '#7a8ba0', letterSpacing: '0.1em', marginBottom: '6px' }}>
                  {field.toUpperCase()}
                </label>
                <input
                  type={field === 'password' ? 'password' : 'text'}
                  value={field === 'username' ? username : password}
                  onChange={e => field === 'username' ? setUsername(e.target.value) : setPassword(e.target.value)}
                  placeholder={field === 'username' ? 'commander' : '••••••••'}
                  autoFocus={field === 'username'}
                  style={{
                    width: '100%', padding: '10px 13px',
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '12px', color: '#d4dce8',
                    fontFamily: 'var(--font-mono)', fontSize: '13px',
                    outline: 'none', boxSizing: 'border-box',
                    transition: 'border-color 0.15s, box-shadow 0.15s',
                    letterSpacing: field === 'password' ? '0.1em' : '0',
                  }}
                  onFocus={e => { e.target.style.borderColor = 'rgba(255,77,26,0.4)'; e.target.style.boxShadow = '0 0 0 3px rgba(255,77,26,0.08)' }}
                  onBlur={e => { e.target.style.borderColor = 'rgba(255,255,255,0.08)'; e.target.style.boxShadow = 'none' }}
                />
              </div>
            ))}

            {error && (
              <div style={{
                background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: '12px', padding: '9px 12px',
                fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#ef4444',
                letterSpacing: '0.04em', marginBottom: '14px',
              }}>
                {error}
              </div>
            )}

            <button
              id="pyra-login-btn"
              type="submit"
              disabled={!canSubmit}
              style={{
                width: '100%', padding: '12px',
                background: canSubmit ? '#ff4d1a' : 'rgba(255,255,255,0.04)',
                border: 'none', borderRadius: '14px',
                cursor: canSubmit ? 'pointer' : 'not-allowed',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '11px',
                color: canSubmit ? '#fff' : '#7a8ba0', letterSpacing: '0.1em',
                transition: 'all 0.15s',
                boxShadow: canSubmit ? '0 0 20px rgba(255,77,26,0.3)' : 'none',
              }}
              onMouseEnter={e => { if (canSubmit) e.currentTarget.style.background = '#e03d10' }}
              onMouseLeave={e => { if (canSubmit) e.currentTarget.style.background = '#ff4d1a' }}
            >
              {loading ? 'AUTHENTICATING…' : 'SIGN IN'}
            </button>
          </form>
        </div>

        {/* Demo credentials */}
        <div style={{
          ...loginCardStyle,
          background: 'linear-gradient(180deg, rgba(24,31,43,0.78) 0%, rgba(18,24,35,0.86) 100%)',
          borderRadius: '18px', padding: '16px',
          backdropFilter: 'blur(12px)',
          animation: 'panel-float 12s ease-in-out infinite',
          animationDelay: '-4s',
        }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#7a8ba0', letterSpacing: '0.12em', marginBottom: '10px' }}>
            DEMO CREDENTIALS · PASSWORD: pyra2025
          </div>
          {Object.entries(ROLE_DESC).map(([role, desc]) => (
            <div
              key={role}
              onClick={() => {
                setUsername(role); setPassword('pyra2025')
                setTimeout(() => document.getElementById('pyra-login-btn')?.click(), 50)
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                padding: '8px 10px', borderRadius: '12px', cursor: 'pointer',
                marginBottom: '2px', transition: 'background 0.1s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: ROLE_COLOR[role], boxShadow: `0 0 6px ${ROLE_COLOR[role]}`, flexShrink: 0 }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', fontWeight: 600, color: ROLE_COLOR[role], letterSpacing: '0.04em', flexShrink: 0, minWidth: '80px' }}>
                {role}
              </span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#7a8ba0' }}>{desc}</span>
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}
