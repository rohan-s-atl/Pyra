import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { streamReview } from '../api/client'
import { useAuth } from '../context/AuthContext'

function renderMarkdown(text) {
  if (!text) return null
  return text.split('\n').map((line, i, arr) => {
    // H3 ### 
    if (line.startsWith('### ')) return <div key={i} style={{ fontWeight: 700, fontSize: '11px', color: '#878787', letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: '14px', marginBottom: '4px' }}>{line.slice(4)}</div>
    // H2 ##
    if (line.startsWith('## ')) return <div key={i} style={{ fontWeight: 700, fontSize: '13px', color: '#FBFBFB', marginTop: '8px', marginBottom: '2px' }}>{line.slice(3)}</div>
    // H1 #
    if (line.startsWith('# ')) return <div key={i} style={{ fontWeight: 700, fontSize: '14px', color: '#F56E0F', marginBottom: '6px' }}>{line.slice(2)}</div>
    // Divider
    if (line.trim() === '---') return <div key={i} style={{ height: '1px', background: '#262626', margin: '10px 0' }} />
    // Empty line
    if (!line.trim()) return <div key={i} style={{ height: '6px' }} />
    // Bold inline
    const parts = line.split(/(\*\*[^*]+\*\*)/)
    const rendered = parts.map((part, j) =>
      part.startsWith('**') && part.endsWith('**')
        ? <strong key={j} style={{ color: '#FBFBFB', fontWeight: 700 }}>{part.slice(2, -2)}</strong>
        : part
    )
    return <div key={i} style={{ marginBottom: '4px' }}>{rendered}</div>
  })
}

export default function PostIncidentReview({ incident, onClose }) {
  const [review,   setReview]   = useState('')
  const [loading,  setLoading]  = useState(false)
  const [done,     setDone]     = useState(false)
  const [pos,      setPos]      = useState({ x: window.innerWidth - 520, y: 70 })
  const dragRef  = useRef(null)
  const dragging = useRef(false)
  const offset   = useRef({ x: 0, y: 0 })
  const auth = useAuth()

  function onMouseDown(e) {
    dragging.current = true
    offset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }
  function onMouseMove(e) {
    if (!dragging.current) return
    setPos({ x: e.clientX - offset.current.x, y: e.clientY - offset.current.y })
  }
  function onMouseUp() {
    dragging.current = false
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }

  async function handleGenerate() {
    setReview('')
    setLoading(true)
    setDone(false)
    await streamReview(
      incident.id,
      (chunk) => setReview(prev => prev + chunk),
      () => { setLoading(false); setDone(true) },
      (err) => { console.error('Review error:', err); setLoading(false) },
    )
  }

  function handleCopy() {
    navigator.clipboard.writeText(review).catch(() => {})
  }

  return createPortal(
    <div style={{
      position: 'fixed', left: `${pos.x}px`, top: `${pos.y}px`,
      width: '480px', height: '580px',
      animation: 'slideInUp 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
      background: 'rgba(20,26,36,0.97)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '20px', zIndex: 5200,
      boxShadow: '0 24px 56px rgba(0,0,0,0.56)',
      display: 'flex', flexDirection: 'column',
      backdropFilter: 'blur(16px)',
    }}>
      {/* Header — drag handle */}
      <div
        onMouseDown={onMouseDown}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: '1px solid #262626', flexShrink: 0,
          cursor: 'grab', userSelect: 'none',
        }}
      >
        <div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px', color: '#FBFBFB', letterSpacing: '0.04em' }}>
            POST-INCIDENT REVIEW  <span className="pyra-ai-badge" style={{marginLeft:'6px'}}>⬡ PYRA AI</span>
          </div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787', marginTop: '2px' }}>
            {incident.name} · Commander only
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {done && (
            <button
              onClick={handleCopy}
              style={{
                background: 'transparent', border: '1px solid #333', borderRadius: '3px',
                padding: '3px 8px', cursor: 'pointer',
                fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = '#4ade80'; e.currentTarget.style.color = '#4ade80' }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = '#333'; e.currentTarget.style.color = '#878787' }}
            >
              COPY
            </button>
          )}
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#555', fontSize: '14px' }}>✕</button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
        {!review && !loading && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '16px' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#878787', textAlign: 'center', lineHeight: 1.6 }}>
              Claude will analyze the full audit log and dispatch timeline for this incident and generate a structured lessons-learned document.
            </div>
            <button
              onClick={handleGenerate}
              style={{
                background: '#F56E0F', border: 'none', borderRadius: '4px',
                padding: '10px 24px', cursor: 'pointer',
                fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px',
                color: '#FBFBFB', letterSpacing: '0.04em',
              }}
            >
              GENERATE REVIEW
            </button>
          </div>
        )}
        {(review || loading) && (
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#FBFBFB', lineHeight: 1.7 }}>
            {renderMarkdown(review)}
            {loading && <span style={{ color: '#F56E0F' }}>▋</span>}
          </div>
        )}
      </div>

      {done && (
        <div style={{ padding: '10px 16px', borderTop: '1px solid #262626', flexShrink: 0 }}>
          <button
            onClick={handleGenerate}
            style={{
              width: '100%', padding: '8px', background: 'transparent',
              border: '1px solid #333', borderRadius: '3px', cursor: 'pointer',
              fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px',
              color: '#878787', letterSpacing: '0.04em', transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#F56E0F'; e.currentTarget.style.color = '#F56E0F' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = '#333'; e.currentTarget.style.color = '#878787' }}
          >
            ↺ REGENERATE
          </button>
        </div>
      )}
    </div>,
    document.body
  )
}
