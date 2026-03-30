/**
 * api/client.js
 *
 * Central API client for Pyra.
 *
 * PATCH: Removed ~100-line duplicate of the route engine that was copy-pasted
 * from services/routeEngine.js. routeEngine.js is the authoritative version
 * (has road-distance ETAs, correct destination-inclusive cache key, shared
 * scoreExposure helper). All components already import from routeEngine.js
 * directly; the client.js exports were dead aliases.
 *
 * Exports:
 *   BASE_URL          — backend origin
 *   setAuthToken(tok) — store JWT after login
 *   api               — object with all REST helpers (returns parsed JSON)
 *   streamBriefing    — streams AI operational briefing
 *   streamChat        — streams SITREP chat response
 *   streamReview      — streams post-incident review
 *   getDispatchAdvice — POST /api/dispatch-advice/{id}
 *   getLoadoutAdvice  — POST /api/dispatch/loadout/{id}
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

export function authHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json',
    ...(_token ? { Authorization: `Bearer ${_token}` } : {}),
    ...extra,
  }
}

async function get(path) {
  const res = await fetch(`${BASE_URL}${path}`, { method: 'GET', headers: authHeaders() })
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}

async function post(path, body = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
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
    if (!res.ok) { onError(new Error(`${path} → ${res.status}`)); return }
    const reader  = res.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6).trim()
        if (!payload || payload === '[DONE]') continue
        try {
          const parsed = JSON.parse(payload)
          if (parsed.text)  onChunk(parsed.text)
          else if (parsed.error) onError(new Error(parsed.error))
        } catch (_) {
          onChunk(payload)
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
  alerts:    (limit = 100) => get(`/api/alerts/?limit=${limit}`),
  alertStats: (incidentId) =>
    get(`/api/alerts/stats${incidentId ? `?incident_id=${incidentId}` : ''}`),

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

  // Route safety
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
  dispatch:      (body)                         => post('/api/dispatch/approve', body),
  dispatchAlert: (alertId, incidentId, unitIds) =>
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
  clearAllAlerts: () =>
    fetch(`${BASE_URL}/api/alerts/all`, { method: 'DELETE', headers: authHeaders() })
      .then(r => r.json()),
  clearAcknowledgedAlerts: () =>
    fetch(`${BASE_URL}/api/alerts/acknowledged`, { method: 'DELETE', headers: authHeaders() })
      .then(r => r.json()),
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