import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { toast } from './Toast'

const SEV = {
  critical: { border: 'rgba(239,68,68,0.45)', bg: 'rgba(239,68,68,0.08)', text: '#ef4444' },
  warning:  { border: 'rgba(245,158,11,0.42)', bg: 'rgba(245,158,11,0.08)', text: '#f59e0b' },
  info:     { border: 'rgba(56,189,248,0.38)', bg: 'rgba(56,189,248,0.08)', text: '#38bdf8' },
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
  out_of_service: '#9baac0',
}
const UNIT_TYPE_ICON = {
  engine: '🚒', hand_crew: '👥', dozer: '🚜', water_tender: '🚛',
  helicopter: '🚁', air_tanker: '✈️', command_unit: '📡', rescue: '🚑',
}
const UNIT_CAPABILITIES = {
  engine:       { crew: 4, water: '500 gal', note: 'Structure protection, direct attack' },
  hand_crew:    { crew: 20, water: null, note: 'Handline construction, mop-up' },
  dozer:        { crew: 1, water: null, note: 'Containment line, fuel breaks' },
  water_tender: { crew: 2, water: '4000 gal', note: 'Water resupply, shuttle ops' },
  helicopter:   { crew: 3, water: '300 gal', note: 'Water drops, recon, crew transport' },
  air_tanker:   { crew: 2, water: '1200 gal', note: 'Retardant drops, forward spread' },
  command_unit: { crew: 6, water: null, note: 'ICP ops, unified command' },
  rescue:       { crew: 3, water: null, note: 'Medical support, extraction' },
}
const UNIT_TYPE_ORDER = {
  engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3,
  dozer: 4, water_tender: 5, command_unit: 6, rescue: 7,
}
const UNIT_CAPACITY = {
  engine:       { water_gal: 500, foam_pct_max: 6 },
  water_tender: { water_gal: 4000, foam_pct_max: 3 },
  helicopter:   { water_gal: 300, foam_pct_max: 1 },
  air_tanker:   { water_gal: 0, foam_pct_max: 0 },
  hand_crew:    { water_gal: 0, foam_pct_max: 0 },
  dozer:        { water_gal: 0, foam_pct_max: 0 },
  command_unit: { water_gal: 0, foam_pct_max: 0 },
  rescue:       { water_gal: 0, foam_pct_max: 0 },
}
const STATUS_FILTERS = [
  { key: 'all', label: 'ALL' },
  { key: 'available', label: 'AVAIL' },
  { key: 'on_scene', label: 'SCENE' },
  { key: 'en_route', label: 'ROUTE' },
  { key: 'returning', label: 'RTB' },
]

function parseUTC(str) {
  if (!str) return new Date(0)
  return new Date(str.endsWith('Z') ? str : str + 'Z')
}

function fmtPDT(date) {
  try {
    return date.toLocaleTimeString('en-US', {
      timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit',
      hour12: false,
    }) + ' PDT'
  } catch {
    return date.toLocaleTimeString()
  }
}

function distBetween(unit, incident) {
  if (!incident) return 999
  try {
    const dlat = unit.latitude - incident.latitude
    const dlon = unit.longitude - incident.longitude
    return Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
  } catch {
    return 999
  }
}

