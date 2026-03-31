import { useState, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { toast } from './Toast'

const SEV = {
  critical: { border: 'rgba(239,68,68,0.45)',  bg: 'rgba(239,68,68,0.07)',  text: '#ef4444'  },
  warning:  { border: 'rgba(245,158,11,0.4)',  bg: 'rgba(245,158,11,0.06)', text: '#f59e0b'  },
  info:     { border: 'rgba(34,197,94,0.35)',  bg: 'rgba(34,197,94,0.05)',  text: '#22c55e'  },
}
const TYPE_ICON = {
  spread_warning:          '⬡',
  weather_shift:           '↻',
  route_blocked:           '⊘',
  asset_at_risk:           '!',
  water_source_constraint: '◎',
  evacuation_recommended:  '↑',
  resource_shortage:       '□',
  containment_complete:    '✓',
}
const STATUS_COLOR = {
  available:      '#22c55e',
  en_route:       '#38bdf8',
  on_scene:       '#ff4d1a',
  staging:        '#facc15',
  returning:      '#a78bfa',
  out_of_service: '#3a4558',
}
const UNIT_TYPE_ICON = {
  engine: '🚒', hand_crew: '👥', dozer: '🚜', water_tender: '🚛',
  helicopter: '🚁', air_tanker: '✈️', command_unit: '📡', rescue: '🚑',
}
const UNIT_CAPABILITIES = {
  engine:       { crew: 4,  water: '500 gal',  note: 'Structure protection, direct attack' },
  hand_crew:    { crew: 20, water: null,        note: 'Handline construction, mop-up' },
  dozer:        { crew: 1,  water: null,        note: 'Containment line, fuel breaks' },
  water_tender: { crew: 2,  water: '4000 gal', note: 'Water resupply, shuttle ops' },
  helicopter:   { crew: 3,  water: '300 gal',  note: 'Water drops, recon, crew transport' },
  air_tanker:   { crew: 2,  water: '1200 gal', note: 'Retardant drops, forward spread' },
  command_unit: { crew: 6,  water: null,        note: 'ICP ops, unified command' },
  rescue:       { crew: 3,  water: null,        note: 'Medical support, extraction' },
}
const UNIT_TYPE_ORDER = {
  engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3,
  dozer: 4, water_tender: 5, command_unit: 6, rescue: 7,
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
const STATUS_FILTERS = [
  { key: 'all',       label: 'ALL'      },
  { key: 'available', label: 'AVAIL'    },
  { key: 'en_route',  label: 'EN ROUTE' },
  { key: 'returning', label: 'RTB'      },
]

function distBetween(unit, incident) {
  if (!incident) return 999
  try {
    const dlat = unit.latitude  - incident.latitude
    const dlon = unit.longitude - incident.longitude
    return Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
  } catch { return 999 }
}

// ── Loadout tooltip for unit cards ───────────────────────────────────────────
function UnitLoadoutTooltip({ unit, loadout, rect }) {
  if (!loadout || !rect) return null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}
  const hasWater     = cap.water_gal > 0
  const hasFoam      = cap.foam_pct_max > 0
  const hasRetardant = unit.unit_type === 'air_tanker'
  const waterGal     = hasWater ? Math.round((loadout.water_pct / 100) * cap.water_gal) : 0
  const equipment    = loadout.equipment ?? []

  return createPortal(
    <div style={{
      position: 'fixed',
      top: rect.top + rect.height / 2,
      right: window.innerWidth - rect.left + 8,
      transform: 'translateY(-50%)',
      width: '230px', zIndex: 99999,
      background: 'rgba(13,15,17,0.96)',
      border: '1px solid rgba(255,77,26,0.3)',
      borderRadius: '8px', padding: '11px 13px',
      boxShadow: '0 8px 40px rgba(0,0,0,0.75)',
      pointerEvents: 'none', backdropFilter: 'blur(14px)',
    }}>
      <div style={{ position: 'absolute', right: '-5px', top: '50%', transform: 'translateY(-50%)', width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderLeft: '5px solid rgba(255,77,26,0.3)' }} />
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.1em', marginBottom: '9px' }}>
        ⬡ CONFIRMED LOADOUT · {unit.designation}
      </div>
      {hasWater && (
        <div style={{ marginBottom: '7px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#5a6878' }}>WATER</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#38bdf8' }}>{waterGal.toLocaleString()} gal ({loadout.water_pct}%)</span>
          </div>
          <div style={{ height: '2px', background: 'rgba(255,255,255,0.06)', borderRadius: '1px' }}>
            <div style={{ height: '100%', width: `${loadout.water_pct}%`, background: '#38bdf8', borderRadius: '1px' }} />
          </div>
        </div>
      )}
      {hasFoam && loadout.foam_pct > 0 && (
        <div style={{ marginBottom: '7px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#5a6878' }}>FOAM</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#22c55e' }}>{loadout.foam_pct}%</span>
          </div>
          <div style={{ height: '2px', background: 'rgba(255,255,255,0.06)', borderRadius: '1px' }}>
            <div style={{ height: '100%', width: `${(loadout.foam_pct / cap.foam_pct_max) * 100}%`, background: '#22c55e', borderRadius: '1px' }} />
          </div>
        </div>
      )}
      {hasRetardant && loadout.retardant_pct > 0 && (
        <div style={{ marginBottom: '7px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#5a6878' }}>RETARDANT</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#ff4d1a' }}>{loadout.retardant_pct}%</span>
          </div>
          <div style={{ height: '2px', background: 'rgba(255,255,255,0.06)', borderRadius: '1px' }}>
            <div style={{ height: '100%', width: `${loadout.retardant_pct}%`, background: '#ff4d1a', borderRadius: '1px' }} />
          </div>
        </div>
      )}
      {equipment.length > 0 && (
        <div style={{ marginTop: '8px', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#3a4558', letterSpacing: '0.08em', marginBottom: '5px' }}>EQUIPMENT ({equipment.length})</div>
          {equipment.map(item => (
            <div key={item} style={{ display: 'flex', gap: '5px', marginBottom: '3px' }}>
              <span style={{ color: '#22c55e', fontSize: '9px', flexShrink: 0 }}>✓</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#d4dce8', lineHeight: 1.4 }}>{item}</span>
            </div>
          ))}
        </div>
      )}
    </div>,
    document.body
  )
}

// ── Unit card for the units section ──────────────────────────────────────────
function RightPanelUnitCard({ unit, confirmedLoadouts, onUnitClick }) {
  const [tooltipRect, setTooltipRect] = useState(null)
  const loadout = confirmedLoadouts?.[unit.id] ?? null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}

  return (
    <>
      {tooltipRect && <UnitLoadoutTooltip unit={unit} loadout={loadout} rect={tooltipRect} />}
      <div
        onClick={() => onUnitClick?.(unit)}
        style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '7px 9px', marginBottom: '3px',
          background: 'rgba(255,255,255,0.02)',
          borderRadius: '5px',
          border: `1px solid ${loadout ? 'rgba(255,77,26,0.2)' : 'rgba(255,255,255,0.05)'}`,
          cursor: 'pointer', transition: 'all 0.12s',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = loadout ? 'rgba(255,77,26,0.45)' : 'rgba(255,255,255,0.12)'
          e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
          if (loadout) setTooltipRect(e.currentTarget.getBoundingClientRect())
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = loadout ? 'rgba(255,77,26,0.2)' : 'rgba(255,255,255,0.05)'
          e.currentTarget.style.background = 'rgba(255,255,255,0.02)'
          setTooltipRect(null)
        }}
      >
        <span style={{ fontSize: '13px', flexShrink: 0 }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '11px', color: '#d4dce8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {unit.designation}
            </span>
            {loadout && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#ff4d1a', fontWeight: 700, flexShrink: 0 }}>⬡</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginTop: '1px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: STATUS_COLOR[unit.status] ?? '#3a4558', letterSpacing: '0.04em' }}>
              {unit.status.replace(/_/g, ' ').toUpperCase()}
            </span>
            {loadout && cap.water_gal > 0 && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#38bdf8' }}>
                · {Math.round((loadout.water_pct / 100) * cap.water_gal).toLocaleString()} gal
              </span>
            )}
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#3a4558', marginTop: '1px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {loadout
              ? `${(loadout.equipment ?? []).length} items · hover for loadout`
              : UNIT_CAPABILITIES[unit.unit_type]?.note ?? ''}
          </div>
        </div>
        <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: STATUS_COLOR[unit.status] ?? '#3a4558', flexShrink: 0 }} />
      </div>
    </>
  )
}

