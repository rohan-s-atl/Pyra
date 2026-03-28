/**
 * api/client.js
 *
 * Central API client for Pyra.
 *
 * Exports:
 *   BASE_URL          — backend origin (for direct fetch calls like report downloads)
 *   setAuthToken(tok) — store JWT after login
 *   api               — object with all REST helpers (returns parsed JSON)
 *   streamBriefing    — streams AI operational briefing
 *   streamChat        — streams SITREP chat response
 *   streamReview      — streams post-incident review
 *   getDispatchAdvice — POST /api/dispatch-advice/{id}  (returns JSON)
 *   getLoadoutAdvice  — POST /api/dispatch/loadout/{id} (returns JSON)
 */

// ── Base URL ──────────────────────────────────────────────────────────────────

export const BASE_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL)
  ? import.meta.env.VITE_API_URL.replace(/\/$/, '')
  : ''

// ── Auth token ────────────────────────────────────────────────────────────────

let _token = ''
try { _token = localStorage.getItem('token') ?? '' } catch (_) {}

export function setAuthToken(tok) {
  _token = tok ?? ''
  try {
    if (_token) { localStorage.setItem('token', _token) }
    else        { localStorage.removeItem('token') }
  } catch (_) {}
}

// ── Core fetch helpers ────────────────────────────────────────────────────────

function authHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json',
    ...(_token ? { Authorization: `Bearer ${_token}` } : {}),
    ...extra,
  }
}

async function get(path) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'GET',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`GET ${path} \u2192 ${res.status}`)
  return res.json()
}

async function post(path, body = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} \u2192 ${res.status}`)
  return res.json()
}

// ── Streaming helper ──────────────────────────────────────────────────────────

async function stream(path, body, onChunk, onDone, onError) {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      onError(new Error(`${path} \u2192 ${res.status}`))
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const payload = line.slice(6).trim()
          if (!payload || payload === '[DONE]') continue
          // Backend sends {"text": "chunk"} — parse and extract
          try {
            const parsed = JSON.parse(payload)
            if (parsed.text) onChunk(parsed.text)
            else if (parsed.error) onError(new Error(parsed.error))
          } catch (_) {
            onChunk(payload) // plain text fallback
          }
        }
      }
    }
    onDone()
  } catch (err) {
    onError(err)
  }
}

// ── Named API methods ─────────────────────────────────────────────────────────

export const api = {
  // Incidents
  incidents: () => get('/api/incidents/'),

  // Alerts
  alerts: () => get('/api/alerts/'),

  // Units
  units: () => get('/api/units/'),

  // Intelligence
  spreadRisk:          (incidentId) => get(`/api/intelligence/spread-risk/${incidentId}`),
  fireBehavior:        (incidentId) => get(`/api/intelligence/fire-behavior/${incidentId}`),
  recommendation:      (incidentId) => get(`/api/intelligence/recommendation/${incidentId}`),
  alertRecommendation: (alertId)    => get(`/api/intelligence/alert-recommendation/${alertId}`),
  unitRecommendations: (incidentId) => get(`/api/recommendations/${incidentId}/units`),

  // Map overlays
  fireGrowth: (incidentId, minutes = null) =>
    get(`/api/intelligence/fire-growth/${incidentId}${minutes != null ? `?minutes=${minutes}` : ''}`),

  // Water sources
  waterSources: (incidentId, radiusM = 6000) =>
    get(`/api/water-sources/?incident_id=${incidentId}&radius_m=${radiusM}`),

  // Route safety scoring
  routeSafety: (incidentId) => get(`/api/routes/safety/${incidentId}`),

  // Multi-incident priority
  multiIncidentPriority: () => get('/api/multi-incident/priority'),

  // Recommendation feedback
  submitFeedback: (incidentId, body) => post(`/api/recommendations/${incidentId}/feedback`, body),
  listFeedback:   (incidentId)       => get(`/api/recommendations/${incidentId}/feedback`),

  // Shift handoff briefings
  listHandoffBriefings: (incidentId) => get(`/api/briefing/handoff/${incidentId}`),
  getHandoffBriefing:   (incidentId, briefingId) =>
    get(`/api/briefing/handoff/${incidentId}/${briefingId}`),

  // Incident close-out
  closeoutChecklist: (incidentId) => get(`/api/incidents/${incidentId}/closeout-checklist`),
  closeIncident:     (incidentId, force = false) =>
    post(`/api/incidents/${incidentId}/close${force ? '?force=true' : ''}`, {}),
  evacZones:  (incidentId) => get(`/api/intelligence/evac-zones/${incidentId}`),
  heatmap:    ()           => get('/api/heatmap/'),
  perimeters: ()           => get('/api/perimeters/'),

  // Dispatch
  dispatch:      (body)                          => post('/api/dispatch/approve', body),
  dispatchAlert: (alertId, incidentId, unitIds)  =>
    post('/api/dispatch/alert-approve', { alert_id: alertId, incident_id: incidentId, unit_ids: unitIds }),

  // Triage
  triage: (alertId) => get(`/api/triage/${alertId}`),

  // Audit log
  auditLog: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/api/audit/${q ? '?' + q : ''}`)
  },
  auditVerify: () => get('/api/audit/verify'),

  // Alert management
  clearAllAlerts: () => {
    return fetch(`${BASE_URL}/api/alerts/all`, {
      method: 'DELETE',
      headers: authHeaders(),
    }).then(r => r.json())
  },
  acknowledgeAlert: (alertId) => post(`/api/alerts/${alertId}/acknowledge`, {}),
}

