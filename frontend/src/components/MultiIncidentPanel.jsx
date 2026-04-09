import { useMemo, useState, useEffect, memo } from 'react'
import { api } from '../api/client'

const SEVERITY_COLOR = {
  critical: '#ef4444',
  high:     '#ff4d1a',
  moderate: '#facc15',
  low:      '#22c55e',
}

const SEVERITY_ORDER = { critical: 0, high: 1, moderate: 2, low: 3 }

function formatAcres(n) {
  if (n == null) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k ac`
  return `${Math.round(n)} ac`
}

function ContainmentBar({ pct }) {
  const p = Math.min(pct ?? 0, 100)
  const color = p >= 75 ? '#22c55e' : p >= 35 ? '#ff4d1a' : '#ef4444'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <div style={{ flex: 1, height: '3px', background: 'rgba(255,255,255,0.07)', borderRadius: '2px' }}>
        <div style={{ width: `${p}%`, height: '100%', background: color, borderRadius: '2px', transition: 'width 0.4s' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color, fontWeight: 600, minWidth: '32px' }}>
        {Math.round(p)}%
      </span>
    </div>
  )
}

function MultiIncidentPanel({ incidents, units, alerts, selectedId, onSelect, onClose, panelWidth = 360, topOffset = 86, bottomOffset = 12, rightOffset = 12 }) {
  const [priorityData, setPriorityData] = useState(null)  // API response

  // Fetch priority data on mount and every 30s
  useEffect(() => {
    let cancelled = false
    async function fetchPriority() {
      try {
        const data = await api.multiIncidentPriority()
        if (!cancelled) setPriorityData(data)
      } catch (e) {
        // Silently fall back to client-side sort
      }
    }
    fetchPriority()
    const interval = setInterval(fetchPriority, 30000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  // Build a priority score lookup from API results
  const priorityScores = useMemo(() => {
    const map = {}
    for (const inc of priorityData?.ranked_incidents ?? []) {
      map[inc.incident_id] = {
        score:   inc.priority_score,
        factors: inc.priority_factors ?? [],
      }
    }
    return map
  }, [priorityData])

  // Sort by API priority score when available, else fallback to severity order
  const sorted = useMemo(() => {
    const active = incidents.filter(i => i.status === 'active' || i.status === 'contained')
    if (Object.keys(priorityScores).length > 0) {
      return [...active].sort((a, b) =>
        (priorityScores[b.id]?.score ?? 0) - (priorityScores[a.id]?.score ?? 0)
      )
    }
    return [...active].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99))
  }, [incidents, priorityScores])

  // Pre-compute stats per incident
  const stats = useMemo(() => {
    const out = {}
    for (const inc of incidents) {
      out[inc.id] = {
        unitsCount:  units.filter(u => u.assigned_incident_id === inc.id).length,
        alertsCount: alerts.filter(a => a.incident_id === inc.id && !a.is_acknowledged).length,
        enRoute:     units.filter(u => u.assigned_incident_id === inc.id && u.status === 'en_route').length,
        onScene:     units.filter(u => u.assigned_incident_id === inc.id && u.status === 'on_scene').length,
      }
    }
    return out
  }, [incidents, units, alerts])

  return (
    <div className="ui-shell-panel ui-float-soft-delayed" style={{
      position: 'fixed', top: `${topOffset}px`, right: `${rightOffset}px`, bottom: `${bottomOffset}px`,
      width: `${panelWidth}px`,
      background: 'linear-gradient(180deg, rgba(28,35,47,0.94) 0%, rgba(18,24,34,0.97) 100%)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '24px',
      zIndex: 3000, display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
      boxShadow: '0 24px 56px rgba(0,0,0,0.38), inset 0 1px 0 rgba(255,255,255,0.05)',
      animation: 'slideInRight 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
      backdropFilter: 'blur(14px)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 16px 12px', borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 0,
      }}>
        <div>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#d4dce8', letterSpacing: '0.04em' }}>
            COMMAND OVERVIEW
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#a7b5c7', marginTop: '2px' }}>
            {sorted.length} incident{sorted.length !== 1 ? 's' : ''}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{ width: '34px', height: '34px', borderRadius: '12px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer', color: '#c3d0df', fontSize: '16px', padding: 0 }}
        >
          ✕
        </button>
      </div>

      {/* Summary strip */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px',
        padding: '12px 14px',
        borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 0,
      }}>
        {[
          { label: 'CRITICAL', count: sorted.filter(i => i.severity === 'critical').length, color: '#ef4444' },
          { label: 'HIGH',     count: sorted.filter(i => i.severity === 'high').length,     color: '#ff4d1a' },
          { label: 'MODERATE', count: sorted.filter(i => i.severity === 'moderate').length, color: '#facc15' },
          { label: 'TOTAL UNITS', count: units.filter(u => u.assigned_incident_id).length, color: '#38bdf8' },
        ].map(s => (
          <div key={s.label} style={{ background: 'rgba(10,14,20,0.45)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '18px', padding: '10px 12px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '17px', color: s.color }}>{s.count}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#a7b5c7', letterSpacing: '0.08em' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Incident cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 10px 12px' }}>
        {sorted.length === 0 && (
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#a7b5c7', padding: '20px 8px' }}>
            No active incidents.
          </div>
        )}
        {sorted.map(inc => {
          const s         = stats[inc.id] ?? {}
          const color     = SEVERITY_COLOR[inc.severity] ?? '#9baac0'
          const isSelected = inc.id === selectedId

          return (
            <div
              key={inc.id}
              onClick={() => onSelect(inc.id)}
              style={{
                background: isSelected ? 'linear-gradient(180deg, rgba(61,39,37,0.94) 0%, rgba(48,33,33,0.9) 100%)' : 'rgba(255,255,255,0.05)',
                border: `1px solid ${isSelected ? '#ff4d1a' : 'rgba(255,255,255,0.1)'}`,
                borderRadius: '22px', padding: '14px 14px 12px',
                cursor: 'pointer', marginBottom: '6px',
                transition: 'all 0.15s',
                boxShadow: isSelected ? '0 16px 36px rgba(255,77,26,0.12), inset 0 1px 0 rgba(255,255,255,0.04)' : 'inset 0 1px 0 rgba(255,255,255,0.04)',
              }}
              onMouseEnter={e => { if (!isSelected) e.currentTarget.style.borderColor = '#333' }}
              onMouseLeave={e => { if (!isSelected) e.currentTarget.style.borderColor = 'rgba(255,255,255,0.07)' }}
            >
              {/* Top row */}
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '6px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#d4dce8', marginBottom: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {inc.name}
                  </div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#a7b5c7' }}>
                    {inc.fire_type.replace(/_/g, ' ')} · {formatAcres(inc.acres_burned)}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '3px', flexShrink: 0, marginLeft: '8px' }}>
                  <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '10px', color, background: `${color}18`, border: `1px solid ${color}44`, borderRadius: '8px', padding: '3px 8px', letterSpacing: '0.04em' }}>
                    {inc.severity.toUpperCase()}
                  </span>
                  {priorityScores[inc.id]?.score != null && (() => {
                    const ps = priorityScores[inc.id]
                    const factors = ps.factors ?? []
                    // Build a human-readable tooltip from the scoring factors
                    const factorLabels = {
                      'no_resources_assigned': 'no units assigned',
                      'few_resources': 'few units on scene',
                      'extreme_fire_weather': 'extreme fire weather',
                      'incident_age>24h': 'incident >24h old',
                    }
                    const factorStr = factors
                      .map(f => factorLabels[f] ?? f.replace(/_/g, ' '))
                      .join(', ')
                    const containmentSuppressed = (inc.containment_percent ?? 0) >= 50
                      && inc.severity === 'critical'
                    return (
                      <span style={{
                        fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px',
                        color: ps.score >= 70 ? '#ef4444' : ps.score >= 45 ? '#ff4d1a' : '#9baac0',
                        background: 'rgba(255,255,255,0.04)', border: '1px solid #333',
                        borderRadius: '8px', padding: '3px 7px', letterSpacing: '0.04em',
                        cursor: 'help',
                      }} title={`Priority score ${Math.round(ps.score)}/100\nFactors: ${factorStr || 'none'}${containmentSuppressed ? '\n⚠ Score reduced: high containment' : ''}`}>
                        P{Math.round(ps.score)}
                        {containmentSuppressed && (
                          <span style={{ color: '#facc15', marginLeft: '3px', fontSize: '8px' }}>↓</span>
                        )}
                      </span>
                    )
                  })()}
                  {s.alertsCount > 0 && (
                    <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '9px', color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '8px', padding: '3px 7px' }}>
                      {s.alertsCount} ALERT{s.alertsCount !== 1 ? 'S' : ''}
                    </span>
                  )}
                  {(inc.structures_threatened ?? 0) > 0 && (
                    <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '9px', color: '#facc15', background: 'rgba(250,204,21,0.1)', border: '1px solid rgba(250,204,21,0.3)', borderRadius: '8px', padding: '3px 7px' }}>
                      {inc.structures_threatened} STRUCT
                    </span>
                  )}
                </div>
              </div>

              {/* Containment bar */}
              <div style={{ marginBottom: '8px' }}>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '3px' }}>CONTAINMENT</div>
                <ContainmentBar pct={inc.containment_percent} />
              </div>

              {/* Stats row */}
              <div style={{ display: 'flex', gap: '12px' }}>
                {[
                  { label: 'ON SCENE', value: s.onScene ?? 0,   color: '#ff4d1a' },
                  { label: 'EN ROUTE', value: s.enRoute ?? 0,   color: '#38bdf8' },
                  { label: 'WIND',     value: inc.wind_speed_mph != null ? `${inc.wind_speed_mph.toFixed(0)} mph` : '—', color: '#d4dce8' },
                  { label: 'HUMIDITY', value: inc.humidity_percent != null ? `${inc.humidity_percent.toFixed(0)}%` : '—', color: '#d4dce8' },
                ].map(stat => (
                  <div key={stat.label} style={{ flex: 1 }}>
                    <div style={{ fontFamily: 'var(--font-sans)', fontSize: '8px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '2px' }}>{stat.label}</div>
                    <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: stat.color }}>{stat.value}</div>
                  </div>
                ))}
              </div>

              {/* Spread risk + AQI */}
              {(inc.spread_risk || inc.aqi != null) && (
                <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                  {inc.spread_risk && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#a7b5c7', letterSpacing: '0.06em' }}>SPREAD</div>
                      <div style={{
                        fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px',
                        color: inc.spread_risk === 'extreme' ? '#ef4444' : inc.spread_risk === 'high' ? '#ff4d1a' : inc.spread_risk === 'moderate' ? '#facc15' : '#22c55e',
                        letterSpacing: '0.06em',
                      }}>
                        {inc.spread_risk.toUpperCase()} · {inc.spread_direction || '—'}
                      </div>
                    </div>
                  )}
                  {inc.aqi != null && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#a7b5c7', letterSpacing: '0.06em' }}>AQI</div>
                      <div style={{
                        fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px',
                        color: inc.aqi >= 201 ? '#ef4444' : inc.aqi >= 151 ? '#ff4d1a' : inc.aqi >= 101 ? '#facc15' : '#22c55e',
                        letterSpacing: '0.06em',
                      }}>
                        {Math.round(inc.aqi)}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default memo(MultiIncidentPanel)
