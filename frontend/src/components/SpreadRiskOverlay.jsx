import { useEffect, useState, useRef } from 'react'
import { Polygon, Tooltip } from 'react-leaflet'
import { api } from '../api/client'

const RISK_COLOR = {
  extreme:  '#ef4444',
  high:     '#F56E0F',
  moderate: '#facc15',
  low:      '#4ade80',
}

export default function SpreadRiskOverlay({ incidents, selectedId }) {
  const [cones,    setCones]   = useState({})
  const fetchedIds = useRef(new Set())
  const failedIds  = useRef(new Set())

  useEffect(() => {
    const newIds = incidents
      .map(i => i.id)
      .filter(id => !fetchedIds.current.has(id) && !failedIds.current.has(id))

    if (newIds.length === 0) return

    async function fetchNew() {
      const results = {}
      for (const id of newIds) {
        try {
          const cone = await api.spreadRisk(id)
          results[id] = cone
          fetchedIds.current.add(id)
        } catch (e) {
          console.warn(`Failed to load spread risk for ${id}`)
          failedIds.current.add(id)
        }
      }
      setCones(prev => ({ ...prev, ...results }))
    }

    fetchNew()
  }, [incidents])

  // Refresh cones every 60 seconds without flickering existing ones
  useEffect(() => {
    const id = setInterval(() => {
      fetchedIds.current = new Set()
      failedIds.current  = new Set()
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  return (
    <>
      {Object.entries(cones).map(([incidentId, cone]) => {
        if (!cone?.geometry?.coordinates?.[0]) return null

        const risk            = cone.properties?.spread_risk ?? 'moderate'
        const terrainRisk     = cone.properties?.terrain_adjusted_risk ?? risk
        const terrainAdjusted = cone.properties?.terrain_adjusted ?? false
        const color           = RISK_COLOR[terrainRisk] ?? RISK_COLOR[risk] ?? '#facc15'
        const isSelected      = incidentId === selectedId

        // Safeguard — filter out any invalid coordinates before passing to Leaflet
        const positions = cone.geometry.coordinates[0]
          .map(([lon, lat]) => [lat, lon])
          .filter(([lat, lon]) =>
            lat != null && lon != null && !isNaN(lat) && !isNaN(lon)
          )

        // Need at least 3 valid points to render a polygon
        if (positions.length < 3) return null

        return (
          <Polygon
            key={incidentId}
            positions={positions}
            pathOptions={{
              color:       color,
              fillColor:   color,
              fillOpacity: isSelected ? 0.25 : 0.12,
              weight:      isSelected ? 2.4 : 1.4,
              dashArray:   '6 4',
              opacity:     isSelected ? 0.95 : 0.8,
            }}
          >
            <Tooltip direction="top" sticky className="pyra-tooltip">
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', minWidth: '220px', padding: '14px 16px', color: '#d4dce8', lineHeight: 1.45 }}>
                <div style={{ fontWeight: 700, fontSize: '11px', letterSpacing: '0.04em', marginBottom: '6px', color }}>
                  Spread Risk Zone
                </div>
                <div style={{ color: '#d4dce8', marginBottom: '3px' }}>
                  Risk: <strong style={{ color }}>{terrainRisk.toUpperCase()}</strong>
                  {terrainAdjusted && (
                    <span style={{ color: '#F56E0F', marginLeft: '6px', fontSize: '11px', fontWeight: 600 }}>
                      ▲ terrain-adjusted
                    </span>
                  )}
                </div>
                {terrainAdjusted && risk !== terrainRisk && (
                  <div style={{ color: '#a7b5c7', fontSize: '11px', marginBottom: '4px' }}>
                    Base: {risk.toUpperCase()} · Slope: {cone.properties?.slope_percent?.toFixed(0) ?? '?'}%
                  </div>
                )}
                <div style={{ color: '#c3d0df' }}>Direction: {cone.properties?.spread_direction ?? '—'}</div>
                <div style={{ color: '#c3d0df' }}>Radius: {cone.properties?.radius_km} km</div>
                {cone.properties?.slope_percent != null && (
                  <div style={{ color: '#c3d0df' }}>Slope: {cone.properties.slope_percent.toFixed(0)}% ({cone.properties?.aspect_cardinal ?? '—'} aspect)</div>
                )}
              </div>
            </Tooltip>
          </Polygon>
        )
      })}
    </>
  )
}
