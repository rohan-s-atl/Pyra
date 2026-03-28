import { useState, useEffect } from 'react'
import { BASE_URL } from '../api/client'

export default function SettingsPanel({ onClose }) {
  const [apiKey,    setApiKey]    = useState('')
  const [saved,     setSaved]     = useState(false)
  const [testing,   setTesting]   = useState(false)
  const [testResult, setTestResult] = useState(null)

  useEffect(() => {
    // Load existing key if running in Electron
    if (window.pyraElectron) {
      window.pyraElectron.getApiKey().then(key => setApiKey(key || ''))
    }
  }, [])

  async function handleSave() {
    if (window.pyraElectron) {
      const result = await window.pyraElectron.setApiKey(apiKey)
      if (result.success) {
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
        await window.pyraElectron.restartBackend()
      }
    } else {
      // In browser — just show instructions
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetch(`${BASE_URL}/health`)
      const data = await res.json()
      setTestResult({ ok: true, message: `Backend online — ${data.app} v${data.version}` })
    } catch {
      setTestResult({ ok: false, message: `Cannot reach backend at ${BASE_URL}` })
    } finally {
      setTesting(false)
    }
  }

  const isElectron = !!window.pyraElectron

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      zIndex: 4000, display: 'flex', alignItems: 'center', justifyContent: 'center',
      animation: 'fadeIn 0.15s ease',
    }}>
      <div style={{
        width: '480px', background: '#151419',
        border: '1px solid #262626', borderRadius: '8px',
        boxShadow: '0 16px 48px rgba(0,0,0,0.6)',
        animation: 'slideInUp 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid #262626' }}>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '14px', color: '#FBFBFB', letterSpacing: '0.04em' }}>SETTINGS</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#555', fontSize: '16px' }}>✕</button>
        </div>

        <div style={{ padding: '20px' }}>

          {/* API Key */}
          <div style={{ marginBottom: '24px' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: '#878787', letterSpacing: '0.08em', marginBottom: '8px' }}>
              ANTHROPIC API KEY
            </div>
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#555', marginBottom: '10px', lineHeight: 1.5 }}>
              Required for AI features: briefing generator, SITREP chat, dispatch advisor, alert triage, and post-incident review.
              {!isElectron && ' Set this in backend/.env as ANTHROPIC_API_KEY=sk-ant-...'}
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="sk-ant-api03-..."
                style={{
                  flex: 1, padding: '9px 12px',
                  background: '#1B1B1E', border: '1px solid #333',
                  borderRadius: '3px', color: '#FBFBFB',
                  fontFamily: 'Inter, sans-serif', fontSize: '12px', outline: 'none',
                }}
                onFocus={e => e.target.style.borderColor = '#F56E0F'}
                onBlur={e => e.target.style.borderColor = '#333'}
              />
              <button
                onClick={handleSave}
                disabled={!apiKey.trim()}
                style={{
                  padding: '9px 16px', background: apiKey.trim() ? (saved ? '#4ade80' : '#F56E0F') : '#262626',
                  border: 'none', borderRadius: '3px', cursor: apiKey.trim() ? 'pointer' : 'not-allowed',
                  fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: '#FBFBFB',
                  transition: 'background 0.15s', flexShrink: 0,
                }}
              >
                {saved ? '✓ SAVED' : 'SAVE'}
              </button>
            </div>
          </div>

          {/* Connection test */}
          <div style={{ marginBottom: '24px' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: '#878787', letterSpacing: '0.08em', marginBottom: '8px' }}>
              CONNECTION
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                onClick={handleTest}
                disabled={testing}
                style={{
                  padding: '8px 14px', background: 'transparent',
                  border: '1px solid #444', borderRadius: '3px', cursor: 'pointer',
                  fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#878787',
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = '#60a5fa'; e.currentTarget.style.color = '#60a5fa' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = '#444'; e.currentTarget.style.color = '#878787' }}
              >
                {testing ? 'TESTING...' : 'TEST CONNECTION'}
              </button>
              {testResult && (
                <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: testResult.ok ? '#4ade80' : '#ef4444' }}>
                  {testResult.ok ? '✓' : '✕'} {testResult.message}
                </span>
              )}
            </div>
          </div>

          {/* Keyboard shortcuts */}
          <div>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: '#878787', letterSpacing: '0.08em', marginBottom: '8px' }}>
              KEYBOARD SHORTCUTS
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              {[
                ['Esc',   'Close panels'],
                ['C',     'Toggle command view'],
                ['M',     'Toggle satellite map'],
                ['Enter', 'Confirm / Send chat'],
              ].map(([key, desc]) => (
                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{
                    fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px',
                    background: '#262626', border: '1px solid #333', borderRadius: '3px',
                    padding: '2px 7px', color: '#FBFBFB', minWidth: '36px', textAlign: 'center',
                  }}>{key}</span>
                  <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#878787' }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ padding: '12px 20px', borderTop: '1px solid #262626', display: 'flex', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{
              padding: '8px 20px', background: '#F56E0F', border: 'none',
              borderRadius: '3px', cursor: 'pointer',
              fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px', color: '#FBFBFB',
            }}
          >
            DONE
          </button>
        </div>
      </div>
    </div>
  )
}