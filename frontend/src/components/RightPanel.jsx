import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { toast } from './Toast'

const SEVERITY_STYLE = {
  critical: { border: '#ef4444', text: '#ef4444', bg: 'rgba(239,68,68,0.08)' },
  warning:  { border: '#F56E0F', text: '#F56E0F', bg: 'rgba(245,110,15,0.08)' },
  info:     { border: '#60a5fa', text: '#60a5fa', bg: 'rgba(96,165,250,0.08)' },
}

const TYPE_ICON = {
  spread_warning:          '🔥',
  weather_shift:           '🌬',
  route_blocked:           '🚧',
  asset_at_risk:           '⚠️',
  water_source_constraint: '💧',
  evacuation_recommended:  '🚨',
  resource_shortage:       '📦',
}

const STATUS_COLOR = {
  available:      '#4ade80',
  en_route:       '#60a5fa',
  on_scene:       '#F56E0F',
  staging:        '#facc15',
  returning:      '#a78bfa',
  out_of_service: '#878787',
}

const UNIT_TYPE_ICON = {
  engine:       '🚒',
  hand_crew:    '👥',
  dozer:        '🚜',
  water_tender: '🚛',
  helicopter:   '🚁',
  air_tanker:   '✈️',
  command_unit: '📡',
  rescue:       '🚑',
}

const UNIT_CAPABILITIES = {
  engine:       { crew: 4,  water: '500 gal', note: 'Structure protection, direct attack' },
  hand_crew:    { crew: 20, water: null,       note: 'Handline construction, mop-up' },
  dozer:        { crew: 1,  water: null,       note: 'Containment line, fuel breaks' },
  water_tender: { crew: 2,  water: '4000 gal', note: 'Water resupply, shuttle ops' },
  helicopter:   { crew: 3,  water: '300 gal',  note: 'Water drops, recon, crew transport' },
  air_tanker:   { crew: 2,  water: '1200 gal', note: 'Retardant drops, forward spread' },
  command_unit: { crew: 6,  water: null,       note: 'ICP ops, unified command' },
  rescue:       { crew: 3,  water: null,       note: 'Medical support, extraction' },
}

const UNIT_TYPE_ORDER = {
  engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3,
  dozer: 4, water_tender: 5, command_unit: 6, rescue: 7,
}



const STATUS_FILTERS = [
  { key: 'all',       label: 'ALL' },
  { key: 'available', label: 'AVAIL' },
  { key: 'en_route',  label: 'EN ROUTE' },
  { key: 'returning', label: 'RETURNING' },
]

const PRIORITY_COLOR = {
  immediate:   '#ef4444',
  within_1hr:  '#F56E0F',
  standby:     '#878787',
}


function distBetween(unit, incident) {
  if (!incident) return 999
  try {
    const dlat = unit.latitude  - incident.latitude
    const dlon = unit.longitude - incident.longitude
    return Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
  } catch { return 999 }
}