// ── Inline AI recommendation + dispatch panel ─────────────────────────────────
function AlertRecommendationPanel({ alert, recData, recLoading, units, incidents, onDispatchSuccess, s }) {
  const [selectedUnits, setSelectedUnits] = useState([])
  const [dispatching, setDispatching]     = useState(false)
  const [dispatched, setDispatched]       = useState(false)
  const auth = useAuth()
  const incident = incidents?.find(i => i.id === alert.incident_id)
  const canDispatch = selectedUnits.length > 0 && !dispatching && auth?.role !== 'viewer'
  const recommendedTypes = new Set(recData?.units?.map(u => u.unit_type) ?? [])

  const available = [...units.filter(u => u.status === 'available')].sort((a, b) => {
    const as_ = recommendedTypes.has(a.unit_type) ? 0 : 1
    const bs_ = recommendedTypes.has(b.unit_type) ? 0 : 1
    if (as_ !== bs_) return as_ - bs_
    const ga = UNIT_TYPE_ORDER[a.unit_type] ?? 99
    const gb = UNIT_TYPE_ORDER[b.unit_type] ?? 99
    if (ga !== gb) return ga - gb
    return distBetween(a, incident) - distBetween(b, incident)
  })

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
    } catch { toast('Dispatch failed — check unit availability', 'error') }
    finally { setDispatching(false) }
  }

  if (recLoading) return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#3a4558', letterSpacing: '0.06em', padding: '4px 0' }}>
      LOADING RECOMMENDATION…
    </div>
  )
  if (recData?.error) return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#ef4444' }}>Failed to load recommendation.</div>
  )
  if (!recData) return null
  if (dispatched) return (
    <div style={{
      background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.3)',
      borderRadius: '5px', padding: '8px 10px', textAlign: 'center',
      fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: '#22c55e', letterSpacing: '0.06em',
    }}>
      ✓ UNITS DISPATCHED · ALERT RESOLVED
    </div>
  )

  return (
    <>
      {recData.summary && (
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.5, marginBottom: '9px' }}>
          {recData.summary}
        </div>
      )}

      {recData.actions?.length > 0 && (
        <div style={{ marginBottom: '9px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: s.text, letterSpacing: '0.08em', marginBottom: '5px' }}>ACTIONS</div>
          {recData.actions.map((action, i) => (
            <div key={i} style={{ display: 'flex', gap: '6px', marginBottom: '3px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: s.text, flexShrink: 0, marginTop: '1px' }}>{i + 1}.</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.5 }}>{action}</span>
            </div>
          ))}
        </div>
      )}

      {recData.units?.length > 0 && (
        <div style={{ marginBottom: '9px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: s.text, letterSpacing: '0.08em', marginBottom: '5px' }}>RECOMMENDED UNITS</div>
          {recData.units.map((u, i) => {
            const filled = (selectedByType[u.unit_type] ?? 0) >= u.quantity
            return (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                background: filled ? 'rgba(34,197,94,0.07)' : 'rgba(255,255,255,0.02)',
                border: `1px solid ${filled ? 'rgba(34,197,94,0.3)' : 'rgba(255,255,255,0.06)'}`,
                borderRadius: '4px', padding: '4px 8px', marginBottom: '3px',
                transition: 'all 0.15s',
              }}>
                <span style={{ fontSize: '11px' }}>{UNIT_TYPE_ICON[u.unit_type] ?? '◉'}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px', color: filled ? '#22c55e' : '#d4dce8', flex: 1 }}>
                  {u.quantity}× {u.unit_type.replace(/_/g, ' ').toUpperCase()}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: filled ? '#22c55e' : '#3a4558', letterSpacing: '0.04em' }}>
                  {filled ? '✓ FILLED' : u.priority?.replace(/_/g, ' ').toUpperCase()}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {alert.incident_id && (
        <>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: s.text, letterSpacing: '0.08em', marginBottom: '5px' }}>SELECT UNITS TO DISPATCH</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '9px' }}>
            {available.length === 0 && (
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#3a4558', padding: '4px 0' }}>No available units</div>
            )}
            {(() => {
              let lastType = null
              return available.map(unit => {
                const isSelected  = selectedUnits.includes(unit.id)
                const isSuggested = recommendedTypes.has(unit.unit_type)
                const showHeader  = unit.unit_type !== lastType
                lastType = unit.unit_type
                const dist = distBetween(unit, incident)
                const distLabel = dist < 999 ? (dist < 1 ? `${Math.round(dist * 5280)} ft` : `${dist.toFixed(1)} mi`) : null
                return (
                  <div key={unit.id}>
                    {showHeader && (
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', fontWeight: 600, color: '#3a4558', letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: '5px', marginBottom: '2px', paddingLeft: '2px' }}>
                        {unit.unit_type.replace(/_/g, ' ')}
                      </div>
                    )}
                    <div
                      onClick={() => setSelectedUnits(prev => prev.includes(unit.id) ? prev.filter(id => id !== unit.id) : [...prev, unit.id])}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '6px',
                        padding: '5px 8px', borderRadius: '4px', cursor: 'pointer',
                        background: isSelected ? 'rgba(255,77,26,0.08)' : 'rgba(255,255,255,0.02)',
                        border: `1px solid ${isSelected ? 'rgba(255,77,26,0.4)' : isSuggested ? 'rgba(255,77,26,0.15)' : 'rgba(255,255,255,0.05)'}`,
                        transition: 'all 0.12s',
                      }}
                    >
                      <span style={{ fontSize: '11px' }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px', color: isSelected ? '#d4dce8' : '#5a6878', flex: 1 }}>{unit.designation}</span>
                      {distLabel && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: '#3a4558' }}>{distLabel}</span>}
                      {isSuggested && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#ff4d1a' }}>★</span>}
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
              width: '100%', padding: '8px',
              background: canDispatch ? '#ff4d1a' : 'rgba(255,255,255,0.04)',
              border: 'none', borderRadius: '5px',
              cursor: canDispatch ? 'pointer' : 'not-allowed',
              fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px',
              color: canDispatch ? '#fff' : '#3a4558',
              letterSpacing: '0.08em', transition: 'all 0.15s',
              boxShadow: canDispatch ? '0 0 16px rgba(255,77,26,0.3)' : 'none',
            }}
          >
            {dispatching
              ? 'DISPATCHING…'
              : auth?.role === 'viewer'
              ? 'COMMANDER / DISPATCHER ONLY'
              : selectedUnits.length
              ? `DISPATCH ${selectedUnits.length} UNIT${selectedUnits.length !== 1 ? 'S' : ''} · RESOLVE ALERT`
              : 'SELECT UNITS'}
          </button>
        </>
      )}
    </>
  )
}

// ── Main RightPanel ───────────────────────────────────────────────────────────
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
    if (activeAlertId === alert.id) { setActiveAlertId(null); setRecData(null); return }
    setActiveAlertId(alert.id); setRecData(null); setRecLoading(true)
    if (!triageCache[alert.id]) {
      api.triage(alert.id)
        .then(result => setTriageCache(prev => ({ ...prev, [alert.id]: result })))
        .catch(() => {})
    }
    try {
      const data = await api.alertRecommendation(alert.id)
      setRecData(data)
    } catch { setRecData({ error: true }) }
    finally { setRecLoading(false) }
  }

  function handleDispatchSuccess() { setActiveAlertId(null); setRecData(null); onAlertsChanged?.() }

  const filteredAlerts = selectedIncidentId ? alerts.filter(a => a.incident_id === selectedIncidentId) : alerts
  const unacked   = filteredAlerts.filter(a => !a.is_acknowledged)
  const acked     = filteredAlerts.filter(a =>  a.is_acknowledged)
  const deployed  = units.filter(u => u.assigned_incident_id)
  const available = units.filter(u => u.status === 'available')

  return (
    <div style={{
      width: 'min(268px, 30vw)', minWidth: '200px',
      background: 'rgba(13,15,17,0.88)',
      borderLeft: '1px solid rgba(255,255,255,0.055)',
      backdropFilter: 'blur(14px)',
      display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden',
      animation: 'slide-left 0.25s ease-out',
    }}>

      {/* ── ALERTS SECTION ── */}
      <div style={{ height: `${alertsHeight}px`, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '80px' }}>

        {/* Header */}
        <div style={{ padding: '10px 12px 8px', flexShrink: 0, display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: '#d4dce8', letterSpacing: '0.1em', flex: 1 }}>
            ACTIVE ALERTS
          </span>
          {unacked.length > 0 && (
            <span style={{
              background: '#ff4d1a', color: '#fff',
              borderRadius: '3px', padding: '1px 6px',
              fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px',
              boxShadow: '0 0 8px rgba(255,77,26,0.4)',
            }}>
              {unacked.length > 99 ? '99+' : unacked.length}
            </span>
          )}
          {alerts.length > 5 && (
            <button
              onClick={() => { if (window.confirm(`Clear all ${alerts.length} alerts?`)) api.clearAllAlerts().then(() => onAlertsChanged?.()) }}
              style={{
                background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)',
                borderRadius: '3px', padding: '2px 7px', cursor: 'pointer',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '8.5px',
                color: '#ef4444', letterSpacing: '0.06em', transition: 'background 0.1s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.2)'}
              onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.1)'}
            >
              CLEAR ALL
            </button>
          )}
        </div>

        {/* Alert list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '5px 8px 0' }}>
          {unacked.length === 0 && (
            <div style={{ padding: '20px', textAlign: 'center' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', color: '#22c55e', opacity: 0.3, marginBottom: '6px' }}>✓</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#3a4558', letterSpacing: '0.1em' }}>ALL CLEAR</div>
            </div>
          )}

          {unacked.map(alert => {
            const s        = SEV[alert.severity] ?? SEV.info
            const isActive = activeAlertId === alert.id
            const triage   = triageCache[alert.id]
            return (
              <div key={alert.id} style={{ marginBottom: '6px', animation: 'fade-up 0.2s ease-out' }}>
                {/* Alert card header */}
                <div
                  onClick={() => handleAlertClick(alert)}
                  style={{
                    border:       `1px solid ${isActive ? s.border : s.border.replace('0.45', '0.2').replace('0.4', '0.18').replace('0.35', '0.15')}`,
                    background:   isActive ? s.bg : 'transparent',
                    borderRadius: isActive ? '6px 6px 0 0' : '6px',
                    padding:      '9px 10px',
                    cursor:       'pointer',
                    transition:   'all 0.15s',
                    boxShadow:    isActive && alert.severity === 'critical' ? `0 0 12px ${s.border}` : 'none',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '5px' }}>
                    <div style={{
                      width: '18px', height: '18px', borderRadius: '3px', flexShrink: 0,
                      background: s.bg, border: `1px solid ${s.border}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: 'var(--font-mono)', fontSize: '10px', fontWeight: 700, color: s.text,
                    }}>
                      {TYPE_ICON[alert.alert_type] ?? '·'}
                    </div>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: s.text, letterSpacing: '0.08em', flex: 1 }}>
                      {alert.alert_type.replace(/_/g, ' ').toUpperCase()}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#3a4558' }}>
                      {isActive ? '▲' : '▼ TAC'}
                    </span>
                  </div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8', marginBottom: '3px', lineHeight: 1.3 }}>
                    {alert.title}
                  </div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#5a6878', lineHeight: 1.5 }}>
                    {alert.description}
                  </div>
                  {/* AI triage one-liner */}
                  {triage && (
                    <div style={{
                      marginTop: '7px', padding: '5px 8px',
                      background: 'rgba(255,77,26,0.06)',
                      border: '1px solid rgba(255,77,26,0.18)',
                      borderRadius: '4px',
                      display: 'flex', alignItems: 'flex-start', gap: '5px',
                    }}>
                      <span style={{ fontSize: '10px', flexShrink: 0, marginTop: '1px', color: '#ff4d1a' }}>⬡</span>
                      <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#d4dce8', lineHeight: 1.4 }}>
                        {triage.triage}
                      </span>
                    </div>
                  )}
                  {alert.expires_at && (
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#3a4558', marginTop: '4px', letterSpacing: '0.04em' }}>
                      EXP {new Date(alert.expires_at).toLocaleTimeString()}
                    </div>
                  )}
                </div>

                {/* Expanded recommendation + dispatch panel */}
                {isActive && (
                  <div style={{
                    border: `1px solid ${s.border}`, borderTop: 'none',
                    background: 'rgba(13,15,17,0.95)',
                    borderRadius: '0 0 6px 6px', padding: '10px 10px',
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

          {/* Resolved alerts */}
          {acked.length > 0 && (
            <>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#3a4558', letterSpacing: '0.1em', padding: '7px 2px 5px', borderTop: '1px solid rgba(255,255,255,0.05)', marginTop: '4px' }}>
                RESOLVED ({acked.length})
              </div>
              {acked.map(alert => (
                <div key={alert.id} style={{
                  border: '1px solid rgba(255,255,255,0.05)', borderRadius: '5px',
                  padding: '6px 10px', marginBottom: '4px', opacity: 0.4,
                  display: 'flex', alignItems: 'center', gap: '7px',
                }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#3a4558' }}>
                    {TYPE_ICON[alert.alert_type] ?? '·'}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#5a6878', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {alert.title}
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: '#22c55e', letterSpacing: '0.04em' }}>✓ RESOLVED</div>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ── DRAG DIVIDER ── */}
      <div
        onMouseDown={onDividerMouseDown}
        style={{
          height: '10px', flexShrink: 0,
          background: 'rgba(13,15,17,0.8)',
          borderTop: '1px solid rgba(255,255,255,0.05)',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          cursor: 'ns-resize',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,77,26,0.1)'}
        onMouseLeave={e => e.currentTarget.style.background = 'rgba(13,15,17,0.8)'}
      >
        <div style={{ width: '36px', height: '2px', background: '#ff4d1a', borderRadius: '1px', opacity: 0.5 }} />
      </div>

      {/* ── UNITS SECTION ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: '80px' }}>

        {/* Header */}
        <div style={{ padding: '9px 12px 5px', flexShrink: 0, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: '#d4dce8', letterSpacing: '0.1em' }}>
            UNITS DEPLOYED
          </span>
        </div>

        {/* Deployment bar */}
        <div style={{ padding: '8px 12px 5px', flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px', color: '#d4dce8' }}>
              {deployed.length} / {units.length} deployed
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px', color: '#22c55e' }}>
              {available.length} avail
            </span>
          </div>
          <div style={{ height: '2px', background: 'rgba(255,255,255,0.06)', borderRadius: '1px' }}>
            <div style={{ height: '100%', borderRadius: '1px', width: `${units.length ? (deployed.length / units.length) * 100 : 0}%`, background: '#ff4d1a', transition: 'width 0.4s ease' }} />
          </div>
        </div>

        {/* Status filter tabs */}
        <div style={{ display: 'flex', gap: '3px', padding: '0 8px 6px', flexShrink: 0 }}>
          {STATUS_FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setUnitFilter(f.key)}
              style={{
                flex: 1, padding: '4px 0',
                background: unitFilter === f.key ? '#ff4d1a' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${unitFilter === f.key ? '#ff4d1a' : 'rgba(255,255,255,0.06)'}`,
                borderRadius: '4px', cursor: 'pointer',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '8px',
                color: unitFilter === f.key ? '#fff' : '#3a4558',
                letterSpacing: '0.05em', transition: 'all 0.15s',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Unit list */}
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
              return <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#3a4558', padding: '10px 4px' }}>No units match filter</div>
            }

            let lastType = null
            return filtered.map(unit => {
              const showHeader = unit.unit_type !== lastType
              lastType = unit.unit_type
              return (
                <div key={unit.id}>
                  {showHeader && (
                    <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '8.5px', color: '#3a4558', letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: '8px', marginBottom: '3px', paddingLeft: '2px' }}>
                      {unit.unit_type.replace(/_/g, ' ')}
                    </div>
                  )}
                  <RightPanelUnitCard unit={unit} confirmedLoadouts={confirmedLoadouts} onUnitClick={onUnitClick} />
                </div>
              )
            })
          })()}
        </div>
      </div>
    </div>
  )
}
