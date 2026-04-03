import { useState, useRef } from 'react'

const SEVERITY_COLOR = {
  critical: '#ef4444',
  high:     '#ff4d1a',
  moderate: '#facc15',
  low:      '#22c55e',
}

function statColor(label, value) {
  if (value == null) return '#9baac0'
  if (label === 'WIND')  return value >= 25 ? '#ef4444' : value >= 15 ? '#ff4d1a' : '#FBFBFB'
  if (label === 'RH')    return value < 12  ? '#ef4444' : value < 20  ? '#ff4d1a' : '#FBFBFB'
  if (label === 'SLOPE') return value >= 30 ? '#ff4d1a' : '#FBFBFB'
  if (label === 'AQI')   return value >= 151 ? '#ef4444' : value >= 101 ? '#ff4d1a' : value >= 51 ? '#facc15' : '#22c55e'
  return '#FBFBFB'
}

export default function WeatherPanel({ incidents, onClose }) {
  const active = incidents.filter(i => i.status === 'active' || i.status === 'contained')

  const PANEL_WIDTH = 900
  const PANEL_HEIGHT = 500

  const [pos, setPos] = useState({
    x: Math.round((window.innerWidth - PANEL_WIDTH) / 2),
    y: Math.round((window.innerHeight - PANEL_HEIGHT) / 2),
  })

  const dragging = useRef(false)
  const offset   = useRef({ x: 0, y: 0 })

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

  return (
    <div style={{
      position: 'fixed',
      left: `${pos.x}px`,
      top: `${pos.y}px`,
      width: '900px',                         // ✅ WIDER
      maxWidth: 'calc(100vw - 40px)',
      zIndex: 900,
      background: 'rgba(20,26,36,0.96)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '20px',
      boxShadow: '0 24px 56px rgba(0,0,0,0.52)',
      display: 'flex',
      flexDirection: 'column',
      maxHeight: '85vh',                      // ✅ MORE HEIGHT
      backdropFilter: 'blur(16px)',
    }}>
      
      {/* HEADER */}
      <div onMouseDown={onMouseDown} style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 20px',
        minHeight: '60px',
        borderBottom: '1px solid #262626',
        cursor: 'grab',
        userSelect: 'none',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '8px', height: '8px', borderRadius: '50%',
            background: '#22c55e', boxShadow: '0 0 8px #22c55e'
          }} />
          <span style={{
            fontFamily: 'var(--font-sans)',
            fontWeight: 700,
            fontSize: '13px',
            color: '#d4dce8',
            letterSpacing: '0.05em'
          }}>
            WEATHER · ALL ACTIVE INCIDENTS
          </span>
          <span style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '11px',
            color: '#8b9bb0'
          }}>
            {active.length} incidents
          </span>
        </div>

        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: '#9baac0',
            fontSize: '18px'
          }}
        >
          ✕
        </button>
      </div>

      {/* GRID */}
      <div style={{
        overflowY: 'auto',
        padding: '12px',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', // ✅ BETTER LAYOUT
        gap: '10px',
        width: '100%',
      }}>
        {active.map(inc => {
          const sevColor = SEVERITY_COLOR[inc.severity] ?? '#9baac0'
          const stats = [
            { label: 'WIND',  value: inc.wind_speed_mph != null   ? `${inc.wind_speed_mph} mph`        : '—',   raw: inc.wind_speed_mph },
            { label: 'RH',    value: inc.humidity_percent != null ? `${inc.humidity_percent}%`         : '—',   raw: inc.humidity_percent },
            { label: 'DIR',   value: inc.spread_direction         ?? '—', raw: null },
            { label: 'SLOPE', value: inc.slope_percent != null    ? `${inc.slope_percent.toFixed(0)}%` : '—',   raw: inc.slope_percent },
            { label: 'ELEV',  value: inc.elevation_m != null      ? `${Math.round(inc.elevation_m)}m`  : '—',   raw: null },
            { label: 'AQI',   value: inc.aqi != null              ? String(inc.aqi)                    : 'N/A', raw: inc.aqi },
          ]

          return (
            <div key={inc.id} style={{
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '14px',
              padding: '10px',
            }}>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                <div style={{
                  width: '6px', height: '6px',
                  borderRadius: '50%',
                  background: sevColor
                }} />
                <div style={{
                  fontWeight: 700,
                  fontSize: '12px',
                  color: '#d4dce8',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis'
                }}>
                  {inc.name}
                </div>
              </div>

              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: '6px 8px'
              }}>
                {stats.map(({ label, value, raw }) => (
                  <div key={label}>
                    <div style={{ fontSize: '9px', color: '#8b9bb0', marginBottom: '2px' }}>{label}</div>
                    <div style={{ fontWeight: 700, fontSize: '11px', color: statColor(label, raw) }}>{value}</div>
                  </div>
                ))}
              </div>

              <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid #262626' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                  <span style={{ fontSize: '9px', color: '#8b9bb0' }}>CONTAINMENT</span>
                  <span style={{
                    fontWeight: 700,
                    fontSize: '10px',
                    color: (inc.containment_percent ?? 0) > 50
                      ? '#22c55e'
                      : (inc.containment_percent ?? 0) > 20
                      ? '#ff4d1a'
                      : '#ef4444'
                  }}>
                    {inc.containment_percent ?? 0}%
                  </span>
                </div>

                <div style={{ height: '3px', background: 'rgba(255,255,255,0.07)', borderRadius: '2px' }}>
                  <div style={{
                    height: '100%',
                    borderRadius: '2px',
                    width: `${inc.containment_percent ?? 0}%`,
                    background: (inc.containment_percent ?? 0) > 50
                      ? '#22c55e'
                      : (inc.containment_percent ?? 0) > 20
                      ? '#ff4d1a'
                      : '#ef4444'
                  }} />
                </div>
              </div>

            </div>
          )
        })}
      </div>
    </div>
  )
}
