import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'

const STATUS_COLOR = {
  available:      '#22c55e',
  en_route:       '#38bdf8',
  on_scene:       '#ff4d1a',
  staging:        '#facc15',
  returning:      '#a78bfa',
  out_of_service: '#3a4558',
}
const STATUS_LABEL = {
  available:      'AVAIL',
  en_route:       'EN ROUTE',
  on_scene:       'ON SCENE',
  staging:        'STAGING',
  returning:      'RTB',
  out_of_service: 'OOS',
}
const TYPE_ABBR = {
  engine:       'ENG',
  hand_crew:    'CREW',
  dozer:        'DOZ',
  water_tender: 'TNDR',
  helicopter:   'HELO',
  air_tanker:   'ATNK',
  command_unit: 'CMD',
  rescue:       'RESC',
}
const TYPE_ICON = {
  engine:       '🚒',
  hand_crew:    '👥',
  dozer:        '🚜',
  water_tender: '🚛',
  helicopter:   '🚁',
  air_tanker:   '✈️',
  command_unit: '📡',
  rescue:       '🚑',
}
const UNIT_TYPE_ORDER = {
  engine: 0, hand_crew: 1, helicopter: 2, air_tanker: 3,
  dozer: 4, water_tender: 5, command_unit: 6, rescue: 7,
}
const UNIT_CAPACITY = {
  engine:       { water_gal: 500 },
  water_tender: { water_gal: 4000 },
  helicopter:   { water_gal: 300 },
  air_tanker:   { water_gal: 0 },
  hand_crew:    { water_gal: 0 },
  dozer:        { water_gal: 0 },
  command_unit: { water_gal: 0 },
  rescue:       { water_gal: 0 },
}
const DEFAULT_LOADOUTS = {
  engine:       { water_pct: 100, foam_pct: 0, retardant_pct: 0, equipment: ['Hand tools (Pulaskis, McLeods)', 'Medical kit (ALS)'] },
  water_tender: { water_pct: 100, foam_pct: 0, retardant_pct: 0, equipment: ['Portable tank (3000 gal)', 'Extra hose (200ft)'] },
  helicopter:   { water_pct: 100, foam_pct: 0, retardant_pct: 0, equipment: ['Helibucket (300 gal)', 'Medical kit'] },
  air_tanker:   { water_pct: 0,   foam_pct: 0, retardant_pct: 100, equipment: ['Fire retardant (Phos-Chek)', 'Air tactical radio'] },
  hand_crew:    { water_pct: 0,   foam_pct: 0, retardant_pct: 0, equipment: ['Chainsaws (2×)', 'Hand tools', 'Medical kit (ALS)'] },
  dozer:        { water_pct: 0,   foam_pct: 0, retardant_pct: 0, equipment: ['Dozer blade (standard)', 'Fire shelter'] },
  command_unit: { water_pct: 0,   foam_pct: 0, retardant_pct: 0, equipment: ['Satellite comms', 'GIS / mapping laptop'] },
  rescue:       { water_pct: 0,   foam_pct: 0, retardant_pct: 0, equipment: ['ALS medical kit', 'Oxygen / airway kit'] },
}

const VIEWS = [
  { id: 'live',  label: 'ALL',   icon: '◈' },
  { id: 'fires', label: 'FIRES', icon: '⬡' },
  { id: 'units', label: 'UNITS', icon: '◉' },
]

const ENGAGED_STATUS = new Set(['en_route', 'on_scene', 'returning'])

