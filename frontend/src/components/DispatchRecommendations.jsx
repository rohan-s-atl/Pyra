import { useEffect, useState, useCallback } from 'react'
import { api } from '../api/client'
import { toast } from './Toast'
import { useAuth } from '../context/AuthContext'

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

const S = {
  root: {
    marginBottom: '14px',
  },
  sectionLabel: {
    fontFamily: 'var(--font-sans)',
    fontWeight: 700,
    fontSize: '11px',
    color: '#5a6878',
    letterSpacing: '0.06em',
    marginBottom: '6px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  badge: (color) => ({
    fontFamily: 'var(--font-sans)',
    fontWeight: 700,
    fontSize: '8px',
    color: '#151419',
    background: color,
    borderRadius: '2px',
    padding: '2px 5px',
    letterSpacing: '0.04em',
  }),
  card: (selected) => ({
    background:   selected ? 'rgba(245,110,15,0.1)' : '#1B1B1E',
    border:       `1px solid ${selected ? '#ff4d1a' : 'rgba(255,255,255,0.07)'}`,
    borderRadius: '3px',
    padding:      '7px 10px',
    cursor:       'pointer',
    transition:   'all 0.15s',
    display:      'flex',
    alignItems:   'flex-start',
    gap:          '8px',
    marginBottom: '4px',
    userSelect:   'none',
  }),
  shortageCard: {
    background:   'rgba(239,68,68,0.08)',
    border:       '1px solid rgba(239,68,68,0.3)',
    borderRadius: '3px',
    padding:      '7px 10px',
    display:      'flex',
    alignItems:   'center',
    gap:          '8px',
    marginBottom: '4px',
  },
  designation: {
    fontFamily: 'var(--font-sans)',
    fontWeight: 700,
    fontSize:   '12px',
    color:      '#FBFBFB',
    marginBottom: '2px',
  },
  meta: {
    fontFamily: 'var(--font-sans)',
    fontSize:   '10px',
    color:      '#878787',
    marginBottom: '2px',
  },
  reason: {
    fontFamily: 'var(--font-sans)',
    fontSize:   '10px',
    color:      '#aaaaaa',
    lineHeight: 1.4,
    marginTop:  '3px',
  },
  checkBox: (selected) => ({
    width:        '14px',
    height:       '14px',
    border:       `1px solid ${selected ? '#ff4d1a' : '#444'}`,
    borderRadius: '2px',
    background:   selected ? '#ff4d1a' : 'transparent',
    flexShrink:   0,
    marginTop:    '1px',
    display:      'flex',
    alignItems:   'center',
    justifyContent: 'center',
    color:        '#151419',
    fontSize:     '9px',
    fontWeight:   700,
  }),
  approveBtn: (canApprove) => ({
    width:       '100%',
    padding:     '11px',
    marginTop:   '8px',
    background:  canApprove ? '#ff4d1a' : 'rgba(255,255,255,0.07)',
    border:      'none',
    borderRadius:'3px',
    cursor:      canApprove ? 'pointer' : 'not-allowed',
    fontFamily:  'Inter, sans-serif',
    fontWeight:  700,
    fontSize:    '13px',
    color:       '#FBFBFB',
    letterSpacing: '0.03em',
    transition:  'background 0.15s',
  }),
  selectAll: {
    fontFamily:  'Inter, sans-serif',
    fontSize:    '10px',
    color:       '#ff4d1a',
    cursor:      'pointer',
    background:  'none',
    border:      'none',
    padding:     0,
    letterSpacing: '0.02em',
  },
  successBanner: {
    background:  'rgba(74,222,128,0.1)',
    border:      '1px solid #22c55e',
    borderRadius:'3px',
    padding:     '10px',
    textAlign:   'center',
    fontFamily:  'Inter, sans-serif',
    fontWeight:  700,
    fontSize:    '12px',
    color:       '#22c55e',
    marginTop:   '8px',
  },
  summaryRow: {
    display:        'flex',
    alignItems:     'center',
    justifyContent: 'space-between',
    fontFamily:     'Inter, sans-serif',
    fontSize:       '10px',
    color:          '#878787',
    marginTop:      '6px',
    marginBottom:   '2px',
  },
  loadingRow: {
    display:    'flex',
    gap:        '8px',
    marginBottom: '4px',
  },
}

