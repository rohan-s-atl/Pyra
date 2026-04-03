import { useEffect, useRef, useState } from 'react'
import { Polygon, Tooltip, Marker, useMap } from 'react-leaflet'
import L from 'leaflet'
import { api } from '../api/client'

const HORIZON_STYLE = {
  1:  { color: '#facc15', label: '+1 HR',  desc: 'Near-term' },
  4:  { color: '#F56E0F', label: '+4 HR',  desc: 'Mid-term'  },
  12: { color: '#ef4444', label: '+12 HR', desc: 'Extended'  },
}

const SHORT_HORIZON_STYLE = {
  15: { color: '#4ade80', label: '+15 MIN', desc: 'Immediate' },
  30: { color: '#facc15', label: '+30 MIN', desc: 'Short-term' },
  60: { color: '#F56E0F', label: '+60 MIN', desc: 'Near-term'  },
}

// ── Timeline legend panel (fixed top-right of map) ────────────────────────
export function FireGrowthLegend({ data, visible, onClose, timeMode, onTimeModeChange, topOffset = 86, rightOffset = 12 }) {
  if (!visible || !data) return null

  const wind = data.wind_speed_mph ?? 0
  const rh   = data.humidity_percent ?? 0
  const ros  = data.ros_mph ?? 0

  const isShort = timeMode === 'short'

  return (
    <div className="ui-shell-panel ui-float-soft-delayed" style={{
      position: 'absolute', top: `${topOffset}px`, right: `${rightOffset}px`, zIndex: 1450,
      maxHeight: 'calc(50vh - 24px)', overflowY: 'auto',
      background: 'rgba(22,28,38,0.96)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '16px', padding: '12px 14px', minWidth: '220px',
      backdropFilter: 'blur(14px)', boxShadow: '0 18px 40px rgba(0,0,0,0.45)',
      pointerEvents: 'auto',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
        <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#F56E0F', letterSpacing: '0.06em' }}>
          ⬡ FIRE GROWTH PROJECTION
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#878787', cursor: 'pointer', fontSize: '12px', padding: '0 0 0 8px' }}>✕</button>
      </div>

      {/* Time mode toggle */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '10px' }}>
        {[
          { key: 'standard', label: '1/4/12 HR' },
          { key: 'short',    label: '15/30/60 MIN' },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onTimeModeChange?.(key)}
            style={{
              flex: 1, padding: '4px 0', fontSize: '9px', fontFamily: 'Inter, sans-serif',
              fontWeight: 700, letterSpacing: '0.04em', cursor: 'pointer', borderRadius: '3px',
              border: timeMode === key ? '1px solid #F56E0F' : '1px solid rgba(255,255,255,0.1)',
              background: timeMode === key ? 'rgba(245,110,15,0.18)' : 'rgba(255,255,255,0.05)',
              color: timeMode === key ? '#F56E0F' : '#878787',
              transition: 'all 0.15s',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Incident name */}
      <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#FBFBFB', fontWeight: 600, marginBottom: '6px' }}>
        {data.incident_name}
      </div>

      {/* Conditions row */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '8px' }}>
        <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
          ROS <span style={{ color: '#FBFBFB', fontWeight: 700 }}>{ros} mph</span>
        </div>
        <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
          Wind <span style={{ color: '#FBFBFB', fontWeight: 700 }}>{wind} mph</span>
        </div>
        <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
          RH <span style={{ color: '#FBFBFB', fontWeight: 700 }}>{rh}%</span>
        </div>
      </div>

      {/* Projection rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
        {/* Current */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ width: '28px', height: '3px', background: '#4ade80', borderRadius: '2px', flexShrink: 0 }} />
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#4ade80', fontWeight: 700, width: '60px' }}>NOW</div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB' }}>
            {(data.current_acres || 0).toLocaleString()} ac
          </div>
        </div>

        {(data.projections ?? []).map(p => {
          const hrs  = p.properties.hours
          const mins = Math.round(hrs * 60)
          const style = isShort
            ? (SHORT_HORIZON_STYLE[mins] ?? { color: '#ef4444', label: `+${mins}MIN` })
            : (HORIZON_STYLE[hrs]        ?? { color: '#ef4444', label: `+${hrs}HR`  })
          return (
            <div key={`${hrs}-${mins}`} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                width: '28px', height: '3px', flexShrink: 0,
                background: style.color, borderRadius: '2px',
                opacity: 0.9,
              }} />
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: style.color, fontWeight: 700, width: '60px' }}>{style.label}</div>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB' }}>
                ~{(p.properties.projected_acres || 0).toLocaleString()} ac
              </div>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787', marginLeft: 'auto' }}>
                {p.properties.forward_km.toFixed(1)} km fwd
              </div>
            </div>
          )
        })}
      </div>

      {/* Wind shift warning */}
      {data.wind_shift_risk && (
        <div style={{
          background: 'rgba(239,68,68,0.12)', border: '1px solid #ef444455',
          borderRadius: '3px', padding: '5px 8px',
          fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#ef4444',
        }}>
          ⚠ High wind + critically low humidity — wind shift risk
        </div>
      )}

      {/* Direction */}
      <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#555', marginTop: '6px' }}>
        Primary spread: {data.spread_direction ?? '—'} · Rothermel simplified model
      </div>
    </div>
  )
}

