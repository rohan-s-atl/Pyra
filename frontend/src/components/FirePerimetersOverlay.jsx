import { useEffect, useRef, useState } from 'react'
import { GeoJSON, Tooltip } from 'react-leaflet'
import { api } from '../api/client'

const CACHE_TTL_MS = 15 * 60 * 1000 // 15 minutes

export default function FirePerimetersOverlay({ visible }) {
  const [perimeters, setPerimeters] = useState([])
  // Ref so the cache check never reads stale state and doesn't trigger extra re-renders
  const lastFetchRef = useRef(null)

  useEffect(() => {
    if (!visible) return
    const now = Date.now()
    if (lastFetchRef.current && now - lastFetchRef.current < CACHE_TTL_MS) return

    api.perimeters()
      .then(data => {
        setPerimeters(data.perimeters ?? [])
        lastFetchRef.current = Date.now()
      })
      .catch(err => console.warn('[perimeters] fetch failed:', err))
  }, [visible])

  if (!visible || !perimeters.length) return null

  return (
    <>
      {perimeters.map(p => {
        if (!p.geometry) return null
        const geojsonFeature = { type: 'Feature', geometry: p.geometry, properties: p }
        return (
          <GeoJSON
            key={p.id}
            data={geojsonFeature}
            style={{ color: '#F56E0F', weight: 2, fillColor: '#F56E0F', fillOpacity: 0.30, opacity: 0.85 }}
          >
            <Tooltip sticky>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px' }}>
                <div style={{ fontWeight: 700, marginBottom: '3px' }}>{p.name}</div>
                {p.acres != null && <div>{Math.round(p.acres).toLocaleString()} acres</div>}
                {p.containment != null && <div>{p.containment}% contained</div>}
                <div style={{ color: '#F56E0F', fontSize: '10px', marginTop: '3px' }}>NIFC OFFICIAL PERIMETER</div>
              </div>
            </Tooltip>
          </GeoJSON>
        )
      })}
    </>
  )
}