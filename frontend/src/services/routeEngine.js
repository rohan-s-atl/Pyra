import { etaTimeString } from '../utils/timeUtils'

/**
 * routeEngine.js
 * Two-tier routing:
 * - scoreBadges()       → synchronous, no network, instant badge for every unit
 * - computeUnitRoutes() → async OSRM fetch, only for selected units (map rendering)
 */

const UNIT_SPEED_MPH = {
  engine: 45, hand_crew: 35, dozer: 25, water_tender: 40,
  helicopter: 100, air_tanker: 180, command_unit: 50, rescue: 55,
}

const AIR_TYPES = new Set(['helicopter', 'air_tanker'])

// ── Route fetch — POST to build route on demand via OSRM ─────────────────────
async function fetchBackendRoute(unitId, toLat, toLon) {
  try {
    const token = localStorage.getItem('token') ?? ''
    const res = await fetch(`/api/units/${unitId}/route`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ to_lat: toLat, to_lon: toLon }),
    })
    if (!res.ok) return null
    const payload = await res.json()
    if (!Array.isArray(payload.waypoints) || !payload.waypoints.length) return null
    return {
      coords: payload.waypoints.map(([lat, lon]) => [lat, lon]),
      isRoadRouted: payload.is_road_routed ?? false,
    }
  } catch {
    return null
  }
}

