import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'

const STATUS_COLOR = {
  available:      '#4ade80',
  en_route:       '#60a5fa',
  on_scene:       '#F56E0F',
  staging:        '#facc15',
  returning:      '#a78bfa',
  out_of_service: '#878787',
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

const UNIT_CAPACITY = {
  engine:       { water_gal: 500,  foam_pct_max: 6  },
  water_tender: { water_gal: 4000, foam_pct_max: 3  },
  helicopter:   { water_gal: 300,  foam_pct_max: 1  },
  air_tanker:   { water_gal: 0,    foam_pct_max: 0  },
  hand_crew:    { water_gal: 0,    foam_pct_max: 0  },
  dozer:        { water_gal: 0,    foam_pct_max: 0  },
  command_unit: { water_gal: 0,    foam_pct_max: 0  },
  rescue:       { water_gal: 0,    foam_pct_max: 0  },
}

const MAP_VIEWS = [
  { id: 'live',  icon: '⬡', label: 'Live Map',   desc: 'Fires + Units' },
  { id: 'fires', icon: '🔥', label: 'Fires Only', desc: 'Incidents & Risk' },
  { id: 'units', icon: '◈', label: 'Units Only',  desc: 'All Resources' },
]


function UnitLoadoutTooltip({ unit, loadout, rect }) {
  if (!loadout || !rect) return null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}
  const hasWater     = cap.water_gal > 0
  const hasFoam      = cap.foam_pct_max > 0
  const hasRetardant = unit.unit_type === 'air_tanker'
  const waterGal     = hasWater ? Math.round((loadout.water_pct / 100) * cap.water_gal) : 0
  const equipment    = loadout.equipment ?? []
  // Decide whether to render left or right of the card based on horizontal position
  const renderLeft = rect.left > window.innerWidth / 2
  const tooltipStyle = renderLeft
    ? { right: window.innerWidth - rect.left + 8, left: 'auto' }
    : { left: rect.right + 8 }

  return createPortal(
    <div style={{
      position: 'fixed',
      top: rect.top + rect.height / 2,
      transform: 'translateY(-50%)',
      width: '230px',
      zIndex: 99999,
      background: '#1B1B1E',
      border: '1px solid #F56E0F66',
      borderRadius: '4px',
      padding: '10px 12px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.7)',
      pointerEvents: 'none',
      ...tooltipStyle,
    }}>
      {/* Arrow */}
      {renderLeft ? (
        <div style={{ position: 'absolute', right: '-5px', top: '50%', transform: 'translateY(-50%)', width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderLeft: '5px solid #F56E0F66' }} />
      ) : (
        <div style={{ position: 'absolute', left: '-5px', top: '50%', transform: 'translateY(-50%)', width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderRight: '5px solid #F56E0F66' }} />
      )}

      <div style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '9px', color: '#F56E0F', letterSpacing: '0.06em', marginBottom: '8px' }}>
        ⬡ CONFIRMED LOADOUT · {unit.designation}
      </div>

      {hasWater && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>WATER</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#60a5fa' }}>
              {waterGal.toLocaleString()} gal ({loadout.water_pct}%)
            </span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', width: `${loadout.water_pct}%`, background: '#60a5fa', borderRadius: '2px' }} />
          </div>
        </div>
      )}
      {hasFoam && loadout.foam_pct > 0 && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>FOAM</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#4ade80' }}>{loadout.foam_pct}%</span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', width: `${(loadout.foam_pct / cap.foam_pct_max) * 100}%`, background: '#4ade80', borderRadius: '2px' }} />
          </div>
        </div>
      )}
      {hasRetardant && loadout.retardant_pct > 0 && (
        <div style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#878787' }}>RETARDANT</span>
            <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 700, fontSize: '10px', color: '#F56E0F' }}>{loadout.retardant_pct}%</span>
          </div>
          <div style={{ height: '3px', background: '#262626', borderRadius: '2px' }}>
            <div style={{ height: '100%', width: `${loadout.retardant_pct}%`, background: '#F56E0F', borderRadius: '2px' }} />
          </div>
        </div>
      )}
      {equipment.length > 0 && (
        <div style={{ marginTop: '8px', borderTop: '1px solid #262626', paddingTop: '8px' }}>
          <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#878787', letterSpacing: '0.04em', marginBottom: '5px' }}>
            EQUIPMENT ({equipment.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            {equipment.map(item => (
              <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ color: '#4ade80', fontSize: '9px', flexShrink: 0 }}>✓</span>
                <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#FBFBFB', lineHeight: 1.3 }}>{item}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>,
    document.body
  )
}

function UnitCard({ unit, confirmedLoadouts, onUnitClick }) {
  const [tooltipRect, setTooltipRect] = useState(null)
  const loadout = confirmedLoadouts[unit.id] ?? null
  const cap = UNIT_CAPACITY[unit.unit_type] ?? {}

  return (
    <>
      {tooltipRect && <UnitLoadoutTooltip unit={unit} loadout={loadout} rect={tooltipRect} />}
      <div
        onClick={() => onUnitClick?.(unit)}
        style={{
          padding: '6px 8px', marginBottom: '4px',
          background: '#1B1B1E', borderRadius: '3px',
          border: `1px solid ${loadout ? '#F56E0F33' : '#262626'}`,
          cursor: 'pointer', transition: 'border-color 0.15s',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = '#F56E0F'
          if (loadout) setTooltipRect(e.currentTarget.getBoundingClientRect())
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = loadout ? '#F56E0F33' : '#262626'
          setTooltipRect(null)
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
          <span style={{ fontSize: '12px' }}>{TYPE_ICON[unit.unit_type] ?? '◉'}</span>
          <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '13px', color: '#FBFBFB' }}>
            {unit.designation}
          </span>
          {loadout ? (
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '8px', color: '#F56E0F', fontWeight: 700, marginLeft: 'auto', letterSpacing: '0.04em' }}>⬡ LOADED</span>
          ) : (
            <span style={{ fontFamily: 'Inter, sans-serif', fontSize: '9px', color: '#878787', marginLeft: 'auto' }}>📍</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: loadout ? '3px' : '0' }}>
          <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: STATUS_COLOR[unit.status] ?? '#878787', flexShrink: 0 }} />
          <span style={{ fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '11px', color: STATUS_COLOR[unit.status] ?? '#878787', letterSpacing: '0.02em' }}>
            {unit.status.replace(/_/g, ' ').toUpperCase()}
          </span>
        </div>
        {loadout && (() => {
          const parts = []
          if (cap.water_gal) parts.push(`${Math.round((loadout.water_pct / 100) * cap.water_gal).toLocaleString()} gal`)
          if (loadout.foam_pct > 0) parts.push(`${loadout.foam_pct}% foam`)
          if (loadout.retardant_pct > 0) parts.push(`${loadout.retardant_pct}% retardant`)
          const eqCount = (loadout.equipment ?? []).length
          return (
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '10px', color: '#60a5fa', lineHeight: 1.4 }}>
              {parts.join(' · ')}
              {eqCount > 0 && <span style={{ color: '#878787' }}> · {eqCount} items</span>}
            </div>
          )
        })()}
      </div>
    </>
  )
}

