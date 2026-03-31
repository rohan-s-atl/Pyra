import { BASE_URL } from '../api/client'
import { useState } from 'react'

const ROLE_COLOR = {
  commander:  '#ff4d1a',
  dispatcher: '#38bdf8',
  viewer:     '#5a6878',
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
      background: '#0d0f11',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'var(--font-sans)',
      // Subtle grid background
      backgroundImage: 'radial-gradient(rgba(255,77,26,0.04) 1px, transparent 1px)',
      backgroundSize: '32px 32px',
    }}>
      <div style={{ width: 'min(400px, 90vw)', padding: '0 16px', animation: 'fade-up 0.4s ease-out' }}>

        {/* Logo + wordmark */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '40px' }}>
          <div style={{
            width: '44px', height: '44px', borderRadius: '10px',
            background: 'linear-gradient(135deg, #ff4d1a 0%, #c0320a 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 28px rgba(255,77,26,0.45), inset 0 1px 0 rgba(255,255,255,0.15)',
          }}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M10 2L10 10L17 14" stroke="white" strokeWidth="2.2" strokeLinecap="round"/>
              <path d="M10 10L3 14" stroke="white" strokeWidth="2.2" strokeLinecap="round"/>
              <circle cx="10" cy="10" r="2.5" fill="white"/>
            </svg>
          </div>
          <div>
            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '24px', color: '#edf2f7', letterSpacing: '0.08em', lineHeight: 1 }}>
              PYRA
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#3a4558', letterSpacing: '0.14em', marginTop: '3px' }}>
              WILDFIRE COMMAND INTELLIGENCE
            </div>
          </div>
        </div>

        {/* Login card */}
        <div style={{
          background: 'rgba(20,26,36,0.94)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '20px', padding: '28px',
          backdropFilter: 'blur(16px)',
          boxShadow: '0 24px 56px rgba(0,0,0,0.5)',
          marginBottom: '12px',
        }}>
          <div style={{ fontWeight: 700, fontSize: '15px', color: '#d4dce8', marginBottom: '5px' }}>
            Sign in to Pyra
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#3a4558', letterSpacing: '0.06em', marginBottom: '24px' }}>
            AUTHENTICATED ACCESS REQUIRED
          </div>

          <form onSubmit={handleLogin}>
            {['username', 'password'].map((field) => (
              <div key={field} style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 600, color: '#3a4558', letterSpacing: '0.1em', marginBottom: '6px' }}>
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
                color: canSubmit ? '#fff' : '#3a4558', letterSpacing: '0.1em',
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
          background: 'rgba(20,26,36,0.82)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '18px', padding: '16px',
          backdropFilter: 'blur(12px)',
        }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#3a4558', letterSpacing: '0.12em', marginBottom: '10px' }}>
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
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#3a4558' }}>{desc}</span>
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}
