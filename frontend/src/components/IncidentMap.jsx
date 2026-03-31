import { useState, useEffect, useRef } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, Polyline, Marker, useMapEvents, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import SpreadRiskOverlay from './SpreadRiskOverlay'
import FireGrowthOverlay from './FireGrowthOverlay'
import EvacZonesOverlay from './EvacZonesOverlay'
import FirePerimetersOverlay from './FirePerimetersOverlay'
import RiskHeatmapOverlay from './RiskHeatmapOverlay'
import WaterSourcesOverlay from './WaterSourcesOverlay'
import { api, BASE_URL } from '../api/client'

const SEVERITY_COLOR = {
  critical: '#ef4444',
  high:     '#F56E0F',
  moderate: '#facc15',
  low:      '#4ade80',
}
const SEVERITY_RADIUS = {
  critical: 28, high: 20, moderate: 14, low: 9,
}
const UNIT_STATUS_COLOR = {
  available:      '#4ade80',
  en_route:       '#60a5fa',
  on_scene:       '#F56E0F',
  staging:        '#facc15',
  returning:      '#a78bfa',
  out_of_service: '#878787',
}
const UNIT_TYPE_SYMBOL = {
  engine: '🚒', hand_crew: '👥', dozer: '🚜', water_tender: '🚛',
  helicopter: '🚁', air_tanker: '✈️', command_unit: '📡', rescue: '🚑',
}
const GROUND_UNIT_TYPES = new Set(['engine', 'hand_crew', 'dozer', 'water_tender', 'command_unit', 'rescue'])

// Route status → line color
const ROUTE_STATUS_COLOR = {
  FASTEST: '#22c55e',
  CAUTION: '#eab308',
  AVOID:   '#ef4444',
}
const ROUTE_STATUS_GLOW = {
  FASTEST: '#14532d',
  CAUTION: '#713f12',
  AVOID:   '#7f1d1d',
}

function ZoomTracker({ onZoomChange }) {
  useMapEvents({ zoomend: (e) => onZoomChange(e.target.getZoom()) })
  return null
}

function MapController({ focusedUnit, focusedIncident, unitRoutes, selectedIncident, followUnit, followMode, fitAll, incidents }) {
  const map = useMap()

  useEffect(() => {
    if (!focusedUnit) return
    const lat = focusedUnit.latitude
    const lon = focusedUnit.longitude
    if (!isNaN(lat) && !isNaN(lon)) map.flyTo([lat, lon], 13, { duration: 1.2 })
  }, [focusedUnit])

  // Fly to incident when selected from command panel
  useEffect(() => {
    if (!focusedIncident) return
    map.flyTo([focusedIncident.latitude, focusedIncident.longitude], 12, { duration: 1.0 })
  }, [focusedIncident?._ts])

  useEffect(() => {
    if (!followMode || !followUnit) return
    const lat = followUnit.latitude
    const lon = followUnit.longitude
    if (!isNaN(lat) && !isNaN(lon)) map.panTo([lat, lon], { animate: true, duration: 0.5 })
  }, [followUnit?.latitude, followUnit?.longitude, followMode])

  useEffect(() => {
    if (!unitRoutes?.length) return
    const allCoords = unitRoutes.flatMap(r => r.coords ?? [])
    if (selectedIncident) allCoords.push([selectedIncident.latitude, selectedIncident.longitude])
    if (allCoords.length < 2) return
    const bounds = L.latLngBounds(allCoords)
    map.flyToBounds(bounds, { padding: [80, 80], duration: 1.2, maxZoom: 13 })
  }, [unitRoutes?.length])

  // Fit all incidents when command view opens
  useEffect(() => {
    if (!fitAll || !incidents?.length) return
    const coords = incidents.map(i => [i.latitude, i.longitude])
    if (coords.length < 2) return
    map.flyToBounds(L.latLngBounds(coords), { padding: [60, 60], duration: 1.2, maxZoom: 10 })
  }, [fitAll])

  return null
}

function createCallsignIcon(designation, color) {
  return L.divIcon({
    className: '',
    html: `<div style="font-family:Inter,sans-serif;font-weight:600;font-size:10px;color:${color};background:rgba(21,20,25,0.92);border:1px solid ${color};border-radius:2px;padding:1px 6px;white-space:nowrap;letter-spacing:0.02em;line-height:15px;pointer-events:none;transform:translateX(-50%);display:inline-block;">${designation}</div>`,
    iconSize: [0, 0], iconAnchor: [0, 28],
  })
}