// ── Streaming exports ─────────────────────────────────────────────────────────

export function streamBriefing(incidentId, onChunk, onDone, onError) {
  return stream(`/api/briefing/${incidentId}`, {}, onChunk, onDone, onError)
}

export async function generateHandoffBriefing(incidentId, periodHours = 12) {
  const token = (() => { try { return localStorage.getItem('token') ?? '' } catch { return '' } })()
  const res = await fetch(
    `${BASE_URL}/api/briefing/handoff/${incidentId}?period_hours=${periodHours}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } }
  )
  if (!res.ok) throw new Error(`Handoff briefing → ${res.status}`)
  return res.json()
}

export function streamChat(incidentId, messages, onChunk, onDone, onError) {
  return stream(`/api/chat/${incidentId}`, { messages }, onChunk, onDone, onError)
}

export function streamReview(incidentId, onChunk, onDone, onError) {
  return stream(`/api/review/${incidentId}`, {}, onChunk, onDone, onError)
}

// ── Non-streaming AI advice ───────────────────────────────────────────────────

export async function getDispatchAdvice(incidentId, unitIds = []) {
  return post(`/api/dispatch-advice/${incidentId}`, { unit_ids: unitIds })
}

export async function getLoadoutAdvice(incidentId, unitIds = []) {
  return post(`/api/dispatch/loadout/${incidentId}`, { unit_ids: unitIds })
}

// ── Route engine (kept here for backward compat — also in services/routeEngine.js) ──

import { etaTimeString } from '../utils/timeUtils'

const UNIT_SPEED_MPH = {
  engine: 45, hand_crew: 35, dozer: 25, water_tender: 40,
  helicopter: 100, air_tanker: 180, command_unit: 50, rescue: 55,
}

const AIR_TYPES = new Set(['helicopter', 'air_tanker'])

const CARDINAL_TO_DEG = {
  N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315,
}
const SPREAD_RADIUS_KM = { extreme: 6, high: 4, moderate: 3, low: 1.5 }
const CONE_HALF_ANGLE  = { extreme: 60, high: 50, moderate: 40, low: 30 }

function buildCone(inc) {
  const risk      = (inc.spread_risk ?? 'moderate').toLowerCase()
  let radiusKm    = SPREAD_RADIUS_KM[risk] ?? 3
  const halfAngle = CONE_HALF_ANGLE[risk] ?? 40
  if (inc.wind_speed_mph) radiusKm *= Math.min(1.25, 1.0 + inc.wind_speed_mph / 100.0)
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

function pointInPolygon(lat, lon, polygonCoords) {
  let inside = false
  const x = lon, y = lat
  for (let i = 0, j = polygonCoords.length - 1; i < polygonCoords.length; j = i++) {
    const xi = polygonCoords[i][0], yi = polygonCoords[i][1]
    const xj = polygonCoords[j][0], yj = polygonCoords[j][1]
    if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi))
      inside = !inside
  }
  return inside
}

function computeETA(unit, incident) {
  const dlat = unit.latitude  - incident.latitude
  const dlon = unit.longitude - incident.longitude
  const distMiles = Math.sqrt((dlat * 69) ** 2 + (dlon * 54) ** 2)
  const speedMph  = UNIT_SPEED_MPH[unit.unit_type] ?? 40
  return { distMiles, minutes: Math.round((distMiles / speedMph) * 60) }
}

function exposureToStatus(level) {
  if (level === 'none' || level === 'low') return { status: 'FASTEST', statusColor: '#22c55e' }
  if (level === 'moderate')               return { status: 'CAUTION', statusColor: '#eab308' }
  return                                         { status: 'AVOID',   statusColor: '#ef4444' }
}

export function scoreBadges(units, incident, allIncidents) {
  if (!units.length || !incident) return {}
  const activeCones = allIncidents
    .filter(inc => inc.spread_risk && inc.status !== 'out')
    .map(inc => ({
      inc,
      cone:      buildCone(inc),
      dirDeg:    CARDINAL_TO_DEG[inc.spread_direction?.toUpperCase()] ?? 0,
      halfAngle: CONE_HALF_ANGLE[(inc.spread_risk ?? 'moderate').toLowerCase()] ?? 40,
    }))
  const result = {}
  for (const unit of units) {
    if (isNaN(unit.latitude) || isNaN(unit.longitude)) continue
    const { distMiles, minutes: etaMinutes } = computeETA(unit, incident)
    let exposureLevel = 'none'
    for (const { inc, cone, dirDeg, halfAngle } of activeCones) {
      const dlat = unit.latitude  - inc.latitude
      const dlon = unit.longitude - inc.longitude
      const bearingRad = Math.atan2(dlon * Math.cos(inc.latitude * Math.PI / 180), dlat)
      const bearingDeg = ((bearingRad * 180 / Math.PI) + 360) % 360
      let angleDiff = Math.abs(bearingDeg - dirDeg)
      if (angleDiff > 180) angleDiff = 360 - angleDiff
      const distKm = Math.sqrt((dlat * 111) ** 2 + (dlon * 111 * Math.cos(inc.latitude * Math.PI / 180)) ** 2)
      const coneRadiusKm = (SPREAD_RADIUS_KM[(inc.spread_risk ?? 'moderate').toLowerCase()] ?? 3) * 1.25
      const inCone = pointInPolygon(unit.latitude, unit.longitude, cone)
      if (inCone && distKm < coneRadiusKm) {
        if (angleDiff < halfAngle * 0.5) { exposureLevel = 'high' }
        else if (exposureLevel !== 'high') { exposureLevel = 'moderate' }
      } else if (!inCone && distKm < coneRadiusKm * 1.5 && angleDiff < halfAngle) {
        if (exposureLevel !== 'high') exposureLevel = 'moderate'
      }
    }
    const { status, statusColor } = exposureToStatus(exposureLevel)
    result[unit.id] = { status, statusColor, etaMinutes, etaTimeStr: etaTimeString(etaMinutes), distMiles }
  }
  return result
}

export async function fetchUnitRoutes(selectedUnits, incident, allIncidents) {
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
    if (isNaN(unit.latitude) || isNaN(unit.longitude)) return null
    const { distMiles, minutes: etaMinutes } = computeETA(unit, incident)
    let coords
    try {
      const res = await fetch(`${BASE_URL}/api/units/${unit.id}/route`, {
        headers: authHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        coords = data.waypoints?.length ? data.waypoints : null
      }
    } catch { coords = null }
    if (!coords || !coords.length) {
      coords = [[unit.latitude, unit.longitude], [incident.latitude, incident.longitude]]
    }
    let exposureLevel = 'none'
    for (const { inc, cone, dirDeg, halfAngle } of activeCones) {
      const dlat = unit.latitude  - inc.latitude
      const dlon = unit.longitude - inc.longitude
      const bearingRad = Math.atan2(dlon * Math.cos(inc.latitude * Math.PI / 180), dlat)
      const bearingDeg = ((bearingRad * 180 / Math.PI) + 360) % 360
      let angleDiff = Math.abs(bearingDeg - dirDeg)
      if (angleDiff > 180) angleDiff = 360 - angleDiff
      const distKm = Math.sqrt((dlat * 111) ** 2 + (dlon * 111 * Math.cos(inc.latitude * Math.PI / 180)) ** 2)
      const coneRadiusKm = (SPREAD_RADIUS_KM[(inc.spread_risk ?? 'moderate').toLowerCase()] ?? 3) * 1.25
      const inCone = pointInPolygon(unit.latitude, unit.longitude, cone)
      if (inCone && distKm < coneRadiusKm) {
        exposureLevel = angleDiff < halfAngle * 0.5 ? 'high' : (exposureLevel !== 'high' ? 'moderate' : exposureLevel)
      } else if (!inCone && distKm < coneRadiusKm * 1.5 && angleDiff < halfAngle) {
        if (exposureLevel !== 'high') exposureLevel = 'moderate'
      }
    }
    const { status, statusColor } = exposureToStatus(exposureLevel)
    let explanation
    if (status === 'FASTEST') {
      const dist = distMiles < 1 ? `${Math.round(distMiles * 5280)} ft` : `${distMiles.toFixed(1)} mi`
      explanation = `Fastest route — ${dist}, ${etaMinutes} min ETA. Low fire exposure.`
    } else if (status === 'CAUTION') {
      explanation = 'Route approaches active fire spread zone. Proceed with caution.'
    } else {
      explanation = 'Unit positioned in active fire spread zone. Consider alternate approach or aerial support.'
    }
    return {
      unitId: unit.id,
      designation: unit.designation,
      unit_type: unit.unit_type,
      isAir: AIR_TYPES.has(unit.unit_type),
      coords, etaMinutes,
      etaTimeStr: etaTimeString(etaMinutes),
      distMiles, status, statusColor, explanation,
    }
  }))
  return results.filter(Boolean)
}

export const computeUnitRoutes = fetchUnitRoutes