function LoadoutTooltip({ unit, loadout, rect, isDefault }) {
  if (!loadout || !rect) return null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}
  const waterGal = cap.water_gal ? Math.round((loadout.water_pct / 100) * cap.water_gal) : 0
  const renderLeft = rect.left > window.innerWidth / 2
  const pos = renderLeft ? { right: window.innerWidth - rect.left + 10 } : { left: rect.right + 10 }

  return createPortal(
    <div style={{
      position: 'fixed', top: rect.top + rect.height / 2, transform: 'translateY(-50%)',
      width: '236px', zIndex: 99999,
      background: 'rgba(11,15,20,0.86)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '14px', padding: '12px 14px',
      boxShadow: '0 20px 50px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.08)',
      pointerEvents: 'none', backdropFilter: 'blur(16px)',
      ...pos,
    }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: isDefault ? '#38bdf8' : '#ff4d1a', letterSpacing: '0.1em', marginBottom: '10px' }}>
        {isDefault ? '◈ STANDARD LOADOUT' : '⬡ CONFIRMED'} · {unit.designation}
      </div>
      {cap.water_gal > 0 && (
        <div style={{ marginBottom: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#7a8ba0' }}>WATER</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '9px', color: '#38bdf8' }}>{waterGal.toLocaleString()} gal</span>
          </div>
          <div style={{ height: '2px', background: 'rgba(255,255,255,0.08)', borderRadius: '1px' }}>
            <div style={{ height: '100%', width: `${loadout.water_pct}%`, background: '#38bdf8', borderRadius: '1px' }} />
          </div>
        </div>
      )}
      {(loadout.equipment ?? []).length > 0 && (
        <div style={{ marginTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '8px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#6d7d92', letterSpacing: '0.08em', marginBottom: '5px' }}>EQUIPMENT</div>
          {(loadout.equipment ?? []).map(item => (
            <div key={item} style={{ display: 'flex', gap: '5px', marginBottom: '3px' }}>
              <span style={{ color: '#22c55e', fontSize: '9px', flexShrink: 0 }}>✓</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#d4dce8', lineHeight: 1.4 }}>{item}</span>
            </div>
          ))}
        </div>
      )}
    </div>,
    document.body
  )
}

function UnitRow({ unit, confirmedLoadouts, onUnitClick }) {
  const [tooltipRect, setTooltipRect] = useState(null)
  const rowRef = useRef(null)
  const statusColor = STATUS_COLOR[unit.status] ?? '#5a6878'
  const loadout = confirmedLoadouts?.[String(unit.id)] ?? DEFAULT_LOADOUTS[unit.unit_type]
  const isDefault = !confirmedLoadouts?.[String(unit.id)]

  return (
    <>
      <div
        ref={rowRef}
        onClick={() => onUnitClick?.(unit)}
        onMouseEnter={() => setTooltipRect(rowRef.current?.getBoundingClientRect())}
        onMouseLeave={() => setTooltipRect(null)}
        style={{
          display: 'flex', alignItems: 'center', gap: '9px',
          padding: '9px 11px', cursor: 'pointer',
          border: '1px solid rgba(255,255,255,0.08)',
          background: 'rgba(255,255,255,0.02)',
          borderRadius: '12px',
          transition: 'all 0.15s',
          marginBottom: '7px',
        }}
        onMouseEnterCapture={e => {
          e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.15)'
          e.currentTarget.style.transform = 'translateY(-1px)'
        }}
        onMouseLeaveCapture={e => {
          e.currentTarget.style.background = 'rgba(255,255,255,0.02)'
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'
          e.currentTarget.style.transform = 'translateY(0)'
        }}
      >
        <div style={{
          width: '5px', height: '30px', borderRadius: '8px',
          background: statusColor,
          opacity: unit.status === 'out_of_service' ? 0.3 : 1,
          flexShrink: 0,
        }} />

        <div style={{ fontSize: '13px', flexShrink: 0, width: '18px', textAlign: 'center' }}>
          {TYPE_ICON[unit.unit_type] ?? '◉'}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '11px', color: '#d4dce8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {unit.designation}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: '#70839b', letterSpacing: '0.06em', marginTop: '1px' }}>
            {TYPE_ABBR[unit.unit_type] ?? unit.unit_type?.toUpperCase()}
          </div>
        </div>

        <div style={{
          fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '8.5px',
          color: statusColor, letterSpacing: '0.06em',
          padding: '3px 7px',
          background: `${statusColor}12`,
          border: `1px solid ${statusColor}30`,
          borderRadius: '999px', flexShrink: 0,
          whiteSpace: 'nowrap',
        }}>
          {STATUS_LABEL[unit.status] ?? unit.status?.toUpperCase()}
        </div>
      </div>
      {tooltipRect && <LoadoutTooltip unit={unit} loadout={loadout} rect={tooltipRect} isDefault={isDefault} />}
    </>
  )
}

