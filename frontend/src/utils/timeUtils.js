/**
 * timeUtils.js — shared time formatting utilities.
 * Uses the browser's local timezone by default.
 * Override by setting VITE_DISPLAY_TIMEZONE in your .env
 * e.g. VITE_DISPLAY_TIMEZONE=America/Los_Angeles
 */

const DISPLAY_TZ = import.meta.env.VITE_DISPLAY_TIMEZONE || undefined

/**
 * Format an ISO timestamp for display.
 */
export function formatTimestamp(iso) {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
      ...(DISPLAY_TZ ? { timeZone: DISPLAY_TZ } : {}),
    })
  } catch {
    return iso ?? '—'
  }
}

/**
 * Format a Date object as a short time string (e.g. "2:45 PM").
 */
export function formatTimeShort(date) {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', hour12: true,
    ...(DISPLAY_TZ ? { timeZone: DISPLAY_TZ } : {}),
  })
}

/**
 * Return an arrival time string for `minutes` from now.
 */
export function etaTimeString(minutes) {
  const d = new Date()
  d.setMinutes(d.getMinutes() + minutes)
  return formatTimeShort(d)
}

/**
 * Format a clock time string from a Date for the TopBar clock.
 */
export function formatClockTime(date) {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
    ...(DISPLAY_TZ ? { timeZone: DISPLAY_TZ } : {}),
  })
}

/**
 * Format a timezone label string (e.g. "PDT", "EST").
 */
export function formatTimezone(date) {
  return date.toLocaleDateString('en-US', {
    timeZoneName: 'short',
    ...(DISPLAY_TZ ? { timeZone: DISPLAY_TZ } : {}),
  }).split(', ')[1] ?? ''
}