function UnitLoadoutTooltip({ unit, loadout, rect }) {
  if (!loadout || !rect) return null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}
  const hasWater = cap.water_gal > 0
  const hasFoam = cap.foam_pct_max > 0
  const hasRetardant = unit.unit_type === 'air_tanker'
  const waterGal = hasWater ? Math.round((loadout.water_pct / 100) * cap.water_gal) : 0
  const equipment = loadout.equipment ?? []

  return createPortal(
    <div style={{
      position: 'fixed',
      top: rect.top + rect.height / 2,
      right: window.innerWidth - rect.left + 10,
      transform: 'translateY(-50%)',
      width: '236px', zIndex: 99999,
      background: 'rgba(20,26,36,0.94)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '16px', padding: '12px 14px',
      boxShadow: '0 18px 48px rgba(0,0,0,0.55)',
      pointerEvents: 'none', backdropFilter: 'blur(14px)',
    }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.1em', marginBottom: '9px' }}>
        ⬡ CONFIRMED LOADOUT · {unit.designation}
      </div>
      {hasWater && (
        <div style={{ marginBottom: '7px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#9baac0' }}>WATER</span>
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
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#9baac0' }}>FOAM</span>
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
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#9baac0' }}>RETARDANT</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#ff4d1a' }}>{loadout.retardant_pct}%</span>
          </div>
          <div style={{ height: '2px', background: 'rgba(255,255,255,0.06)', borderRadius: '1px' }}>
            <div style={{ height: '100%', width: `${loadout.retardant_pct}%`, background: '#ff4d1a', borderRadius: '1px' }} />
          </div>
        </div>
      )}
      {equipment.length > 0 && (
        <div style={{ marginTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '8px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#9baac0', letterSpacing: '0.08em', marginBottom: '5px' }}>EQUIPMENT ({equipment.length})</div>
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

function RightPanelUnitCard({ unit, confirmedLoadouts, onUnitClick, focused, incidentName }) {
  const [tooltipRect, setTooltipRect] = useState(null)
  const loadout = confirmedLoadouts?.[unit.id] ?? null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}

  return (
    <>
      {tooltipRect && <UnitLoadoutTooltip unit={unit} loadout={loadout} rect={tooltipRect} />}
      <div
        className="ui-hover-lift"
        onClick={() => onUnitClick?.(unit)}
        style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '8px 9px', marginBottom: '5px',
          background: focused ? 'rgba(56,189,248,0.12)' : 'rgba(255,255,255,0.05)',
          borderRadius: '14px',
          border: `1px solid ${focused ? 'rgba(56,189,248,0.28)' : loadout ? 'rgba(255,77,26,0.22)' : 'rgba(255,255,255,0.08)'}`,
          cursor: 'pointer', transition: 'all 0.12s',
          boxShadow: focused ? '0 12px 24px rgba(56,189,248,0.16)' : 'none',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = focused ? 'rgba(56,189,248,0.38)' : loadout ? 'rgba(255,77,26,0.45)' : 'rgba(255,255,255,0.16)'
          e.currentTarget.style.background = focused ? 'rgba(56,189,248,0.15)' : 'rgba(255,255,255,0.07)'
          if (loadout) setTooltipRect(e.currentTarget.getBoundingClientRect())
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = focused ? 'rgba(56,189,248,0.28)' : loadout ? 'rgba(255,77,26,0.22)' : 'rgba(255,255,255,0.08)'
          e.currentTarget.style.background = focused ? 'rgba(56,189,248,0.12)' : 'rgba(255,255,255,0.05)'
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
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: STATUS_COLOR[unit.status] ?? '#7a8ba0', letterSpacing: '0.04em' }}>
              {unit.status.replace(/_/g, ' ').toUpperCase()}
            </span>
            {loadout && cap.water_gal > 0 && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#38bdf8' }}>
                · {Math.round((loadout.water_pct / 100) * cap.water_gal).toLocaleString()} gal
              </span>
            )}
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#9baac0', marginTop: '1px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {incidentName
              ? `${incidentName} · ${loadout ? `${(loadout.equipment ?? []).length} items` : UNIT_CAPABILITIES[unit.unit_type]?.note ?? ''}`
              : loadout
              ? `${(loadout.equipment ?? []).length} items · hover for loadout`
              : UNIT_CAPABILITIES[unit.unit_type]?.note ?? ''}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
          {focused && <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#38bdf8', boxShadow: '0 0 10px #38bdf8' }} />}
          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: STATUS_COLOR[unit.status] ?? '#7a8ba0' }} />
        </div>
      </div>
    </>
  )
}