function AlertRecommendationPanel({ alert, recData, recLoading, units, incidents, onDispatchSuccess, s }) {
  const [selectedUnits, setSelectedUnits] = useState([])
  const [dispatching,   setDispatching]   = useState(false)
  const [dispatched,    setDispatched]    = useState(false)
  const auth = useAuth()

  const incident = incidents?.find(i => i.id === alert.incident_id)
  const canDispatch = selectedUnits.length > 0 && !dispatching && auth?.role !== 'viewer'

  const recommendedTypes = new Set(recData?.units?.map(u => u.unit_type) ?? [])

  // Group by type, sort by distance within each group, suggested types first
  const available = units.filter(u => u.status === 'available')
  const sorted = [...available].sort((a, b) => {
    const aSugg = recommendedTypes.has(a.unit_type) ? 0 : 1
    const bSugg = recommendedTypes.has(b.unit_type) ? 0 : 1
    if (aSugg !== bSugg) return aSugg - bSugg
    const ga = UNIT_TYPE_ORDER[a.unit_type] ?? 99
    const gb = UNIT_TYPE_ORDER[b.unit_type] ?? 99
    if (ga !== gb) return ga - gb
    return distBetween(a, incident) - distBetween(b, incident)
  })

  // Count selected units per type for filling recommended boxes
  const selectedByType = selectedUnits.reduce((acc, uid) => {
    const u = units.find(x => x.id === uid)
    if (u) acc[u.unit_type] = (acc[u.unit_type] || 0) + 1
    return acc
  }, {})

  async function handleDispatch() {
    if (!selectedUnits.length) return
    setDispatching(true)
    try {
      await api.dispatchAlert(alert.id, alert.incident_id, selectedUnits)
      setDispatched(true)
      onDispatchSuccess?.()
    } catch (e) {
      console.error(e)
      toast('Dispatch failed — check unit availability', 'error')
    } finally {
      setDispatching(false)
    }
  }

  if (recLoading) return (
    <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#878787', padding: '4px 0' }}>
      Loading recommendation...
    </div>
  )
  if (recData?.error) return (
    <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#ef4444' }}>
      Failed to load recommendation.
    </div>
  )
  if (!recData) return null
  if (dispatched) return (
    <div style={{
      background: 'rgba(74,222,128,0.1)', border: '1px solid #4ade80',
      borderRadius: '3px', padding: '8px 10px', textAlign: 'center',
      fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px', color: '#4ade80',
    }}>
      ✓ UNITS DISPATCHED · ALERT RESOLVED
    </div>
  )

  return (
    <>
      {recData.summary && (
        <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.5, marginBottom: '8px' }}>
          {recData.summary}
        </div>
      )}

      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: s.text, letterSpacing: '0.04em', marginBottom: '4px' }}>
        ACTIONS
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginBottom: '8px' }}>
        {recData.actions?.map((action, i) => (
          <div key={i} style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: s.text, flexShrink: 0, marginTop: '1px' }}>{i + 1}.</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#FBFBFB', lineHeight: 1.5, fontWeight: 400 }}>{action}</span>
          </div>
        ))}
      </div>

      {/* Recommended unit types — go green when filled */}
      {recData.units?.length > 0 && (
        <>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: s.text, letterSpacing: '0.04em', marginBottom: '4px' }}>
            RECOMMENDED UNITS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '8px' }}>
            {recData.units.map((u, i) => {
              const filled = (selectedByType[u.unit_type] ?? 0) >= u.quantity
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  background: filled ? 'rgba(74,222,128,0.1)' : '#262626',
                  border: `1px solid ${filled ? '#4ade80' : '#333'}`,
                  borderRadius: '2px', padding: '3px 7px',
                  transition: 'all 0.2s',
                }}>
                  <span style={{ fontSize: '11px' }}>{UNIT_TYPE_ICON[u.unit_type] ?? '◉'}</span>
                  <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: filled ? '#4ade80' : '#FBFBFB', flex: 1 }}>
                    {u.quantity}× {u.unit_type.replace(/_/g, ' ').toUpperCase()}
                  </span>
                  <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '9px', color: filled ? '#4ade80' : (PRIORITY_COLOR[u.priority] ?? '#878787'), letterSpacing: '0.03em' }}>
                    {filled ? '✓ FILLED' : u.priority.replace(/_/g, ' ').toUpperCase()}
                  </span>
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Unit selector — grouped by type, sorted by distance, no auto-select */}
      {alert.incident_id && (
        <>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: s.text, letterSpacing: '0.04em', marginBottom: '4px' }}>
            SELECT UNITS TO DISPATCH
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '8px' }}>
            {sorted.length === 0 && (
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#aaaaaa' }}>No available units</div>
            )}
            {(() => {
              let lastType = null
              return sorted.map(unit => {
                const isSelected  = selectedUnits.includes(unit.id)
                const isSuggested = recommendedTypes.has(unit.unit_type)
                const showHeader  = unit.unit_type !== lastType
                lastType = unit.unit_type
                const dist = distBetween(unit, incident)
                const distLabel = dist < 999 ? (dist < 1 ? `${Math.round(dist * 5280)} ft` : `${dist.toFixed(1)} mi`) : null
                return (
                  <div key={unit.id}>
                    {showHeader && (
                      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#878787', letterSpacing: '0.04em', textTransform: 'uppercase', marginTop: '5px', marginBottom: '2px', paddingLeft: '2px' }}>
                        {unit.unit_type.replace(/_/g, ' ')}
                      </div>
                    )}
                    <div
                      onClick={() => setSelectedUnits(prev =>
                        prev.includes(unit.id) ? prev.filter(id => id !== unit.id) : [...prev, unit.id]
                      )}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '6px',
                        padding: '4px 7px', borderRadius: '2px',
                        background: isSelected ? 'rgba(245,110,15,0.12)' : '#262626',
                        border: `1px solid ${isSelected ? '#F56E0F' : isSuggested ? '#F56E0F44' : '#333'}`,
                        cursor: 'pointer',
                      }}
                    >
                      <span style={{ fontSize: '11px' }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
                      <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#FBFBFB', flex: 1 }}>{unit.designation}</span>
                      {distLabel && <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#aaaaaa' }}>{distLabel}</span>}
                      {isSuggested && <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#F56E0F' }}>★</span>}
                    </div>
                  </div>
                )
              })
            })()}
          </div>

          <button
            onClick={handleDispatch}
            disabled={!canDispatch}
            style={{
              width: '100%', padding: '7px',
              background: canDispatch ? s.border : '#262626',
              border: 'none', borderRadius: '3px',
              cursor: canDispatch ? 'pointer' : 'not-allowed',
              fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px',
              color: '#FBFBFB', letterSpacing: '0.03em', transition: 'background 0.15s',
            }}
          >
            {dispatching ? 'DISPATCHING...' : auth?.role === 'viewer' ? 'COMMANDER / DISPATCHER ONLY' : selectedUnits.length ? `DISPATCH ${selectedUnits.length} UNIT${selectedUnits.length !== 1 ? 'S' : ''} · RESOLVE ALERT` : 'SELECT UNITS'}
          </button>
        </>
      )}
    </>
  )
}


