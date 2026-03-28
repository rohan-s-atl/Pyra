import { useEffect, useRef } from 'react'
import { Polygon, Tooltip } from 'react-leaflet'
import { api } from '../api/client'

const ZONE_META = {
  order: {
    label: 'EVACUATION ORDER',
    short: 'ORDER',
    color: '#ef4444',
    icon:  '🔴',
    desc:  'Immediate — mandatory evacuation',
  },
  warning: {
    label: 'EVACUATION WARNING',
    short: 'WARNING',
    color: '#F56E0F',
    icon:  '🟠',
    desc:  'Likely threatened — prepare to leave',
  },
  watch: {
    label: 'EVACUATION WATCH',
    short: 'WATCH',
    color: '#facc15',
    icon:  '🟡',
    desc:  'Monitor — be ready to leave',
  },
}

// ── Control panel ──────────────────────────────────────────────────────────
export function EvacZonesPanel({ data, visible, loading, onClose, onExport, activeZones, onToggleZone }) {

  if (!visible) return null

  return (
    <div style={{
      position: 'absolute', bottom: '44px', right: '12px', zIndex: 1000,
      background: 'rgba(21,20,25,0.97)', border: '1px solid #ef444444',
      borderRadius: '4px', width: '260px',
      maxHeight: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column',
      backdropFilter: 'blur(8px)', boxShadow: '0 4px 24px rgba(0,0,0,0.6)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px 8px',
        borderBottom: '1px solid #262626',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#ef4444', letterSpacing: '0.06em' }}>
            ⬡ EVACUATION ZONES
          </div>
          {data && (
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#FBFBFB', fontWeight: 600, marginTop: '2px' }}>
              {data.incident_name}
            </div>
          )}
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#878787', cursor: 'pointer', fontSize: '14px' }}>✕</button>
      </div>

      <div style={{ padding: '10px 14px', overflowY: 'auto', flex: 1 }}>
        {loading && (
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#878787', padding: '8px 0' }}>
            <span style={{ color: '#ef4444' }}>⬡</span> Generating zones...
          </div>
        )}

        {data && !loading && (
          <>
            {/* Conditions strip */}
            <div style={{ display: 'flex', gap: '10px', marginBottom: '10px', padding: '6px 8px', background: '#1B1B1E', borderRadius: '3px' }}>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
                ROS <span style={{ color: '#FBFBFB', fontWeight: 700 }}>{data.ros_mph} mph</span>
              </div>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
                Wind <span style={{ color: '#FBFBFB', fontWeight: 700 }}>{data.wind_speed_mph ?? '—'} mph</span>
              </div>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>
                Dir <span style={{ color: '#FBFBFB', fontWeight: 700 }}>{data.spread_direction}</span>
              </div>
            </div>

            {/* Zone toggles */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginBottom: '10px' }}>
              {(data.zones ?? []).map(zone => {
                const ztype  = zone.properties.zone_type
                const meta   = ZONE_META[ztype] ?? {}
                const active = activeZones[ztype]
                const p      = zone.properties
                return (
                  <div
                    key={ztype}
                    onClick={() => onToggleZone?.(ztype)}
                    style={{
                      display: 'flex', alignItems: 'flex-start', gap: '8px',
                      padding: '7px 9px', borderRadius: '3px', cursor: 'pointer',
                      background: active ? `${meta.color}18` : '#1B1B1E',
                      border: `1px solid ${active ? meta.color + '55' : '#262626'}`,
                      transition: 'all 0.15s',
                    }}
                  >
                    {/* Color swatch / toggle */}
                    <div style={{
                      width: '12px', height: '12px', borderRadius: '2px', flexShrink: 0, marginTop: '1px',
                      background: active ? meta.color : 'transparent',
                      border: `2px solid ${meta.color}`,
                      transition: 'background 0.15s',
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: active ? meta.color : '#878787', letterSpacing: '0.04em' }}>
                        {meta.short}
                      </div>
                      <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787', marginTop: '1px' }}>
                        {meta.desc}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', fontWeight: 600 }}>
                        {p.forward_km.toFixed(1)} km
                      </div>
                      <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#878787' }}>
                        {p.area_sq_mi.toFixed(1)} mi²
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Rationale */}
            <div style={{
              background: '#1B1B1E', border: '1px solid #262626',
              borderRadius: '3px', padding: '7px 9px', marginBottom: '10px',
            }}>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#F56E0F', fontWeight: 700, letterSpacing: '0.04em', marginBottom: '4px' }}>
                ⬡ AI RATIONALE
              </div>
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#aaa', lineHeight: 1.5 }}>
                {data.rationale}
              </div>
            </div>

            {/* Structures */}
            {data.structures_threatened > 0 && (
              <div style={{
                background: 'rgba(239,68,68,0.08)', border: '1px solid #ef444433',
                borderRadius: '3px', padding: '6px 9px', marginBottom: '10px',
                fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#ef4444',
              }}>
                ⚠ {data.structures_threatened.toLocaleString()} structures in threatened area
              </div>
            )}

            {/* Export */}
            <button
              onClick={() => onExport?.(data, activeZones)}
              style={{
                width: '100%', padding: '7px',
                background: 'rgba(239,68,68,0.12)',
                border: '1px solid #ef444455',
                borderRadius: '3px', cursor: 'pointer',
                fontFamily: 'Inter, sans-serif', fontWeight: 700,
                fontSize: '10px', color: '#ef4444', letterSpacing: '0.04em',
              }}
            >
              ↓ EXPORT GEOJSON
            </button>
          </>
        )}

        {!data && !loading && (
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '11px', color: '#555', padding: '8px 0' }}>
            Select an incident to generate zones
          </div>
        )}
      </div>
    </div>
  )
}

// ── GeoJSON export helper ──────────────────────────────────────────────────
export function exportEvacZones(data, activeZones) {
  const features = (data.zones ?? []).filter(z => activeZones[z.properties.zone_type])
  const geojson = {
    type: 'FeatureCollection',
    features,
    metadata: {
      incident:   data.incident_name,
      generated:  new Date().toISOString(),
      ros_mph:    data.ros_mph,
      direction:  data.spread_direction,
      model:      'Pyra AI — Rothermel simplified evac zone model',
    },
  }
  const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `evac-zones-${data.incident_name.replace(/\s+/g, '-').toLowerCase()}-${Date.now()}.geojson`
  a.click()
  URL.revokeObjectURL(url)
}

// ── Map overlay ────────────────────────────────────────────────────────────
export default function EvacZonesOverlay({ visible, data, activeZones }) {
  if (!visible || !data?.zones) return null

  // Render outermost (watch) first, order on top
  return (
    <>
      {[...data.zones].reverse().map(zone => {
        const ztype = zone.properties.zone_type
        if (activeZones && !activeZones[ztype]) return null

        const p      = zone.properties
        const coords = zone.geometry.coordinates[0]
        if (!coords?.length) return null

        const positions = coords.map(([lon, lat]) => [lat, lon])

        return (
          <Polygon
            key={ztype}
            positions={positions}
            pathOptions={{
              color:       p.color,
              fillColor:   p.color,
              fillOpacity: p.fill_opacity,
              weight:      ztype === 'order' ? 2.5 : 1.5,
              dashArray:   p.dash ?? undefined,
              opacity:     0.9,
            }}
          >
            <Tooltip sticky direction="top">
              <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', minWidth: '180px' }}>
                <div style={{ fontWeight: 700, color: p.color, marginBottom: '3px' }}>
                  {p.label}
                </div>
                <div style={{ color: '#555', fontSize: '11px', marginBottom: '4px' }}>
                  {p.description}
                </div>
                <div>{p.forward_km.toFixed(1)} km forward extent</div>
                <div>{p.area_sq_mi.toFixed(1)} mi² total area</div>
                <div style={{ color: '#878787', fontSize: '10px', marginTop: '3px' }}>
                  Based on +{p.based_on_hours}hr fire growth projection
                </div>
              </div>
            </Tooltip>
          </Polygon>
        )
      })}
    </>
  )
}