import { useState, useRef, useEffect } from 'react'
import { streamChat } from '../api/client'
import { useAuth } from '../context/AuthContext'

function renderMarkdown(text) {
  if (!text) return null
  // Split into lines, process each
  const lines = text.split('\n')
  return lines.map((line, i) => {
    // Convert **bold** to <strong>
    const parts = line.split(/(\*\*[^*]+\*\*)/)
    const rendered = parts.map((part, j) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={j} style={{ color: '#d4dce8', fontWeight: 700 }}>{part.slice(2, -2)}</strong>
      }
      return part
    })
    return (
      <span key={i}>
        {rendered}
        {i < lines.length - 1 && <br />}
      </span>
    )
  })
}

function buildOpeningMessage(incident) {
  const parts = [
    `Pyra online. I have full situational awareness for **${incident.name}**`,
    `${(incident.acres_burned || 0).toLocaleString()} acres`,
    `${incident.containment_percent || 0}% contained`,
    `${(incident.spread_risk || '').toUpperCase()} spread risk`,
  ]

  const extras = []
  if (incident.wind_speed_mph != null)   extras.push(`wind ${incident.wind_speed_mph} mph`)
  if (incident.humidity_percent != null) extras.push(`RH ${incident.humidity_percent}%`)
  if (incident.aqi != null)              extras.push(`AQI ${incident.aqi}`)
  if (incident.slope_percent != null)    extras.push(`${incident.slope_percent.toFixed(0)}% slope`)

  let msg = parts.join(', ') + '.'
  if (extras.length) msg += ` Current conditions: ${extras.join(', ')}.`
  msg += ' What do you need?'
  return msg
}

export default function SitrepChat({ incident, onClose }) {
  const [messages,  setMessages]  = useState(() => [
    { role: 'assistant', content: buildOpeningMessage(incident) }
  ])

  useEffect(() => {
    setMessages([{ role: 'assistant', content: buildOpeningMessage(incident) }])
    setStreaming(false)
    setInput('')
  }, [incident.id])
  const [input,     setInput]     = useState('')
  const [streaming, setStreaming] = useState(false)
  const [pos,       setPos]       = useState({ x: window.innerWidth - 412, y: window.innerHeight - 660 })
  const bottomRef  = useRef(null)
  const dragging   = useRef(false)
  const offset     = useRef({ x: 0, y: 0 })
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    if (!input.trim() || streaming) return
    const userMsg = { role: 'user', content: input.trim() }
    const history = [...messages, userMsg]
    setMessages(history)
    setInput('')
    setStreaming(true)

    // Add empty assistant message to stream into
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    await streamChat(
      incident.id,
      history.filter(m => m.role !== 'assistant' || m.content).map(m => ({ role: m.role, content: m.content })),
      (chunk) => setMessages(prev => {
        const copy = [...prev]
        copy[copy.length - 1] = { role: 'assistant', content: copy[copy.length - 1].content + chunk }
        return copy
      }),
      () => setStreaming(false),
      (err) => { console.error('Chat error:', err); setStreaming(false) },
    )
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  return (
    <div style={{
      position: 'fixed', left: `${pos.x}px`, top: `${pos.y}px`,
      width: '380px', height: '480px',
      animation: 'slideInUp 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
      background: 'rgba(20,26,36,0.96)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '18px', zIndex: 2500,
      boxShadow: '0 24px 56px rgba(0,0,0,0.52)',
      display: 'flex', flexDirection: 'column',
      backdropFilter: 'blur(16px)',
    }}>
      {/* Header — drag handle */}
      <div
        onMouseDown={onMouseDown}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', borderBottom: '1px solid #262626', flexShrink: 0,
          cursor: 'grab', userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#ff4d1a', boxShadow: '0 0 6px #ff4d1a' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8', letterSpacing: '0.04em' }}>
            PYRA SITREP
          </span>
          <span className="pyra-ai-badge">⬡ AI</span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#5a6878' }}>
            {incident.name}
          </span>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#555', fontSize: '14px' }}>✕</button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}>
            <div style={{
              maxWidth: '85%',
              background: msg.role === 'user' ? 'rgba(245,110,15,0.15)' : '#1B1B1E',
              border: `1px solid ${msg.role === 'user' ? 'rgba(245,110,15,0.3)' : 'rgba(255,255,255,0.07)'}`,
              borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
              padding: '8px 12px',
              fontFamily: 'var(--font-sans)', fontSize: '12px',
              color: '#d4dce8', lineHeight: 1.7,
            }}>
              {msg.content
                ? renderMarkdown(msg.content)
                : (streaming && i === messages.length - 1
                    ? <span style={{ color: '#ff4d1a' }}>▋</span>
                    : '')
              }
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '10px 14px', borderTop: '1px solid #262626', flexShrink: 0, display: 'flex', gap: '8px' }}>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask about tactics, resources, weather..."
          rows={2}
          style={{
            flex: 1, background: 'var(--surface)', border: '1px solid #333',
            borderRadius: '4px', padding: '7px 10px', resize: 'none',
            fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#d4dce8',
            outline: 'none', lineHeight: 1.5,
          }}
          onFocus={e => e.target.style.borderColor = '#ff4d1a'}
          onBlur={e => e.target.style.borderColor = '#333'}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || streaming}
          style={{
            background: input.trim() && !streaming ? '#ff4d1a' : 'rgba(255,255,255,0.07)',
            border: 'none', borderRadius: '4px', padding: '0 14px',
            cursor: input.trim() && !streaming ? 'pointer' : 'not-allowed',
            fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px',
            color: '#d4dce8', letterSpacing: '0.04em', transition: 'background 0.15s',
            flexShrink: 0,
          }}
        >
          {streaming ? '...' : 'SEND'}
        </button>
      </div>
    </div>
  )
}
