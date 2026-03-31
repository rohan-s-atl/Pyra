import { useState, useRef, useCallback, useEffect } from 'react'
import { api } from '../api/client'
import { formatTimestamp } from '../utils/timeUtils'
import { useAuth } from '../context/AuthContext'
import { toast } from './Toast'

const TYPE_COLOR = {
  spread_warning:          '#ef4444',
  weather_shift:           '#38bdf8',
  route_blocked:           '#f59e0b',
  asset_at_risk:           '#f59e0b',
  water_source_constraint: '#38bdf8',
  evacuation_recommended:  '#ef4444',
  resource_shortage:       '#f59e0b',
  containment_complete:    '#22c55e',
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
const UNIT_TYPE_ICON = {
  engine: '🚒', hand_crew: '👥', dozer: '🚜', water_tender: '🚛',
  helicopter: '🚁', air_tanker: '✈️', command_unit: '📡', rescue: '🚑',
}
const PRIORITY_COLOR = {
  immediate:  '#ef4444',
  within_1hr: '#f59e0b',
  standby:    '#3a4558',
}
const UNIT_TYPE_ORDER = {
  engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3,
  dozer: 4, water_tender: 5, command_unit: 6, rescue: 7,
}

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
  } catch { return date.toLocaleTimeString() }
}