// ── Point-in-polygon (ray casting) ───────────────────────────────────────────
// polygonCoords is GeoJSON [lon, lat] order
function pointInPolygon(lat, lon, polygonCoords) {
  let inside = false
  const x = lon, y = lat
  for (let i = 0, j = polygonCoords.length - 1; i < polygonCoords.length; j = i++) {
    const xi = polygonCoords[i][0], yi = polygonCoords[i][1]
    const xj = polygonCoords[j][0], yj = polygonCoords[j][1]
    const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

// ── Build directional spread cone polygon ────────────────────────────────────
const CARDINAL_TO_DEG = {
  N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315,
}
const SPREAD_RADIUS_KM = { extreme: 6, high: 4, moderate: 3, low: 1.5 }
const CONE_HALF_ANGLE  = { extreme: 60, high: 50, moderate: 40, low: 30 }

function buildCone(inc) {
  const risk      = (inc.spread_risk ?? 'moderate').toLowerCase()
  let radiusKm    = SPREAD_RADIUS_KM[risk] ?? 3
  const halfAngle = CONE_HALF_ANGLE[risk] ?? 40

  if (inc.wind_speed_mph) {
    radiusKm *= Math.min(1.25, 1.0 + inc.wind_speed_mph / 100.0)
  }

  const dirDeg = CARDINAL_TO_DEG[inc.spread_direction?.toUpperCase()] ?? 0
  const { latitude: lat, longitude: lon } = inc
  const points = [[lon, lat]]

  for (let i = 0; i <= 20; i++) {
    const angleDeg = (dirDeg - halfAngle) + (halfAngle * 2) * (i / 20)
    const angleRad = angleDeg * Math.PI / 180
    const dLat = (radiusKm / 111.0) * Math.cos(angleRad)
    const dLon = (radiusKm / (111.0 * Math.cos(lat * Math.PI / 180))) * Math.sin(angleRad)
    points.push([lon + dLon, lat + dLat])
  }
  points.push([lon, lat])
  return points
}

// ── Status from exposure level ────────────────────────────────────────────────
function exposureToStatus(exposureLevel) {
  if (exposureLevel === 'none' || exposureLevel === 'low') return { status: 'FASTEST', statusColor: '#22c55e' }
  if (exposureLevel === 'moderate')                        return { status: 'CAUTION', statusColor: '#eab308' }
  return                                                          { status: 'AVOID',   statusColor: '#ef4444' }
}

// ── Straight-line ETA (used for badges and air units) ────────────────────────
function computeETA(unit, incident) {
  const dlat = unit.latitude  - incident.latitude
  const dlon = unit.longitude - incident.longitude
  const distMiles = Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
  const speedMph  = UNIT_SPEED_MPH[unit.unit_type] ?? 40
  return { distMiles, minutes: Math.round((distMiles / speedMph) * 60) }
}

// ── Road-distance ETA from OSRM waypoints ────────────────────────────────────
// Sums haversine segments along the returned polyline so the displayed ETA
// reflects actual road distance rather than straight-line crow-flies distance.
function computeRoadETA(unit, coords) {
  if (!coords || coords.length < 2) return null
  const R = 3958.8 // Earth radius in miles
  let totalMiles = 0
  for (let i = 0; i < coords.length - 1; i++) {
    const [lat1, lon1] = coords[i]
    const [lat2, lon2] = coords[i + 1]
    const dLat = (lat2 - lat1) * Math.PI / 180
    const dLon = (lon2 - lon1) * Math.PI / 180
    const a = Math.sin(dLat / 2) ** 2
      + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2
    totalMiles += R * 2 * Math.asin(Math.sqrt(a))
  }
  const speedMph = UNIT_SPEED_MPH[unit.unit_type] ?? 40
  return { distMiles: totalMiles, minutes: Math.round((totalMiles / speedMph) * 60) }
}

// ── Route cache — MUST include destination to avoid cross-incident cache hits ─
// Bug: the old key was `unitId-fromLat-fromLon` only, so Unit A's route to
// Incident 1 was returned unchanged when the same unit was selected for
// Incident 2, drawing the route line to the wrong fire on the map.
const _routeCache = {}
function cacheKey(unit, toLat, toLon) {
  return [
    unit.id,
    Math.round(unit.latitude  * 1000),
    Math.round(unit.longitude * 1000),
    Math.round(toLat * 100),   // destination at ~1 km grid precision
    Math.round(toLon * 100),
  ].join('-')
}

// ── Shared exposure scoring ───────────────────────────────────────────────────
function scoreExposure(ulat, ulon, activeCones) {
  let exposureLevel = 'none'
  for (const { inc, cone, dirDeg, halfAngle } of activeCones) {
    const dlat = ulat - inc.latitude
    const dlon = ulon - inc.longitude
    const bearingRad = Math.atan2(dlon * Math.cos(inc.latitude * Math.PI / 180), dlat)
    const bearingDeg = ((bearingRad * 180 / Math.PI) + 360) % 360
    let angleDiff = Math.abs(bearingDeg - dirDeg)
    if (angleDiff > 180) angleDiff = 360 - angleDiff
    const distKm = Math.sqrt((dlat * 111) ** 2 + (dlon * 111 * Math.cos(inc.latitude * Math.PI / 180)) ** 2)
    const coneRadiusKm = (SPREAD_RADIUS_KM[(inc.spread_risk ?? 'moderate').toLowerCase()] ?? 3) * 1.25
    const unitInCone = pointInPolygon(ulat, ulon, cone)

    if (unitInCone && distKm < coneRadiusKm) {
      if (angleDiff < halfAngle * 0.5) {
        exposureLevel = 'high'
      } else {
        if (exposureLevel !== 'high') exposureLevel = 'moderate'
      }
    } else if (!unitInCone && distKm < coneRadiusKm * 1.5 && angleDiff < halfAngle) {
      if (exposureLevel !== 'high') exposureLevel = 'moderate'
    }
  }
  return exposureLevel
}

// ── EXPORT 1: instant badge scoring — NO network calls ───────────────────────
export function scoreBadges(units, incident, allIncidents) {
  if (!units.length || !incident) return {}
  const result = {}

  const activeCones = allIncidents
    .filter(inc => inc.spread_risk && inc.status !== 'out')
    .map(inc => ({
      inc,
      cone:      buildCone(inc),
      dirDeg:    CARDINAL_TO_DEG[inc.spread_direction?.toUpperCase()] ?? 0,
      halfAngle: CONE_HALF_ANGLE[(inc.spread_risk ?? 'moderate').toLowerCase()] ?? 40,
    }))

  for (const unit of units) {
    const ulat = unit.latitude
    const ulon = unit.longitude
    if (isNaN(ulat) || isNaN(ulon)) continue

    const { distMiles, minutes: etaMinutes } = computeETA(unit, incident)
    const exposureLevel = scoreExposure(ulat, ulon, activeCones)
    const { status, statusColor } = exposureToStatus(exposureLevel)
    result[unit.id] = { status, statusColor, etaMinutes, etaTimeStr: etaTimeString(etaMinutes), distMiles }
  }

  return result
}

// ── EXPORT 2: full route compute — fetches real OSRM geometry ────────────────
export async function computeUnitRoutes(selectedUnits, incident, allIncidents) {
  if (!selectedUnits.length || !incident) return []

  const activeCones = allIncidents
    .filter(inc => inc.spread_risk && inc.status !== 'out')
    .map(inc => ({
      inc,
      cone:      buildCone(inc),
      dirDeg:    CARDINAL_TO_DEG[inc.spread_direction?.toUpperCase()] ?? 0,
      halfAngle: CONE_HALF_ANGLE[(inc.spread_risk ?? 'moderate').toLowerCase()] ?? 40,
    }))

  const results = await Promise.all(selectedUnits.map(async (unit) => {
    const ulat = unit.latitude
    const ulon = unit.longitude
    if (isNaN(ulat) || isNaN(ulon)) return null

    const isAir = AIR_TYPES.has(unit.unit_type)

    // ── Fetch / cache road geometry ──────────────────────────────────────────
    let coords
    let isRoadRouted = false

    if (isAir) {
      coords = [[ulat, ulon], [incident.latitude, incident.longitude]]
    } else {
      // Cache key now includes destination — fixes cross-incident route reuse
      const key = cacheKey(unit, incident.latitude, incident.longitude)
      if (_routeCache[key]) {
        coords       = _routeCache[key].coords
        isRoadRouted = _routeCache[key].isRoadRouted
      } else {
        const route = await fetchBackendRoute(unit.id, incident.latitude, incident.longitude)
        if (route?.coords?.length) {
          coords       = route.coords
          isRoadRouted = route.isRoadRouted
          _routeCache[key] = { coords, isRoadRouted }
        } else {
          coords       = [[ulat, ulon], [incident.latitude, incident.longitude]]
          isRoadRouted = false
        }
      }
    }

    // ── ETA — road distance when OSRM succeeded, straight-line otherwise ─────
    // The old code always used straight-line distance even when a real road
    // route was returned, producing ETAs that could be 30–50% too low for
    // mountain or indirect routes.
    let distMiles, etaMinutes
    if (isRoadRouted && coords.length > 2) {
      const roadETA = computeRoadETA(unit, coords)
      distMiles  = roadETA.distMiles
      etaMinutes = roadETA.minutes
    } else {
      ;({ distMiles, minutes: etaMinutes } = computeETA(unit, incident))
    }

    // ── Exposure scoring ─────────────────────────────────────────────────────
    const exposureLevel = scoreExposure(ulat, ulon, activeCones)
    const { status, statusColor } = exposureToStatus(exposureLevel)

    // ── Explanation ──────────────────────────────────────────────────────────
    const distLabel = distMiles < 1
      ? `${Math.round(distMiles * 5280)} ft`
      : `${distMiles.toFixed(1)} mi`

    let explanation
    if (status === 'FASTEST') {
      const routeType = isRoadRouted ? 'Road route' : isAir ? 'Direct flight path' : 'Straight-line estimate'
      explanation = `${routeType} — ${distLabel}, ~${etaMinutes} min ETA. Low fire exposure.`
    } else if (status === 'CAUTION') {
      explanation = `Route approaches active fire spread zone. Proceed with caution — monitor conditions.`
    } else {
      explanation = `Unit positioned in active fire spread zone. Consider alternate approach or aerial support.`
    }

    if (!isAir && selectedUnits.length > 1) {
      const others = selectedUnits.filter(u => u.id !== unit.id && !AIR_TYPES.has(u.unit_type))
      for (const other of others) {
        const dlat = unit.latitude - other.latitude
        const dlon = unit.longitude - other.longitude
        if (Math.sqrt(dlat ** 2 + dlon ** 2) < 0.01) {
          explanation += ' Similar path to another unit — bottleneck possible.'
          break
        }
      }
    }

    return {
      unitId: unit.id, designation: unit.designation, unit_type: unit.unit_type,
      isAir, coords, etaMinutes, etaTimeStr: etaTimeString(etaMinutes),
      distMiles, status, statusColor, explanation,
    }
  }))

  return results.filter(Boolean)
}