const UNIT_CAPACITY = {
  engine:       { water_gal: 500,  foam_pct_max: 6  },
  water_tender: { water_gal: 4000, foam_pct_max: 3  },
  helicopter:   { water_gal: 300,  foam_pct_max: 1  },
  air_tanker:   { water_gal: 0,    foam_pct_max: 0  },
  hand_crew:    { water_gal: 0,    foam_pct_max: 0  },
  dozer:        { water_gal: 0,    foam_pct_max: 0  },
  command_unit: { water_gal: 0,    foam_pct_max: 0  },
  rescue:       { water_gal: 0,    foam_pct_max: 0  },
}

function UnitLoadoutTooltip({ unit, loadout, rect }) {
  if (!loadout || !rect) return null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}
  const hasWater     = cap.water_gal > 0
  const hasFoam      = cap.foam_pct_max > 0
  const hasRetardant = unit.unit_type === 'air_tanker'
  const waterGal     = hasWater ? Math.round((loadout.water_pct / 100) * cap.water_gal) : 0
  const equipment    = loadout.equipment ?? []
  // RightPanel is on the right side — render tooltip to the LEFT of the card
  return createPortal(
    <div style={{
      position: 'fixed',
      top:  rect.top + rect.height / 2,
      right: window.innerWidth - rect.left + 8,
      transform: 'translateY(-50%)',
      width: '230px',
      zIndex: 99999,
      background: '#1B1B1E',
      border: '1px solid #F56E0F66',
      borderRadius: '4px',
      padding: '10px 12px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.7)',
      pointerEvents: 'none',
    }}>
      {/* Arrow pointing right toward the panel */}
      <div style={{ position: 'absolute', right: '-5px', top: '50%', transform: 'translateY(-50%)', width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderLeft: '5px solid #F56E0F66' }} />

      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#F56E0F', letterSpacing: '0.06em', marginBottom: '8px' }}>
        ⬡ CONFIRMED LOADOUT · {unit.designation}
      </div>

      {hasWater && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>WATER</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#60a5fa' }}>{waterGal.toLocaleString()} gal ({loadout.water_pct}%)</span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', width: `${loadout.water_pct}%`, background: '#60a5fa', borderRadius: '2px' }} />
          </div>
        </div>
      )}
      {hasFoam && loadout.foam_pct > 0 && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>FOAM</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#4ade80' }}>{loadout.foam_pct}%</span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', width: `${(loadout.foam_pct / cap.foam_pct_max) * 100}%`, background: '#4ade80', borderRadius: '2px' }} />
          </div>
        </div>
      )}
      {hasRetardant && loadout.retardant_pct > 0 && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>RETARDANT</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#F56E0F' }}>{loadout.retardant_pct}%</span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', width: `${loadout.retardant_pct}%`, background: '#F56E0F', borderRadius: '2px' }} />
          </div>
        </div>
      )}
      {equipment.length > 0 && (
        <div style={{ marginTop: '8px', borderTop: '1px solid #262626', paddingTop: '8px' }}>
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#878787', letterSpacing: '0.04em', marginBottom: '5px' }}>
            EQUIPMENT ({equipment.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            {equipment.map(item => (
              <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ color: '#4ade80', fontSize: '9px', flexShrink: 0 }}>✓</span>
                <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.3 }}>{item}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>,
    document.body
  )
}

function RightPanelUnitCard({ unit, confirmedLoadouts, onUnitClick }) {
  const [tooltipRect, setTooltipRect] = useState(null)
  const loadout = confirmedLoadouts[unit.id] ?? null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}

  return (
    <>
      {tooltipRect && <UnitLoadoutTooltip unit={unit} loadout={loadout} rect={tooltipRect} />}
      <div
        onClick={() => onUnitClick && onUnitClick(unit)}
        style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '6px 8px', marginBottom: '3px',
          background: '#1B1B1E', borderRadius: '3px',
          border: `1px solid ${loadout ? '#F56E0F33' : '#262626'}`,
          cursor: 'pointer', transition: 'border-color 0.15s',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = '#F56E0F'
          if (loadout) setTooltipRect(e.currentTarget.getBoundingClientRect())
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = loadout ? '#F56E0F33' : '#262626'
          setTooltipRect(null)
        }}
      >
        <span style={{ fontSize: '13px', flexShrink: 0 }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '13px', color: '#FBFBFB', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {unit.designation}
            </div>
            {loadout && <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '8px', color: '#F56E0F', fontWeight: 700, letterSpacing: '0.04em', flexShrink: 0 }}>⬡</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '11px', color: STATUS_COLOR[unit.status] ?? '#878787', letterSpacing: '0.02em' }}>
              {unit.status.replace(/_/g, ' ').toUpperCase()}
            </div>
            {loadout ? (
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#60a5fa' }}>
                {(() => {
                  const parts = []
                  if (cap.water_gal) parts.push(`${Math.round((loadout.water_pct/100)*cap.water_gal).toLocaleString()} gal`)
                  if (loadout.foam_pct > 0) parts.push(`${loadout.foam_pct}% foam`)
                  if (loadout.retardant_pct > 0) parts.push(`${loadout.retardant_pct}% retardant`)
                  return parts.length ? '· ' + parts.join(' · ') : null
                })()}
              </div>
            ) : UNIT_CAPABILITIES[unit.unit_type] && (
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#666' }}>
                · {UNIT_CAPABILITIES[unit.unit_type].crew}p
              </div>
            )}
          </div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '1px' }}>
            {loadout
              ? `${(loadout.equipment ?? []).length} items loaded · hover for details`
              : UNIT_CAPABILITIES[unit.unit_type]?.note ?? ''}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px', flexShrink: 0 }}>
          <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: STATUS_COLOR[unit.status] ?? '#878787' }} />
        </div>
      </div>
    </>
  )
}


