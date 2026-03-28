import { BASE_URL } from '../api/client'
import { useState } from 'react'

const ROLE_COLOR = {
  commander:  '#F56E0F',
  dispatcher: '#60a5fa',
  viewer:     '#878787',
}

const ROLE_DESC = {
  commander:  'Full access — dispatch, briefings, all actions',
  dispatcher: 'Can view and approve dispatch',
  viewer:     'Read-only — no dispatch or briefings',
}

export default function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  async function handleLogin(e) {
    e.preventDefault()
    if (!username || !password) return
    setLoading(true)
    setError(null)

    try {
      const res = await fetch(`${BASE_URL}/api/auth/token`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ username, password }),
      })

      if (!res.ok) {
        let detail = `Login failed (${res.status})`
        try {
          const data = await res.json()
          detail = data.detail || detail
        } catch (_) {}
        throw new Error(detail)
      }

      const data = await res.json()
      onLogin(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      height: '100vh', width: '100vw',
      background: '#151419',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'Inter, sans-serif',
    }}>
      <div style={{ width: 'min(380px, 90vw)', padding: '0 16px' }}>

        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '40px' }}>
          <div style={{
            width: '40px', height: '40px', borderRadius: '6px',
            background: '#F56E0F',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 20px rgba(245,110,15,0.4)',
          }}>
            <span style={{ color: '#FBFBFB', fontWeight: 700, fontSize: '20px' }}>P</span>
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '22px', color: '#FBFBFB', letterSpacing: '0.04em' }}>
              Pyra
            </div>
            <div style={{ fontSize: '11px', color: '#878787', letterSpacing: '0.08em' }}>
              WILDFIRE COMMAND INTELLIGENCE
            </div>
          </div>
        </div>

        {/* Login card */}
        <div style={{
          background: '#1B1B1E',
          border: '1px solid #262626',
          borderRadius: '6px',
          padding: '28px',
        }}>
          <div style={{ fontWeight: 700, fontSize: '15px', color: '#FBFBFB', marginBottom: '6px' }}>
            Sign in
          </div>
          <div style={{ fontSize: '12px', color: '#878787', marginBottom: '24px' }}>
            Enter your credentials to access the command platform.
          </div>

          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', fontSize: '11px', color: '#878787', fontWeight: 600, letterSpacing: '0.06em', marginBottom: '6px' }}>
                USERNAME
              </label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="commander"
                autoFocus
                style={{
                  width: '100%', padding: '9px 12px',
                  background: '#151419', border: '1px solid #333',
                  borderRadius: '3px', color: '#FBFBFB',
                  fontFamily: 'Inter, sans-serif', fontSize: '13px',
                  outline: 'none', boxSizing: 'border-box',
                  transition: 'border-color 0.15s',
                }}
                onFocus={e => e.target.style.borderColor = '#F56E0F'}
                onBlur={e => e.target.style.borderColor = '#333'}
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '11px', color: '#878787', fontWeight: 600, letterSpacing: '0.06em', marginBottom: '6px' }}>
                PASSWORD
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                style={{
                  width: '100%', padding: '9px 12px',
                  background: '#151419', border: '1px solid #333',
                  borderRadius: '3px', color: '#FBFBFB',
                  fontFamily: 'Inter, sans-serif', fontSize: '13px',
                  outline: 'none', boxSizing: 'border-box',
                  transition: 'border-color 0.15s',
                }}
                onFocus={e => e.target.style.borderColor = '#F56E0F'}
                onBlur={e => e.target.style.borderColor = '#333'}
              />
            </div>

            {error && (
              <div style={{
                background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444',
                borderRadius: '3px', padding: '8px 12px',
                fontSize: '12px', color: '#ef4444', marginBottom: '14px',
              }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !username || !password}
              style={{
                width: '100%', padding: '11px',
                background: loading || !username || !password ? '#262626' : '#F56E0F',
                border: 'none', borderRadius: '3px',
                cursor: loading || !username || !password ? 'not-allowed' : 'pointer',
                fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px',
                color: '#FBFBFB', letterSpacing: '0.04em',
                transition: 'background 0.15s',
              }}
            >
              {loading ? 'SIGNING IN...' : 'SIGN IN'}
            </button>
          </form>
        </div>

        {/* Demo credentials */}
        <div style={{
          marginTop: '20px', background: '#1B1B1E',
          border: '1px solid #262626', borderRadius: '6px', padding: '16px',
        }}>
          <div style={{ fontSize: '10px', color: '#878787', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>
            DEMO CREDENTIALS — PASSWORD: pyra2025
          </div>
          {Object.entries(ROLE_DESC).map(([role, desc]) => (
            <div
              key={role}
              onClick={() => { setUsername(role); setPassword('pyra2025') }}
              style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                padding: '7px 8px', borderRadius: '3px', cursor: 'pointer',
                marginBottom: '4px', transition: 'background 0.1s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = '#262626'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: ROLE_COLOR[role], flexShrink: 0,
              }} />
              <div>
                <span style={{ fontSize: '12px', fontWeight: 600, color: ROLE_COLOR[role], marginRight: '8px' }}>
                  {role}
                </span>
                <span style={{ fontSize: '11px', color: '#878787' }}>{desc}</span>
              </div>
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}