function AlertRecommendationPanel({ alert, recData, recLoading, units, incidents, onDispatchSuccess, s }) {
  const [selectedUnits, setSelectedUnits] = useState([])
  const [dispatching, setDispatching] = useState(false)
  const [dispatched, setDispatched] = useState(false)
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
    } catch {
      toast('Dispatch failed — check unit availability', 'error')
    } finally {
      setDispatching(false)
    }
  }

  if (recLoading) {
    return (
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#9baac0', letterSpacing: '0.06em', padding: '4px 0' }}>
        LOADING RECOMMENDATION…
      </div>
    )
  }
  if (recData?.error) {
    return <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#ef4444' }}>Failed to load recommendation.</div>
  }
  if (!recData) return null
  if (dispatched) {
    return (
      <div style={{
        background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.3)',
        borderRadius: '10px', padding: '9px 10px', textAlign: 'center',
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: '#22c55e', letterSpacing: '0.06em',
      }}>
        ✓ UNITS DISPATCHED · ALERT RESOLVED
      </div>
    )
  }

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
                background: filled ? 'rgba(34,197,94,0.08)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${filled ? 'rgba(34,197,94,0.3)' : 'rgba(255,255,255,0.1)'}`,
                borderRadius: '9px', padding: '4px 8px', marginBottom: '3px',
              }}>
                <span style={{ fontSize: '11px' }}>{UNIT_TYPE_ICON[u.unit_type] ?? '◉'}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px', color: filled ? '#22c55e' : '#d4dce8', flex: 1 }}>
                  {u.quantity}× {u.unit_type.replace(/_/g, ' ').toUpperCase()}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: filled ? '#22c55e' : '#9baac0', letterSpacing: '0.04em' }}>
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '9px', maxHeight: '180px', overflowY: 'auto' }}>
            {available.length === 0 && (
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#9baac0', padding: '4px 0' }}>No available units</div>
            )}
            {(() => {
              let lastType = null
              return available.map(unit => {
                const isSelected = selectedUnits.includes(unit.id)
                const isSuggested = recommendedTypes.has(unit.unit_type)
                const showHeader = unit.unit_type !== lastType
                lastType = unit.unit_type
                const dist = distBetween(unit, incident)
                const distLabel = dist < 999 ? (dist < 1 ? `${Math.round(dist * 5280)} ft` : `${dist.toFixed(1)} mi`) : null
                return (
                  <div key={unit.id}>
                    {showHeader && (
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', fontWeight: 600, color: '#9baac0', letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: '5px', marginBottom: '2px', paddingLeft: '2px' }}>
                        {unit.unit_type.replace(/_/g, ' ')}
                      </div>
                    )}
                    <div
                      className="ui-hover-lift"
                      onClick={() => setSelectedUnits(prev => prev.includes(unit.id) ? prev.filter(id => id !== unit.id) : [...prev, unit.id])}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '6px',
                        padding: '5px 8px', borderRadius: '8px', cursor: 'pointer',
                        background: isSelected ? 'rgba(255,77,26,0.1)' : 'rgba(255,255,255,0.03)',
                        border: `1px solid ${isSelected ? 'rgba(255,77,26,0.45)' : isSuggested ? 'rgba(255,77,26,0.2)' : 'rgba(255,255,255,0.1)'}`,
                      }}
                    >
                      <span style={{ fontSize: '11px' }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px', color: isSelected ? '#d4dce8' : '#9baac0', flex: 1 }}>{unit.designation}</span>
                      {distLabel && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: '#9baac0' }}>{distLabel}</span>}
                      {isSuggested && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#ff4d1a' }}>★</span>}
                    </div>
                  </div>
                )
              })
            })()}
          </div>

          <button
            className={canDispatch ? 'ui-interactive-btn' : ''}
            onClick={handleDispatch}
            disabled={!canDispatch}
            style={{
              width: '100%', padding: '8px',
              background: canDispatch ? '#ff4d1a' : 'rgba(255,255,255,0.06)',
              border: 'none', borderRadius: '9px',
              cursor: canDispatch ? 'pointer' : 'not-allowed',
              fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px',
              color: canDispatch ? '#fff' : '#9baac0',
              letterSpacing: '0.08em', boxShadow: canDispatch ? '0 8px 20px rgba(255,77,26,0.32)' : 'none',
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

export default function RightPanel({ alerts, units, incidents = [], selectedIncidentId, onUnitClick, onAlertsChanged, confirmedLoadouts = {}, focusedUnitId = null, panelWidth = 360 }) {
  const [activeAlertId, setActiveAlertId] = useState(null)
  const [triageCache, setTriageCache] = useState({})
  const [unitFilter, setUnitFilter] = useState('all')
  const [recData, setRecData] = useState(null)
  const [recLoading, setRecLoading] = useState(false)
  const [showResolved, setShowResolved] = useState(false)
  const [allAlertsMode, setAllAlertsMode] = useState(null) // null | 'newest' | 'oldest'
  const [pinnedIds, setPinnedIds] = useState(new Set())
  const [collapsed, setCollapsed] = useState(false)
  const [feedRatio, setFeedRatio] = useState(0.62)
  const [isResizing, setIsResizing] = useState(false)
  const panelRef = useRef(null)
  const feedRef = useRef(null)

  useEffect(() => {
    if (!isResizing) return

    function onMove(e) {
      if (!panelRef.current) return
      const rect = panelRef.current.getBoundingClientRect()
      const relativeY = e.clientY - rect.top
      const next = (relativeY - 132) / Math.max(rect.height - 250, 1)
      setFeedRatio(Math.min(0.78, Math.max(0.28, next)))
    }

    function onUp() {
      setIsResizing(false)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [isResizing])

  async function handleAlertClick(alert) {
    if (activeAlertId === alert.id) {
      setActiveAlertId(null)
      setRecData(null)
      return
    }
    setActiveAlertId(alert.id)
    setRecData(null)
    setRecLoading(true)
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

  const filteredAlerts = (selectedIncidentId && !allAlertsMode) ? alerts.filter(a => a.incident_id === selectedIncidentId) : alerts
  const unacked = filteredAlerts.filter(a => !a.is_acknowledged)
  const timelineEvents = incidents
    .filter(i => !selectedIncidentId || allAlertsMode || i.id === selectedIncidentId)
    .map(i => ({
      id: `inc-${i.id}`,
      type: 'timeline',
      ts: parseUTC(i.started_at).getTime(),
      time: fmtPDT(parseUTC(i.started_at)),
      title: `${i.name} detected`,
      subtitle: `${i.severity?.toUpperCase()} · ${i.acres_burned?.toLocaleString()} acres · ${i.spread_risk} spread risk`,
      severity: i.severity,
      incident_id: i.id,
    }))

  const alertEvents = filteredAlerts.map(a => ({
    id: a.id,
    type: 'alert',
    ts: parseUTC(a.created_at).getTime(),
    time: fmtPDT(parseUTC(a.created_at)),
    title: a.title,
    subtitle: a.description,
    severity: a.severity,
    alert_type: a.alert_type,
    acknowledged: a.is_acknowledged,
    incident_id: a.incident_id,
    expires_at: a.expires_at,
    raw: a,
  }))

  const activityFeed = [...alertEvents, ...timelineEvents]
    .filter(e => allAlertsMode || showResolved || e.type === 'timeline' || !e.acknowledged)
    .sort((a, b) => {
      if (!allAlertsMode) {
        const aPinned = pinnedIds.has(a.id) ? 0 : 1
        const bPinned = pinnedIds.has(b.id) ? 0 : 1
        if (aPinned !== bPinned) return aPinned - bPinned
      }
      return allAlertsMode === 'oldest' ? a.ts - b.ts : b.ts - a.ts
    })

  const selectedAlert = filteredAlerts.find(a => a.id === activeAlertId) ?? null

  const systemUnits = units.filter(
    u => ['available', 'en_route', 'on_scene', 'returning'].includes(u.status)
  )
  const filteredUnits = systemUnits
    .filter(u => unitFilter === 'all' || u.status === unitFilter)
    .sort((a, b) => {
      const statusOrder = { on_scene: 0, en_route: 1, returning: 2, available: 3 }
      const sa = statusOrder[a.status] ?? 9
      const sb = statusOrder[b.status] ?? 9
      if (sa !== sb) return sa - sb
      const ga = UNIT_TYPE_ORDER[a.unit_type] ?? 99
      const gb = UNIT_TYPE_ORDER[b.unit_type] ?? 99
      return ga !== gb ? ga - gb : (a.designation ?? '').localeCompare(b.designation ?? '')
    })

  if (collapsed) {
    return (
      <div className="ui-shell-panel ui-float-soft-delayed ui-panel-enter" style={{
        width: '58px',
        background: 'linear-gradient(180deg, rgba(28,35,47,0.9) 0%, rgba(18,24,34,0.95) 100%)',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '20px',
        backdropFilter: 'blur(14px)',
        boxShadow: '0 24px 56px rgba(0,0,0,0.38), inset 0 1px 0 rgba(255,255,255,0.05)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '10px',
        padding: '12px 8px',
      }}>
        <button
          className="ui-interactive-btn"
          onClick={() => setCollapsed(false)}
          style={{
            width: '40px', height: '40px', borderRadius: '12px',
            border: '1px solid rgba(255,255,255,0.14)',
            background: 'rgba(255,255,255,0.04)',
            cursor: 'pointer', color: '#d4dce8',
            fontFamily: 'var(--font-mono)', fontSize: '16px',
          }}
        >
          ≡
        </button>
        <div style={{ width: '100%', textAlign: 'center' }}>
          <div style={{ color: '#ef4444', fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 700 }}>{unacked.length}</div>
          <div style={{ color: '#a7b5c7', fontFamily: 'var(--font-mono)', fontSize: '8px', letterSpacing: '0.08em' }}>ACTIVE</div>
        </div>
        <div style={{ width: '100%', textAlign: 'center' }}>
          <div style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 700 }}>{filteredUnits.length}</div>
          <div style={{ color: '#a7b5c7', fontFamily: 'var(--font-mono)', fontSize: '8px', letterSpacing: '0.08em' }}>UNITS</div>
        </div>
      </div>
    )
  }

  return (
    <div ref={panelRef} className="ui-shell-panel ui-float-soft-delayed ui-panel-enter" style={{
      width: `${panelWidth}px`,
      minWidth: `${panelWidth}px`,
      maxWidth: `${panelWidth}px`,
      height: '100%',
      background: 'linear-gradient(180deg, rgba(28,35,47,0.9) 0%, rgba(18,24,34,0.95) 100%)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '20px',
      backdropFilter: 'blur(14px)',
      boxShadow: '0 24px 56px rgba(0,0,0,0.38), inset 0 1px 0 rgba(255,255,255,0.05)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      animation: 'slide-left 0.25s ease-out',
    }}>
      <div style={{ padding: '12px 13px 10px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: '#d4dce8', letterSpacing: '0.1em' }}>ACTIVITY FEED</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#a7b5c7', letterSpacing: '0.08em', marginTop: '2px' }}>
            ALERTS + TIMELINE STREAM
          </div>
        </div>
        <span style={{
          background: 'rgba(239,68,68,0.18)', color: '#ef4444',
          border: '1px solid rgba(239,68,68,0.35)', borderRadius: '999px',
          padding: '2px 8px', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px',
        }}>
          {unacked.length} ACTIVE
        </span>
        <button
          className="ui-interactive-btn"
          onClick={() => setCollapsed(true)}
          style={{
            width: '30px', height: '30px', borderRadius: '9px',
            border: '1px solid rgba(255,255,255,0.14)',
            background: 'rgba(255,255,255,0.06)',
            cursor: 'pointer', color: '#c3d0df', fontSize: '15px',
          }}
        >
          ×
        </button>
      </div>

      <div style={{ padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', gap: '7px', flexWrap: 'wrap' }}>
        <button
          className="ui-interactive-btn"
          onClick={() => setAllAlertsMode(m => m === null ? 'newest' : m === 'newest' ? 'oldest' : null)}
          style={{
            borderRadius: '999px',
            border: `1px solid ${allAlertsMode ? 'rgba(56,189,248,0.45)' : 'rgba(255,255,255,0.12)'}`,
            background: allAlertsMode ? 'rgba(56,189,248,0.12)' : 'rgba(255,255,255,0.05)',
            color: allAlertsMode ? '#38bdf8' : '#c3d0df',
            fontFamily: 'var(--font-mono)', fontSize: '8px', letterSpacing: '0.06em',
            padding: '4px 9px', cursor: 'pointer',
          }}
        >
          {allAlertsMode === 'oldest' ? '↑ ALL OLDEST' : allAlertsMode === 'newest' ? '↓ ALL NEWEST' : 'ALL ALERTS'}
        </button>
        <button
          className="ui-interactive-btn"
          onClick={() => setShowResolved(v => !v)}
          style={{
            borderRadius: '999px',
            border: `1px solid ${showResolved ? 'rgba(34,197,94,0.35)' : 'rgba(255,255,255,0.12)'}`,
            background: showResolved ? 'rgba(34,197,94,0.12)' : 'rgba(255,255,255,0.05)',
            color: showResolved ? '#22c55e' : '#c3d0df',
            fontFamily: 'var(--font-mono)', fontSize: '8px', letterSpacing: '0.06em',
            padding: '4px 9px', cursor: 'pointer',
          }}
        >
          {showResolved ? 'HIDE RESOLVED' : 'SHOW RESOLVED'}
        </button>
        {alerts.length > 5 && (
          <button
            className="ui-interactive-btn"
            onClick={() => {
              if (window.confirm(`Clear all ${alerts.length} alerts?`)) {
                api.clearAllAlerts().then(() => onAlertsChanged?.())
              }
            }}
            style={{
              borderRadius: '999px', border: '1px solid rgba(239,68,68,0.32)',
              background: 'rgba(239,68,68,0.08)', color: '#ef4444',
              fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '8px',
              padding: '4px 9px', letterSpacing: '0.06em', cursor: 'pointer',
            }}
          >
            CLEAR ALERTS
          </button>
        )}
      </div>

      <div
        ref={feedRef}
        style={{
          flex: `${feedRatio} 1 0`,
          minHeight: '150px',
          overflowY: 'auto',
          padding: '8px 10px 10px',
        }}
      >
        {activityFeed.length === 0 && (
          <div style={{ padding: '18px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', color: '#22c55e', opacity: 0.4, marginBottom: '5px' }}>✓</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#a7b5c7', letterSpacing: '0.1em' }}>NO ACTIVE EVENTS</div>
          </div>
        )}

        {activityFeed.map(event => {
          const isAlert = event.type === 'alert'
          const isActive = isAlert && activeAlertId === event.id
          const isPinned = pinnedIds.has(event.id)
          const s = SEV[event.severity] ?? SEV.info
          const triage = isAlert ? triageCache[event.id] : null
          const badgeText = isAlert ? (event.acknowledged ? 'UPDATE' : 'ALERT') : 'LOG'
          const badgeColor = isAlert ? (event.acknowledged ? '#22c55e' : s.text) : '#38bdf8'
          const incidentName = incidents.find(i => i.id === event.incident_id)?.name

          return (
            <div key={event.id} style={{ marginBottom: '7px' }}>
              <div
                className="ui-hover-lift"
                onClick={() => {
                  if (isAlert && !event.acknowledged) handleAlertClick(event.raw)
                }}
                style={{
                  border: `1px solid ${isActive ? s.border : 'rgba(255,255,255,0.11)'}`,
                  background: isActive ? s.bg : 'rgba(255,255,255,0.04)',
                  borderRadius: isActive ? '12px 12px 0 0' : '12px',
                  padding: '9px 10px',
                  cursor: isAlert && !event.acknowledged ? 'pointer' : 'default',
                  transition: 'all 0.15s',
                  opacity: event.acknowledged ? 0.72 : 1,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '5px' }}>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '8px',
                    color: badgeColor, border: `1px solid ${badgeColor}44`,
                    background: `${badgeColor}16`, borderRadius: '999px',
                    letterSpacing: '0.06em', padding: '2px 7px',
                  }}>
                    {badgeText}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#c3d0df', letterSpacing: '0.04em' }}>
                    {event.time}
                  </span>
                  {incidentName && (
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#8b9bb0',
                      letterSpacing: '0.03em', overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap', maxWidth: '90px',
                    }} title={incidentName}>
                      · {incidentName}
                    </span>
                  )}
                  {isAlert && (
                    <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: '10px', color: s.text }}>
                      {TYPE_ICON[event.alert_type] ?? '·'}
                    </span>
                  )}
                  <button
                    className="ui-interactive-btn"
                    onClick={(e) => {
                      e.stopPropagation()
                      setPinnedIds(prev => {
                        const next = new Set(prev)
                        if (next.has(event.id)) next.delete(event.id)
                        else next.add(event.id)
                        return next
                      })
                    }}
                    title={isPinned ? 'Unpin event' : 'Pin event'}
                    style={{
                      marginLeft: isAlert ? 0 : 'auto',
                      background: 'none',
                      border: 'none',
                      color: isPinned ? '#ff4d1a' : '#a7b5c7',
                      cursor: 'pointer',
                      fontSize: '10px',
                      lineHeight: 1,
                      padding: '0',
                    }}
                  >
                    📌
                  </button>
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8', lineHeight: 1.3, marginBottom: '3px' }}>
                  {event.title}
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#c7d2df', lineHeight: 1.45 }}>
                  {event.subtitle}
                </div>
                {triage && (
                  <div style={{
                    marginTop: '7px', padding: '5px 8px',
                    background: 'rgba(255,77,26,0.06)',
                    border: '1px solid rgba(255,77,26,0.2)',
                    borderRadius: '8px',
                    display: 'flex', alignItems: 'flex-start', gap: '5px',
                  }}>
                    <span style={{ fontSize: '10px', flexShrink: 0, marginTop: '1px', color: '#ff4d1a' }}>⬡</span>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#d4dce8', lineHeight: 1.4 }}>
                      {triage.triage}
                    </span>
                  </div>
                )}
                {isAlert && event.expires_at && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#a7b5c7', marginTop: '5px', letterSpacing: '0.04em' }}>
                    EXP {new Date(event.expires_at).toLocaleTimeString()}
                  </div>
                )}
              </div>

              {isActive && selectedAlert && (
                <div style={{
                  border: `1px solid ${s.border}`,
                  borderTop: 'none',
                  background: 'rgba(18,24,34,0.96)',
                  borderRadius: '0 0 12px 12px',
                  padding: '10px',
                }}>
                  <AlertRecommendationPanel
                    alert={selectedAlert}
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
      </div>

      <div
        onMouseDown={() => setIsResizing(true)}
        style={{
          height: '14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'row-resize',
          borderTop: '1px solid rgba(255,255,255,0.08)',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          background: isResizing ? 'rgba(56,189,248,0.08)' : 'rgba(255,255,255,0.02)',
          flexShrink: 0,
        }}
      >
        <div style={{ width: '42px', height: '4px', borderRadius: '999px', background: isResizing ? '#38bdf8' : 'rgba(255,255,255,0.18)' }} />
      </div>

      <div style={{ flex: `${1 - feedRatio} 1 0`, minHeight: '160px', borderTop: '1px solid rgba(255,255,255,0.04)', padding: '10px 12px 8px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: '#d4dce8', letterSpacing: '0.1em', marginBottom: '7px' }}>
          SYSTEM UNITS · {filteredUnits.length}
        </div>
        <div style={{ display: 'flex', gap: '4px', marginBottom: '8px' }}>
          {STATUS_FILTERS.map(f => (
            <button
              className="ui-interactive-btn"
              key={f.key}
              onClick={() => setUnitFilter(f.key)}
              style={{
                flex: 1, padding: '4px 0',
                background: unitFilter === f.key ? 'rgba(56,189,248,0.14)' : 'rgba(255,255,255,0.05)',
                border: `1px solid ${unitFilter === f.key ? 'rgba(56,189,248,0.3)' : 'rgba(255,255,255,0.1)'}`,
                borderRadius: '999px', cursor: 'pointer',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '8px',
                color: unitFilter === f.key ? '#7dd3fc' : '#c3d0df',
                letterSpacing: '0.05em',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
          {filteredUnits.length === 0 ? (
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#a7b5c7', padding: '8px 4px' }}>No units match this filter</div>
          ) : (
            filteredUnits.map(unit => (
              <RightPanelUnitCard
                key={unit.id}
                unit={unit}
                confirmedLoadouts={confirmedLoadouts}
                onUnitClick={onUnitClick}
                focused={focusedUnitId === unit.id}
                incidentName={incidents.find(i => i.id === unit.assigned_incident_id)?.name ?? (unit.status === 'available' ? 'Available system-wide' : 'Unassigned')}
              />
            ))
          )}
        </div>
      </div>
    </div>
  )
}
