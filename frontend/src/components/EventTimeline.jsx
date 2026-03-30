import { useState, useRef, useCallback, useEffect } from 'react'
import { api } from '../api/client'
import { formatTimestamp } from '../utils/timeUtils'
import { useAuth } from '../context/AuthContext'
import { toast } from './Toast'

const TYPE_COLOR = {
  spread_warning:          '#ef4444',
  weather_shift:           '#60a5fa',
  route_blocked:           '#F56E0F',
  asset_at_risk:           '#F56E0F',
  water_source_constraint: '#60a5fa',
  evacuation_recommended:  '#ef4444',
  resource_shortage:       '#F56E0F',
  containment_complete:    '#4ade80',
}

const TYPE_ICON = {
  spread_warning:          '🔥',
  weather_shift:           '🌬',
  route_blocked:           '🚧',
  asset_at_risk:           '⚠️',
  water_source_constraint: '💧',
  evacuation_recommended:  '🚨',
  resource_shortage:       '📦',
  containment_complete:    '✅',
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

const PRIORITY_COLOR = {
  immediate:   '#ef4444',
  within_1hr:  '#F56E0F',
  standby:     '#878787',
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

  // Backend returns UTC strings without Z — append Z so JS parses as UTC
  function parseUTC(str) {
    if (!str) return new Date(0)
    return new Date(str.endsWith('Z') ? str : str + 'Z')
  }

  function fmtPDT(date) {
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    })
  }

  const allEvents = [
    ...alerts.map(a => ({
      id:           a.id,
      type:         'alert',
      alertType:    a.alert_type,
      incidentId:   a.incident_id,
      incidentName: incidents.find(i => i.id === a.incident_id)?.name ?? a.incident_id,
      acknowledged: a.is_acknowledged,
      severity:     a.severity,
      _ts:          parseUTC(a.created_at).getTime(),
      time:         fmtPDT(parseUTC(a.created_at)),
      title:        a.title,
      subtitle:     a.description,
      color:        TYPE_COLOR[a.alert_type] ?? '#878787',
      icon:         TYPE_ICON[a.alert_type]  ?? '⚠️',
    })),
    ...incidents.map(i => ({
      id:           i.id,
      type:         'incident',
      alertType:    null,
      incidentId:   i.id,
      incidentName: i.name,
      acknowledged: false,
      severity:     i.severity,
      _ts:          parseUTC(i.started_at).getTime(),
      time:         fmtPDT(parseUTC(i.started_at)),
      title:        `${i.name} Detected`,
      subtitle:     `${i.severity.toUpperCase()} · ${i.acres_burned?.toLocaleString()} acres · ${i.spread_risk} spread risk`,
      color:        i.severity === 'critical' ? '#ef4444' : i.severity === 'high' ? '#F56E0F' : '#60a5fa',
      icon:         '🔥',
    })),
  ].sort((a, b) => b._ts - a._ts)

  const pinned   = allEvents.filter(e => pinnedIds.has(e.id))
  const unpinned = allEvents.filter(e => !pinnedIds.has(e.id))
  const events   = [...pinned, ...unpinned]

  // Triage fetched lazily on hover

  function togglePin(id, e) {
    e.stopPropagation()
    setPinnedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  async function handleEventClick(event) {
    if (!event.alertType || event.acknowledged) return
    if (activeEvent?.id === event.id) {
      setActiveEvent(null); setRecData(null); setSelectedUnits([]); setDispatched(false); return
    }
    setActiveEvent(event)
    setRecData(null)
    setSelectedUnits([])
    setDispatched(false)
    setRecLoading(true)

    // Fetch triage lazily on first click
    if (!triageCache[event.id]) {
      api.triage(event.id)
        .then(result => setTriageCache(prev => ({ ...prev, [event.id]: result })))
        .catch(() => {})
    }

    try {
      const data = await api.alertRecommendation(event.id)
      setRecData(data)
    } catch {
      setRecData({ error: true })
    } finally {
      setRecLoading(false)
    }
  }

  async function handleDispatch() {
    if (!selectedUnits.length || !activeEvent?.incidentId) return
    setDispatching(true)
    try {
      await api.dispatchAlert(activeEvent.id, activeEvent.incidentId, selectedUnits)
      setDispatched(true)
      setActiveEvent(null)
      setRecData(null)
      setSelectedUnits([])
      onAlertsChanged?.()
    } catch (e) {
      console.error(e)
      toast('Dispatch failed — check unit availability', 'error')
    } finally {
      setDispatching(false)
    }
  }

  // Units for dispatch panel — grouped by type, sorted by distance, suggested first
  const recommendedTypes = new Set(recData?.units?.map(u => u.unit_type) ?? [])
  const activeIncident   = incidents.find(i => i.id === activeEvent?.incidentId)
  const UNIT_TYPE_ORDER_TL = { engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3, dozer: 4, water_tender: 5, command_unit: 6, rescue: 7 }

  function distToActiveFire(unit) {
    if (!activeIncident) return 999
    try {
      const dlat = unit.latitude  - activeIncident.latitude
      const dlon = unit.longitude - activeIncident.longitude
      return Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
    } catch { return 999 }
  }

  const displayUnits = [...units.filter(u => u.status === 'available')].sort((a, b) => {
    const aSugg = recommendedTypes.has(a.unit_type) ? 0 : 1
    const bSugg = recommendedTypes.has(b.unit_type) ? 0 : 1
    if (aSugg !== bSugg) return aSugg - bSugg
    const ga = UNIT_TYPE_ORDER_TL[a.unit_type] ?? 99
    const gb = UNIT_TYPE_ORDER_TL[b.unit_type] ?? 99
    if (ga !== gb) return ga - gb
    return distToActiveFire(a) - distToActiveFire(b)
  })

  // Count selected units per type for recommended box filling
  const selectedByType = selectedUnits.reduce((acc, uid) => {
    const u = units.find(x => x.id === uid)
    if (u) acc[u.unit_type] = (acc[u.unit_type] || 0) + 1
    return acc
  }, {})

  return (
    <>
      {/* Floating recommendation + dispatch panel */}
      {activeEvent && (
        <div style={{
          position: 'absolute', bottom: `${height + 4}px`, left: '50%',
          transform: 'translateX(-50%)', width: '600px',
          background: '#1B1B1E', border: `1px solid ${activeEvent.color}`,
          borderRadius: '4px', zIndex: 2000, boxShadow: '0 4px 24px rgba(0,0,0,0.6)',
          overflow: 'hidden', maxHeight: '65vh', display: 'flex', flexDirection: 'column',
        }}>
          {/* Header */}
          <div style={{
            padding: '8px 12px', borderBottom: `1px solid ${activeEvent.color}44`,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: `${activeEvent.color}12`, flexShrink: 0,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <span style={{ fontSize: '13px' }}>{activeEvent.icon}</span>
              <div>
                <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px', color: activeEvent.color, letterSpacing: '0.04em' }}>
                  TACTICAL RECOMMENDATION
                </div>
                <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#FBFBFB', marginTop: '1px' }}>
                  {activeEvent.title}
                </div>
              </div>
            </div>
            <button onClick={() => { setActiveEvent(null); setRecData(null); setSelectedUnits([]) }}
              style={{ background: 'none', border: 'none', color: '#878787', cursor: 'pointer', fontSize: '13px', padding: '0 4px' }}>
              ✕
            </button>
          </div>

          {/* Body */}
          <div style={{ padding: '12px 14px', overflowY: 'auto', flex: 1 }}>
            {recLoading && (
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#878787' }}>
                Loading recommendation...
              </div>
            )}
            {!recLoading && recData?.error && (
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#ef4444' }}>
                Failed to load recommendation.
              </div>
            )}
            {dispatched && (
              <div style={{ background: 'rgba(74,222,128,0.1)', border: '1px solid #4ade80', borderRadius: '3px', padding: '10px', textAlign: 'center', fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: '#4ade80' }}>
                ✓ UNITS DISPATCHED · ALERT RESOLVED
              </div>
            )}
            {!recLoading && recData && !recData.error && !dispatched && (
              <div style={{ display: 'flex', gap: '16px' }}>
                {/* Left: actions + unit selector */}
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: activeEvent.color, letterSpacing: '0.06em', marginBottom: '6px' }}>
                    IMMEDIATE ACTIONS
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '12px' }}>
                    {recData.actions?.map((action, i) => (
                      <div key={i} style={{ display: 'flex', gap: '7px', alignItems: 'flex-start' }}>
                        <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: activeEvent.color, flexShrink: 0 }}>{i + 1}.</span>
                        <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.6 }}>{action}</span>
                      </div>
                    ))}
                  </div>

                  {/* Unit selector — grouped by type, sorted by distance, no auto-select */}
                  {activeEvent.incidentId && (
                    <>
                      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: activeEvent.color, letterSpacing: '0.06em', marginBottom: '6px' }}>
                        SELECT UNITS TO DISPATCH
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginBottom: '10px' }}>
                        {displayUnits.length === 0 && (
                          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#aaaaaa' }}>No available units</div>
                        )}
                        {(() => {
                          let lastType = null
                          return displayUnits.map(unit => {
                            const isSelected  = selectedUnits.includes(unit.id)
                            const isSuggested = recommendedTypes.has(unit.unit_type)
                            const showHeader  = unit.unit_type !== lastType
                            lastType = unit.unit_type
                            const dist = distToActiveFire(unit)
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
                                    display: 'flex', alignItems: 'center', gap: '7px',
                                    padding: '5px 8px', borderRadius: '2px',
                                    background: isSelected ? `${activeEvent.color}15` : '#262626',
                                    border: `1px solid ${isSelected ? activeEvent.color : isSuggested ? activeEvent.color + '44' : '#333'}`,
                                    cursor: 'pointer',
                                  }}
                                >
                                  <span style={{ fontSize: '12px' }}>{UNIT_TYPE_ICON[unit.unit_type] ?? '◉'}</span>
                                  <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '12px', color: '#FBFBFB', flex: 1 }}>{unit.designation}</span>
                                  {distLabel && <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#aaaaaa' }}>{distLabel}</span>}
                                  {isSuggested && <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: activeEvent.color }}>★</span>}
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
                          background: canDispatch ? activeEvent.color : '#262626',
                          border: 'none', borderRadius: '3px',
                          cursor: canDispatch ? 'pointer' : 'not-allowed',
                          fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px',
                          color: '#FBFBFB', letterSpacing: '0.03em', transition: 'background 0.15s',
                        }}
                      >
                        {dispatching
                          ? 'DISPATCHING...'
                          : auth?.role === 'viewer'
                            ? 'DISPATCH — COMMANDER / DISPATCHER ONLY'
                            : selectedUnits.length
                              ? `DISPATCH ${selectedUnits.length} UNIT${selectedUnits.length !== 1 ? 'S' : ''} · RESOLVE ALERT`
                              : 'SELECT UNITS TO DISPATCH'
                        }
                      </button>
                    </>
                  )}
                </div>

                {/* Right: recommended unit types — go green when filled */}
                {recData.units?.length > 0 && (
                  <div style={{ width: '170px', flexShrink: 0 }}>
                    <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: activeEvent.color, letterSpacing: '0.06em', marginBottom: '6px' }}>
                      RECOMMENDED
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      {recData.units.map((u, i) => {
                        const filled = (selectedByType[u.unit_type] ?? 0) >= u.quantity
                        return (
                          <div key={i} style={{
                            background: filled ? 'rgba(74,222,128,0.1)' : '#262626',
                            border: `1px solid ${filled ? '#4ade80' : '#333'}`,
                            borderRadius: '2px', padding: '6px 8px',
                            transition: 'all 0.2s',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                              <span style={{ fontSize: '12px' }}>{UNIT_TYPE_ICON[u.unit_type] ?? '◉'}</span>
                              <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '11px', color: filled ? '#4ade80' : '#FBFBFB' }}>
                                {u.quantity}× {u.unit_type.replace(/_/g, ' ').toUpperCase()}
                              </span>
                            </div>
                            <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '9px', color: filled ? '#4ade80' : (PRIORITY_COLOR[u.priority] ?? '#878787'), letterSpacing: '0.03em', marginTop: '2px' }}>
                              {filled ? '✓ FILLED' : u.priority.replace(/_/g, ' ').toUpperCase()}
                            </div>
                            {!filled && (
                              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.4, marginTop: '2px' }}>
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

      {/* Timeline bar */}
      <div style={{
        height: `${height}px`, background: '#151419', borderTop: '1px solid #262626',
        flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative',
      }}>
        <div onMouseDown={onMouseDown} style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: '8px',
          cursor: 'ns-resize', zIndex: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ width: '36px', height: '2px', background: '#262626', borderRadius: '2px', marginTop: '2px' }} />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px 5px', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '12px', color: '#878787', letterSpacing: '0.02em' }}>
              EVENT TIMELINE
            </span>
            {pinnedIds.size > 0 && (
              <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#F56E0F', letterSpacing: '0.03em' }}>
                📌 {pinnedIds.size} PINNED
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#F56E0F', boxShadow: '0 0 5px #F56E0F' }} />
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#F56E0F', letterSpacing: '0.03em' }}>LIVE STREAM</span>
          </div>
        </div>

        <div ref={scrollRef} className="pyra-timeline" style={{
          flex: 1, display: 'flex', gap: '8px',
          padding: '0 12px 8px', overflowX: 'auto', overflowY: 'hidden', alignItems: 'stretch',
        }}>
          <style>{`
            .pyra-timeline::-webkit-scrollbar { height: 3px; }
            .pyra-timeline::-webkit-scrollbar-track { background: transparent; }
            .pyra-timeline::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
          `}</style>
          {events.map(event => {
            const isPinned   = pinnedIds.has(event.id)
            const isActive   = activeEvent?.id === event.id
            const isResolved = event.acknowledged
            const hasRec     = !!event.alertType && !isResolved
            return (
              <div key={event.id} onClick={() => handleEventClick(event)} style={{
                flexShrink: 0, width: '220px',
                background: isActive ? `${event.color}12` : '#1B1B1E',
                border: `1px solid ${isActive ? event.color : isPinned ? '#F56E0F55' : '#262626'}`,
                borderTop: `2px solid ${isResolved ? '#333' : event.color}`,
                borderRadius: '3px', padding: '7px 10px', overflow: 'hidden',
                cursor: hasRec ? 'pointer' : 'default',
                opacity: isResolved ? 0.4 : 1, position: 'relative',
                transition: 'border-color 0.15s, background 0.15s',
              }}
                onMouseEnter={e => { if (hasRec && !isActive) e.currentTarget.style.borderColor = event.color }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.borderColor = isPinned ? '#F56E0F55' : '#262626' }}
              >
                <button onClick={(e) => togglePin(event.id, e)} title={isPinned ? 'Unpin' : 'Pin'}
                  style={{ position: 'absolute', top: '5px', right: '6px', background: 'none', border: 'none', cursor: 'pointer', fontSize: '10px', color: isPinned ? '#F56E0F' : '#878787', padding: '0', lineHeight: 1 }}>
                  📌
                </button>
                <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '11px', color: '#878787', marginBottom: '3px', letterSpacing: '0.06em' }}>
                  {event.time}
                  {isResolved && <span style={{ marginLeft: '6px', color: '#4ade80', fontSize: '9px', letterSpacing: '0.03em' }}>RESOLVED</span>}
                </div>
                <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '13px', color: isResolved ? '#878787' : '#FBFBFB', lineHeight: 1.25, marginBottom: '4px', paddingRight: '14px' }}>
                  {event.title}
                </div>
                <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.5, overflowWrap: 'break-word', opacity: 0.8 }}>
                  {event.subtitle}
                </div>
                {hasRec && !triageCache[event.id] && (
                  <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: event.color, marginTop: '5px', letterSpacing: '0.03em' }}>
                    ✦ CLICK FOR RECOMMENDATION
                  </div>
                )}
                {hasRec && triageCache[event.id] && (
                  <div style={{ marginTop: '5px', display: 'flex', alignItems: 'flex-start', gap: '4px' }}>
                    <span style={{ fontSize: '9px', color: '#F56E0F', flexShrink: 0 }}>⬡</span>
                    <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#FBFBFB', lineHeight: 1.4, opacity: 0.9 }}>
                      {triageCache[event.id].triage}
                    </span>
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