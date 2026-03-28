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
import { api } from '../api/client'

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
}) {
  const [units,        setUnits]        = useState([])
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

  useEffect(() => {
    function handleUnits(u) {
      setUnits(u)
      recordPositions(u)
      // Update interpolation targets for moving units
      u.forEach(unit => {
        const lat = unit.latitude
        const lon = unit.longitude
        if (!isNaN(lat) && !isNaN(lon)) {
          targetPositions.current[unit.id] = { lat, lon }
          // Snap immediately if no current smooth position yet
          if (!smoothPositions.current[unit.id]) {
            smoothPositions.current[unit.id] = { lat, lon }
          }
        }
      })
      setDisplayUnits(u)
    }
    api.units().then(handleUnits).catch(() => {})
    const interval = setInterval(() => api.units().then(handleUnits).catch(() => {}), 1000)
    return () => clearInterval(interval)
  }, [])

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

      fetch(`/api/units/${unit.id}/route`, {
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

    const key = `${unit.id}-${Math.round(ulat * 100)}-${Math.round(ulon * 100)}`
    if (clickedRouteCache.current[key]) {
      setClickedRoute({ type: 'ground', coords: clickedRouteCache.current[key] }); return
    }

    fetch(`/api/units/${unit.id}/route`, {
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
          const color      = UNIT_STATUS_COLOR[unit.status] ?? '#878787'
          const isSelected = unit.id === selectedUnit
          return (
            <div key={unit.id}>
              {showLabels && (
                <Marker position={[lat, lon]} icon={createCallsignIcon(unit.designation, color)} interactive={false} zIndexOffset={-100} />
              )}
              <CircleMarker
                center={[lat, lon]}
                radius={isSelected ? 9 : 6}
                pathOptions={{ color: isSelected ? '#ffffff' : color, fillColor: color, fillOpacity: 0.9, weight: isSelected ? 2 : 1.5 }}
                eventHandlers={{ click: (e) => {
                  e.originalEvent.stopPropagation()
                  const newSel = selectedUnit === unit.id ? null : unit.id
                  setSelectedUnit(newSel)
                  if (!newSel) setFollowMode(false)
                }}}
              >
                <Tooltip direction="top" offset={[0, -8]}>
                  <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px' }}>
                    <div style={{ fontWeight: 700, marginBottom: '2px' }}>{UNIT_TYPE_SYMBOL[unit.unit_type]} {unit.designation}</div>
                    <div style={{ color }}>{unit.status.replace(/_/g, ' ').toUpperCase()}</div>
                    {unit.status === 'returning' && <div style={{ color: '#878787', fontSize: '10px' }}>← Returning to station</div>}
                    {unit.assigned_incident_id && unit.status !== 'returning' && (
                      <div style={{ color: '#878787', fontSize: '10px' }}>
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
          const color    = SEVERITY_COLOR[inc.severity] ?? '#888'
          const radius   = SEVERITY_RADIUS[inc.severity] ?? 10
          const selected = inc.id === selectedId
          return (
            <CircleMarker
              key={inc.id}
              center={[inc.latitude, inc.longitude]}
              radius={selected ? radius + 8 : radius}
              pathOptions={{ color: selected ? '#ffffff' : color, fillColor: color, fillOpacity: 0.85, weight: selected ? 3 : 1.5 }}
              eventHandlers={{ click: (e) => { e.originalEvent.stopPropagation(); setSelectedUnit(null); onSelect(inc.id) } }}
            >
              <Tooltip direction="top" offset={[0, -radius]}>
                <div>
                  <div style={{ fontWeight: 'bold', marginBottom: '2px' }}>{inc.name}</div>
                  <div>{inc.acres_burned?.toLocaleString()} ac · {inc.severity.toUpperCase()}</div>
                  <div>Spread: {inc.spread_risk?.toUpperCase()} → {inc.spread_direction ?? '—'}</div>
                  <div>Wind: {inc.wind_speed_mph} mph · Humidity: {inc.humidity_percent}%</div>
                  <div>Containment: {inc.containment_percent}%</div>
                </div>
              </Tooltip>
            </CircleMarker>
          )
        })}

        {/* Follow mode button — shown when a unit is selected */}
        {selectedUnit && (
          <div style={{
            position: 'absolute', bottom: '24px', right: '12px', zIndex: 1000,
          }}>
            <button
              onClick={() => setFollowMode(v => !v)}
              style={{
                background: followMode ? 'rgba(96,165,250,0.2)' : 'rgba(21,20,25,0.9)',
                border: `1px solid ${followMode ? '#60a5fa' : '#333'}`,
                borderRadius: '3px', padding: '6px 12px', cursor: 'pointer',
                fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px',
                color: followMode ? '#60a5fa' : '#878787',
                letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: '6px',
                transition: 'all 0.15s',
              }}
            >
              <div style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: followMode ? '#60a5fa' : '#555',
                boxShadow: followMode ? '0 0 6px #60a5fa' : 'none',
              }} />
              {followMode ? 'FOLLOWING UNIT' : 'FOLLOW UNIT'}
            </button>
          </div>
        )}

        {/* Legend */}
        <div style={{
          position: 'absolute', bottom: '24px', left: '12px', zIndex: 1000,
          background: 'rgba(21,20,25,0.9)', border: '1px solid #262626',
          borderRadius: '3px', padding: '8px 12px',
          display: 'flex', flexDirection: 'column', gap: '4px', pointerEvents: 'none',
        }}>
          {showFires && (
            <>
              <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#878787', letterSpacing: '0.06em', marginBottom: '2px' }}>FIRE SEVERITY</div>
              {Object.entries(SEVERITY_COLOR).map(([sev, color]) => (
                <div key={sev} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: color }} />
                  <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB' }}>{sev.toUpperCase()}</span>
                </div>
              ))}
            </>
          )}
          {showFires && showUnits && <div style={{ height: '1px', background: '#262626', margin: '4px 0' }} />}
          {showUnits && (
            <>
              <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#878787', letterSpacing: '0.06em', marginBottom: '2px' }}>UNIT STATUS</div>
              {Object.entries(UNIT_STATUS_COLOR).slice(0, 5).map(([status, color]) => (
                <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: color }} />
                  <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB' }}>{status.replace(/_/g, ' ').toUpperCase()}</span>
                </div>
              ))}
            </>
          )}
          {unitRoutes.length > 0 && (
            <>
              <div style={{ height: '1px', background: '#262626', margin: '4px 0' }} />
              <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#878787', letterSpacing: '0.06em', marginBottom: '2px' }}>ROUTE STATUS</div>
              {Object.entries(ROUTE_STATUS_COLOR).map(([status, color]) => (
                <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '16px', height: '3px', background: color, borderRadius: '1px' }} />
                  <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB' }}>{status}</span>
                </div>
              ))}
            </>
          )}
          {!showLabels && showUnits && (
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#878787', marginTop: '4px' }}>Zoom in for callsigns</div>
          )}
          {showWaterSources && (
            <>
              <div style={{ height: '1px', background: '#262626', margin: '4px 0' }} />
              <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#878787', letterSpacing: '0.06em', marginBottom: '2px' }}>WATER SOURCES</div>
              {[
                { label: 'Fire Hydrant',   color: '#60a5fa' },
                { label: 'Lake',           color: '#38bdf8' },
                { label: 'River / Canal',  color: '#22d3ee' },
                { label: 'Reservoir',      color: '#818cf8' },
                { label: 'Water Tank',     color: '#a78bfa' },
              ].map(({ label, color }) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: color }} />
                  <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB' }}>{label}</span>
                </div>
              ))}
            </>
          )}
        </div>
      </MapContainer>
    </div>
  )
}