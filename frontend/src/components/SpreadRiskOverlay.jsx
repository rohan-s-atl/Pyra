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

  useEffect(() => {
    const newIds = incidents
      .map(i => i.id)
      .filter(id => !fetchedIds.current.has(id))

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
        }
      }
      setCones(prev => ({ ...prev, ...results }))
    }

    fetchNew()
  }, [incidents])

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
            <Tooltip direction="top" sticky>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', background: 'rgba(20,26,36,0.96)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '14px', padding: '10px 12px', boxShadow: '0 16px 36px rgba(0,0,0,0.42)' }}>
                <div style={{ fontWeight: 700, marginBottom: '2px', color }}>
                  Spread Risk Zone
                </div>
                <div>
                  Risk: <strong>{terrainRisk.toUpperCase()}</strong>
                  {terrainAdjusted && (
                    <span style={{ color: '#F56E0F', marginLeft: '4px', fontSize: '11px' }}>
                      ▲ terrain-adjusted
                    </span>
                  )}
                </div>
                {terrainAdjusted && risk !== terrainRisk && (
                  <div style={{ color: '#878787', fontSize: '11px' }}>
                    Base: {risk.toUpperCase()} · Slope: {cone.properties?.slope_percent?.toFixed(0) ?? '?'}%
                  </div>
                )}
                <div>Direction: {cone.properties?.spread_direction ?? '—'}</div>
                <div>Radius: {cone.properties?.radius_km} km</div>
                {cone.properties?.slope_percent != null && (
                  <div>Slope: {cone.properties.slope_percent.toFixed(0)}% ({cone.properties?.aspect_cardinal ?? '—'} aspect)</div>
                )}
              </div>
            </Tooltip>
          </Polygon>
        )
      })}
    </>
  )
}
