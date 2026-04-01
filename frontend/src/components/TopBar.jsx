import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { formatClockTime, formatTimezone } from '../utils/timeUtils'
import { BASE_URL } from '../api/client'

const THREAT_COLOR = {
  low:      '#22c55e',
  moderate: '#38bdf8',
  high:     '#f59e0b',
  extreme:  '#ef4444',
}

export default function TopBar({
  incidents, units,
  showEvacZones, onToggleEvacZones,
  showFireGrowth, onToggleFireGrowth,
  showPerimeters, onTogglePerimeters,
  showHeatmap, onToggleHeatmap,
  showCommand, onToggleCommand,
  showSatellite, onToggleSatellite,
  showWeather, onToggleWeather,
  showWaterSources, onToggleWaterSources,
  auth, onLogout, onToggleAudit, onToggleSettings,
}) {
  const [time, setTime] = useState(new Date())
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [optionsPos, setOptionsPos] = useState(null)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [userMenuPos, setUserMenuPos] = useState(null)
  const [aiReady, setAiReady] = useState(null)
  const optBtnRef = useRef(null)
  const userBtnRef = useRef(null)

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    fetch(`${BASE_URL}/health`)
      .then(r => r.json())
      .then(d => setAiReady(!!d.ai_ready))
      .catch(() => setAiReady(false))
  }, [])

  useEffect(() => {
    if (!optionsOpen) return
    const h = (e) => {
      if (!e.target.closest('[data-opts-menu]') && !e.target.closest('[data-opts-btn]'))
        setOptionsOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [optionsOpen])

  useEffect(() => {
    if (!userMenuOpen) return
    const h = (e) => {
      if (!e.target.closest('[data-user-menu]') && !e.target.closest('[data-user-btn]'))
        setUserMenuOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [userMenuOpen])

  const activeInc = incidents.filter(i => i.status === 'active' || i.status === 'contained')
  const assignedUnits = units.filter(u => u.assigned_incident_id)
  const criticalCount = incidents.filter(i => i.severity === 'critical').length

  const avgContainment = activeInc.length
    ? Math.round(activeInc.reduce((s, i) => s + (i.containment_percent ?? 0), 0) / activeInc.length)
    : 0
  const minHumidity = activeInc.length ? Math.min(...activeInc.map(i => i.humidity_percent ?? 100)) : 0
  const maxAqi = activeInc.length ? Math.max(...activeInc.map(i => i.aqi ?? 0)) : 0

  const threatLevel = activeInc.some(i => i.severity === 'critical') ? 'extreme'
    : activeInc.some(i => i.severity === 'high') ? 'high'
    : activeInc.some(i => i.severity === 'moderate') ? 'moderate' : 'low'

  const stats = [
    { label: 'INCIDENTS',   value: activeInc.length,                   color: activeInc.length > 0 ? '#ff4d1a' : '#22c55e' },
    { label: 'DEPLOYED',    value: `${assignedUnits.length}/${units.length}`, color: '#f59e0b' },
    { label: 'CONTAIN',     value: `${avgContainment}%`,               color: avgContainment > 50 ? '#22c55e' : avgContainment > 20 ? '#f59e0b' : '#ef4444' },
    { label: 'RH',          value: `${minHumidity}%`,                  color: minHumidity < 15 ? '#ef4444' : '#d4dce8' },
    { label: 'AQI',         value: maxAqi > 0 ? maxAqi : '—',          color: maxAqi >= 151 ? '#ef4444' : maxAqi >= 101 ? '#f59e0b' : maxAqi >= 51 ? '#facc15' : maxAqi > 0 ? '#22c55e' : '#8b9bb0' },
    { label: 'THREAT',      value: threatLevel.toUpperCase(),           color: THREAT_COLOR[threatLevel] },
  ]

  const layers = [
    { label: 'EVAC ZONES',     active: showEvacZones,    onClick: onToggleEvacZones,    dot: '#ef4444', hotkey: '1' },
    { label: 'FIRE GROWTH',    active: showFireGrowth,   onClick: onToggleFireGrowth,   dot: '#ff4d1a', hotkey: '2' },
    { label: 'PERIMETERS',     active: showPerimeters,   onClick: onTogglePerimeters,   dot: '#f59e0b', hotkey: '3' },
    { label: 'HEAT MAP',       active: showHeatmap,      onClick: onToggleHeatmap,      dot: '#ef4444', hotkey: '4' },
    { label: 'SATELLITE',      active: showSatellite,    onClick: onToggleSatellite,    dot: '#38bdf8', hotkey: '5' },
    { label: 'WEATHER',        active: showWeather,      onClick: onToggleWeather,      dot: '#22c55e', hotkey: '6' },
    { label: 'WATER SOURCES',  active: showWaterSources, onClick: onToggleWaterSources, dot: '#38bdf8', hotkey: '7' },
  ]

  const roleColor = auth?.role === 'commander' ? '#ff4d1a' : auth?.role === 'dispatcher' ? '#38bdf8' : '#8b9bb0'

  const S = {
    bar: {
      height: '58px',
      margin: '8px 8px 0',
      borderRadius: '20px',
      background: 'linear-gradient(180deg, rgba(28,35,47,0.92) 0%, rgba(18,24,34,0.94) 100%)',
      border: '1px solid rgba(255,255,255,0.1)',
      display: 'flex', alignItems: 'center', gap: '0',
      padding: '0 16px',
      flexShrink: 0,
      position: 'relative', zIndex: 9000,
      backdropFilter: 'blur(14px)',
      boxShadow: '0 18px 38px rgba(0,0,0,0.32), inset 0 1px 0 rgba(255,255,255,0.05)',
    },
    divider: { width: '1px', height: '28px', background: 'rgba(255,255,255,0.08)', flexShrink: 0, margin: '0 14px' },
  }

  return (
    <div className="ui-shell-panel" style={S.bar}>

      {/* LOGO */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
        <div style={{
          width: '30px', height: '30px', borderRadius: '7px',
          background: 'linear-gradient(135deg, #ff4d1a 0%, #c0320a 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 0 16px rgba(255,77,26,0.45), inset 0 1px 0 rgba(255,255,255,0.15)',
          flexShrink: 0,
        }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 1 L7 7 L12 10" stroke="white" strokeWidth="1.8" strokeLinecap="round"/>
            <path d="M7 7 L2 10" stroke="white" strokeWidth="1.8" strokeLinecap="round"/>
            <circle cx="7" cy="7" r="1.5" fill="white"/>
          </svg>
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '14px', color: '#edf2f7', letterSpacing: '0.05em', lineHeight: 1 }}>
            PYRA
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.1em', lineHeight: 1, marginTop: '2px' }}>
            WILDFIRE C2
          </div>
        </div>
      </div>

      <div style={S.divider} />

      {/* AI STATUS */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        padding: '4px 10px',
        background: aiReady === false ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.07)',
        border: `1px solid ${aiReady === false ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.18)'}`,
        borderRadius: '4px', flexShrink: 0,
      }}>
        <div style={{
          width: '5px', height: '5px', borderRadius: '50%',
          background: aiReady === false ? '#ef4444' : '#22c55e',
          boxShadow: `0 0 8px ${aiReady === false ? '#ef4444' : '#22c55e'}`,
          animation: aiReady !== false ? 'status-blink 2.5s ease-in-out infinite' : 'none',
        }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: '10px', color: aiReady === false ? '#ef4444' : '#22c55e', letterSpacing: '0.06em' }}>
          {aiReady === false ? 'AI OFFLINE' : 'AGENT LIVE'}
        </span>
      </div>

      <div style={S.divider} />

      {/* LAYER TOGGLE BUTTON */}
      <div ref={optBtnRef}>
        <button
          className="ui-interactive-btn"
          data-opts-btn="true"
          onClick={() => {
            if (optionsOpen) { setOptionsOpen(false); return }
            const r = optBtnRef.current?.getBoundingClientRect()
            if (r) setOptionsPos({ top: r.bottom + 6, left: r.left })
            setOptionsOpen(true)
          }}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            background: optionsOpen ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '10px', padding: '6px 12px', cursor: 'pointer',
            fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: '10px',
            color: optionsOpen ? '#f1f5f9' : '#b7c4d4', letterSpacing: '0.08em',
            transition: 'all 0.15s', flexShrink: 0,
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="1" y="2" width="10" height="1.5" rx="0.75"/>
            <rect x="1" y="5.25" width="10" height="1.5" rx="0.75"/>
            <rect x="1" y="8.5" width="10" height="1.5" rx="0.75"/>
          </svg>
          LAYERS
          <span style={{ fontSize: '8px', opacity: 0.5 }}>{optionsOpen ? '▲' : '▼'}</span>
        </button>
      </div>

      {/* STATS — center */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'stretch', minWidth: 0, margin: '0 4px', overflow: 'hidden' }}>
        {stats.map((s, i) => (
          <div key={s.label} style={{
            flex: '1 1 90px', minWidth: '72px',
            padding: '0 14px',
            borderRight: i < stats.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
            display: 'flex', flexDirection: 'column', justifyContent: 'center',
            overflow: 'hidden',
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 500, color: '#8b9bb0', letterSpacing: '0.1em', marginBottom: '2px', whiteSpace: 'nowrap' }}>
              {s.label}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '14px', color: s.color, lineHeight: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* RIGHT SECTION */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>

        {/* COMMAND BUTTON */}
        <button
          className="ui-interactive-btn"
          onClick={onToggleCommand}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            background: showCommand ? 'rgba(56,189,248,0.12)' : 'rgba(255,255,255,0.03)',
            border: `1px solid ${showCommand ? 'rgba(56,189,248,0.26)' : 'rgba(255,255,255,0.1)'}`,
            borderRadius: '10px', padding: '6px 12px', cursor: 'pointer',
            transition: 'all 0.2s', flexShrink: 0,
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke={showCommand ? '#38bdf8' : '#b7c4d4'} strokeWidth="1.5">
            <rect x="1" y="1" width="4.5" height="4.5" rx="1"/>
            <rect x="6.5" y="1" width="4.5" height="4.5" rx="1"/>
            <rect x="1" y="6.5" width="4.5" height="4.5" rx="1"/>
            <rect x="6.5" y="6.5" width="4.5" height="4.5" rx="1"/>
          </svg>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: '10px', color: showCommand ? '#38bdf8' : '#d4dce8', letterSpacing: '0.08em' }}>
            COMMAND
          </span>
          {criticalCount > 0 && (
            <span style={{
              background: '#ef4444', color: '#fff',
              fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px',
              borderRadius: '10px', padding: '1px 5px', lineHeight: 1.4,
              boxShadow: '0 0 8px rgba(239,68,68,0.5)',
            }}>{criticalCount}</span>
          )}
        </button>

        <div style={S.divider} />

        {/* USER MENU */}
        {auth && (
          <div style={{ position: 'relative' }}>
            <button
              className="ui-interactive-btn"
              ref={userBtnRef}
              data-user-btn="true"
              onClick={() => {
                if (userMenuOpen) {
                  setUserMenuOpen(false)
                  return
                }
                const r = userBtnRef.current?.getBoundingClientRect()
                if (r) {
                  setUserMenuPos({ top: r.bottom + 8, right: Math.max(window.innerWidth - r.right, 8) })
                }
                setUserMenuOpen(true)
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: '8px',
                background: userMenuOpen ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '10px', padding: '6px 10px', cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              <div style={{ width: '22px', height: '22px', borderRadius: '50%', background: 'rgba(255,255,255,0.06)', border: `1px solid ${roleColor}40`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: roleColor, boxShadow: `0 0 6px ${roleColor}` }} />
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '12px', color: '#d4dce8', lineHeight: 1 }}>{auth.username}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.06em', lineHeight: 1, marginTop: '2px' }}>{auth.role?.toUpperCase()}</div>
              </div>
              <span style={{ color: '#8b9bb0', fontSize: '8px' }}>{userMenuOpen ? '▲' : '▼'}</span>
            </button>
          </div>
        )}

        {/* CLOCK */}
        <div style={{ textAlign: 'right', flexShrink: 0, paddingLeft: '4px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '18px', color: '#d4dce8', letterSpacing: '0.02em', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
            {formatClockTime(time)}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.1em', marginTop: '2px' }}>
            {formatTimezone(time)}
          </div>
        </div>
      </div>

      {/* LAYERS DROPDOWN */}
      {optionsOpen && optionsPos && createPortal(
        <div
          className="ui-panel-enter"
          data-opts-menu="true"
          style={{
            position: 'fixed', top: optionsPos.top, left: optionsPos.left, zIndex: 99999,
            background: 'rgba(22,28,38,0.96)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '14px', overflow: 'hidden',
            boxShadow: '0 8px 40px rgba(0,0,0,0.7)',
            minWidth: '200px',
            backdropFilter: 'blur(14px)',
          }}
        >
          <div style={{ padding: '8px 14px 6px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 500, color: '#8b9bb0', letterSpacing: '0.12em' }}>MAP OVERLAYS</span>
          </div>
          {layers.map((l, i) => (
            <button
              className="ui-interactive-btn"
              key={l.label}
              onClick={() => { l.onClick(); setOptionsOpen(false) }}
              style={{
                display: 'flex', alignItems: 'center', width: '100%', gap: '10px',
                padding: '9px 14px',
                background: l.active ? `rgba(255,255,255,0.04)` : 'transparent',
                border: 'none', borderBottom: i < layers.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                cursor: 'pointer',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
              onMouseLeave={e => e.currentTarget.style.background = l.active ? 'rgba(255,255,255,0.04)' : 'transparent'}
            >
              <div style={{
                width: '7px', height: '7px', borderRadius: '50%',
                background: l.active ? l.dot : 'transparent',
                border: `1px solid ${l.active ? l.dot : '#66768b'}`,
                boxShadow: l.active ? `0 0 6px ${l.dot}` : 'none',
                flexShrink: 0,
              }} />
              <span style={{
                fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: '11px',
                color: l.active ? '#f1f5f9' : '#c3d0df', letterSpacing: '0.06em', flex: 1, textAlign: 'left',
              }}>
                {l.label}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                fontSize: '9px',
                color: '#8b9bb0',
                letterSpacing: '0.06em',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '6px',
                padding: '1px 5px',
                marginRight: '6px',
              }}>
                {l.hotkey}
              </span>
              {l.active && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: l.dot }}>ON</span>
              )}
            </button>
          ))}
        </div>,
        document.body
      )}

      {userMenuOpen && userMenuPos && createPortal(
        <div
          className="ui-panel-enter"
          data-user-menu="true"
          style={{
            position: 'fixed', top: userMenuPos.top, right: userMenuPos.right, zIndex: 99999,
            background: 'linear-gradient(180deg, rgba(28,35,47,0.96) 0%, rgba(18,24,34,0.98) 100%)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '16px',
            overflow: 'hidden',
            boxShadow: '0 18px 44px rgba(0,0,0,0.46)',
            minWidth: '180px',
            backdropFilter: 'blur(14px)',
          }}
        >
          {[
            { label: 'Audit Log', action: () => { onToggleAudit(); setUserMenuOpen(false) } },
            { label: 'Settings', action: () => { onToggleSettings(); setUserMenuOpen(false) } },
            { label: 'Sign Out', action: () => { onLogout(); setUserMenuOpen(false) }, danger: true },
          ].map((item, i) => (
            <button
              className="ui-interactive-btn"
              key={item.label}
              onClick={item.action}
              style={{
                display: 'block',
                width: '100%',
                padding: '12px 16px',
                textAlign: 'left',
                background: 'transparent',
                border: 'none',
                borderBottom: i < 2 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                cursor: 'pointer',
                fontFamily: 'var(--font-sans)',
                fontWeight: 600,
                fontSize: '12px',
                color: item.danger ? '#ef4444' : '#d4dce8',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              {item.label}
            </button>
          ))}
        </div>,
        document.body
      )}
    </div>
  )
}
