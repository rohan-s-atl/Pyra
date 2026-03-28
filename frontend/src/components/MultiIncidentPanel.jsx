import { useMemo, useState, useEffect } from 'react'
import { api } from '../api/client'

const SEVERITY_COLOR = {
  critical: '#ef4444',
  high:     '#F56E0F',
  moderate: '#facc15',
  low:      '#4ade80',
}

const SEVERITY_ORDER = { critical: 0, high: 1, moderate: 2, low: 3 }

function formatAcres(n) {
  if (n == null) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k ac`
  return `${Math.round(n)} ac`
}

function ContainmentBar({ pct }) {
  const p = Math.min(pct ?? 0, 100)
  const color = p >= 75 ? '#4ade80' : p >= 35 ? '#F56E0F' : '#ef4444'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <div style={{ flex: 1, height: '3px', background: '#262626', borderRadius: '2px' }}>
        <div style={{ width: `${p}%`, height: '100%', background: color, borderRadius: '2px', transition: 'width 0.4s' }} />
      </div>
      <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color, fontWeight: 600, minWidth: '32px' }}>
        {Math.round(p)}%
      </span>
    </div>
  )
}

export default function MultiIncidentPanel({ incidents, units, alerts, selectedId, onSelect, onClose }) {
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
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0,
      width: '420px', background: '#151419',
      borderLeft: '1px solid #262626',
      zIndex: 3000, display: 'flex', flexDirection: 'column',
      boxShadow: '-4px 0 24px rgba(0,0,0,0.5)',
      animation: 'slideInRight 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 16px', borderBottom: '1px solid #262626', flexShrink: 0,
      }}>
        <div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: '#FBFBFB', letterSpacing: '0.04em' }}>
            COMMAND OVERVIEW
          </div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#878787', marginTop: '2px' }}>
            {sorted.length} incident{sorted.length !== 1 ? 's' : ''}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#555', fontSize: '16px', padding: '2px 4px' }}
        >
          ✕
        </button>
      </div>

      {/* Summary strip */}
      <div style={{
        display: 'flex', gap: '1px', background: '#262626',
        borderBottom: '1px solid #262626', flexShrink: 0,
      }}>
        {[
          { label: 'CRITICAL', count: sorted.filter(i => i.severity === 'critical').length, color: '#ef4444' },
          { label: 'HIGH',     count: sorted.filter(i => i.severity === 'high').length,     color: '#F56E0F' },
          { label: 'MODERATE', count: sorted.filter(i => i.severity === 'moderate').length, color: '#facc15' },
          { label: 'TOTAL UNITS', count: units.filter(u => u.assigned_incident_id).length, color: '#60a5fa' },
        ].map(s => (
          <div key={s.label} style={{ flex: 1, background: '#151419', padding: '8px 0', textAlign: 'center' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '16px', color: s.color }}>{s.count}</div>
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '8px', color: '#555', letterSpacing: '0.08em' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Incident cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {sorted.length === 0 && (
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#878787', padding: '20px 8px' }}>
            No active incidents.
          </div>
        )}
        {sorted.map(inc => {
          const s         = stats[inc.id] ?? {}
          const color     = SEVERITY_COLOR[inc.severity] ?? '#878787'
          const isSelected = inc.id === selectedId

          return (
            <div
              key={inc.id}
              onClick={() => onSelect(inc.id)}
              style={{
                background: isSelected ? 'rgba(245,110,15,0.08)' : '#1B1B1E',
                border: `1px solid ${isSelected ? '#F56E0F' : '#262626'}`,
                borderRadius: '4px', padding: '12px 14px',
                cursor: 'pointer', marginBottom: '6px',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (!isSelected) e.currentTarget.style.borderColor = '#333' }}
              onMouseLeave={e => { if (!isSelected) e.currentTarget.style.borderColor = '#262626' }}
            >
              {/* Top row */}
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '6px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: '#FBFBFB', marginBottom: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {inc.name}
                  </div>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
                    {inc.fire_type.replace(/_/g, ' ')} · {formatAcres(inc.acres_burned)}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '3px', flexShrink: 0, marginLeft: '8px' }}>
                  <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color, background: `${color}18`, border: `1px solid ${color}44`, borderRadius: '2px', padding: '1px 6px', letterSpacing: '0.04em' }}>
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
                        fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px',
                        color: ps.score >= 70 ? '#ef4444' : ps.score >= 45 ? '#F56E0F' : '#878787',
                        background: 'rgba(255,255,255,0.04)', border: '1px solid #333',
                        borderRadius: '2px', padding: '1px 5px', letterSpacing: '0.04em',
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
                    <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '9px', color: '#ef4444', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '2px', padding: '1px 5px' }}>
                      {s.alertsCount} ALERT{s.alertsCount !== 1 ? 'S' : ''}
                    </span>
                  )}
                </div>
              </div>

              {/* Containment bar */}
              <div style={{ marginBottom: '8px' }}>
                <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#555', letterSpacing: '0.06em', marginBottom: '3px' }}>CONTAINMENT</div>
                <ContainmentBar pct={inc.containment_percent} />
              </div>

              {/* Stats row */}
              <div style={{ display: 'flex', gap: '12px' }}>
                {[
                  { label: 'ON SCENE', value: s.onScene ?? 0,   color: '#F56E0F' },
                  { label: 'EN ROUTE', value: s.enRoute ?? 0,   color: '#60a5fa' },
                  { label: 'WIND',     value: inc.wind_speed_mph != null ? `${inc.wind_speed_mph.toFixed(0)} mph` : '—', color: '#FBFBFB' },
                  { label: 'HUMIDITY', value: inc.humidity_percent != null ? `${inc.humidity_percent.toFixed(0)}%` : '—', color: '#FBFBFB' },
                ].map(stat => (
                  <div key={stat.label} style={{ flex: 1 }}>
                    <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '8px', color: '#555', letterSpacing: '0.06em', marginBottom: '2px' }}>{stat.label}</div>
                    <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: stat.color }}>{stat.value}</div>
                  </div>
                ))}
              </div>

              {/* Spread risk */}
              {inc.spread_risk && (
                <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#555', letterSpacing: '0.06em' }}>SPREAD</div>
                  <div style={{
                    fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px',
                    color: inc.spread_risk === 'extreme' ? '#ef4444' : inc.spread_risk === 'high' ? '#F56E0F' : inc.spread_risk === 'moderate' ? '#facc15' : '#4ade80',
                    letterSpacing: '0.06em',
                  }}>
                    {inc.spread_risk.toUpperCase()} · {inc.spread_direction || '—'}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}