// ── Map overlay polygons ───────────────────────────────────────────────────
export default function FireGrowthOverlay({ incidents, selectedId, visible, timeMode = 'standard' }) {
  const [growthData, setGrowthData] = useState({})  // `${incidentId}-${timeMode}` → response
  const fetchedKeys = useRef(new Set())
  const incidentInputsKey = incidents.map(incident => [
    incident.id,
    incident.fire_type,
    incident.wind_speed_mph,
    incident.humidity_percent,
    incident.slope_percent,
    incident.spread_risk,
    incident.aqi,
    incident.spread_direction,
    incident.acres_burned,
  ].join(':')).join('|')

  useEffect(() => {
    if (!visible) return

    const targetIds = selectedId
      ? [selectedId]
      : incidents.map(i => i.id)

    const needed = targetIds.filter(id => !fetchedKeys.current.has(`${id}-${timeMode}`))
    if (needed.length === 0) return

    async function fetchAll() {
      const results = {}
      for (const id of needed) {
        try {
          // For short mode, fetch all three short horizons (15, 30, 60 min) and merge projections
          if (timeMode === 'short') {
            const [r15, r30, r60] = await Promise.all([
              api.fireGrowth(id, 15),
              api.fireGrowth(id, 30),
              api.fireGrowth(id, 60),
            ])
            // Merge all projections into one response object
            results[`${id}-short`] = {
              ...r60,
              projections: [
                ...(r15.projections ?? []),
                ...(r30.projections ?? []),
                ...(r60.projections ?? []),
              ],
            }
          } else {
            results[`${id}-standard`] = await api.fireGrowth(id)
          }
          fetchedKeys.current.add(`${id}-${timeMode}`)
        } catch (e) {
          console.warn(`[FireGrowth] failed for ${id} (${timeMode}):`, e)
        }
      }
      setGrowthData(prev => ({ ...prev, ...results }))
    }
    fetchAll()
  }, [visible, selectedId, incidents, timeMode])

  // Invalidate the fetch cache when incident data or mode changes so stale
  // projections are re-fetched, but keep growthData in state so existing
  // polygons stay visible on the map while the new fetch is in progress.
  useEffect(() => {
    fetchedKeys.current.clear()
  }, [selectedId, timeMode, incidentInputsKey])

  if (!visible) return null

  const displayIds = selectedId ? [selectedId] : incidents.map(i => i.id)

  return (
    <>
      {displayIds.map(incidentId => {
        const key    = `${incidentId}-${timeMode}`
        const altKey = `${incidentId}-${timeMode === 'short' ? 'standard' : 'short'}`
        // Fall back to the other mode's cached data while the preferred fetch is in-flight
        const data = growthData[key] ?? growthData[altKey]
        if (!data?.projections) return null

        return [...data.projections].reverse().map(feature => {
          const hrs    = feature.properties.hours
          const mins   = Math.round(hrs * 60)
          const style  = timeMode === 'short'
            ? (SHORT_HORIZON_STYLE[mins] ?? { color: '#ef4444', label: `+${mins}MIN` })
            : (HORIZON_STYLE[hrs]        ?? { color: '#ef4444', label: `+${hrs}HR`  })
          const coords = feature.geometry.coordinates[0]
          if (!coords?.length) return null

          const positions = coords.map(([lon, lat]) => [lat, lon])

          return (
            <Polygon
              key={`${incidentId}-${hrs}-${timeMode}`}
              positions={positions}
              pathOptions={{
                color:       style.color,
                fillColor:   style.color,
                fillOpacity: feature.properties.fill_opacity ?? 0.2,
                weight:      timeMode === 'short' ? (mins === 15 ? 2 : 1.5) : (hrs === 1 ? 2 : 1.5),
                dashArray:   timeMode === 'short' ? null : (hrs === 12 ? '8 5' : hrs === 4 ? '5 3' : null),
                opacity:     0.85,
              }}
            >
              <Tooltip sticky direction="top" className="pyra-tooltip">
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', minWidth: '170px', padding: '14px 16px', color: '#d4dce8', lineHeight: 1.45 }}>
                  <div style={{ fontWeight: 700, color: style.color, marginBottom: '6px', letterSpacing: '0.03em' }}>
                    {style.label} PROJECTION
                  </div>
                  <div style={{ color: '#d4dce8' }}>~{(feature.properties.projected_acres || 0).toLocaleString()} acres</div>
                  <div style={{ color: '#a7b5c7', fontSize: '11px', marginTop: '4px' }}>
                    {feature.properties.forward_km.toFixed(1)} km forward spread
                  </div>
                  <div style={{ color: '#a7b5c7', fontSize: '11px' }}>
                    ROS: {feature.properties.ros_mph} mph
                  </div>
                  {data.wind_shift_risk && hrs >= 4 && (
                    <div style={{ color: '#ef4444', fontSize: '10px', marginTop: '5px' }}>
                      ⚠ Wind shift may alter direction
                    </div>
                  )}
                </div>
              </Tooltip>
            </Polygon>
          )
        })
      })}
    </>
  )
}