export default function EventTimeline({ alerts, incidents, units = [], onAlertsChanged }) {
  const [height,        setHeight]        = useState(130)
  const [pinnedIds,     setPinnedIds]     = useState(new Set())
  const [activeEvent,   setActiveEvent]   = useState(null)
  const [triageCache,   setTriageCache]   = useState({})
  const [recData,       setRecData]       = useState(null)
  const [recLoading,    setRecLoading]    = useState(false)
  const [selectedUnits, setSelectedUnits] = useState([])
  const [dispatching,   setDispatching]   = useState(false)
  const [dispatched,    setDispatched]    = useState(false)
  const scrollRef = useRef(null)
  const dragging  = useRef(false)
  const startY    = useRef(0)
  const startH    = useRef(0)
  const auth      = useAuth()
  const canDispatch = selectedUnits.length > 0 && !dispatching && auth?.role !== 'viewer'

  const onMouseDown = useCallback((e) => {
    e.preventDefault()
    dragging.current = true
    startY.current   = e.clientY
    startH.current   = height
    const onMove = (e) => {
      if (!dragging.current) return
      const delta = startY.current - e.clientY
      setHeight(Math.min(320, Math.max(90, startH.current + delta)))
    }
    const onUp = () => {
      dragging.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [height])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e) => { e.preventDefault(); el.scrollLeft += e.deltaY + e.deltaX }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Auto-clear if active event gets resolved
  useEffect(() => {
    if (!activeEvent) return
    const current = alerts.find(a => a.id === activeEvent.id)
    if (!current || current.is_acknowledged) {
      setActiveEvent(null); setRecData(null); setSelectedUnits([])
    }
  }, [alerts])

  // Build combined event list: alerts + incident detections
  const allEvents = [
    ...alerts.map(a => ({
      id:           a.id,
      alertType:    a.alert_type,
      incidentId:   a.incident_id,
      incidentName: incidents.find(i => i.id === a.incident_id)?.name ?? '',
      acknowledged: a.is_acknowledged,
      severity:     a.severity,
      _ts:          parseUTC(a.created_at).getTime(),
      time:         fmtPDT(parseUTC(a.created_at)),
      title:        a.title,
      subtitle:     a.description,
      color:        TYPE_COLOR[a.alert_type] ?? '#5a6878',
      icon:         TYPE_ICON[a.alert_type]  ?? '·',
    })),
    ...incidents.map(i => ({
      id:           `inc-${i.id}`,
      alertType:    null,
      incidentId:   i.id,
      incidentName: i.name,
      acknowledged: i.status === 'contained' || i.status === 'resolved',
      severity:     i.severity,
      _ts:          parseUTC(i.started_at).getTime(),
      time:         fmtPDT(parseUTC(i.started_at)),
      title:        `${i.name} Detected`,
      subtitle:     `${i.severity?.toUpperCase()} · ${i.acres_burned?.toLocaleString()} acres · ${i.spread_risk} spread risk`,
      color:        i.severity === 'critical' ? '#ef4444' : i.severity === 'high' ? '#ff4d1a' : '#38bdf8',
      icon:         '⬡',
    })),
  ].sort((a, b) => b._ts - a._ts)

  const pinned   = allEvents.filter(e => pinnedIds.has(e.id))
  const unpinned = allEvents.filter(e => !pinnedIds.has(e.id))
  const events   = [...pinned, ...unpinned]

  function togglePin(id, e) {
    e.stopPropagation()
    setPinnedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  async function handleEventClick(event) {
    if (!event.alertType || event.acknowledged) return
    if (activeEvent?.id === event.id) {
      setActiveEvent(null); setRecData(null); setSelectedUnits([]); setDispatched(false); return
    }
    setActiveEvent(event); setRecData(null); setSelectedUnits([]); setDispatched(false); setRecLoading(true)
    if (!triageCache[event.id]) {
      api.triage(event.id)
        .then(result => setTriageCache(prev => ({ ...prev, [event.id]: result })))
        .catch(() => {})
    }
    try {
      const data = await api.alertRecommendation(event.id)
      setRecData(data)
    } catch { setRecData({ error: true }) }
    finally { setRecLoading(false) }
  }

  async function handleDispatch() {
    if (!selectedUnits.length || !activeEvent?.incidentId) return
    setDispatching(true)
    try {
      await api.dispatchAlert(activeEvent.id, activeEvent.incidentId, selectedUnits)
      setDispatched(true)
      setActiveEvent(null); setRecData(null); setSelectedUnits([])
      onAlertsChanged?.()
    } catch { toast('Dispatch failed — check unit availability', 'error') }
    finally { setDispatching(false) }
  }

  // Units for dispatch — sorted by suggestion + distance
  const recommendedTypes = new Set(recData?.units?.map(u => u.unit_type) ?? [])
  const activeIncident   = incidents.find(i => i.id === activeEvent?.incidentId)

  function distToFire(unit) {
    if (!activeIncident) return 999
    try {
      const dlat = unit.latitude  - activeIncident.latitude
      const dlon = unit.longitude - activeIncident.longitude
      return Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
    } catch { return 999 }
  }

  const dispatchUnits = [...units.filter(u => u.status === 'available')].sort((a, b) => {
    const aSugg = recommendedTypes.has(a.unit_type) ? 0 : 1
    const bSugg = recommendedTypes.has(b.unit_type) ? 0 : 1
    if (aSugg !== bSugg) return aSugg - bSugg
    const ga = UNIT_TYPE_ORDER[a.unit_type] ?? 99
    const gb = UNIT_TYPE_ORDER[b.unit_type] ?? 99
    if (ga !== gb) return ga - gb
    return distToFire(a) - distToFire(b)
  })

  const selectedByType = selectedUnits.reduce((acc, uid) => {
    const u = units.find(x => x.id === uid)
    if (u) acc[u.unit_type] = (acc[u.unit_type] || 0) + 1
    return acc
  }, {})

  const unackCount = alerts.filter(a => !a.is_acknowledged).length

  return (
    <>
      {/* ── FLOATING TACTICAL PANEL ── */}
      {activeEvent && (
        <div style={{
          position: 'absolute', bottom: `${height + 8}px`, left: '50%',
          transform: 'translateX(-50%)', width: '620px',
          background: 'rgba(13,15,17,0.96)',
          border: `1px solid ${activeEvent.color}50`,
          borderRadius: '10px', zIndex: 2000,
          boxShadow: `0 8px 40px rgba(0,0,0,0.7), 0 0 0 1px ${activeEvent.color}15`,
          overflow: 'hidden', maxHeight: '60vh',
          display: 'flex', flexDirection: 'column',
          backdropFilter: 'blur(16px)',
          animation: 'fade-up 0.2s ease-out',
        }}>
          {/* Header */}
          <div style={{
            padding: '10px 14px', flexShrink: 0,
            borderBottom: `1px solid rgba(255,255,255,0.05)`,
            background: `${activeEvent.color}08`,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                width: '24px', height: '24px', borderRadius: '5px', flexShrink: 0,
                background: `${activeEvent.color}15`, border: `1px solid ${activeEvent.color}35`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '11px', color: activeEvent.color,
              }}>{activeEvent.icon}</div>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: activeEvent.color, letterSpacing: '0.1em' }}>
                  TACTICAL RECOMMENDATION
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#d4dce8', marginTop: '1px' }}>
                  {activeEvent.title}
                </div>
              </div>
            </div>
            <button
              onClick={() => { setActiveEvent(null); setRecData(null); setSelectedUnits([]) }}
              style={{ background: 'none', border: 'none', color: '#3a4558', cursor: 'pointer', fontSize: '16px', padding: '0 4px', lineHeight: 1, transition: 'color 0.1s' }}
              onMouseEnter={e => e.currentTarget.style.color = '#d4dce8'}
              onMouseLeave={e => e.currentTarget.style.color = '#3a4558'}
            >×</button>
          </div>

          {/* Body */}
          <div style={{ padding: '14px 16px', overflowY: 'auto', flex: 1 }}>
            {recLoading && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#3a4558', letterSpacing: '0.06em' }}>
                LOADING RECOMMENDATION…
              </div>
            )}
            {!recLoading && recData?.error && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#ef4444' }}>Failed to load recommendation.</div>
            )}
            {dispatched && (
              <div style={{
                background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.3)',
                borderRadius: '6px', padding: '12px', textAlign: 'center',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '11px', color: '#22c55e', letterSpacing: '0.08em',
              }}>✓ UNITS DISPATCHED · ALERT RESOLVED</div>
            )}
            {!recLoading && recData && !recData.error && !dispatched && (
              <div style={{ display: 'flex', gap: '18px' }}>

                {/* Left: summary + actions + unit selector */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  {recData.summary && (
                    <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#5a6878', lineHeight: 1.55, marginBottom: '12px' }}>
                      {recData.summary}
                    </div>
                  )}

                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: activeEvent.color, letterSpacing: '0.1em', marginBottom: '6px' }}>
                    IMMEDIATE ACTIONS
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '14px' }}>
                    {recData.actions?.map((action, i) => (
                      <div key={i} style={{ display: 'flex', gap: '7px' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: activeEvent.color, flexShrink: 0, marginTop: '2px' }}>{i + 1}.</span>
                        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.55 }}>{action}</span>
                      </div>
                    ))}
                  </div>

                  {activeEvent.incidentId && (
                    <>
                      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: activeEvent.color, letterSpacing: '0.1em', marginBottom: '6px' }}>
                        SELECT UNITS TO DISPATCH
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '12px', maxHeight: '160px', overflowY: 'auto' }}>
                        {dispatchUnits.length === 0 && (
                          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#3a4558' }}>No available units</div>
                        )}
                        {(() => {
                          let lastType = null
                          return dispatchUnits.map(unit => {
                            const isSelected  = selectedUnits.includes(unit.id)
                            const isSuggested = recommendedTypes.has(unit.unit_type)
                            const showHeader  = unit.unit_type !== lastType
                            lastType = unit.unit_type
                            const dist = distToFire(unit)
                            const distLabel = dist < 999 ? (dist < 1 ? `${Math.round(dist * 5280)} ft` : `${dist.toFixed(1)} mi`) : null
                            return (
                              <div key={unit.id}>
                                {showHeader && (
                                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '8.5px', color: '#3a4558', letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: '5px', marginBottom: '2px', paddingLeft: '2px' }}>
                                    {unit.unit_type.replace(/_/g, ' ')}
                                  </div>
                                )}
                                <div
                                  onClick={() => setSelectedUnits(prev => prev.includes(unit.id) ? prev.filter(id => id !== unit.id) : [...prev, unit.id])}
                                  style={{
                                    display: 'flex', alignItems: 'center', gap: '7px',
                                    padding: '5px 8px', borderRadius: '4px', cursor: 'pointer',
                                    background: isSelected ? `${activeEvent.color}10` : 'rgba(255,255,255,0.02)',
                                    border: `1px solid ${isSelected ? activeEvent.color + '60' : isSuggested ? activeEvent.color + '25' : 'rgba(255,255,255,0.06)'}`,
                                    transition: 'all 0.12s',
                                  }}
                                >
                                  <span style={{ fontSize: '12px' }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
                                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '11px', color: isSelected ? '#d4dce8' : '#5a6878', flex: 1 }}>{unit.designation}</span>
                                  {distLabel && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: '#3a4558' }}>{distLabel}</span>}
                                  {isSuggested && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: activeEvent.color }}>★</span>}
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
                          width: '100%', padding: '9px',
                          background: canDispatch ? activeEvent.color : 'rgba(255,255,255,0.04)',
                          border: 'none', borderRadius: '6px',
                          cursor: canDispatch ? 'pointer' : 'not-allowed',
                          fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '11px',
                          color: canDispatch ? '#fff' : '#3a4558',
                          letterSpacing: '0.08em', transition: 'all 0.15s',
                          boxShadow: canDispatch ? `0 0 16px ${activeEvent.color}40` : 'none',
                        }}
                      >
                        {dispatching
                          ? 'DISPATCHING…'
                          : auth?.role === 'viewer'
                          ? 'COMMANDER / DISPATCHER ONLY'
                          : selectedUnits.length
                          ? `DISPATCH ${selectedUnits.length} UNIT${selectedUnits.length !== 1 ? 'S' : ''} · RESOLVE ALERT`
                          : 'SELECT UNITS TO DISPATCH'}
                      </button>
                    </>
                  )}
                </div>

                {/* Right: recommended unit slots */}
                {recData.units?.length > 0 && (
                  <div style={{ width: '175px', flexShrink: 0 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: activeEvent.color, letterSpacing: '0.1em', marginBottom: '7px' }}>
                      RECOMMENDED
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                      {recData.units.map((u, i) => {
                        const filled = (selectedByType[u.unit_type] ?? 0) >= u.quantity
                        return (
                          <div key={i} style={{
                            background: filled ? 'rgba(34,197,94,0.07)' : 'rgba(255,255,255,0.02)',
                            border: `1px solid ${filled ? 'rgba(34,197,94,0.3)' : 'rgba(255,255,255,0.06)'}`,
                            borderRadius: '5px', padding: '7px 9px',
                            transition: 'all 0.2s',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '2px' }}>
                              <span style={{ fontSize: '12px' }}>{UNIT_TYPE_ICON[u.unit_type] ?? '◉'}</span>
                              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '10px', color: filled ? '#22c55e' : '#d4dce8', flex: 1 }}>
                                {u.quantity}× {u.unit_type.replace(/_/g, ' ').toUpperCase()}
                              </span>
                            </div>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: filled ? '#22c55e' : (PRIORITY_COLOR[u.priority] ?? '#3a4558'), letterSpacing: '0.06em', marginBottom: filled || !u.rationale ? 0 : '3px' }}>
                              {filled ? '✓ FILLED' : u.priority?.replace(/_/g, ' ').toUpperCase()}
                            </div>
                            {!filled && u.rationale && (
                              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#5a6878', lineHeight: 1.4 }}>
                                {u.rationale}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TIMELINE BAR ── */}
      <div style={{
        height: `${height}px`,
        background: 'rgba(10,12,14,0.94)',
        borderTop: '1px solid rgba(255,255,255,0.055)',
        flexShrink: 0, display: 'flex', flexDirection: 'column',
        overflow: 'hidden', position: 'relative',
        backdropFilter: 'blur(14px)',
      }}>
        {/* Drag handle */}
        <div
          onMouseDown={onMouseDown}
          style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: '10px',
            cursor: 'ns-resize', zIndex: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div style={{ width: '32px', height: '2px', background: 'rgba(255,255,255,0.1)', borderRadius: '1px', marginTop: '3px' }} />
        </div>

        {/* Header bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px 5px', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px', color: '#3a4558', letterSpacing: '0.12em' }}>
              EVENT TIMELINE
            </span>
            {pinnedIds.size > 0 && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.04em' }}>
                📌 {pinnedIds.size} PINNED
              </span>
            )}
            {unackCount > 0 && (
              <span style={{
                background: '#ef4444', color: '#fff',
                fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '8px',
                borderRadius: '8px', padding: '1px 6px',
                boxShadow: '0 0 8px rgba(239,68,68,0.4)',
                letterSpacing: '0.04em',
              }}>{unackCount} ACTIVE</span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#ff4d1a', boxShadow: '0 0 6px #ff4d1a', animation: 'status-blink 2s ease-in-out infinite' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.08em' }}>LIVE STREAM</span>
          </div>
        </div>

        {/* Scrollable event cards */}
        <div ref={scrollRef} style={{
          flex: 1, display: 'flex', gap: '7px',
          padding: '0 12px 8px', overflowX: 'auto', overflowY: 'hidden', alignItems: 'stretch',
        }}>
          {events.map(event => {
            const isPinned   = pinnedIds.has(event.id)
            const isActive   = activeEvent?.id === event.id
            const isResolved = event.acknowledged
            const hasRec     = !!event.alertType && !isResolved
            const triage     = triageCache[event.id]

            return (
              <div
                key={event.id}
                onClick={() => handleEventClick(event)}
                style={{
                  flexShrink: 0, width: '200px',
                  background: isActive ? `${event.color}0e` : 'rgba(255,255,255,0.02)',
                  border: `1px solid ${isActive ? event.color + '60' : isPinned ? 'rgba(255,77,26,0.3)' : 'rgba(255,255,255,0.06)'}`,
                  borderTop: `2px solid ${isResolved ? 'rgba(255,255,255,0.06)' : event.color + (isActive ? '' : '80')}`,
                  borderRadius: '6px', padding: '8px 10px',
                  cursor: hasRec ? 'pointer' : 'default',
                  opacity: isResolved ? 0.4 : 1, position: 'relative',
                  transition: 'all 0.15s',
                  overflow: 'hidden',
                }}
                onMouseEnter={e => { if (hasRec && !isActive) e.currentTarget.style.background = `${event.color}08` }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.02)' }}
              >
                {/* Pin button */}
                <button
                  onClick={(e) => togglePin(event.id, e)}
                  title={isPinned ? 'Unpin' : 'Pin'}
                  style={{
                    position: 'absolute', top: '5px', right: '6px',
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontSize: '9px', color: isPinned ? '#ff4d1a' : '#3a4558',
                    padding: '0', lineHeight: 1, transition: 'color 0.1s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.color = '#ff4d1a'}
                  onMouseLeave={e => e.currentTarget.style.color = isPinned ? '#ff4d1a' : '#3a4558'}
                >📌</button>

                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#3a4558', marginBottom: '4px', letterSpacing: '0.06em' }}>
                  {event.time}
                  {isResolved && <span style={{ marginLeft: '6px', color: '#22c55e', letterSpacing: '0.04em' }}>RESOLVED</span>}
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: isResolved ? '#3a4558' : '#d4dce8', lineHeight: 1.25, marginBottom: '3px', paddingRight: '14px' }}>
                  {event.title}
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#5a6878', lineHeight: 1.5, overflowWrap: 'break-word' }}>
                  {event.subtitle}
                </div>

                {/* AI triage or CTA */}
                {hasRec && triage && (
                  <div style={{ marginTop: '5px', display: 'flex', alignItems: 'flex-start', gap: '4px' }}>
                    <span style={{ fontSize: '9px', color: '#ff4d1a', flexShrink: 0 }}>⬡</span>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9.5px', color: '#d4dce8', lineHeight: 1.4 }}>
                      {triage.triage}
                    </span>
                  </div>
                )}
                {hasRec && !triage && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: event.color, marginTop: '5px', letterSpacing: '0.04em' }}>
                    ✦ CLICK FOR RECOMMENDATION
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}