export default function IncidentMap({
  incidents, selectedId, onSelect, mapView = 'live',
  focusedUnit, focusedIncident, unitRoutes = [], selectedIncident,
  showPerimeters = false, showHeatmap = false, showCommand = false, showSatellite = false,
  showFireGrowth = false,
  showEvacZones = false, evacZonesData = null, activeEvacZones = null,
  showWaterSources = false,
  onWaterSourceStatus = null,
  fireGrowthTimeMode = 'standard',
  units: unitsProp = [],
}) {
  const [units,        setUnits]        = useState(unitsProp)
  const [selectedUnit, setSelectedUnit] = useState(null)
  const [clickedRoute, setClickedRoute] = useState(null)
  const [zoomLevel,    setZoomLevel]    = useState(7)
  const [followMode,   setFollowMode]   = useState(false)

  const clickedRouteCache = useRef({})
  const posHistory        = useRef({})
  const [trailSnapshot, setTrailSnapshot] = useState({})
  const TRAIL_MAX         = 30

  // Smooth position interpolation
  const targetPositions  = useRef({})   // server-reported positions (targets)
  const smoothPositions  = useRef({})   // current interpolated display positions
  const [displayUnits, setDisplayUnits] = useState([])
  const animFrameRef     = useRef(null)
  const LERP_SPEED       = 0.12         // fraction to close per frame (~60fps → ~0.6s to arrive)

  const center     = [37.5, -119.5]
  const showLabels = zoomLevel >= 9
  const showFires  = mapView === 'live' || mapView === 'fires'
  const showUnits  = mapView === 'live' || mapView === 'units'

  // Snapshot of last-known positions for diff — avoids re-renders when nothing moved
  const prevPositions = useRef({})

  // Animation loop — runs at 60fps, lerps each unit toward its target
  useEffect(() => {
    function animate() {
      let dirty = false
      for (const [id, target] of Object.entries(targetPositions.current)) {
        const current = smoothPositions.current[id]
        if (!current) {
          smoothPositions.current[id] = { ...target }
          dirty = true
          continue
        }
        const dLat = target.lat - current.lat
        const dLon = target.lon - current.lon
        if (Math.abs(dLat) > 0.000001 || Math.abs(dLon) > 0.000001) {
          smoothPositions.current[id] = {
            lat: current.lat + dLat * LERP_SPEED,
            lon: current.lon + dLon * LERP_SPEED,
          }
          dirty = true
        }
      }
      if (dirty) {
        setDisplayUnits(prev => prev.map(u => {
          const pos = smoothPositions.current[u.id]
          if (!pos) return u
          return { ...u, latitude: pos.lat, longitude: pos.lon }
        }))
      }
      animFrameRef.current = requestAnimationFrame(animate)
    }
    animFrameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(animFrameRef.current)
  }, [])

  function recordPositions(unitList) {
    unitList.forEach(unit => {
      if (!['en_route', 'on_scene', 'returning'].includes(unit.status)) return
      const lat = unit.latitude
      const lon = unit.longitude
      if (isNaN(lat) || isNaN(lon)) return
      const hist = posHistory.current[unit.id] ?? []
      const last = hist[hist.length - 1]
      if (!last || Math.abs(last[0] - lat) > 0.00005 || Math.abs(last[1] - lon) > 0.00005) {
        posHistory.current[unit.id] = [...hist, [lat, lon]].slice(-TRAIL_MAX)
        setTrailSnapshot({ ...posHistory.current })
      }
    })
  }

  // Process units from parent prop — runs the same diff/interpolation logic
  // that the old polling useEffect used, just fed by App.jsx's poll instead
  // of a duplicate fetch here.
  useEffect(() => {
    const u = unitsProp
    if (!u || u.length === 0) return
    let positionChanged = false
    u.forEach(unit => {
      const lat = unit.latitude
      const lon = unit.longitude
      if (!isNaN(lat) && !isNaN(lon)) {
        targetPositions.current[unit.id] = { lat, lon }
        if (!smoothPositions.current[unit.id]) {
          smoothPositions.current[unit.id] = { lat, lon }
        }
        const prev = prevPositions.current[unit.id]
        if (!prev || Math.abs(prev.lat - lat) > 0.000005 || Math.abs(prev.lon - lon) > 0.000005) {
          prevPositions.current[unit.id] = { lat, lon }
          positionChanged = true
        }
      }
    })
    setUnits(u)
    if (positionChanged) {
      recordPositions(u)
      setDisplayUnits(u)
    }
  }, [unitsProp])

  // Fetch road route when user clicks an en-route unit
  useEffect(() => {
    setTrailSnapshot({ ...posHistory.current })
  }, [units])

  useEffect(() => {
    if (!selectedUnit) { setClickedRoute(null); return }
    const unit = units.find(u => u.id === selectedUnit)
    if (!unit || !['en_route', 'returning'].includes(unit.status) || !unit.assigned_incident_id) {
      setClickedRoute(null); return
    }

    const ulat = unit.latitude
    const ulon = unit.longitude
    if (isNaN(ulat) || isNaN(ulon)) { setClickedRoute(null); return }

    const isAir = new Set(['helicopter', 'air_tanker']).has(unit.unit_type)
    const token = localStorage.getItem('token') ?? ''

    if (unit.status === 'returning') {
      // Build a fresh route from current position to home station
      const destLat = unit.station_lat
      const destLon = unit.station_lon
      if (!destLat || !destLon) { setClickedRoute(null); return }

      if (isAir) {
        setClickedRoute({ type: 'air', coords: [[ulat, ulon], [destLat, destLon]] })
        return
      }

      fetch(`${BASE_URL}/api/units/${unit.id}/route`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ to_lat: destLat, to_lon: destLon }),
      }).then(r => r.json()).then(data => {
        const coords = Array.isArray(data.waypoints) && data.waypoints.length >= 2
          ? data.waypoints.map(([lat, lon]) => [lat, lon])
          : [[ulat, ulon], [destLat, destLon]]
        setClickedRoute({ type: data.is_road_routed ? 'ground' : 'ground', coords })
      }).catch(() => {
        setClickedRoute({ type: 'ground', coords: [[ulat, ulon], [destLat, destLon]] })
      })
      return
    }

    // en_route — route to incident
    const incident = incidents.find(i => i.id === unit.assigned_incident_id)
    if (!incident) { setClickedRoute(null); return }

    if (isAir) {
      setClickedRoute({ type: 'air', coords: [[ulat, ulon], [incident.latitude, incident.longitude]] })
      return
    }

    // FIX: include destination in key — old key caused wrong route to be drawn
    // when the same unit was selected for a different incident (cross-incident cache hit)
    const key = `${unit.id}-${Math.round(ulat * 100)}-${Math.round(ulon * 100)}-${Math.round(incident.latitude * 100)}-${Math.round(incident.longitude * 100)}`
    if (clickedRouteCache.current[key]) {
      setClickedRoute({ type: 'ground', coords: clickedRouteCache.current[key] }); return
    }

    fetch(`${BASE_URL}/api/units/${unit.id}/route`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ to_lat: incident.latitude, to_lon: incident.longitude }),
    }).then(r => r.json()).then(data => {
      const coords = Array.isArray(data.waypoints) ? data.waypoints.map(([lat, lon]) => [lat, lon]) : []
      const type = data.is_road_routed ? 'ground' : (isAir ? 'air' : 'ground')
      if (coords.length) {
        clickedRouteCache.current[key] = coords
        setClickedRoute({ type, coords })
      } else {
        setClickedRoute({ type: 'ground', coords: [[ulat, ulon], [incident.latitude, incident.longitude]] })
      }
    }).catch(() => {
      setClickedRoute({ type: 'ground', coords: [[ulat, ulon], [incident.latitude, incident.longitude]] })
    })
  }, [selectedUnit, units, incidents])

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <MapContainer center={center} zoom={7} style={{ width: '100%', height: '100%' }} zoomControl={true}>
        {showSatellite ? (
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution="Tiles &copy; Esri"
            className="satellite-layer"
          />
        ) : (
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; OpenStreetMap' />
        )}
        <ZoomTracker onZoomChange={setZoomLevel} />
        <MapController
          focusedUnit={focusedUnit}
          focusedIncident={focusedIncident}
          unitRoutes={unitRoutes}
          selectedIncident={selectedIncident}
          followUnit={units.find(u => u.id === selectedUnit)}
          followMode={followMode}
          fitAll={showCommand}
          incidents={incidents}
        />

        {showFires && <SpreadRiskOverlay incidents={incidents} selectedId={selectedId} />}

        {/* Real NIFC fire perimeters */}
        <FirePerimetersOverlay visible={showPerimeters} />
        <FireGrowthOverlay incidents={incidents} selectedId={selectedId} visible={showFireGrowth} timeMode={fireGrowthTimeMode} />
        <EvacZonesOverlay visible={showEvacZones} data={evacZonesData} activeZones={activeEvacZones} />

        {/* Water sources overlay */}
        <WaterSourcesOverlay selectedIncident={selectedIncident} visible={showWaterSources} onStatusChange={onWaterSourceStatus} />

        {/* Predictive risk heatmap */}
        <RiskHeatmapOverlay visible={showHeatmap} />

        {/* Per-unit computed routes */}
        {unitRoutes.map(ur => {
          const lineColor = ur.statusColor ?? ROUTE_STATUS_COLOR[ur.status] ?? '#22c55e'
          const glowColor = ROUTE_STATUS_GLOW[ur.status] ?? '#14532d'
          if (!ur.coords || ur.coords.length < 2) return null
          return (
            <div key={ur.unitId}>
              {/* White outline for contrast against map */}
              <Polyline
                positions={ur.coords}
                pathOptions={{
                  color: '#ffffff', weight: ur.isAir ? 4 : 8,
                  opacity: 0.6,
                  dashArray: ur.isAir ? '6 5' : undefined,
                }}
              />
              {/* Main colored line */}
              <Polyline
                positions={ur.coords}
                pathOptions={{
                  color:     lineColor,
                  weight:    ur.isAir ? 2 : 5,
                  opacity:   1,
                  dashArray: ur.isAir ? '6 5' : undefined,
                }}
              />
            </div>
          )
        })}

        {/* En-route / returning unit path when clicking a unit on map */}
        {clickedRoute && clickedRoute.coords?.length >= 2 && (() => {
          const unit = units.find(u => u.id === selectedUnit)
          const lineColor = unit?.status === 'returning' ? '#a78bfa' : '#60a5fa'
          return (
            <Polyline
              positions={clickedRoute.coords}
              pathOptions={{
                color:     lineColor,
                weight:    clickedRoute.type === 'air' ? 2 : 3,
                dashArray: '8 5',
                opacity:   0.85,
              }}
            />
          )
        })()}

        {/* Position history trails — en_route only, returning units don't need a trail */}
        {showUnits && units.filter(u => u.status === 'en_route').map(unit => {
          const trail = trailSnapshot[unit.id] ?? []
          if (trail.length < 2) return null
          return (
            <Polyline
              key={`trail-${unit.id}`}
              positions={trail}
              pathOptions={{ color: '#60a5fa', weight: 2, opacity: 0.3, dashArray: '4 4' }}
            />
          )
        })}

        {showUnits && displayUnits.map(unit => {
          const lat = unit.latitude
          const lon = unit.longitude
          if (isNaN(lat) || isNaN(lon)) return null
          const color      = UNIT_STATUS_COLOR[unit.status] ?? '#3a4558'
          const isSelected = unit.id === selectedUnit
          return (
            <div key={unit.id}>
              {showLabels && (
                <Marker position={[lat, lon]} icon={createCallsignIcon(unit.designation, color)} interactive={false} zIndexOffset={-100} />
              )}
              <CircleMarker
                center={[lat, lon]}
                radius={isSelected ? 10 : 6}
                pathOptions={{
                  color: isSelected ? '#ffffff' : color,
                  fillColor: color,
                  fillOpacity: isSelected ? 1 : 0.85,
                  weight: isSelected ? 2.5 : 1.5,
                }}
                eventHandlers={{ click: (e) => {
                  e.originalEvent.stopPropagation()
                  const newSel = selectedUnit === unit.id ? null : unit.id
                  setSelectedUnit(newSel)
                  if (!newSel) setFollowMode(false)
                }}}
              >
                <Tooltip direction="top" offset={[0, -8]}>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', lineHeight: 1.5 }}>
                    <div style={{ fontWeight: 700, marginBottom: '2px', color }}>{UNIT_TYPE_SYMBOL[unit.unit_type]} {unit.designation}</div>
                    <div style={{ color, fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.06em' }}>{unit.status.replace(/_/g, ' ').toUpperCase()}</div>
                    {unit.status === 'returning' && <div style={{ color: '#5a6878', fontSize: '10px' }}>← RTB to station</div>}
                    {unit.assigned_incident_id && unit.status !== 'returning' && (
                      <div style={{ color: '#5a6878', fontSize: '10px' }}>
                        → {incidents.find(i => i.id === unit.assigned_incident_id)?.name ?? unit.assigned_incident_id}
                      </div>
                    )}
                  </div>
                </Tooltip>
              </CircleMarker>
            </div>
          )
        })}

        {showFires && incidents.map(inc => {
          const FIRE_COLORS = {
            critical: { core: '#ff2200', mid: '#ff6600', outer: '#ff440020', ring: '#ef4444' },
            high:     { core: '#ff4d1a', mid: '#f59e0b', outer: '#f59e0b15', ring: '#f59e0b' },
            moderate: { core: '#f59e0b', mid: '#fbbf24', outer: '#fbbf2412', ring: '#fbbf24' },
            low:      { core: '#22c55e', mid: '#4ade80', outer: '#22c55e10', ring: '#22c55e' },
          }
          const fc = FIRE_COLORS[inc.severity] ?? FIRE_COLORS.low
          const sz = { critical: 48, high: 38, moderate: 28, low: 20 }[inc.severity] ?? 22
          const selected = inc.id === selectedId
          const anim = inc.severity === 'critical'
            ? 'fire-ring-critical 1.8s ease-in-out infinite'
            : inc.severity === 'high'
            ? 'fire-ring-high 2.5s ease-in-out infinite'
            : 'none'

          const icon = L.divIcon({
            className: '',
            html: `
              <div style="position:relative;width:${sz}px;height:${sz}px;transform:translate(-50%,-50%)">
                <!-- Outer glow ring -->
                <div style="
                  position:absolute;inset:0;border-radius:50%;
                  background:radial-gradient(circle, ${fc.mid}30 0%, ${fc.outer} 60%, transparent 100%);
                  animation:${anim};
                "></div>
                <!-- Mid ring -->
                <div style="
                  position:absolute;inset:${sz*0.18}px;border-radius:50%;
                  background:radial-gradient(circle, ${fc.mid}60 0%, ${fc.mid}20 70%, transparent 100%);
                  border:1px solid ${fc.ring}40;
                "></div>
                <!-- Core -->
                <div style="
                  position:absolute;inset:${sz*0.35}px;border-radius:50%;
                  background:radial-gradient(circle, #fff 0%, ${fc.core} 50%, ${fc.mid} 100%);
                  box-shadow:0 0 ${sz*0.6}px ${fc.core}, 0 0 ${sz*0.3}px ${fc.mid};
                "></div>
                ${selected ? `
                <!-- Selected ring -->
                <div style="
                  position:absolute;inset:-6px;border-radius:50%;
                  border:2px solid rgba(255,255,255,0.6);
                  box-shadow:0 0 12px rgba(255,255,255,0.2);
                "></div>` : ''}
              </div>`,
            iconSize: [0, 0],
            iconAnchor: [0, 0],
          })

          return (
            <Marker
              key={inc.id}
              position={[inc.latitude, inc.longitude]}
              icon={icon}
              eventHandlers={{ click: (e) => { e.originalEvent.stopPropagation(); setSelectedUnit(null); onSelect(inc.id) } }}
              zIndexOffset={selected ? 1000 : 0}
            >
              <Tooltip direction="top" offset={[0, -sz/2]}>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', lineHeight: 1.5 }}>
                  <div style={{ fontWeight: 700, marginBottom: '3px', color: fc.core }}>{inc.name}</div>
                  <div>{inc.acres_burned?.toLocaleString()} ac · <span style={{ color: fc.ring }}>{inc.severity?.toUpperCase()}</span></div>
                  <div style={{ color: '#5a6878' }}>Wind: {inc.wind_speed_mph} mph · RH: {inc.humidity_percent}%</div>
                  <div>Containment: <span style={{ color: inc.containment_percent > 50 ? '#22c55e' : fc.core }}>{inc.containment_percent}%</span></div>
                </div>
              </Tooltip>
            </Marker>
          )
        })}

        {/* Follow mode button */}
        {selectedUnit && (
          <div style={{ position: 'absolute', bottom: '28px', right: '14px', zIndex: 1000 }}>
            <button
              onClick={() => setFollowMode(v => !v)}
              style={{
                background: followMode ? 'rgba(56,189,248,0.12)' : 'rgba(13,15,17,0.9)',
                border: `1px solid ${followMode ? 'rgba(56,189,248,0.4)' : 'rgba(255,255,255,0.1)'}`,
                borderRadius: '6px', padding: '7px 14px', cursor: 'pointer',
                fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '10px',
                color: followMode ? '#38bdf8' : '#5a6878',
                letterSpacing: '0.08em', display: 'flex', alignItems: 'center', gap: '7px',
                transition: 'all 0.15s', backdropFilter: 'blur(12px)',
                boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
              }}
            >
              <div style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: followMode ? '#38bdf8' : '#3a4558',
                boxShadow: followMode ? '0 0 8px #38bdf8' : 'none',
                animation: followMode ? 'status-blink 1.5s ease-in-out infinite' : 'none',
              }} />
              {followMode ? 'TRACKING' : 'TRACK UNIT'}
            </button>
          </div>
        )}

        {/* Map Legend */}
        <div style={{
          position: 'absolute', bottom: '28px', left: '14px', zIndex: 1000,
          background: 'rgba(13,15,17,0.88)', border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: '8px', padding: '10px 12px',
          display: 'flex', flexDirection: 'column', gap: '5px', pointerEvents: 'none',
          backdropFilter: 'blur(12px)',
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        }}>
          {showFires && (
            <>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '8px', color: '#3a4558', letterSpacing: '0.12em', marginBottom: '2px' }}>FIRE SEVERITY</div>
              {[
                { sev: 'critical', color: '#ef4444' },
                { sev: 'high',     color: '#ff4d1a' },
                { sev: 'moderate', color: '#f59e0b' },
                { sev: 'low',      color: '#22c55e' },
              ].map(({ sev, color }) => (
                <div key={sev} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: color, boxShadow: `0 0 5px ${color}60` }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#5a6878', letterSpacing: '0.06em' }}>{sev.toUpperCase()}</span>
                </div>
              ))}
            </>
          )}
          {showFires && showUnits && <div style={{ height: '1px', background: 'rgba(255,255,255,0.06)', margin: '3px 0' }} />}
          {showUnits && (
            <>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '8px', color: '#3a4558', letterSpacing: '0.12em', marginBottom: '2px' }}>UNIT STATUS</div>
              {[
                { status: 'available',      color: '#22c55e' },
                { status: 'en route',       color: '#38bdf8' },
                { status: 'on scene',       color: '#ff4d1a' },
                { status: 'staging',        color: '#facc15' },
                { status: 'returning',      color: '#a78bfa' },
              ].map(({ status, color }) => (
                <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: color }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#5a6878', letterSpacing: '0.06em' }}>{status.toUpperCase()}</span>
                </div>
              ))}
            </>
          )}
          {unitRoutes.length > 0 && (
            <>
              <div style={{ height: '1px', background: 'rgba(255,255,255,0.06)', margin: '3px 0' }} />
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '8px', color: '#3a4558', letterSpacing: '0.12em', marginBottom: '2px' }}>ROUTES</div>
              {[{ status: 'FASTEST', color: '#22c55e' }, { status: 'CAUTION', color: '#eab308' }, { status: 'AVOID', color: '#ef4444' }].map(({ status, color }) => (
                <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '14px', height: '2px', background: color, borderRadius: '1px' }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#5a6878', letterSpacing: '0.06em' }}>{status}</span>
                </div>
              ))}
            </>
          )}
          {!showLabels && showUnits && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: '#3a4558', marginTop: '2px' }}>Zoom in for callsigns</div>
          )}
        </div>
      </MapContainer>
    </div>
  )
}