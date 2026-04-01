import { useEffect, useState, useRef } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'
import { api } from '../api/client'

function scoreToColor(score) {
  if (score < 0.25) return { r: 74,  g: 222, b: 128 }
  if (score < 0.50) return { r: 250, g: 204, b: 21  }
  if (score < 0.75) return { r: 245, g: 110, b: 15  }
  return              { r: 239, g: 68,  b: 68  }
}

function drawHeatmap(map, points, overlayRef) {
  if (overlayRef.current) {
    map.removeLayer(overlayRef.current)
    overlayRef.current = null
  }
  if (!points?.length) return

  const bounds   = map.getBounds()
  const sw       = bounds.getSouthWest()
  const ne       = bounds.getNorthEast()
  const latRange = ne.lat - sw.lat
  const lonRange = ne.lng - sw.lng
  if (latRange <= 0 || lonRange <= 0) return

  const mapSize = map.getSize()
  const size = Math.max(420, Math.min(640, Math.round(Math.max(mapSize.x, mapSize.y) * 0.6)))
  const canvas = document.createElement('canvas')
  canvas.width  = size
  canvas.height = size
  const ctx = canvas.getContext('2d')

  for (const pt of points) {
    const x = ((pt.lon - sw.lng) / lonRange) * size
    const y = size - ((pt.lat - sw.lat) / latRange) * size
    if (x < -100 || x > size + 100 || y < -100 || y > size + 100) continue

    const { r, g, b } = scoreToColor(pt.score)
    const alpha  = Math.min(0.55, pt.score * 0.75)
    const radius = Math.max(40, pt.score * 100)

    const grad = ctx.createRadialGradient(x, y, 0, x, y, radius)
    grad.addColorStop(0,   `rgba(${r},${g},${b},${alpha})`)
    grad.addColorStop(0.5, `rgba(${r},${g},${b},${alpha * 0.45})`)
    grad.addColorStop(1,   `rgba(${r},${g},${b},0)`)

    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    ctx.fill()
  }

  const imgData = canvas.toDataURL('image/png')
  const overlay = L.imageOverlay(imgData, bounds, { opacity: 1, interactive: false, zIndex: 200 })
  overlay.addTo(map)
  overlayRef.current = overlay
}

function HeatmapLayer({ points }) {
  const map        = useMap()
  const overlayRef = useRef(null)
  const redrawFrameRef = useRef(null)
  const lastSignatureRef = useRef('')

  useEffect(() => {
    if (!points?.length) return

    function boundsSignature() {
      const bounds = map.getBounds()
      const sw = bounds.getSouthWest()
      const ne = bounds.getNorthEast()
      return [
        sw.lat.toFixed(2),
        sw.lng.toFixed(2),
        ne.lat.toFixed(2),
        ne.lng.toFixed(2),
        map.getZoom(),
      ].join(':')
    }

    function scheduleDraw(force = false) {
      const nextSignature = boundsSignature()
      if (!force && nextSignature === lastSignatureRef.current) return
      lastSignatureRef.current = nextSignature
      if (redrawFrameRef.current) cancelAnimationFrame(redrawFrameRef.current)
      redrawFrameRef.current = requestAnimationFrame(() => {
        drawHeatmap(map, points, overlayRef)
        redrawFrameRef.current = null
      })
    }

    scheduleDraw(true)

    function onMapChange() {
      scheduleDraw()
    }

    map.on('moveend', onMapChange)
    map.on('zoomend', onMapChange)

    return () => {
      map.off('moveend', onMapChange)
      map.off('zoomend', onMapChange)
      if (redrawFrameRef.current) {
        cancelAnimationFrame(redrawFrameRef.current)
        redrawFrameRef.current = null
      }
      if (overlayRef.current) {
        map.removeLayer(overlayRef.current)
        overlayRef.current = null
      }
      lastSignatureRef.current = ''
    }
  }, [map, points])

  return null
}

export default function RiskHeatmapOverlay({ visible, rightOffset = 12, bottomOffset = 32 }) {
  const [points,  setPoints]  = useState([])
  const [meta,    setMeta]    = useState(null)
  const fetchedRef = useRef(false)

  useEffect(() => {
    if (!visible || fetchedRef.current) return
    fetchedRef.current = true
    api.heatmap()
      .then(data => {
        setPoints(data.points ?? [])
        setMeta({ incidentCount: data.incident_count, model: data.scoring_model })
      })
      .catch(err => {
        console.warn('[heatmap] fetch failed:', err)
        fetchedRef.current = false
      })
  }, [visible])

  if (!visible || !points.length) return null

  return (
    <>
      <HeatmapLayer points={points} />
      {/* Legend overlay */}
      <div className="ui-shell-panel ui-float-soft-delayed" style={{
        position: 'absolute', bottom: `${bottomOffset}px`, right: `${rightOffset}px`, zIndex: 1250,
        background: 'rgba(22,28,38,0.94)', border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '14px', padding: '10px 12px',
        fontFamily: 'Inter, sans-serif', pointerEvents: 'none',
        backdropFilter: 'blur(14px)',
        boxShadow: '0 16px 36px rgba(0,0,0,0.4)',
      }}>
        <div style={{ fontSize: '9px', color: '#878787', letterSpacing: '0.06em', marginBottom: '6px' }}>
          COMPOSITE RISK · {meta?.incidentCount ?? '—'} INCIDENTS
        </div>
        {[
          { label: 'Extreme', color: '#ef4444' },
          { label: 'High',    color: '#F56E0F' },
          { label: 'Moderate',color: '#facc15' },
          { label: 'Low',     color: '#4ade80' },
        ].map(({ label, color }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
            <div style={{ width: '10px', height: '10px', borderRadius: '2px', background: color, opacity: 0.8 }} />
            <span style={{ fontSize: '10px', color: '#FBFBFB' }}>{label}</span>
          </div>
        ))}
      </div>
    </>
  )
}