export default function LeftSidebar({ units, activeView, onViewChange, selectedIncidentId, onUnitClick, confirmedLoadouts }) {
  const [filter, setFilter] = useState('all')

  const incidentUnits = !selectedIncidentId
    ? []
    : units.filter(u => u.assigned_incident_id === selectedIncidentId && ENGAGED_STATUS.has(u.status))

  const sortedUnits = [...incidentUnits].sort((a, b) => {
    const statusPriority = { on_scene: 0, en_route: 1, returning: 2 }
    const sa = statusPriority[a.status] ?? 9
    const sb = statusPriority[b.status] ?? 9
    if (sa !== sb) return sa - sb
    const ta = UNIT_TYPE_ORDER[a.unit_type] ?? 9
    const tb = UNIT_TYPE_ORDER[b.unit_type] ?? 9
    if (ta !== tb) return ta - tb
    return (a.designation ?? '').localeCompare(b.designation ?? '')
  })

  const filteredUnits = filter === 'all' ? sortedUnits : sortedUnits.filter(u => u.status === filter)

  const counts = {
    on_scene:  incidentUnits.filter(u => u.status === 'on_scene').length,
    en_route:  incidentUnits.filter(u => u.status === 'en_route').length,
    returning: incidentUnits.filter(u => u.status === 'returning').length,
  }

  return (
    <div style={{
      width: '272px',
      display: 'flex', flexDirection: 'column',
      background: 'rgba(10,14,19,0.72)',
      border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: '20px',
      backdropFilter: 'blur(18px)',
      boxShadow: '0 28px 60px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.08)',
      overflow: 'hidden',
      animation: 'slide-right 0.25s ease-out',
      maxHeight: '100%',
    }}>

      <div style={{ padding: '14px 14px 10px', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 500, color: '#7a8ba0', letterSpacing: '0.12em', marginBottom: '8px' }}>
          MAP VIEW
        </div>
        <div style={{ display: 'flex', gap: '5px' }}>
          {VIEWS.map(v => (
            <button
              key={v.id}
              onClick={() => onViewChange(v.id)}
              style={{
                flex: 1, padding: '6px 0',
                background: activeView === v.id ? 'rgba(56,189,248,0.14)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${activeView === v.id ? 'rgba(56,189,248,0.35)' : 'rgba(255,255,255,0.12)'}`,
                borderRadius: '999px', cursor: 'pointer', transition: 'all 0.15s',
              }}
            >
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 600, color: activeView === v.id ? '#7dd3fc' : '#93a4b8', letterSpacing: '0.06em' }}>
                {v.label}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,0.07)', display: 'flex', gap: '7px' }}>
        {[
          { key: 'on_scene',  label: 'SCENE', color: '#ff4d1a' },
          { key: 'en_route',  label: 'ROUTE', color: '#38bdf8' },
          { key: 'returning', label: 'RTB',   color: '#a78bfa' },
        ].map(c => (
          <div key={c.key}
            onClick={() => setFilter(filter === c.key ? 'all' : c.key)}
            style={{
              flex: 1, textAlign: 'center', padding: '6px 4px',
              background: filter === c.key ? `${c.color}16` : 'rgba(255,255,255,0.03)',
              border: `1px solid ${filter === c.key ? `${c.color}35` : 'rgba(255,255,255,0.12)'}`,
              borderRadius: '10px', cursor: 'pointer', transition: 'all 0.15s',
            }}
          >
            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '13px', color: c.color, lineHeight: 1 }}>
              {counts[c.key]}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#7a8ba0', letterSpacing: '0.08em', marginTop: '2px' }}>
              {c.label}
            </div>
          </div>
        ))}
      </div>

      <div style={{ padding: '10px 14px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', fontWeight: 600, color: '#93a4b8', letterSpacing: '0.12em' }}>
          ENGAGED UNITS · {filteredUnits.length}
        </span>
        {filter !== 'all' && (
          <button onClick={() => setFilter('all')} style={{ background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '8px', color: '#93a4b8', letterSpacing: '0.06em' }}>
            CLEAR ×
          </button>
        )}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0, padding: '0 12px 10px' }}>
        {!selectedIncidentId ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#7a8ba0', letterSpacing: '0.06em' }}>
            SELECT AN INCIDENT TO VIEW DEPLOYED UNITS
          </div>
        ) : filteredUnits.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: '10px', color: '#7a8ba0', letterSpacing: '0.06em' }}>
            NO ACTIVE UNITS FOR THIS INCIDENT
          </div>
        ) : (
          filteredUnits.map(u => (
            <UnitRow
              key={u.id}
              unit={u}
              confirmedLoadouts={confirmedLoadouts}
              onUnitClick={onUnitClick}
            />
          ))
        )}
      </div>
    </div>
  )
}