export default function LeftSidebar({ units, activeView, onViewChange, selectedIncidentId, onUnitClick, confirmedLoadouts = {} }) {
  const incidentUnits  = units.filter(u => u.assigned_incident_id === selectedIncidentId)
  const availableUnits = units.filter(u => u.status === 'available')

  return (
    <div style={{
      width: 'min(200px, 20vw)', minWidth: '160px',
      background:  '#151419',
      borderRight: '1px solid #262626',
      display:     'flex',
      flexDirection: 'column',
      flexShrink:  0,
      overflow:    'hidden',
    }}>

      {/* Monitor section */}
      <div style={{ padding: '14px 14px 5px', fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#878787', letterSpacing: '0.02em' }}>
        MONITOR
      </div>

      {MAP_VIEWS.map(view => {
        const isActive = activeView === view.id
        return (
          <button
            key={view.id}
            onClick={() => onViewChange(view.id)}
            style={{
              width: '100%', textAlign: 'left',
              padding: '7px 14px',
              display: 'flex', alignItems: 'center', gap: '8px',
              background:   isActive ? 'rgba(245,110,15,0.12)' : 'none',
              border:       'none',
              borderLeft:   isActive ? '2px solid #F56E0F' : '2px solid transparent',
              cursor:       'pointer',
              fontFamily:   'Inter, sans-serif',
              fontWeight:   600,
              fontSize:     '13px',
              color:        isActive ? '#F56E0F' : '#FBFBFB',
              letterSpacing:'0.05em',
              transition:   'all 0.15s',
            }}
          >
            <span style={{ fontSize: '13px', width: '18px', textAlign: 'center', flexShrink: 0 }}>{view.icon}</span>
            <div>
              <div>{view.label}</div>
              <div style={{ fontSize: '10px', color: isActive ? '#F56E0F' : '#878787', fontWeight: 400 }}>
                {view.desc}
              </div>
            </div>
          </button>
        )
      })}

      <div style={{ height: '1px', background: '#262626', margin: '8px 0' }} />

      {/* Units on incident */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '6px 14px 8px', fontFamily: 'Inter, sans-serif', fontWeight: 600, fontSize: '11px', color: '#878787', letterSpacing: '0.02em' }}>
          UNITS ON INCIDENT
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {incidentUnits.length === 0 && (
            <div style={{ fontFamily: 'Inter, sans-serif', fontSize: '12px', color: '#878787', padding: '8px 6px' }}>
              No units assigned
            </div>
          )}
          {incidentUnits.map(unit => (
            <UnitCard
              key={unit.id}
              unit={unit}
              confirmedLoadouts={confirmedLoadouts}
              onUnitClick={onUnitClick}
            />
          ))}
        </div>

        <div style={{ padding: '8px 14px', borderTop: '1px solid #262626', fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '12px', color: '#878787' }}>
          <span style={{ color: '#4ade80', fontWeight: 700 }}>{availableUnits.length}</span> units available
        </div>
      </div>

    </div>
  )
}