// ── Confidence score bar ─────────────────────────────────────────────────────
function ConfidenceBar({ score, label }) {
  const pct = Math.round((score ?? 0) * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 45 ? '#facc15' : '#ef4444'
  const confidenceLabel = pct >= 70 ? 'HIGH' : pct >= 45 ? 'MODERATE' : 'LOW'
  return (
    <div style={{
      marginBottom: '8px',
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid #2a2a2e',
      borderRadius: '3px',
      padding: '6px 9px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '5px' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', fontWeight: 700, color: '#5a6878', letterSpacing: '0.06em' }}>
          AI CONFIDENCE
        </span>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', fontWeight: 700, color }}>
          {confidenceLabel} · {pct}%
        </span>
      </div>
      <div style={{ height: '3px', background: '#1e1e22', borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: '2px', transition: 'width 0.4s ease' }} />
      </div>
      {label && (
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#555', marginTop: '4px' }}>
          Overall risk: {label}
        </div>
      )}
    </div>
  )
}

// ── Route safety panel ────────────────────────────────────────────────────────
const SAFETY_STATUS_COLOR = { safe: '#22c55e', risky: '#facc15', blocked: '#ef4444' }
const SAFETY_STATUS_BG    = { safe: 'rgba(74,222,128,0.08)', risky: 'rgba(250,204,21,0.08)', blocked: 'rgba(239,68,68,0.08)' }

function RouteSafetyPanel({ routes, summary }) {
  const [expanded, setExpanded] = useState(false)
  if (!routes?.length) return null

  const safeCt    = summary?.safe    ?? 0
  const riskyCt   = summary?.risky   ?? 0
  const blockedCt = summary?.blocked ?? 0

  return (
    <div style={{ marginBottom: '8px' }}>
      {/* Header row — clickable to expand */}
      <button
        onClick={() => setExpanded(v => !v)}
        style={{
          width: '100%', background: 'rgba(255,255,255,0.03)', border: '1px solid #2a2a2e',
          borderRadius: '3px', padding: '6px 9px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}
      >
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', fontWeight: 700, color: '#5a6878', letterSpacing: '0.06em' }}>
          ROUTE SAFETY
        </span>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {safeCt    > 0 && <StatusPill label={`${safeCt} SAFE`}    status="safe"    />}
          {riskyCt   > 0 && <StatusPill label={`${riskyCt} RISKY`}  status="risky"   />}
          {blockedCt > 0 && <StatusPill label={`${blockedCt} BLOCK`} status="blocked" />}
          <span style={{ color: '#555', fontSize: '10px' }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Expanded route list */}
      {expanded && (
        <div style={{ border: '1px solid #2a2a2e', borderTop: 'none', borderRadius: '0 0 3px 3px', overflow: 'hidden' }}>
          {routes.map(route => (
            <RouteRow key={route.route_id} route={route} />
          ))}
        </div>
      )}
    </div>
  )
}

function StatusPill({ label, status }) {
  return (
    <span style={{
      fontFamily: 'var(--font-sans)', fontSize: '9px', fontWeight: 700,
      color: SAFETY_STATUS_COLOR[status],
      background: SAFETY_STATUS_BG[status],
      border: `1px solid ${SAFETY_STATUS_COLOR[status]}44`,
      borderRadius: '2px', padding: '1px 5px', letterSpacing: '0.04em',
    }}>
      {label}
    </span>
  )
}

function RouteRow({ route }) {
  const status = route.status ?? 'safe'
  const color  = SAFETY_STATUS_COLOR[status] ?? '#878787'
  const score  = route.safety_score ?? 0

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '8px',
      padding: '6px 9px', borderBottom: '1px solid #1e1e22',
      background: SAFETY_STATUS_BG[status] ?? 'transparent',
    }}>
      {/* Score circle */}
      <div style={{
        width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0,
        background: `${color}22`, border: `2px solid ${color}88`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: 'var(--font-sans)', fontSize: '9px', fontWeight: 700, color,
      }}>
        {Math.round(score)}
      </div>

      {/* Label + explanation */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', fontWeight: 600, color: '#d4dce8', marginBottom: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {route.label ?? route.route_id}
        </div>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#5a6878', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {route.explanation ?? (route.risk_factors?.[0] ?? 'No hazards detected')}
        </div>
      </div>

      {/* Status badge */}
      <StatusPill label={status.toUpperCase()} status={status} />
    </div>
  )
}

// ── Loading skeleton ────────────────────────────────────────────────────────
function SkeletonCard() {
  return (
    <div style={{ marginBottom: '4px' }}>
      <div className="pyra-skeleton" style={{ height: '58px', borderRadius: '3px' }} />
    </div>
  )
}

// ── Single recommended unit row ─────────────────────────────────────────────
function UnitRow({ unit, selected, onToggle }) {
  const scoreColor = unit.score <= 5
    ? '#22c55e'
    : unit.score <= 15
      ? '#facc15'
      : '#ef4444'

  return (
    <div style={S.card(selected)} onClick={() => onToggle(unit.unit_id)}>
      <div style={S.checkBox(selected)}>
        {selected && '✓'}
      </div>
      <span style={{ fontSize: '14px', flexShrink: 0, marginTop: '1px' }}>
        {UNIT_ICON[unit.unit_type] ?? '◉'}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={S.designation}>{unit.designation}</div>
        <div style={S.meta}>
          <span style={{ textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            {unit.unit_type.replace(/_/g, ' ')}
          </span>
          <span style={{ margin: '0 5px', color: '#444' }}>·</span>
          <span>{unit.distance_km != null ? `${unit.distance_km.toFixed(1)} km` : '—'}</span>
          <span style={{ margin: '0 5px', color: '#444' }}>·</span>
          <span style={{ color: scoreColor }}>score {unit.score.toFixed(2)}</span>
        </div>
        {unit.reason && (
          <div style={S.reason}>{unit.reason}</div>
        )}
      </div>
    </div>
  )
}

// ── Shortage notice ─────────────────────────────────────────────────────────
function ShortageRow({ entry }) {
  return (
    <div style={S.shortageCard}>
      <span style={{ fontSize: '14px' }}>⚠️</span>
      <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#ef4444' }}>
        Missing {entry.missing ?? entry.shortfall ?? 1} {(entry.unit_type ?? '').replace(/_/g, ' ')} unit{(entry.missing ?? entry.shortfall ?? 1) !== 1 ? 's' : ''}
      </div>
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────
export default function DispatchRecommendations({
  incident,
  onDispatchSuccess,
  onConfirmLoadouts,
  onOpenLoadout,                    // open LoadoutConfigurator with selected unit IDs
  alreadyAssignedIds = [],
  alreadyAssignedDesignations = [],
  externalSelectedUnits,
  onSelectionChange,
}) {
  const auth = useAuth()
  const isViewer = auth?.role === 'viewer'

  const [data,          setData]          = useState(null)   // full API response
  const [loading,       setLoading]       = useState(false)
  const [error,         setError]         = useState(null)
  const [_internalSelected, _setInternalSelected] = useState([])
  // If parent passes externalSelectedUnits, use that (controlled); otherwise own state
  const selectedUnits = externalSelectedUnits ?? _internalSelected
  function setSelectedUnits(val) {
    const next = typeof val === 'function' ? val(selectedUnits) : val
    _setInternalSelected(next)
    onSelectionChange?.(next)
  }
  const [dispatching,   setDispatching]   = useState(false)
  const [dispatched,    setDispatched]    = useState(false)

  const [routeSafety,       setRouteSafety]       = useState(null)
  const [feedbackSent,      setFeedbackSent]      = useState(false)
  // Track unit IDs that have already been dispatched for this incident
  const [dispatchedUnitIds, setDispatchedUnitIds] = useState(new Set())

  // ── Fetch on incident change ──────────────────────────────────────────────
  const fetchRecommendations = useCallback(async (incidentId) => {
    setLoading(true)
    setError(null)
    setData(null)
    setSelectedUnits([])
    setDispatched(false)
    setFeedbackSent(false)
    try {
      const [result, safety] = await Promise.allSettled([
        api.unitRecommendations(incidentId),
        api.routeSafety(incidentId),
      ])
      if (result.status === 'fulfilled') setData(result.value)
      else setError(result.reason?.message ?? 'Failed to load unit recommendations.')
      if (safety.status === 'fulfilled') setRouteSafety(safety.value)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!incident?.id) return
    setDispatchedUnitIds(new Set())
    fetchRecommendations(incident.id)
  }, [incident?.id, fetchRecommendations])

  // ── Derived lists ─────────────────────────────────────────────────────────
  const allRecommendedUnits = data?.recommended_units ?? []
  // Filter out units already on this incident — match by ID or designation
  const assignedIdSet    = new Set(alreadyAssignedIds.map(String))
  const assignedDesigSet = new Set(alreadyAssignedDesignations.map(String))
  const normalUnits = allRecommendedUnits.filter(u =>
    !dispatchedUnitIds.has(u.unit_id) &&
    !assignedIdSet.has(String(u.unit_id)) &&
    !assignedDesigSet.has(u.designation)
  )
  const shortages = data?.summary?.shortages ?? []

  // ── Handlers ──────────────────────────────────────────────────────────────
  function toggleUnit(unitId) {
    setSelectedUnits(prev =>
      prev.includes(unitId)
        ? prev.filter(id => id !== unitId)
        : [...prev, unitId]
    )
  }

  function toggleAll() {
    const allIds = normalUnits.map(u => u.unit_id)
    const allSelected = allIds.every(id => selectedUnits.includes(id))
    setSelectedUnits(allSelected ? [] : allIds)
  }

  async function handleApproveDispatch() {
    if (selectedUnits.length === 0 || dispatching || isViewer) return
    setDispatching(true)
    try {
      await api.dispatch({
        incident_id:     incident.id,
        unit_ids:        selectedUnits,
        loadout_profile: data?.loadout_profile ?? 'initial_attack',
        route_id:        '',
      })
      setDispatched(true)

      // Record these unit IDs as dispatched so they're removed from the list
      setDispatchedUnitIds(prev => {
        const next = new Set(prev)
        selectedUnits.forEach(id => next.add(id))
        return next
      })

      // Notify parent with default loadouts so LeftSidebar hover shows STD correctly
      if (onConfirmLoadouts) {
        const dispatchedUnits = (data?.recommended_units ?? []).filter(u => selectedUnits.includes(u.unit_id))
        const defaultLoadouts = dispatchedUnits.map(u => ({
          unit_id:       u.unit_id,
          unit_type:     u.unit_type,
          designation:   u.designation,
          water_pct:     100,
          foam_pct:      0,
          retardant_pct: u.unit_type === 'air_tanker' ? 100 : 0,
          equipment:     [],
        }))
        if (defaultLoadouts.length > 0) onConfirmLoadouts(defaultLoadouts)
      }

      // Submit accepted feedback with actual units
      const recommended = (data?.recommended_units ?? []).map(u => u.unit_id)
      const isOverride = selectedUnits.some(id => !recommended.includes(id)) ||
                         recommended.some(id => !selectedUnits.includes(id))
      api.submitFeedback(incident.id, {
        outcome: isOverride ? 'overridden' : 'accepted',
        override_unit_ids: isOverride ? selectedUnits : [],
        confidence_reported: data?.summary?.confidence_score?.toString() ?? '',
      }).catch(() => {})  // fire-and-forget

      setSelectedUnits([])
      setFeedbackSent(true)
      toast(
        `${selectedUnits.length} unit${selectedUnits.length !== 1 ? 's' : ''} dispatched to ${incident.name}`,
        'success'
      )
      onDispatchSuccess?.()
      // Delay refresh so DB has time to update unit statuses.
      // dispatchedUnitIds filter handles immediate UI update in the meantime.
      setTimeout(() => fetchRecommendations(incident.id), 3000)
    } catch (e) {
      toast(e.message ?? 'Dispatch failed', 'error')
    } finally {
      setDispatching(false)
    }
  }

  const canApprove  = selectedUnits.length > 0 && !dispatching && !isViewer
  const allSelected = normalUnits.length > 0 &&
    normalUnits.every(u => selectedUnits.includes(u.unit_id))

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={S.root}>
      {/* Section header */}
      <div style={S.sectionLabel}>
        <span>DISPATCH INTELLIGENCE</span>
        <span style={S.badge('#ff4d1a')}>ENGINE</span>
      </div>

      {/* Loading */}
      {loading && (
        <>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </>
      )}

      {/* Error */}
      {!loading && error && (
        <div style={{
          fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#ef4444',
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
          borderRadius: '3px', padding: '10px',
        }}>
          {error}
        </div>
      )}

      {/* Results */}
      {!loading && data && (
        <>
          {/* Summary row */}
          {data.summary && (
            <div style={S.summaryRow}>
              <span>
                {normalUnits.length} unit{normalUnits.length !== 1 ? 's' : ''} remaining
                {(dispatchedUnitIds.size + alreadyAssignedIds.length) > 0 && (
                  <span style={{ color: '#22c55e', marginLeft: '6px' }}>
                    · {dispatchedUnitIds.size + alreadyAssignedIds.length} deployed
                  </span>
                )}
                {data.summary.shortages?.length > 0 && normalUnits.length > 0 && (
                  <span style={{ color: '#ef4444', marginLeft: '6px' }}>
                    · {data.summary.shortages.length} shortage{data.summary.shortages.length !== 1 ? 's' : ''}
                  </span>
                )}
              </span>
              {normalUnits.length > 0 && !isViewer && (
                <button style={S.selectAll} onClick={toggleAll}>
                  {allSelected ? 'Deselect all' : 'Select all'}
                </button>
              )}
            </div>
          )}

          {/* Confidence score bar */}
          {data.summary?.confidence_score != null && (
            <ConfidenceBar
              score={data.summary.confidence_score}
              label={data.summary.overall_risk}
            />
          )}

          {/* Route safety summary */}
          {routeSafety?.routes?.length > 0 && (
            <RouteSafetyPanel routes={routeSafety.routes} summary={routeSafety.summary} />
          )}

          {/* Unit rows */}
          {normalUnits.map(unit => (
            <UnitRow
              key={unit.unit_id}
              unit={unit}
              selected={selectedUnits.includes(unit.unit_id)}
              onToggle={isViewer ? () => {} : toggleUnit}
            />
          ))}

          {normalUnits.length === 0 && shortages.length === 0 && (
            <div style={{
              fontFamily: 'var(--font-sans)', fontSize: '12px',
              padding: '8px 0',
              color: (dispatchedUnitIds.size + alreadyAssignedIds.length) > 0 ? '#22c55e' : '#878787',
            }}>
              {(dispatchedUnitIds.size + alreadyAssignedIds.length) > 0
                ? '✓ All recommended units have been deployed.'
                : 'No units available for dispatch.'}
            </div>
          )}

          {/* Shortage entries */}
          {shortages.map((s, i) => (
            <ShortageRow key={`shortage-${i}`} entry={s} />
          ))}

          {/* Approve dispatch — only show if there are remaining units to dispatch */}
          {!isViewer && normalUnits.length > 0 && (
            <>
              {dispatched && (
                <div style={S.successBanner}>
                  ✓ UNITS DISPATCHED SUCCESSFULLY
                </div>
              )}
              <button
                style={S.approveBtn(canApprove)}
                disabled={!canApprove}
                onClick={() => {
                  if (onOpenLoadout) {
                    onOpenLoadout(selectedUnits)
                  } else {
                    handleApproveDispatch()
                  }
                }}
                className={canApprove ? 'pyra-btn-press' : ''}
              >
                {dispatching
                  ? 'DISPATCHING...'
                  : selectedUnits.length === 0
                    ? 'SELECT UNITS TO DISPATCH'
                    : `CONFIGURE LOADOUT & DISPATCH — ${selectedUnits.length} UNIT${selectedUnits.length !== 1 ? 'S' : ''}`
                }
              </button>
            </>
          )}

          {isViewer && (
            <div style={{
              fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#5a6878',
              textAlign: 'center', marginTop: '6px',
            }}>
              COMMANDER / DISPATCHER ROLE REQUIRED
            </div>
          )}
        </>
      )}
    </div>
  )
}