export default function RightPanel({ alerts, units, incidents = [], selectedIncidentId, onUnitClick, onAlertsChanged, confirmedLoadouts = {} }) {
  const [alertsHeight,  setAlertsHeight]  = useState(320)
  const [activeAlertId, setActiveAlertId] = useState(null)
  const [triageCache,   setTriageCache]   = useState({})
  const [unitFilter,    setUnitFilter]    = useState('all')
  const [recData,       setRecData]       = useState(null)
  const [recLoading,    setRecLoading]    = useState(false)
  const dragging = useRef(false)
  const startY   = useRef(0)
  const startH   = useRef(0)

  const onDividerMouseDown = useCallback((e) => {
    e.preventDefault()
    dragging.current = true
    startY.current   = e.clientY
    startH.current   = alertsHeight
    const onMove = (e) => {
      if (!dragging.current) return
      const delta = e.clientY - startY.current
      setAlertsHeight(Math.min(600, Math.max(80, startH.current + delta)))
    }
    const onUp = () => {
      dragging.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [alertsHeight])

  async function handleAlertClick(alert) {
    if (activeAlertId === alert.id) {
      setActiveAlertId(null); setRecData(null); return
    }
    setActiveAlertId(alert.id)
    setRecData(null)
    setRecLoading(true)

    // Fetch triage lazily on first open
    if (!triageCache[alert.id]) {
      api.triage(alert.id)
        .then(result => setTriageCache(prev => ({ ...prev, [alert.id]: result })))
        .catch(() => {})
    }

    try {
      const data = await api.alertRecommendation(alert.id)
      setRecData(data)
    } catch {
      setRecData({ error: true })
    } finally {
      setRecLoading(false)
    }
  }

  function handleDispatchSuccess() {
    setActiveAlertId(null)
    setRecData(null)
    onAlertsChanged?.()
  }

  const filteredAlerts = selectedIncidentId
    ? alerts.filter(a => a.incident_id === selectedIncidentId)
    : alerts
  const unacked   = filteredAlerts.filter(a => !a.is_acknowledged)
  const acked     = filteredAlerts.filter(a =>  a.is_acknowledged)
  const deployed  = units.filter(u => u.assigned_incident_id)
  const available = units.filter(u => u.status === 'available')

  // Triage fetched lazily when alert is hovered or opened

  return (
    <div style={{
      width: 'min(260px, 30vw)', minWidth: '200px', background: '#151419', borderLeft: '1px solid #262626',
      display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden',
    }}>

      {/* ALERTS */}
      <div style={{ height: `${alertsHeight}px`, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '80px' }}>
        <div style={{ padding: '10px 12px 8px', flexShrink: 0, display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid #262626' }}>
          <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: '#FBFBFB', letterSpacing: '0.06em' }}>
            ACTIVE ALERTS
          </span>
          {unacked.length > 0 && (
            <span style={{ background: '#F56E0F', color: '#FBFBFB', borderRadius: '2px', padding: '1px 6px', fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px' }}>
              {unacked.length}
            </span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '4px' }}>
            {alerts.length > 10 && (
              <button
                title="Clear all alerts"
                onClick={() => {
                  if (window.confirm(`Clear all ${alerts.length} alerts?`)) {
                    api.clearAllAlerts().then(() => onAlertsChanged?.())
                  }
                }}
                style={{
                  background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)',
                  borderRadius: '2px', padding: '1px 6px', cursor: 'pointer',
                  fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px',
                  color: '#ef4444', letterSpacing: '0.04em',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.15)'}
              >
                CLEAR ALL
              </button>
            )}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px 0' }}>
          {unacked.length === 0 && (
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#aaaaaa', padding: '8px 4px' }}>
              No active alerts
            </div>
          )}

          {unacked.map(alert => {
            const s        = SEVERITY_STYLE[alert.severity] ?? SEVERITY_STYLE.info
            const isActive = activeAlertId === alert.id
            return (
              <div key={alert.id} style={{ marginBottom: '6px' }}>
                {/* Alert card */}
                <div
                  onClick={() => handleAlertClick(alert)}
                  style={{
                    border:       `1px solid ${isActive ? s.border : s.border + '88'}`,
                    background:   isActive ? s.bg : 'transparent',
                    borderRadius: isActive ? '3px 3px 0 0' : '3px',
                    padding:      '8px 10px',
                    cursor:       'pointer',
                    transition:   'background 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '12px' }}>{TYPE_ICON[alert.alert_type] ?? '⚠️'}</span>
                    <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: s.text, letterSpacing: '0.04em', flex: 1 }}>
                      {alert.alert_type.replace(/_/g, ' ').toUpperCase()}
                    </span>
                    <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: s.text, opacity: 0.8 }}>
                      {isActive ? '▲' : '▼ TAC'}
                    </span>
                  </div>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: '#FBFBFB', marginBottom: '3px', lineHeight: 1.3 }}>
                    {alert.title}
                  </div>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#FBFBFB', lineHeight: 1.5, fontWeight: 400 }}>
                    {alert.description}
                  </div>
                  {/* Claude triage one-liner */}
                  {triageCache[alert.id] && (
                    <div style={{
                      marginTop: '6px', padding: '5px 8px',
                      background: 'rgba(245,110,15,0.08)',
                      border: '1px solid rgba(245,110,15,0.2)',
                      borderRadius: '2px',
                      display: 'flex', alignItems: 'flex-start', gap: '5px',
                    }}>
                      <span style={{ fontSize: '10px', flexShrink: 0, marginTop: '1px', color: '#F56E0F' }}>⬡</span>
                      <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.4 }}>
                        {triageCache[alert.id].triage}
                      </span>
                      <span className="pyra-ai-badge" style={{ flexShrink: 0, marginLeft: '2px' }}>AI</span>
                    </div>
                  )}
                  {alert.expires_at && (
                    <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#aaaaaa', marginTop: '4px' }}>
                      EXP {new Date(alert.expires_at).toLocaleTimeString()}
                    </div>
                  )}
                </div>

                {/* Inline rec + dispatch panel */}
                {isActive && (
                  <div style={{
                    border: `1px solid ${s.border}`, borderTop: 'none',
                    background: '#1B1B1E', borderRadius: '0 0 3px 3px', padding: '8px 10px',
                  }}>
                    <AlertRecommendationPanel
                      alert={alert}
                      recData={recData}
                      recLoading={recLoading}
                      units={units}
                      incidents={incidents}
                      onDispatchSuccess={handleDispatchSuccess}
                      s={s}
                    />
                  </div>
                )}
              </div>
            )
          })}

          {/* Resolved tab */}
          {acked.length > 0 && (
            <>
              <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#878787', letterSpacing: '0.06em', padding: '6px 2px 4px', borderTop: '1px solid #262626', marginTop: '4px' }}>
                RESOLVED ({acked.length})
              </div>
              {acked.map(alert => (
                <div key={alert.id} style={{ border: '1px solid #262626', borderRadius: '3px', padding: '6px 10px', marginBottom: '4px', opacity: 0.45, display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: '11px' }}>{TYPE_ICON[alert.alert_type] ?? '⚠️'}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#FBFBFB', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {alert.title}
                    </div>
                    <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#4ade80', letterSpacing: '0.03em' }}>
                      ✓ RESOLVED
                    </div>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* DIVIDER */}
      <div
        onMouseDown={onDividerMouseDown}
        style={{
          height: '10px', flexShrink: 0, background: '#1B1B1E',
          borderTop: '1px solid #262626', borderBottom: '1px solid #262626',
          cursor: 'ns-resize', display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(245,110,15,0.2)'}
        onMouseLeave={e => e.currentTarget.style.background = '#1B1B1E'}
      >
        <div style={{ width: '40px', height: '3px', background: '#F56E0F', borderRadius: '2px', opacity: 0.6 }} />
      </div>

      {/* UNITS */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '80px' }}>
        {/* Header */}
        <div style={{ padding: '10px 12px 6px', flexShrink: 0 }}>
          <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: '#FBFBFB', letterSpacing: '0.06em' }}>
            UNITS DEPLOYED
          </span>
        </div>

        {/* Stats bar */}
        <div style={{ padding: '0 12px 6px', flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '12px', color: '#FBFBFB' }}>
              {deployed.length} / {units.length} deployed
            </span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '12px', color: '#4ade80' }}>
              {available.length} available
            </span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', borderRadius: '2px', width: `${units.length ? (deployed.length / units.length) * 100 : 0}%`, background: '#F56E0F' }} />
          </div>
        </div>

        {/* Status filter tabs */}
        <div style={{ display: 'flex', gap: '3px', padding: '0 8px 6px', flexShrink: 0 }}>
          {STATUS_FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setUnitFilter(f.key)}
              style={{
                flex: 1,
                padding: '3px 0',
                background:    unitFilter === f.key ? '#F56E0F' : '#1B1B1E',
                border:        `1px solid ${unitFilter === f.key ? '#F56E0F' : '#333'}`,
                borderRadius:  '2px',
                cursor:        'pointer',
                fontFamily:    'Inter, sans-serif',
                fontWeight:    700,
                fontSize:      '9px',
                color:         unitFilter === f.key ? '#FBFBFB' : '#878787',
                letterSpacing: '0.02em',
                transition:    'all 0.15s',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Grouped unit list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {(() => {
            const filtered = units
              .filter(u => unitFilter === 'all' || u.status === unitFilter)
              .sort((a, b) => {
                const ga = UNIT_TYPE_ORDER[a.unit_type] ?? 99
                const gb = UNIT_TYPE_ORDER[b.unit_type] ?? 99
                return ga !== gb ? ga - gb : a.designation.localeCompare(b.designation)
              })

            if (filtered.length === 0) {
              return (
                <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#aaaaaa', padding: '8px 4px' }}>
                  No units match filter
                </div>
              )
            }

            let lastType = null
            return filtered.map(unit => {
              const showHeader = unit.unit_type !== lastType
              lastType = unit.unit_type
              return (
                <div key={unit.id}>
                  {showHeader && (
                    <div style={{
                      fontFamily: 'Inter, sans-serif', fontWeight: 700,
                      fontSize: '10px', color: '#878787', letterSpacing: '0.06em',
                      textTransform: 'uppercase', marginTop: '8px', marginBottom: '3px',
                      paddingLeft: '2px',
                    }}>
                      {unit.unit_type.replace(/_/g, ' ')}
                    </div>
                  )}
                  <RightPanelUnitCard
                    unit={unit}
                    confirmedLoadouts={confirmedLoadouts}
                    onUnitClick={onUnitClick}
                  />
                </div>
              )
            })
          })()}
        </div>
      </div>
    </div>
  )
}