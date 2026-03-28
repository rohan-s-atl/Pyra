import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { formatClockTime, formatTimezone } from '../utils/timeUtils'

const THREAT_COLOR = {
  low: '#4ade80',
  moderate: '#60a5fa',
  high: '#F56E0F',
  extreme: '#ef4444',
}

export default function TopBar({
  incidents,
  units,
  showEvacZones,
  onToggleEvacZones,
  showFireGrowth,
  onToggleFireGrowth,
  showPerimeters,
  onTogglePerimeters,
  showHeatmap,
  onToggleHeatmap,
  showCommand,
  onToggleCommand,
  showSatellite,
  onToggleSatellite,
  showWeather,
  onToggleWeather,
  showWaterSources,
  onToggleWaterSources,
  auth,
  onLogout,
  onToggleAudit,
  onToggleSettings,
}) {
  const [time, setTime] = useState(new Date())
  const [optionsMenuOpen, setOptionsMenuOpen] = useState(false)
  const [optionsMenuPos, setOptionsMenuPos] = useState(null)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [aiReady, setAiReady] = useState(null) // null = unknown, true/false = known
  const optionsBtnRef = useRef(null)

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    fetch('/health')
      .then(r => r.json())
      .then(d => setAiReady(!!d.ai_ready))
      .catch(() => setAiReady(false))
  }, [])

  // Close on outside click
  useEffect(() => {
    if (!optionsMenuOpen) return
    const handler = (e) => {
      if (
        !e.target.closest('[data-options-menu]') &&
        !e.target.closest('[data-options-btn]')
      ) {
        setOptionsMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [optionsMenuOpen])

  const activeIncidents = incidents.filter(i => i.status === 'active' || i.status === 'contained')
  const criticalAlerts = incidents.filter(i => i.severity === 'critical').length
  const assignedUnits = units.filter(u => u.assigned_incident_id)

  const avgContainment = activeIncidents.length
    ? Math.round(
        activeIncidents.reduce((sum, i) => sum + (i.containment_percent ?? 0), 0) /
          activeIncidents.length
      )
    : 0

  const minHumidity = activeIncidents.length
    ? Math.min(...activeIncidents.map(i => i.humidity_percent ?? 100))
    : 0

  const maxAqi = activeIncidents.length
    ? Math.max(...activeIncidents.map(i => i.aqi ?? 0))
    : 0

  const threatLevel = activeIncidents.some(i => i.severity === 'critical')
    ? 'extreme'
    : activeIncidents.some(i => i.severity === 'high')
    ? 'high'
    : activeIncidents.some(i => i.severity === 'moderate')
    ? 'moderate'
    : 'low'

  const timeStr = formatClockTime(time)
  const tzLabel = formatTimezone(time)

  const stats = [
    { label: 'INCIDENTS',   value: activeIncidents.length,             color: activeIncidents.length > 0 ? '#F56E0F' : '#4ade80' },
    { label: 'DEPLOYED',    value: `${assignedUnits.length} / ${units.length}`, color: '#F56E0F' },
    { label: 'CONTAINMENT', value: `${avgContainment}%`,               color: avgContainment > 50 ? '#4ade80' : avgContainment > 20 ? '#F56E0F' : '#ef4444' },
    { label: 'HUMIDITY',    value: `${minHumidity}%`,                  color: minHumidity < 15 ? '#ef4444' : '#FBFBFB' },
    { label: 'AQI',         value: maxAqi > 0 ? maxAqi : 'N/A',        color: maxAqi >= 151 ? '#ef4444' : maxAqi >= 101 ? '#F56E0F' : maxAqi >= 51 ? '#facc15' : maxAqi > 0 ? '#4ade80' : '#555' },
    { label: 'THREAT',      value: threatLevel.toUpperCase(),           color: THREAT_COLOR[threatLevel] },
  ]

  const mapLayerButtons = [
    { label: 'EVAC',   active: showEvacZones,    onClick: onToggleEvacZones,    color: '#ef4444' },
    { label: 'GROWTH', active: showFireGrowth,   onClick: onToggleFireGrowth,   color: '#ef4444' },
    { label: 'PERIM',  active: showPerimeters,   onClick: onTogglePerimeters,   color: '#F56E0F' },
    { label: 'HEAT',   active: showHeatmap,      onClick: onToggleHeatmap,      color: '#ef4444' },
    { label: 'SAT',    active: showSatellite,    onClick: onToggleSatellite,    color: '#60a5fa' },
    { label: 'WX',     active: showWeather,      onClick: onToggleWeather,      color: '#4ade80' },
    { label: 'WATER',  active: showWaterSources, onClick: onToggleWaterSources, color: '#60a5fa' },
  ]

  function openOptionsMenu() {
    if (optionsBtnRef.current) {
      const rect = optionsBtnRef.current.getBoundingClientRect()
      setOptionsMenuPos({ top: rect.bottom + 4, left: rect.left })
    }
    setOptionsMenuOpen(true)
  }

  return (
    <div
      style={{
        minHeight: '56px',
        background: '#151419',
        borderBottom: '1px solid #262626',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '8px 16px',
        flexWrap: 'nowrap',
        overflow: 'visible',
        position: 'relative',
        zIndex: 9000,
      }}
    >
      {/* Left section */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 1, minWidth: 0 }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          <div style={{ width: '28px', height: '28px', borderRadius: '4px', background: '#F56E0F', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 14px rgba(245,110,15,0.5)' }}>
            <span style={{ color: '#FBFBFB', fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px' }}>P</span>
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '15px', color: '#FBFBFB', letterSpacing: '0.03em', lineHeight: 1, whiteSpace: 'nowrap' }}>Pyra</div>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '10px', color: '#878787', letterSpacing: '0.04em', lineHeight: 1, whiteSpace: 'nowrap' }}>WILDFIRE COMMAND</div>
          </div>
        </div>

        <div style={{ width: '1px', height: '32px', background: '#262626', flexShrink: 0 }} />

        {/* Agent status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: aiReady === false ? 'rgba(239,68,68,0.1)' : 'rgba(74,222,128,0.1)', border: `1px solid ${aiReady === false ? 'rgba(239,68,68,0.3)' : 'rgba(74,222,128,0.3)'}`, borderRadius: '3px', padding: '3px 10px', flexShrink: 0, whiteSpace: 'nowrap' }}>
          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: aiReady === false ? '#ef4444' : '#4ade80', boxShadow: `0 0 6px ${aiReady === false ? '#ef4444' : '#4ade80'}` }} />
          <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: aiReady === false ? '#ef4444' : '#4ade80', letterSpacing: '0.04em' }}>
            {aiReady === false ? 'AI KEY MISSING' : 'AGENT ACTIVE'}
          </span>
        </div>

        {/* OPTIONS button */}
        <div ref={optionsBtnRef} style={{ flexShrink: 0 }}>
          <button
            data-options-btn="true"
            onClick={() => optionsMenuOpen ? setOptionsMenuOpen(false) : openOptionsMenu()}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              background: optionsMenuOpen ? 'rgba(139,139,139,0.1)' : 'transparent',
              border: `1px solid ${optionsMenuOpen ? '#555' : '#333'}`,
              borderRadius: '3px', padding: '3px 8px', cursor: 'pointer',
              fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '10px',
              color: '#878787', letterSpacing: '0.04em', transition: 'all 0.15s', whiteSpace: 'nowrap',
            }}
          >
            OPTIONS
            <span style={{ color: '#555', fontSize: '8px', marginLeft: '2px' }}>
              {optionsMenuOpen ? '▲' : '▼'}
            </span>
          </button>
        </div>
      </div>

      {/* Middle stats */}
      <div style={{ display: 'flex', alignItems: 'stretch', flex: 1, minWidth: 0, overflow: 'hidden' }}>
        {stats.map((stat, i) => (
          <div key={stat.label} style={{ flex: '1 1 110px', minWidth: '90px', padding: '0 12px', borderRight: i < stats.length - 1 ? '1px solid #262626' : 'none', overflow: 'hidden' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '10px', color: '#878787', letterSpacing: '0.06em', marginBottom: '3px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {stat.label}
            </div>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '15px', color: stat.color, lineHeight: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* Right section */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
        {/* Command button */}
        <button
          onClick={onToggleCommand}
          style={{ display: 'flex', alignItems: 'center', gap: '5px', background: showCommand ? 'rgba(96,165,250,0.15)' : 'transparent', border: `1px solid ${showCommand ? '#60a5fa' : '#333'}`, borderRadius: '3px', padding: '3px 10px', cursor: 'pointer', transition: 'all 0.15s', whiteSpace: 'nowrap', flexShrink: 0 }}
        >
          <div style={{ width: '6px', height: '6px', borderRadius: '1px', background: showCommand ? '#60a5fa' : '#555' }} />
          <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: showCommand ? '#60a5fa' : '#555', letterSpacing: '0.04em' }}>COMMAND</span>
          {criticalAlerts > 0 && (
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', background: '#ef4444', color: '#FBFBFB', borderRadius: '8px', padding: '1px 5px', letterSpacing: '0.02em', lineHeight: 1 }}>
              {criticalAlerts}
            </span>
          )}
        </button>

        {/* User menu */}
        {auth && (
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <button
              onClick={() => setUserMenuOpen(v => !v)}
              style={{ display: 'flex', alignItems: 'center', gap: '7px', background: userMenuOpen ? '#1B1B1E' : 'transparent', border: `1px solid ${userMenuOpen ? '#444' : '#333'}`, borderRadius: '4px', padding: '4px 10px', cursor: 'pointer', transition: 'all 0.15s' }}
            >
              <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: auth.role === 'commander' ? '#F56E0F' : auth.role === 'dispatcher' ? '#60a5fa' : '#878787' }} />
              <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#FBFBFB', letterSpacing: '0.04em' }}>{auth.username}</span>
              <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#555', letterSpacing: '0.04em' }}>{auth.role.toUpperCase()}</span>
              <span style={{ color: '#555', fontSize: '9px', marginLeft: '2px' }}>{userMenuOpen ? '▲' : '▼'}</span>
            </button>

            {userMenuOpen && (
              <div style={{ position: 'fixed', top: '52px', right: '108px', zIndex: 99999, background: '#1B1B1E', border: '1px solid #333', borderRadius: '4px', overflow: 'hidden', boxShadow: '0 4px 16px rgba(0,0,0,0.5)', minWidth: '140px' }}>
                {[
                  { label: 'Audit Log', action: () => { onToggleAudit();   setUserMenuOpen(false) }, color: '#FBFBFB' },
                  { label: 'Settings',  action: () => { onToggleSettings(); setUserMenuOpen(false) }, color: '#FBFBFB' },
                  { label: 'Sign Out',  action: () => { onLogout();         setUserMenuOpen(false) }, color: '#ef4444' },
                ].map(item => (
                  <button key={item.label} onClick={item.action}
                    style={{ display: 'block', width: '100%', padding: '9px 14px', textAlign: 'left', background: 'transparent', border: 'none', borderBottom: '1px solid #262626', cursor: 'pointer', fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '12px', color: item.color, transition: 'background 0.1s' }}
                    onMouseEnter={e => e.currentTarget.style.background = '#262626'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Clock */}
        <div style={{ flexShrink: 0, textAlign: 'right', minWidth: '96px' }}>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '20px', color: '#FBFBFB', letterSpacing: '0.01em', lineHeight: 1, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
            {timeStr}
          </div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '10px', color: '#878787', letterSpacing: '0.06em', marginTop: '2px', whiteSpace: 'nowrap' }}>
            {tzLabel}
          </div>
        </div>
      </div>

      {/* OPTIONS dropdown — portalled to document.body to escape ALL overflow/stacking contexts */}
      {optionsMenuOpen && optionsMenuPos && createPortal(
        <div
          data-options-menu="true"
          style={{
            position: 'fixed',
            top: optionsMenuPos.top,
            left: optionsMenuPos.left,
            zIndex: 99999,
            background: '#1B1B1E',
            border: '1px solid #333',
            borderRadius: '4px',
            overflow: 'hidden',
            boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
            minWidth: '120px',
          }}
        >
          {mapLayerButtons.map((btn, i) => (
            <button
              key={btn.label}
              onClick={() => { btn.onClick(); setOptionsMenuOpen(false) }}
              style={{
                display: 'flex', alignItems: 'center', width: '100%', gap: '8px',
                padding: '8px 12px', textAlign: 'left',
                background: btn.active ? `${btn.color}12` : 'transparent',
                border: 'none', borderBottom: i < mapLayerButtons.length - 1 ? '1px solid #262626' : 'none',
                cursor: 'pointer', fontFamily: 'Inter, sans-serif', fontWeight: 600,
                fontSize: '11px', color: btn.active ? btn.color : '#878787',
                letterSpacing: '0.04em', transition: 'all 0.1s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = btn.active ? `${btn.color}12` : '#262626' }}
              onMouseLeave={e => { e.currentTarget.style.background = btn.active ? `${btn.color}12` : 'transparent' }}
            >
              <div style={{ width: '6px', height: '6px', borderRadius: '1px', background: btn.active ? btn.color : '#555', flexShrink: 0 }} />
              {btn.label}
            </button>
          ))}
        </div>,
        document.body
      )}
    </div>
  )
}