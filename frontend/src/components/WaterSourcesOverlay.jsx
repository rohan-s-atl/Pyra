import { Fragment, useEffect, useState, useRef } from 'react'
import { CircleMarker, Tooltip } from 'react-leaflet'
import { BASE_URL } from '../api/client'

const SOURCE_CONFIG = {
  hydrant:    { color: '#60a5fa', radius: 7,  icon: '💧', label: 'Fire Hydrant'    },
  lake:       { color: '#38bdf8', radius: 10, icon: '🏞',  label: 'Lake'            },
  pond:       { color: '#38bdf8', radius: 8,  icon: '🏞',  label: 'Pond'            },
  river:      { color: '#22d3ee', radius: 8,  icon: '〰️', label: 'River / Canal'   },
  reservoir:  { color: '#818cf8', radius: 9,  icon: '🛡',  label: 'Reservoir'       },
  tank:       { color: '#a78bfa', radius: 8,  icon: '🛢',  label: 'Water Tank'      },
  unknown:    { color: '#6b7280', radius: 6,  icon: '💧', label: 'Water Source'    },
}

function getSourceConfig(type) {
  return SOURCE_CONFIG[type] ?? SOURCE_CONFIG.unknown
}

export function WaterSourceLegend({ visible, summary }) {
  if (!visible) return null
  return (
    <div style={{
      position: 'absolute', bottom: '24px', right: '48px', zIndex: 1000,
      background: 'rgba(22,28,38,0.94)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '14px', padding: '10px 12px', minWidth: '160px',
      pointerEvents: 'none',
      fontFamily: 'Inter, sans-serif',
      backdropFilter: 'blur(14px)',
      boxShadow: '0 16px 36px rgba(0,0,0,0.4)',
    }}>
      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#878787', letterSpacing: '0.06em', marginBottom: '5px' }}>
        WATER SOURCES
      </div>
      {Object.entries(SOURCE_CONFIG).filter(([k]) => k !== 'unknown').map(([type, cfg]) => (
        <div key={type} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
          <div style={{
            width: '8px', height: '8px', borderRadius: '50%',
            background: cfg.color, flexShrink: 0,
          }} />
          <span style={{ fontSize: '10px', color: '#FBFBFB' }}>{cfg.label}</span>
        </div>
      ))}
      {summary && (
        <div style={{ marginTop: '5px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '5px', fontSize: '9px', color: '#878787' }}>
          {summary.total_sources} sources · {summary.hydrants} hydrants
        </div>
      )}
    </div>
  )
}


export default function WaterSourcesOverlay({ selectedIncident, visible, onStatusChange }) {
  const [sources,     setSources]     = useState([])
  const [assignments, setAssignments] = useState({})
  const [summary,     setSummary]     = useState(null)
  const [loading,     setLoading]     = useState(false)
  const [noResults,   setNoResults]   = useState(false)
  const fetchedId = useRef(null)

  // Single effect handles both fetch and reset — avoids race between two effects
  useEffect(() => {
    if (!visible || !selectedIncident?.id) {
      setSources([])
      setAssignments({})
      setSummary(null)
      setLoading(false)
      setNoResults(false)
      fetchedId.current = null
      return
    }

    // Already fetched for this incident — don't re-fetch
    if (fetchedId.current === selectedIncident.id) return
    fetchedId.current = selectedIncident.id

    // Clear stale data from previous incident immediately
    setSources([])
    setAssignments({})
    setSummary(null)
    setNoResults(false)
    setLoading(true)
    onStatusChange?.({ loading: true, noResults: false, count: 0 })

    const token = (() => { try { return localStorage.getItem('token') ?? '' } catch { return '' } })()
    const incidentId = selectedIncident.id   // capture before async

    fetch(`${BASE_URL}/api/water-sources/?incident_id=${incidentId}&radius_m=8000`, {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => {
        // Guard: discard result if user switched incident while fetching
        if (fetchedId.current !== incidentId) return

        const features = data?.sources?.features ?? []
        setSources(features)
        setNoResults(features.length === 0)
        onStatusChange?.({ loading: false, noResults: features.length === 0, count: features.length })

        const map = {}
        for (const a of data?.unit_assignments ?? []) {
          if (!map[a.source_id]) map[a.source_id] = []
          map[a.source_id].push(a)
        }
        setAssignments(map)
        setSummary(data?.summary ?? null)
      })
      .catch(err => {
        if (fetchedId.current !== incidentId) return
        console.warn('[WaterSources] fetch failed:', err)
        setNoResults(true)
      })
      .finally(() => {
        if (fetchedId.current === incidentId) setLoading(false)
      })
  }, [visible, selectedIncident?.id])

  if (!visible) return null
  if (sources.length === 0) return null

  return (
    <>
      {sources.map(feature => {
        const { id, type, name, fill_rate_gpm, distance_from_incident_km, osm_type } =
          feature.properties ?? {}
        const [lon, lat] = feature.geometry?.coordinates ?? []
        if (!lat || !lon) return null

        const cfg = getSourceConfig(type)
        const assigned = assignments[id] ?? []

        return (
          <Fragment key={id}>
            <CircleMarker
              center={[lat, lon]}
              radius={cfg.radius + (assigned.length > 0 ? 8 : 6)}
              pathOptions={{
                color: 'transparent',
                fillColor: cfg.color,
                fillOpacity: assigned.length > 0 ? 0.16 : 0.1,
                weight: 0,
                opacity: 0,
              }}
            />
            <CircleMarker
              key={id}
              center={[lat, lon]}
              radius={cfg.radius}
              pathOptions={{
                color:       assigned.length > 0 ? '#f8fbff' : `${cfg.color}dd`,
                fillColor:   cfg.color,
                fillOpacity: 0.92,
                weight:      assigned.length > 0 ? 2.5 : 1.8,
                dashArray:   assigned.length > 0 ? null : '3 2',
                opacity:     1,
              }}
            >
            <Tooltip direction="top" sticky className="pyra-tooltip">
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', minWidth: '180px', padding: '14px 16px', color: '#d4dce8', lineHeight: 1.45 }}>
                <div style={{ fontWeight: 700, color: cfg.color, marginBottom: '3px', display: 'flex', alignItems: 'center', gap: '5px' }}>
                  {cfg.icon} {cfg.label}
                  {osm_type && osm_type !== 'node' && (
                    <span style={{ fontSize: '9px', color: '#a7b5c7', fontWeight: 400, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '999px', padding: '2px 6px' }}>
                      OSM {osm_type}
                    </span>
                  )}
                </div>
                <div style={{ color: '#FBFBFB', marginBottom: '2px', fontWeight: 600 }}>{name}</div>
                <div style={{ color: '#a7b5c7', fontSize: '11px' }}>
                  {distance_from_incident_km != null
                    ? `${distance_from_incident_km.toFixed(1)} km from incident`
                    : '—'}
                </div>
                <div style={{ color: '#a7b5c7', fontSize: '11px' }}>
                  Fill rate: <span style={{ color: '#60a5fa' }}>{fill_rate_gpm} gal/min</span>
                </div>
                {assigned.length > 0 && (
                  <div style={{ marginTop: '5px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '5px' }}>
                    <div style={{ fontSize: '10px', color: '#60a5fa', fontWeight: 600, marginBottom: '3px' }}>
                      ASSIGNED UNITS
                    </div>
                    {assigned.map(a => (
                      <div key={a.unit_id} style={{ fontSize: '10px', color: '#FBFBFB', marginBottom: '2px' }}>
                        {a.designation} ({a.unit_type})
                        {a.road_distance_km != null && (
                          <span style={{ color: '#a7b5c7' }}> · {a.road_distance_km.toFixed(1)} km</span>
                        )}
                        {a.fill_time_minutes != null && (
                          <span style={{ color: '#a78bfa' }}> · {a.fill_time_minutes}min fill</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Tooltip>
          </CircleMarker>
          </Fragment>
        )
      })}
    </>
  )
}
