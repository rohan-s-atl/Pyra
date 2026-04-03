import { useEffect, useState, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { api, BASE_URL, authHeaders, streamBriefing, getDispatchAdvice, generateHandoffBriefing } from '../api/client'
import { scoreBadges, computeUnitRoutes } from '../services/routeEngine'
import { formatTimeShort, formatTimestamp } from '../utils/timeUtils'
import { toast } from './Toast'
import { useAuth } from '../context/AuthContext'
import SitrepChat from './SitrepChat'
import LoadoutConfigurator from './LoadoutConfigurator'
import PostIncidentReview from './PostIncidentReview'
import DispatchRecommendations from './DispatchRecommendations'

// ── Briefing markdown renderer ───────────────────────────────────────────────
function renderBriefing(text) {
  if (!text) return null
  return text.split('\n').map((line, i) => {
    if (!line.trim()) return <div key={i} style={{ height: '5px' }} />
    if (line.trim() === '---') return <div key={i} style={{ height: '1px', background: '#262626', margin: '8px 0' }} />
    // ALLCAPS section header (ICS style: "SITUATION:", "WEATHER:", etc.)
    if (/^[A-Z][A-Z\s\-\/]{2,}:/.test(line.trim())) {
      const colonIdx = line.indexOf(':')
      const header = line.slice(0, colonIdx)
      const rest = line.slice(colonIdx + 1).trim()
      return (
        <div key={i} style={{ marginBottom: '4px' }}>
          <span style={{ fontWeight: 700, color: '#ff4d1a', fontSize: '11px', letterSpacing: '0.06em' }}>{header}:</span>
          {rest && <span style={{ color: '#d4dce8' }}> {rest}</span>}
        </div>
      )
    }
    // **bold** inline
    const parts = line.split(/(\*\*[^*]+\*\*)/)
    const rendered = parts.map((part, j) =>
      part.startsWith('**') && part.endsWith('**')
        ? <strong key={j} style={{ color: '#d4dce8', fontWeight: 700 }}>{part.slice(2, -2)}</strong>
        : <span key={j}>{part}</span>
    )
    return <div key={i} style={{ marginBottom: '3px', color: '#d4d4d4' }}>{rendered}</div>
  })
}


const PRIORITY_COLOR = {
  immediate:   '#ef4444',
  within_1hr:  '#ff4d1a',
  standby:     '#9baac0',
}

const UNIT_ICON = {
  engine:       '🚒',
  hand_crew:    '👥',
  dozer:        '🚜',
  water_tender: '🚛',
  helicopter:   '🚁',
  air_tanker:   '✈️',
  command_unit: '📡',
  rescue:       '🚑',
}

const LOADOUT_LABEL = {
  structure_protection:  'Structure Protection',
  extended_suppression:  'Extended Suppression',
  aerial_suppression:    'Aerial Suppression',
  containment_support:   'Containment Support',
  initial_attack:        'Initial Attack',
  remote_access_support: 'Remote Access Support',
}

const SEVERITY_COLOR = {
  critical: '#ef4444',
  high:     '#ff4d1a',
  moderate: '#facc15',
  low:      '#4ade80',
}

const AIR_TYPES    = new Set(['helicopter', 'air_tanker'])
const AIR_STATIONS = new Set(['AAB', 'HB'])
const ENGAGED_STATUSES = new Set(['en_route', 'on_scene', 'staging'])

const UNIT_TYPE_ORDER = {
  engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3,
  dozer: 4, water_tender: 5, command_unit: 6, rescue: 7,
}

function isAirUnitAtAirBase(unit) {
  if (!AIR_TYPES.has(unit.unit_type)) return true
  return AIR_STATIONS.has(unit.station_type)
}

function distToIncident(unit, incident) {
  try {
    const lat = unit.latitude
    const lon = unit.longitude
    if (isNaN(lat) || isNaN(lon)) return 999
    return Math.sqrt(((lat - incident.latitude) * 69) ** 2 + ((lon - incident.longitude) * 54) ** 2)
  } catch { return 999 }
}

function sortUnitsForDispatch(units, incident) {
  return [...units].sort((a, b) => {
    const groupA = UNIT_TYPE_ORDER[a.unit_type] ?? 99
    const groupB = UNIT_TYPE_ORDER[b.unit_type] ?? 99
    if (groupA !== groupB) return groupA - groupB
    return distToIncident(a, incident) - distToIncident(b, incident)
  })
}

// formatTimeShort imported from utils/timeUtils

// ── Route status badge ────────────────────────────────────────────────────────
function RouteBadge({ status, statusColor }) {
  return (
    <span style={{
      fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px',
      color: '#151419', background: statusColor, borderRadius: '2px',
      padding: '1px 5px', letterSpacing: '0.03em',
    }}>
      {status}
    </span>
  )
}

// ── Per-unit route card ───────────────────────────────────────────────────────
function UnitRouteCard({ unitRoute }) {
  const [expanded, setExpanded] = useState(false)
  const borderColor = unitRoute.status === 'FASTEST' ? '#1a3a1a'
    : unitRoute.status === 'CAUTION' ? '#3a3000'
    : '#3a0000'

  return (
    <div style={{
      background: 'var(--surface)', border: `1px solid ${borderColor}`,
      borderRadius: '5px', padding: '7px 10px', marginBottom: '4px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '13px', flexShrink: 0 }}>{UNIT_ICON[unitRoute.unit_type] ?? '◉'}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8' }}>
              {unitRoute.designation}
            </span>
            <RouteBadge status={unitRoute.status} statusColor={unitRoute.statusColor} />
            {unitRoute.isAir && (
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#60a5fa', letterSpacing: '0.02em' }}>
                AERIAL
              </span>
            )}
            {!unitRoute.isAir && unitRoute.isRoadRouted === false && (
              <span title="Road routing unavailable — showing straight-line estimate. Add OPENROUTESERVICE_API_KEY to .env for road routes." style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#facc15', letterSpacing: '0.02em', cursor: 'help' }}>
                ⚠ EST
              </span>
            )}
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#a7b5c7' }}>
            {unitRoute.distMiles < 1
              ? `${Math.round(unitRoute.distMiles * 5280)} ft`
              : `${unitRoute.distMiles.toFixed(1)} mi`
            } · {unitRoute.etaMinutes} min · ETA ~{unitRoute.etaTimeStr}
          </div>
        </div>
        <button
          onClick={() => setExpanded(v => !v)}
          style={{ background: 'none', border: 'none', color: '#c3d0df', cursor: 'pointer', fontSize: '10px', padding: '2px 4px' }}
        >
          {expanded ? '▲' : '▼'}
        </button>
      </div>
      {expanded && (
        <div style={{
          fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#c3d0df',
          lineHeight: 1.5, marginTop: '6px', paddingTop: '6px',
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}>
          {unitRoute.explanation}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function IncidentDetailPanel({
  incident, units, allIncidents = [],
  onClose, onDispatchSuccess, onUnitRoutesChange, onPreviewUnits, onConfirmLoadouts,
  rightOffset = 0,
  panelWidth = 360,
  topOffset = 86,
  bottomOffset = 12,
}) {
  const [recommendation, setRecommendation] = useState(null)
  const [fireBehavior,   setFireBehavior]   = useState(null)
  const [loading,        setLoading]        = useState(true)
  const [dispatching,    setDispatching]    = useState(false)
  const [dispatched,     setDispatched]     = useState(false)
  const [confirmDispatch, setConfirmDispatch] = useState(false)
  const [loadoutOpen,    setLoadoutOpen]    = useState(false)
  const [pendingLoadouts, setPendingLoadouts] = useState([])
  const [selectedUnits,  setSelectedUnits]  = useState([])
  const [unitRoutes,     setUnitRoutes]     = useState([])       // selected units → map
  const [allUnitRoutes,  setAllUnitRoutes]  = useState({})       // unitId → route, all available
  const [routesLoading,  setRoutesLoading]  = useState(false)

  // Briefing state
  const [briefing,         setBriefing]         = useState('')
  const [briefingLoading,  setBriefingLoading]  = useState(false)
  const [briefingOpen,     setBriefingOpen]     = useState(false)
  const briefingRef = useRef(null)

  // Close-out state
  const [closeoutOpen,     setCloseoutOpen]     = useState(false)
  const [checklist,        setChecklist]        = useState(null)
  const [checklistLoading, setChecklistLoading] = useState(false)
  const [closeLoading,     setCloseLoading]     = useState(false)
  const [handoffLoading,   setHandoffLoading]   = useState(false)

  // Chat, review, dispatch advice state
  const [chatOpen,         setChatOpen]         = useState(false)
  const [reviewOpen,       setReviewOpen]       = useState(false)
  const [dispatchAdvice,   setDispatchAdvice]   = useState(null)
  const [adviceLoading,    setAdviceLoading]    = useState(false)

  // Keep the incident summary aligned with dispatch intelligence:
  // only units actively committed to this incident count as already deployed.
  const alreadyAssigned = units.filter(
    u => u.assigned_incident_id === incident.id && ENGAGED_STATUSES.has(u.status)
  )
  const selectedUnitsKey = selectedUnits.slice().sort().join(',')
  const selectedPreviewUnits = units.filter(u => selectedUnits.includes(u.id))
  const availableUnits = units.filter(u => u.status === 'available' && isAirUnitAtAirBase(u))
  const availableUnitsKey = availableUnits
    .map(unit => [
      unit.id,
      unit.status,
      Number.isFinite(unit.latitude) ? unit.latitude.toFixed(4) : 'na',
      Number.isFinite(unit.longitude) ? unit.longitude.toFixed(4) : 'na',
    ].join(':'))
    .sort()
    .join('|')
  const selectedPreviewUnitsKey = selectedPreviewUnits
    .map(unit => [
      unit.id,
      unit.status,
      Number.isFinite(unit.latitude) ? unit.latitude.toFixed(4) : 'na',
      Number.isFinite(unit.longitude) ? unit.longitude.toFixed(4) : 'na',
    ].join(':'))
    .sort()
    .join('|')
  const routeRiskInputsKey = [
    incident.id,
    incident.spread_risk,
    incident.spread_direction,
    incident.wind_speed_mph,
    incident.humidity_percent,
    ...allIncidents
      .filter(inc => inc.status !== 'out')
      .map(inc => [
        inc.id,
        inc.status,
        inc.spread_risk,
        inc.spread_direction,
        Number.isFinite(inc.latitude) ? inc.latitude.toFixed(3) : 'na',
        Number.isFinite(inc.longitude) ? inc.longitude.toFixed(3) : 'na',
      ].join(':'))
      .sort(),
  ].join('|')

  // Load recommendation on incident change
  useEffect(() => {
    setLoading(true)
    setDispatched(false)
    setSelectedUnits([])
    setUnitRoutes([])
    setAllUnitRoutes({})          // clear stale route badges from previous incident
    setRoutesLoading(false)       // cancel any in-progress routing indicator
    setDispatchAdvice(null)       // clear stale advice from previous incident
    setAdviceLoading(false)
    setBriefing('')               // clear stale briefing from previous incident
    setBriefingOpen(false)
    setBriefingLoading(false)
    onUnitRoutesChange?.([])
    onPreviewUnits?.([])

    Promise.all([
      api.recommendation(incident.id),
      api.fireBehavior(incident.id).catch(() => null),
    ]).then(([rec, fb]) => {
      setRecommendation(rec)
      setFireBehavior(fb)
    }).catch(() => setRecommendation(null))
      .finally(() => setLoading(false))
  }, [incident.id])

  // Instantly score ALL available units using straight-line path — no network
  useEffect(() => {
    if (!availableUnits.length || !incident || !allIncidents.length) return
    const badges = scoreBadges(availableUnits, incident, allIncidents)
    setAllUnitRoutes(badges)
  }, [availableUnitsKey, routeRiskInputsKey, incident.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Recompute routes whenever selected units change
  useEffect(() => {
    onPreviewUnits?.(selectedPreviewUnits)

    if (!selectedPreviewUnits.length) {
      setUnitRoutes([])
      onUnitRoutesChange?.([])
      return
    }

    setRoutesLoading(true)
    computeUnitRoutes(selectedPreviewUnits, incident, allIncidents)
      .then(routes => {
        setUnitRoutes(routes)
        onUnitRoutesChange?.(routes)
      })
      .finally(() => setRoutesLoading(false))
  }, [selectedUnitsKey, selectedPreviewUnitsKey, routeRiskInputsKey, incident.id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDispatch(loadouts = []) {
    if (selectedUnits.length === 0) return
    setDispatching(true)
    try {
      await api.dispatch({
        incident_id:     incident.id,
        unit_ids:        selectedUnits,
        loadout_profile: recommendation?.loadout_profile ?? 'initial_attack',
        route_id:        '',
      })
      // Persist confirmed loadouts so LeftSidebar hover tooltip shows LOADED not STD
      if (loadouts.length > 0) onConfirmLoadouts?.(loadouts)
      setDispatched(true)
      toast(`${selectedUnits.length} unit${selectedUnits.length !== 1 ? 's' : ''} dispatched to ${incident.name}`, 'success')
      onPreviewUnits?.([])
      onUnitRoutesChange?.([])
      onDispatchSuccess?.()
    } catch (e) {
      console.error('Dispatch failed', e)
    } finally {
      setDispatching(false)
    }
  }

  const auth          = useAuth()
  const canDispatch   = selectedUnits.length > 0 && !dispatching && auth?.role !== 'viewer'
  const canBrief      = auth?.role !== 'viewer'
  const canClose      = auth?.role === 'commander' || auth?.role === 'dispatcher'

  async function handleOpenCloseout() {
    setCloseoutOpen(true)
    setChecklistLoading(true)
    try {
      const data = await api.closeoutChecklist(incident.id)
      setChecklist(data)
    } catch (e) {
      toast('Failed to load checklist', 'error')
    } finally {
      setChecklistLoading(false)
    }
  }

  async function handleGenerateHandoff() {
    setHandoffLoading(true)
    try {
      await generateHandoffBriefing(incident.id, 12)
      toast('Shift handoff briefing generated', 'success')
      // Re-fetch checklist to update briefing_generated check
      const data = await api.closeoutChecklist(incident.id)
      setChecklist(data)
    } catch (e) {
      toast('Failed to generate handoff briefing', 'error')
    } finally {
      setHandoffLoading(false)
    }
  }

  async function handleCloseIncident(force = false) {
    setCloseLoading(true)
    try {
      await api.closeIncident(incident.id, force)
      toast(`Incident "${incident.name}" marked OUT`, 'success')
      setCloseoutOpen(false)
      // Notify parent to refresh
      onClose?.()
    } catch (e) {
      const detail = e.message ?? 'Failed to close incident'
      toast(detail, 'error')
    } finally {
      setCloseLoading(false)
    }
  }

  // Dispatch button ETA = slowest selected unit
  const dispatchEta = (() => {
    if (!unitRoutes.length) return null
    const max = Math.max(...unitRoutes.map(r => r.etaMinutes))
    if (!max) return null
    const d = new Date()
    d.setMinutes(d.getMinutes() + max)
    return formatTimeShort(d)
  })()

  const filledUnitTypes = [...selectedUnits, ...alreadyAssigned.map(u => u.id)].reduce((acc, uid) => {
    const unit = units.find(u => u.id === uid)
    if (unit) acc[unit.unit_type] = (acc[unit.unit_type] || 0) + 1
    return acc
  }, {})

  async function handleGenerateBriefing() {
    if (briefing) setBriefing('')  // clear previous briefing on new generate
    setBriefingLoading(true)
    setBriefingOpen(true)
    setTimeout(() => briefingRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    await streamBriefing(
      incident.id,
      (chunk) => setBriefing(prev => prev + chunk),
      () => setBriefingLoading(false),
      (err) => { console.error('Briefing error:', err); setBriefingLoading(false) },
    )
  }

  function exportBriefingPdf() {
    fetch(`${BASE_URL}/api/briefing/${incident.id}/export.pdf`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ content: briefing }),
    })
      .then(res => {
        if (!res.ok) throw new Error('Briefing export failed')
        return res.blob()
      })
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `pyra_ics_briefing_${incident.id}.pdf`
        a.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        toast('Briefing exported to PDF', 'success')
      })
      .catch(() => toast('Failed to export briefing PDF', 'error'))
  }

  // Fetch dispatch advice when units are selected — stable dep avoids flicker
  useEffect(() => {
    if (selectedUnits.length === 0) { setDispatchAdvice(null); return }
    if (auth?.role === 'viewer') return
    let cancelled = false
    setAdviceLoading(true)
    setDispatchAdvice(null)
    getDispatchAdvice(incident.id, selectedUnits)
      .then(result => { if (!cancelled) setDispatchAdvice(result) })
      .catch(() => { if (!cancelled) setDispatchAdvice(null) })
      .finally(() => { if (!cancelled) setAdviceLoading(false) })
    return () => { cancelled = true }
  }, [selectedUnitsKey, incident.id, auth?.role]) // eslint-disable-line react-hooks/exhaustive-deps

  function handleDownloadReport() {
    const token = auth?.access_token
    fetch(`${BASE_URL}/api/report/${incident.id}`, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
    })
      .then(res => {
        if (!res.ok) throw new Error('Report failed')
        return res.blob()
      })
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a   = document.createElement('a')
        a.href     = url
        a.download = `pyra_report_${incident.id}.pdf`
        a.click()
        URL.revokeObjectURL(url)
        toast('Incident report exported to PDF', 'success')
      })
      .catch(err => { console.error('Report error:', err); toast('Failed to export incident report', 'error') })
  }

  return (
    <div className="ui-shell-panel ui-float-soft" style={{
      position: 'fixed', top: `${topOffset}px`, right: `${rightOffset}px`, bottom: `${bottomOffset}px`, width: `${panelWidth}px`,
      transition: 'right 0.2s ease',
      animation: 'slideInRight 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
      background: 'linear-gradient(180deg, rgba(28,35,47,0.94) 0%, rgba(18,24,34,0.97) 100%)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '24px',
      display: 'flex', flexDirection: 'column', zIndex: 2200, overflow: 'hidden',
      boxShadow: '0 24px 56px rgba(0,0,0,0.38), inset 0 1px 0 rgba(255,255,255,0.05)',
      backdropFilter: 'blur(14px)',
      pointerEvents: 'auto',
    }}>

      {/* Header */}
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)',
        flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '15px', color: '#d4dce8', letterSpacing: '0.01em' }}>
            {incident.name}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '3px' }}>
            <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: SEVERITY_COLOR[incident.severity], letterSpacing: '0.04em' }}>
              {incident.severity.toUpperCase()}
            </span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#c3d0df' }}>
              {incident.fire_type.replace(/_/g, ' ').toUpperCase()}
            </span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#c3d0df' }}>
              {incident.acres_burned?.toLocaleString()} ac
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#c3d0df', cursor: 'pointer', fontSize: '18px', padding: '4px 8px' }}
        >✕</button>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>

        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '4px 0' }}>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
              <div className="pyra-skeleton" style={{ height: '52px', flex: 1 }} />
              <div className="pyra-skeleton" style={{ height: '52px', flex: 1 }} />
            </div>
            <div className="pyra-skeleton" style={{ height: '11px', width: '40%' }} />
            <div className="pyra-skeleton" style={{ height: '72px', width: '100%' }} />
            <div className="pyra-skeleton" style={{ height: '11px', width: '40%', marginTop: '4px' }} />
            {[1,2,3].map(i => <div key={i} className="pyra-skeleton" style={{ height: '54px', width: '100%' }} />)}
          </div>
        )}

        {!loading && !recommendation && (
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '13px', color: '#ef4444', padding: '20px 0' }}>
            Failed to load recommendation.
          </div>
        )}

        {!loading && recommendation && (
          <>
            {/* Confidence + Loadout */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '14px' }}>
              <div style={{ background: 'var(--surface)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '5px', padding: '6px 10px', flex: 1 }}>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.06em', marginBottom: '2px' }}>
                  LOADOUT PROFILE
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#ff4d1a' }}>
                  {LOADOUT_LABEL[recommendation.loadout_profile] ?? recommendation.loadout_profile}
                </div>
              </div>
              <div style={{ background: 'var(--surface)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '5px', padding: '6px 10px', flex: 1 }}>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.06em', marginBottom: '2px' }}>
                  CONFIDENCE
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: recommendation.confidence === 'high' ? '#4ade80' : recommendation.confidence === 'moderate' ? '#facc15' : '#9baac0' }}>
                  {recommendation.confidence.toUpperCase()}
                </div>
              </div>
            </div>

            {/* Situation summary */}
            <div style={{ marginBottom: '14px' }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '6px' }}>
                SITUATION SUMMARY
              </div>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.6, background: 'var(--surface)', borderRadius: '5px', padding: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                {recommendation.summary}
              </div>
            </div>

            {/* Fire Intelligence */}
            {fireBehavior && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  FIRE INTELLIGENCE
                  <span className="pyra-ai-badge" style={{ fontSize: '8px' }}>AI</span>
                </div>

                {/* FBI bar */}
                <div style={{ background: 'var(--surface)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '5px', padding: '10px', marginBottom: '4px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#c3d0df', letterSpacing: '0.04em' }}>FIRE BEHAVIOR INDEX</span>
                    <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: fireBehavior.fire_behavior_index >= 0.75 ? '#ef4444' : fireBehavior.fire_behavior_index >= 0.5 ? '#ff4d1a' : fireBehavior.fire_behavior_index >= 0.3 ? '#facc15' : '#4ade80' }}>
                      {(fireBehavior.fire_behavior_index * 100).toFixed(0)}
                    </span>
                  </div>
                  <div style={{ height: '4px', background: '#262626', borderRadius: '2px' }}>
                    <div style={{
                      height: '100%', borderRadius: '2px',
                      width: `${fireBehavior.fire_behavior_index * 100}%`,
                      background: fireBehavior.fire_behavior_index >= 0.75 ? '#ef4444' : fireBehavior.fire_behavior_index >= 0.5 ? '#ff4d1a' : fireBehavior.fire_behavior_index >= 0.3 ? '#facc15' : '#4ade80',
                      transition: 'width 0.4s ease',
                    }} />
                  </div>
                </div>

                {/* Stats grid */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', marginBottom: '4px' }}>
                  {[
                    { label: 'RATE OF SPREAD', value: fireBehavior.rate_of_spread_mph != null ? `${fireBehavior.rate_of_spread_mph} mph` : '—', color: fireBehavior.rate_of_spread_mph >= 5 ? '#ef4444' : fireBehavior.rate_of_spread_mph >= 2 ? '#ff4d1a' : '#FBFBFB' },
                    { label: 'BEHAVIOR', value: (fireBehavior.predicted_behavior ?? 'unknown').toUpperCase(), color: fireBehavior.predicted_behavior === 'extreme' ? '#ef4444' : fireBehavior.predicted_behavior === 'high' ? '#ff4d1a' : fireBehavior.predicted_behavior === 'moderate' ? '#facc15' : '#4ade80' },
                    { label: 'GROWTH (12HR)', value: fireBehavior.projected_growth_percent_12h != null ? `+${fireBehavior.projected_growth_percent_12h}%` : '—', color: fireBehavior.projected_growth_percent_12h >= 50 ? '#ef4444' : fireBehavior.projected_growth_percent_12h >= 20 ? '#ff4d1a' : '#4ade80' },
                    { label: 'SUPPRESSION EFF.', value: fireBehavior.suppression_effectiveness != null ? `${(fireBehavior.suppression_effectiveness * 100).toFixed(0)}%` : '—', color: fireBehavior.suppression_effectiveness >= 0.6 ? '#4ade80' : fireBehavior.suppression_effectiveness >= 0.3 ? '#facc15' : '#ef4444' },
                  ].map(stat => (
                    <div key={stat.label} style={{ background: 'var(--surface)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '5px', padding: '7px 10px' }}>
                      <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.04em', marginBottom: '3px' }}>{stat.label}</div>
                      <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: stat.color }}>{stat.value}</div>
                    </div>
                  ))}
                </div>

                {/* Terrain + AQI row */}
                {(incident.elevation_m != null || incident.aqi != null) && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', marginBottom: '4px' }}>
                    {incident.elevation_m != null && (
                      <div style={{ background: 'var(--surface)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '5px', padding: '7px 10px' }}>
                        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.04em', marginBottom: '3px' }}>TERRAIN</div>
                        <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8' }}>
                          {Math.round(incident.elevation_m)}m
                          {incident.slope_percent != null && <span style={{ fontWeight: 400, color: incident.slope_percent >= 30 ? '#ff4d1a' : '#9baac0', fontSize: '11px' }}> · {incident.slope_percent.toFixed(0)}% slope</span>}
                        </div>
                        {incident.aspect_cardinal && (
                          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#a7b5c7', marginTop: '2px' }}>{incident.aspect_cardinal} aspect</div>
                        )}
                      </div>
                    )}
                    {incident.aqi != null && (
                      <div style={{ background: 'var(--surface)', border: `1px solid ${incident.aqi >= 151 ? '#ef4444' : incident.aqi >= 101 ? '#ff4d1a' : '#262626'}`, borderRadius: '5px', padding: '7px 10px' }}>
                        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.04em', marginBottom: '3px' }}>AIR QUALITY</div>
                        <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: incident.aqi >= 151 ? '#ef4444' : incident.aqi >= 101 ? '#ff4d1a' : incident.aqi >= 51 ? '#facc15' : '#4ade80' }}>
                          AQI {incident.aqi}
                        </div>
                        {incident.aqi_category && (
                          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#a7b5c7', marginTop: '2px' }}>{incident.aqi_category.replace(/_/g, ' ')}</div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Behavior description */}
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.6, background: 'var(--surface)', borderRadius: '5px', padding: '8px 10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                  {fireBehavior.projected_acres_12h != null
                    ? `Projected size in 12 hours: ~${fireBehavior.projected_acres_12h.toLocaleString()} acres at current rate of spread.`
                    : `Fire behavior classified as ${fireBehavior.predicted_behavior ?? 'unknown'}. Monitor conditions closely.`}
                </div>
              </div>
            )}

            {/* Recommended unit types */}
            <div style={{ marginBottom: '14px' }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '6px' }}>
                RECOMMENDED UNITS
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {recommendation.unit_recommendations.map((rec, i) => {
                  const filled = (filledUnitTypes[rec.unit_type] ?? 0) >= rec.quantity
                  const accent = filled ? '#4ade80' : (PRIORITY_COLOR[rec.priority] ?? '#ff4d1a')
                  return (
                    <div key={i} style={{
                      background: filled
                        ? 'linear-gradient(180deg, rgba(17,38,27,0.92) 0%, rgba(18,31,26,0.88) 100%)'
                        : 'linear-gradient(180deg, rgba(20,26,36,0.96) 0%, rgba(16,22,31,0.92) 100%)',
                      border: `1px solid ${filled ? '#4ade80' : 'rgba(255,255,255,0.08)'}`,
                      borderRadius: '16px', padding: '10px 12px',
                      display:      'flex', alignItems: 'flex-start', gap: '10px',
                      boxShadow: filled ? '0 14px 28px rgba(34,197,94,0.1), inset 0 1px 0 rgba(255,255,255,0.04)' : 'inset 0 1px 0 rgba(255,255,255,0.04)',
                    }}>
                      <div style={{
                        width: '34px', height: '34px', borderRadius: '12px', flexShrink: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: `${accent}18`,
                        border: `1px solid ${accent}40`,
                        boxShadow: `0 0 18px ${accent}18`,
                        fontSize: '15px',
                      }}>{UNIT_ICON[rec.unit_type] ?? '◉'}</div>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                          <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#f8fbff' }}>
                            {rec.quantity}× {rec.unit_type.replace(/_/g, ' ').toUpperCase()}
                          </span>
                          <span style={{
                            fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '9px',
                            color: accent, letterSpacing: '0.06em',
                            background: `${accent}12`,
                            border: `1px solid ${accent}30`,
                            borderRadius: '999px', padding: '3px 7px',
                          }}>
                            {filled ? '✓ FILLED' : rec.priority.replace(/_/g, ' ').toUpperCase()}
                          </span>
                        </div>
                        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#c3d0df', lineHeight: 1.5 }}>
                          {rec.rationale}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Already deployed */}
            {alreadyAssigned.length > 0 && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#8b9bb0', letterSpacing: '0.06em', marginBottom: '6px' }}>
                  ALREADY DEPLOYED
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  {alreadyAssigned.map(unit => (
                    <div key={unit.id} style={{
                      display: 'flex', alignItems: 'center', gap: '8px',
                      padding: '5px 10px', background: 'var(--surface)',
                      border: '1px solid rgba(255,255,255,0.06)', borderRadius: '5px',
                    }}>
                      <span style={{ fontSize: '13px' }}>{UNIT_ICON[unit.unit_type] ?? '◉'}</span>
                      <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '12px', color: '#d4dce8', flex: 1 }}>
                        {unit.designation}
                      </span>
                      <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: unit.status === 'on_scene' ? '#ff4d1a' : unit.status === 'en_route' ? '#60a5fa' : '#a78bfa', letterSpacing: '0.02em' }}>
                        {unit.status.replace(/_/g, ' ').toUpperCase()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tactical notes */}
            <div style={{ marginBottom: '14px' }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '6px' }}>
                TACTICAL NOTES
              </div>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.6, background: 'var(--surface)', borderRadius: '5px', padding: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                {recommendation.tactical_notes}
              </div>
            </div>

            {/* Dispatch Intelligence Engine — AI-ranked unit selection */}
            <DispatchRecommendations
              incident={incident}
              onDispatchSuccess={onDispatchSuccess}
              onConfirmLoadouts={onConfirmLoadouts}
              onOpenLoadout={(unitIds) => {
                setSelectedUnits(unitIds)
                setLoadoutOpen(true)
              }}
              alreadyAssignedIds={alreadyAssigned.map(u => u.id)}
              alreadyAssignedDesignations={alreadyAssigned.map(u => u.designation)}
              externalSelectedUnits={selectedUnits}
              onSelectionChange={(unitIds) => setSelectedUnits(unitIds)}
            />

            {/* Unit selector */}
            <div style={{ marginBottom: '14px' }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#a7b5c7', letterSpacing: '0.06em', marginBottom: '6px' }}>
                SELECT UNITS TO DISPATCH
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {(() => {
                  const available = units.filter(u => u.status === 'available' && isAirUnitAtAirBase(u))
                  const sorted = sortUnitsForDispatch(available, incident)
                  let lastType = null
                  return sorted.map(unit => {
                    const isSelected = selectedUnits.includes(unit.id)
                    const showHeader = unit.unit_type !== lastType
                    lastType = unit.unit_type
                    const distMiles = distToIncident(unit, incident)
                    const distLabel = distMiles < 999
                      ? distMiles < 1 ? `${Math.round(distMiles * 5280)} ft` : `${distMiles.toFixed(1)} mi`
                      : null

                    // Pre-computed route for this unit (shows badge before selection)
                    const previewRoute = allUnitRoutes[unit.id]
                    // Selected route (for ETA after selection)
                    const unitRoute = unitRoutes.find(r => r.unitId === unit.id)

                    return (
                      <div key={unit.id}>
                        {showHeader && (
                          <div style={{
                            fontFamily: 'var(--font-sans)', fontWeight: 700,
                            fontSize: '10px', color: '#a7b5c7', letterSpacing: '0.06em',
                            textTransform: 'uppercase', marginTop: '8px', marginBottom: '3px', paddingLeft: '2px',
                          }}>
                            {unit.unit_type.replace(/_/g, ' ')}
                          </div>
                        )}
                        <div
                          onClick={() => setSelectedUnits(prev =>
                            prev.includes(unit.id)
                              ? prev.filter(id => id !== unit.id)
                              : [...prev, unit.id]
                          )}
                          style={{
                            background: isSelected
                              ? 'linear-gradient(180deg, rgba(26,44,66,0.94) 0%, rgba(20,32,48,0.92) 100%)'
                              : 'linear-gradient(180deg, rgba(20,26,36,0.96) 0%, rgba(16,22,31,0.92) 100%)',
                            border: `1px solid ${isSelected ? 'rgba(56,189,248,0.45)' : 'rgba(255,255,255,0.08)'}`,
                            borderRadius: (isSelected && unitRoute) ? '18px 18px 0 0' : '18px',
                            padding: '10px 12px',
                            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px',
                            transition: 'all 0.15s',
                            boxShadow: isSelected ? '0 18px 30px rgba(56,189,248,0.12), inset 0 1px 0 rgba(255,255,255,0.05)' : 'inset 0 1px 0 rgba(255,255,255,0.04)',
                          }}
                        >
                          <div style={{
                            width: '36px', height: '36px', borderRadius: '12px',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: isSelected ? 'rgba(56,189,248,0.16)' : 'rgba(255,255,255,0.04)',
                            border: `1px solid ${isSelected ? 'rgba(56,189,248,0.3)' : 'rgba(255,255,255,0.08)'}`,
                            boxShadow: isSelected ? '0 0 18px rgba(56,189,248,0.14)' : 'none',
                            flexShrink: 0,
                          }}>
                            <span style={{ fontSize: '15px' }}>{UNIT_ICON[unit.unit_type] ?? '◉'}</span>
                          </div>
                          <div style={{
                            width: '6px', alignSelf: 'stretch', borderRadius: '999px',
                            background: previewRoute?.statusColor ?? '#38bdf8',
                            boxShadow: `0 0 12px ${previewRoute?.statusColor ?? '#38bdf8'}55`,
                            opacity: isSelected ? 1 : 0.9,
                            flexShrink: 0,
                          }} />
                          <div style={{ flex: 1 }}>
                            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8', marginBottom: '3px' }}>
                              {unit.designation}
                            </div>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#8b9bb0', letterSpacing: '0.08em' }}>
                              {unit.unit_type.replace(/_/g, ' ').toUpperCase()}
                            </div>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
                            <span style={{
                              fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#4ade80',
                              background: 'rgba(34,197,94,0.12)', border: '1px solid rgba(34,197,94,0.24)',
                              borderRadius: '999px', padding: '3px 8px', letterSpacing: '0.06em',
                            }}>AVAILABLE</span>
                            {distLabel && (
                              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#a7b5c7' }}>{distLabel}</span>
                            )}
                            {previewRoute && (
                              <RouteBadge status={previewRoute.status} statusColor={previewRoute.statusColor} />
                            )}
                            {isSelected && routesLoading && !unitRoute && (
                              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#a7b5c7' }}>routing...</span>
                            )}
                          </div>
                        </div>
                        {/* Inline route drawer — appears below the unit row when selected */}
                        {isSelected && unitRoute && (
                          <div style={{
                            background: 'rgba(255,255,255,0.04)',
                            border: `1px solid ${unitRoute.statusColor}55`,
                            borderTop: 'none',
                            borderRadius: '0 0 18px 18px',
                            padding: '8px 10px',
                            marginBottom: '1px',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '5px' }}>
                              <RouteBadge status={unitRoute.status} statusColor={unitRoute.statusColor} />
                              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#60a5fa' }}>
                                ETA ~{unitRoute.etaTimeStr}
                              </span>
                            </div>
                            <div style={{
                              fontFamily: 'var(--font-sans)', fontSize: '11px',
                              color: '#d4dce8', lineHeight: 1.5,
                            }}>
                              {unitRoute.explanation}
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })
                })()}
                {units.filter(u => u.status === 'available' && isAirUnitAtAirBase(u)).length === 0 && (
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#a7b5c7' }}>
                    No available units
                  </div>
                )}
              </div>
            </div>

          </>
        )}
      </div>

      {/* Dispatch button */}
      {!loading && recommendation && (
        <div style={{ padding: '12px 16px', borderTop: '1px solid rgba(255,255,255,0.06)', flexShrink: 0 }}>

          {/* Dispatch Advisor — shows when units selected */}
          {(dispatchAdvice || adviceLoading) && selectedUnits.length > 0 && (
            <div style={{
              background: 'rgba(255,255,255,0.04)',
              border: `1px solid ${dispatchAdvice?.assessment === 'optimal' ? '#4ade8044' : dispatchAdvice?.assessment === 'suboptimal' ? '#ef444444' : '#26262644'}`,
              borderRadius: '14px', padding: '10px 12px', marginBottom: '10px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <div style={{
                  width: '5px', height: '5px', borderRadius: '50%',
                  background: adviceLoading ? '#ff4d1a' : dispatchAdvice?.assessment === 'optimal' ? '#4ade80' : dispatchAdvice?.assessment === 'suboptimal' ? '#ef4444' : '#facc15',
                  boxShadow: adviceLoading ? '0 0 4px #ff4d1a' : 'none',
                }} />
                <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px', color: '#a7b5c7', letterSpacing: '0.08em' }}>
                  DISPATCH ADVISOR
                </span>
                <span className="pyra-ai-badge">⬡ PYRA AI</span>
                {dispatchAdvice && (
                  <span style={{
                    fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px', letterSpacing: '0.06em',
                    color: dispatchAdvice.assessment === 'optimal' ? '#4ade80' : dispatchAdvice.assessment === 'suboptimal' ? '#ef4444' : '#facc15',
                  }}>
                    {dispatchAdvice.assessment.toUpperCase()}
                  </span>
                )}
              </div>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.5 }}>
                {adviceLoading ? 'Analyzing loadout...' : dispatchAdvice?.advice?.replace(/\*\*[^*]*\*\*:?\s*/g, '').trim()}
              </div>
            </div>
          )}

          {dispatched ? (
            <div style={{
              background: 'rgba(74,222,128,0.1)', border: '1px solid #4ade80',
              borderRadius: '14px', padding: '10px 16px', textAlign: 'center',
              fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#4ade80',
            }}>
              ✓ UNITS DISPATCHED SUCCESSFULLY
            </div>
          ) : confirmDispatch ? (
            <div style={{ display: 'flex', gap: '6px' }}>
              <div style={{ flex: 1, padding: '10px', background: 'rgba(245,110,15,0.1)', border: '1px solid #ff4d1a55', borderRadius: '14px', fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', display: 'flex', alignItems: 'center' }}>
                Dispatch {selectedUnits.length} unit{selectedUnits.length !== 1 ? 's' : ''}?
              </div>
              <button onClick={() => { handleDispatch(pendingLoadouts); setConfirmDispatch(false) }}
                className="pyra-btn-press"
                style={{ padding: '10px 16px', background: '#ff4d1a', border: 'none', borderRadius: '12px', cursor: 'pointer', fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color: '#d4dce8' }}>
                CONFIRM
              </button>
              <button onClick={() => setConfirmDispatch(false)}
                style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', cursor: 'pointer', fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#c3d0df' }}>
                CANCEL
              </button>
            </div>
          ) : (
            <button
              onClick={() => canDispatch && setLoadoutOpen(true)}
              disabled={!canDispatch}
              className="pyra-btn-press" 
              style={{
                width: '100%', padding: '12px',
                background: canDispatch ? 'linear-gradient(180deg, #ff5a24 0%, #e94916 100%)' : 'rgba(255,255,255,0.05)',
                border: canDispatch ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(255,255,255,0.08)',
                borderRadius: '16px',
                cursor:        canDispatch ? 'pointer' : 'not-allowed',
                fontFamily:    'Inter, sans-serif', fontWeight: 700, fontSize: '13px',
                color:         '#FBFBFB', letterSpacing: '0.03em', transition: 'background 0.15s',
                boxShadow: canDispatch ? '0 16px 30px rgba(255,77,26,0.25)' : 'none',
              }}
            >
              {dispatching
                ? 'DISPATCHING...'
                : auth?.role === 'viewer'
                  ? 'DISPATCH — COMMANDER / DISPATCHER ONLY'
                  : selectedUnits.length === 0
                    ? 'SELECT UNITS TO DISPATCH'
                    : `CONFIGURE LOADOUT & DISPATCH ${selectedUnits.length} UNIT${selectedUnits.length !== 1 ? 'S' : ''}`
              }
            </button>
          )}

          {/* Generate Briefing button */}
          <button
            onClick={handleGenerateBriefing}
            disabled={briefingLoading || !canBrief}
            style={{
              width: '100%', padding: '10px', marginTop: '8px',
              background: 'rgba(255,255,255,0.04)',
              border: `1px solid ${briefingLoading || !canBrief ? '#262626' : 'rgba(255,255,255,0.08)'}`,
              borderRadius: '12px',
              cursor: briefingLoading || !canBrief ? 'not-allowed' : 'pointer',
              fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '12px',
              color: briefingLoading || !canBrief ? '#5f6c7d' : '#c3d0df',
              letterSpacing: '0.03em', transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            }}
            onMouseEnter={e => { if (!briefingLoading && canBrief) { e.currentTarget.style.borderColor = '#ff4d1a'; e.currentTarget.style.color = '#ff4d1a' }}}
            onMouseLeave={e => { e.currentTarget.style.borderColor = canBrief ? '#444' : '#262626'; e.currentTarget.style.color = canBrief ? '#c3d0df' : '#5f6c7d' }}
          >
            {briefingLoading ? (
              <>
                <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⟳</span>
                GENERATING BRIEFING...
              </>
            ) : !canBrief ? (
              <>⬡ BRIEFING — COMMANDER ONLY</>
            ) : (
              <>⬡ GENERATE AI BRIEFING</>
            )}
          </button>

          {/* Export PDF Report button */}
          <button
            onClick={handleDownloadReport}
            style={{
              width: '100%', padding: '10px', marginTop: '6px',
              background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '12px', cursor: 'pointer',
              fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '12px',
              color: '#c3d0df', letterSpacing: '0.03em', transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#4ade80'; e.currentTarget.style.color = '#4ade80' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = '#444'; e.currentTarget.style.color = '#c3d0df' }}
          >
            ↓ EXPORT PDF REPORT
          </button>

          {/* Close-out button — only shown when incident is not already out */}
          {canClose && incident.status !== 'out' && (
            <button
              onClick={handleOpenCloseout}
              style={{
                width: '100%', padding: '10px', marginTop: '6px',
                background: 'rgba(239,68,68,0.06)', border: '1px solid #ef444466',
                borderRadius: '12px', cursor: 'pointer',
                fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '12px',
                color: '#ef4444aa', letterSpacing: '0.03em', transition: 'all 0.15s',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = '#ef4444'; e.currentTarget.style.color = '#ef4444' }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = '#ef444466'; e.currentTarget.style.color = '#ef4444aa' }}
            >
              ⬡ CLOSE OUT INCIDENT
            </button>
          )}

          {/* Bottom row — SITREP Chat + Post-Incident Review */}
          <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
            <button
              onClick={() => setChatOpen(v => !v)}
              style={{
                flex: 1, padding: '9px',
                background: chatOpen ? 'rgba(245,110,15,0.14)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${chatOpen ? '#ff4d1a' : 'rgba(255,255,255,0.08)'}`,
                borderRadius: '12px', cursor: 'pointer',
                fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '11px',
                color: chatOpen ? '#ff4d1a' : '#c3d0df',
                letterSpacing: '0.03em', transition: 'all 0.15s',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
              }}
              onMouseEnter={e => { if (!chatOpen) { e.currentTarget.style.borderColor = '#ff4d1a'; e.currentTarget.style.color = '#ff4d1a' }}}
              onMouseLeave={e => { if (!chatOpen) { e.currentTarget.style.borderColor = '#444'; e.currentTarget.style.color = '#c3d0df' }}}
            >
              💬 SITREP CHAT
            </button>
            {auth?.role === 'commander' && (
              <button
                onClick={() => setReviewOpen(v => !v)}
                style={{
                  flex: 1, padding: '9px',
                  background: reviewOpen ? 'rgba(96,165,250,0.14)' : 'rgba(255,255,255,0.04)',
                  border: `1px solid ${reviewOpen ? '#60a5fa' : 'rgba(255,255,255,0.08)'}`,
                  borderRadius: '12px', cursor: 'pointer',
                  fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '11px',
                  color: reviewOpen ? '#60a5fa' : '#c3d0df',
                  letterSpacing: '0.03em', transition: 'all 0.15s',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
                }}
                onMouseEnter={e => { if (!reviewOpen) { e.currentTarget.style.borderColor = '#60a5fa'; e.currentTarget.style.color = '#60a5fa' }}}
                onMouseLeave={e => { if (!reviewOpen) { e.currentTarget.style.borderColor = '#444'; e.currentTarget.style.color = '#c3d0df' }}}
              >
                📋 AAR REVIEW
              </button>
            )}
          </div>
        </div>
      )}

      {/* Briefing panel */}
      {briefingOpen && (
        <div ref={briefingRef} style={{
          borderTop: '1px solid rgba(255,255,255,0.06)',
          background: 'linear-gradient(180deg, rgba(26,34,48,0.92) 0%, rgba(18,24,34,0.96) 100%)',
          flexShrink: 0,
          maxHeight: '380px',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 16px 8px',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, overflow: 'hidden' }}>
              <div style={{
                width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
                background: briefingLoading ? '#ff4d1a' : '#4ade80',
                boxShadow: briefingLoading ? '0 0 6px #ff4d1a' : '0 0 6px #4ade80',
              }} />
              <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#edf2f7', letterSpacing: '0.06em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                ICS OPERATIONAL BRIEFING
              </span>
              <span className="pyra-ai-badge">
                PYRA AI
              </span>
              {briefingLoading && (
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#ff4d1a', flexShrink: 0, whiteSpace: 'nowrap' }}>
                  · GENERATING...
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              {briefing && !briefingLoading && (
                <button
                  onClick={exportBriefingPdf}
                  style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px',
                    padding: '4px 8px',
                    cursor: 'pointer',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '9px',
                    fontWeight: 600,
                    color: '#c3d0df',
                    letterSpacing: '0.06em',
                    transition: 'all 0.15s',
                    whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.borderColor = '#ff4d1a'
                    e.currentTarget.style.color = '#ff4d1a'
                    e.currentTarget.style.background = 'rgba(255,77,26,0.08)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)'
                    e.currentTarget.style.color = '#c3d0df'
                    e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
                  }}
                >
                  EXPORT PDF
                </button>
              )}
              <button
                onClick={() => setBriefingOpen(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#c3d0df', fontSize: '14px', padding: '0 2px' }}
              >
                ✕
              </button>
            </div>
          </div>
          <div style={{
            flex: 1, overflowY: 'auto', padding: '14px 16px',
            fontFamily: 'var(--font-sans)', fontSize: '12px',
            color: '#d4dce8', lineHeight: 1.7,
            background: 'rgba(12,18,27,0.24)',
          }}>
            {!briefing && !briefingLoading && (
              <span style={{ color: '#c3d0df' }}>Press Generate to create a briefing.</span>
            )}
            {(briefing || briefingLoading) && renderBriefing(briefing)}
            {briefingLoading && (
              <span style={{ color: '#ff4d1a', animation: 'blink 1s step-end infinite' }}>▋</span>
            )}
          </div>
        </div>
      )}

      {/* SITREP Chat floating panel */}
      {chatOpen && (
        <SitrepChat incident={incident} onClose={() => setChatOpen(false)} />
      )}

      {/* Post-Incident Review floating panel */}
      {reviewOpen && auth?.role === 'commander' && (
        <PostIncidentReview incident={incident} onClose={() => setReviewOpen(false)} />
      )}

      {/* Close-out modal */}
      {closeoutOpen && createPortal(
        <div style={{
          position: 'fixed', inset: 0, zIndex: 5000,
          background: 'rgba(5,8,12,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          backdropFilter: 'blur(10px)',
        }} onClick={e => { if (e.target === e.currentTarget) setCloseoutOpen(false) }}>
          <div style={{
            background: 'rgba(20,26,36,0.97)', border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '22px', padding: '22px 24px', minWidth: '360px', maxWidth: '460px',
            boxShadow: '0 30px 70px rgba(0,0,0,0.56)',
            backdropFilter: 'blur(16px)',
          }}>
            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#ef4444', letterSpacing: '0.06em', marginBottom: '4px' }}>
              ⬡ INCIDENT CLOSE-OUT
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#a7b5c7', marginBottom: '16px' }}>
              {incident.name}
            </div>

            {checklistLoading && (
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#c3d0df', padding: '12px 0' }}>
                Loading checklist...
              </div>
            )}

            {checklist && !checklistLoading && (
              <>
                {/* Checklist items */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
                  {checklist.checks?.map(check => (
                    <div key={check.key} style={{
                      display: 'flex', alignItems: 'flex-start', gap: '10px',
                        padding: '8px 10px',
                      background: check.passed ? 'rgba(74,222,128,0.06)' : 'rgba(239,68,68,0.06)',
                      border: `1px solid ${check.passed ? '#4ade8033' : '#ef444433'}`,
                      borderRadius: '14px',
                    }}>
                      <span style={{ fontSize: '13px', flexShrink: 0, marginTop: '1px' }}>
                        {check.passed ? '✅' : check.required ? '❌' : '⚠️'}
                      </span>
                      <div>
                        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', fontWeight: 600, color: check.passed ? '#4ade80' : check.required ? '#ef4444' : '#facc15' }}>
                          {check.label}{!check.required && ' (recommended)'}
                        </div>
                        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#a7b5c7', marginTop: '2px' }}>
                          {check.detail}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Generate handoff button if briefing not done */}
                {checklist.checks?.find(c => c.key === 'briefing_generated' && !c.passed) && (
                  <button
                    onClick={handleGenerateHandoff}
                    disabled={handoffLoading}
                    style={{
                      width: '100%', padding: '8px', marginBottom: '8px',
                      background: handoffLoading ? 'rgba(245,110,15,0.08)' : 'rgba(245,110,15,0.12)',
                      border: '1px solid #ff4d1a66', borderRadius: '14px', cursor: handoffLoading ? 'not-allowed' : 'pointer',
                      fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '11px',
                      color: '#ff4d1a', letterSpacing: '0.03em',
                    }}
                  >
                    {handoffLoading ? '⟳ Generating handoff briefing...' : '⬡ GENERATE SHIFT HANDOFF BRIEFING'}
                  </button>
                )}

                {/* Action row */}
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={() => setCloseoutOpen(false)}
                    style={{
                      flex: 1, padding: '9px',
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '14px', cursor: 'pointer',
                      fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '11px', color: '#c3d0df',
                    }}
                  >
                    CANCEL
                  </button>

                  {checklist.ready ? (
                    <button
                      onClick={() => handleCloseIncident(false)}
                      disabled={closeLoading}
                      style={{
                        flex: 2, padding: '9px',
                        background: closeLoading ? 'rgba(239,68,68,0.12)' : 'rgba(239,68,68,0.18)',
                        border: '1px solid #ef4444', borderRadius: '14px',
                        cursor: closeLoading ? 'not-allowed' : 'pointer',
                        fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '11px', color: '#ef4444',
                        letterSpacing: '0.04em',
                      }}
                    >
                      {closeLoading ? 'CLOSING...' : '⬡ CONFIRM CLOSE-OUT'}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleCloseIncident(true)}
                      disabled={closeLoading || auth?.role !== 'commander'}
                      style={{
                        flex: 2, padding: '9px',
                        background: 'rgba(239,68,68,0.08)',
                        border: '1px solid #ef444466', borderRadius: '14px',
                        cursor: (closeLoading || auth?.role !== 'commander') ? 'not-allowed' : 'pointer',
                        fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: '11px',
                        color: auth?.role !== 'commander' ? '#8b9bb0' : '#ef4444aa',
                        letterSpacing: '0.04em',
                      }}
                      title={auth?.role !== 'commander' ? 'Commander role required to force close' : 'Force close bypasses checklist'}
                    >
                      {closeLoading ? 'CLOSING...' : '⚠ FORCE CLOSE (COMMANDER)'}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>,
        document.body
      )}

      {/* Loadout Configurator — true pop-out workspace */}
      {loadoutOpen && (
        <LoadoutConfigurator
          incident={incident}
          selectedUnits={selectedUnits}
          units={units}
          onBack={() => setLoadoutOpen(false)}
          onConfirm={(loadouts) => {
            setLoadoutOpen(false)
            setPendingLoadouts(loadouts)
            onConfirmLoadouts?.(loadouts)
            setConfirmDispatch(true)
          }}
        />
      )}
    </div>
  )
}
