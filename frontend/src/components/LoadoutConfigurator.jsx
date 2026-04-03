import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { getLoadoutAdvice } from '../api/client'

const UNIT_ICON = {
  engine: '🚒', hand_crew: '👥', dozer: '🚜', water_tender: '🚛',
  helicopter: '🚁', air_tanker: '✈️', command_unit: '📡', rescue: '🚑',
}

const UNIT_CAPACITY = {
  engine:       { water_gal: 500,  foam_pct_max: 6,  has_retardant: false },
  water_tender: { water_gal: 4000, foam_pct_max: 3,  has_retardant: false },
  helicopter:   { water_gal: 300,  foam_pct_max: 1,  has_retardant: false },
  air_tanker:   { water_gal: 0,    foam_pct_max: 0,  has_retardant: true  },
  hand_crew:    { water_gal: 0,    foam_pct_max: 0,  has_retardant: false },
  dozer:        { water_gal: 0,    foam_pct_max: 0,  has_retardant: false },
  command_unit: { water_gal: 0,    foam_pct_max: 0,  has_retardant: false },
  rescue:       { water_gal: 0,    foam_pct_max: 0,  has_retardant: false },
}

const EQUIPMENT_OPTIONS = {
  engine:       ['Chainsaw', 'Hand tools (Pulaskis, McLeods)', 'Drip torch', 'Foam proportioner', 'Water thief / gated wye', 'Salvage covers', 'Medical kit (ALS)', 'Thermal imaging camera', 'Portable pump', 'Extra hose (100ft sections)'],
  hand_crew:    ['Chainsaws (2×)', 'Hand tools (full set)', 'Drip torches (2×)', 'Fusees / flares', 'Medical kit (ALS)', 'Portable radio (extra)', 'Water bladder bags (4×)', 'Crew shelter (individual)', 'Headlamps (night ops)', 'GPS units'],
  dozer:        ['Dozer blade (standard)', 'Brush guard', 'Fire shelter (operator)', 'Medical kit', 'GPS / mapping unit', 'Portable radio', 'Extra fuel (jerry cans)', 'Tool kit'],
  water_tender: ['Portable tank (3000 gal)', 'Foam system', 'Extra hose (200ft)', 'Portable pump', 'Nozzles (varied)', 'Water thief', 'Medical kit', 'Portable radio'],
  helicopter:   ['Helibucket (300 gal)', 'Belly tank', 'Hoist / rescue equipment', 'IR / FLIR camera', 'Medical kit (flight medic)', 'Night vision (NVG)', 'Cargo net / sling', 'Extra fuel (ferry cans)'],
  air_tanker:   ['Fire retardant (Phos-Chek)', 'Water load', 'Foam additive', 'Air tactical radio package', 'GPS / terrain mapping'],
  command_unit: ['Satellite comms', 'Radio repeater', 'Weather station (portable)', 'Drone / UAV', 'GIS / mapping laptop', 'Generator', 'Medical kit', 'Command board / whiteboard'],
  rescue:       ['ALS medical kit', 'Extrication tools (Jaws of Life)', 'Backboard / stretcher', 'Oxygen / airway kit', 'IV supplies', 'Burn treatment kit', 'Portable radio', 'GPS unit'],
}

function SliderRow({ label, value, min, max, unit, color, onChange, disabled }) {
  if (disabled) return null
  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#8b9bb0', letterSpacing: '0.04em' }}>
          {label}
        </span>
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '12px', color }}>
          {value}{unit}
        </span>
      </div>
      <div style={{ position: 'relative' }}>
        <div style={{ height: '3px', background: 'rgba(255,255,255,0.07)', borderRadius: '2px', marginBottom: '2px' }}>
          <div style={{ height: '100%', width: `${((value - min) / (max - min)) * 100}%`, background: color, borderRadius: '2px', transition: 'width 0.2s' }} />
        </div>
        <input
          type="range" min={min} max={max} step={1} value={value}
          onChange={e => onChange(parseInt(e.target.value))}
          style={{ position: 'absolute', top: '-6px', left: 0, width: '100%', opacity: 0, cursor: 'pointer', height: '16px' }}
        />
      </div>
    </div>
  )
}

function UnitLoadoutCard({ unit, loadout, aiLoadout, isAiApplied, onUpdate, onApplyAI }) {
  const cap = UNIT_CAPACITY[unit.unit_type] ?? { water_gal: 0, foam_pct_max: 0, has_retardant: false }
  const hasWater = cap.water_gal > 0
  const hasFoam  = cap.foam_pct_max > 0
  const hasRetardant = cap.has_retardant
  const hasEquipment = (EQUIPMENT_OPTIONS[unit.unit_type] ?? []).length > 0
  const equipOptions = EQUIPMENT_OPTIONS[unit.unit_type] ?? []

  const waterGal = hasWater ? Math.round((loadout.water_pct / 100) * cap.water_gal) : 0
  const aiApplied = isAiApplied

  return (
    <div style={{
      background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: '16px', padding: '14px 15px', marginBottom: '10px',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)',
    }}>
      {/* Unit header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
        <span style={{ fontSize: '16px' }}>{UNIT_ICON[unit.unit_type] ?? '◉'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#d4dce8' }}>
            {unit.designation}
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#8b9bb0' }}>
            {unit.unit_type.replace(/_/g, ' ').toUpperCase()}
            {hasWater && <span style={{ color: '#38bdf8' }}> · {waterGal.toLocaleString()} gal loaded</span>}
          </div>
        </div>
        {aiLoadout && (
          <button
            onClick={onApplyAI}
            style={{
              background: aiApplied ? 'rgba(245,110,15,0.15)' : 'rgba(245,110,15,0.08)',
              border: `1px solid ${aiApplied ? '#ff4d1a' : '#ff4d1a44'}`,
              borderRadius: '10px', padding: '4px 9px', cursor: 'pointer',
              fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px',
              color: aiApplied ? '#ff4d1a' : '#ff4d1aaa', letterSpacing: '0.04em',
            }}
          >
            {aiApplied ? '⬡ AI APPLIED' : '⬡ APPLY AI'}
          </button>
        )}
      </div>

      {/* Sliders */}
      {hasWater && (
        <SliderRow
          label="WATER TANK" value={loadout.water_pct} min={0} max={100} unit="%" color="#38bdf8"
          onChange={v => onUpdate({ ...loadout, water_pct: v })}
        />
      )}
      {hasFoam && (
        <SliderRow
          label="FOAM CONCENTRATE" value={loadout.foam_pct} min={0} max={cap.foam_pct_max} unit="%" color="#22c55e"
          onChange={v => onUpdate({ ...loadout, foam_pct: v })}
        />
      )}
      {hasRetardant && (
        <SliderRow
          label="RETARDANT LOAD" value={loadout.retardant_pct} min={0} max={100} unit="%" color="#ff4d1a"
          onChange={v => onUpdate({ ...loadout, retardant_pct: v })}
        />
      )}

      {/* No sliders for this unit type */}
      {!hasWater && !hasFoam && !hasRetardant && (
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#8b9bb0', marginBottom: '10px' }}>
          No fluid loadout — configure equipment below.
        </div>
      )}

      {/* AI rationale — always shown, prominent */}
      <div style={{
        background: aiLoadout?.rationale ? 'rgba(245,110,15,0.08)' : '#1B1B1E',
        border: `1px solid ${aiLoadout?.rationale ? '#ff4d1a33' : 'rgba(255,255,255,0.07)'}`,
        borderRadius: '12px', padding: '8px 10px', marginBottom: '10px',
      }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.06em', marginBottom: '4px' }}>
          ⬡ AI RECOMMENDATION
        </div>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: aiLoadout?.rationale ? '#FBFBFB' : '#555', lineHeight: 1.6 }}>
          {aiLoadout?.rationale ?? 'Analyzing...'}
        </div>
      </div>

      {/* Equipment checklist */}
      {hasEquipment && (
        <div>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.06em', marginBottom: '6px' }}>
            EQUIPMENT MANIFEST
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {equipOptions.map(item => {
              const checked = (loadout.equipment ?? []).includes(item)
              const aiChecked = aiLoadout && (aiLoadout.equipment ?? []).includes(item)
              const note = aiLoadout?.equipment_notes?.[item] ?? null
              const aiRecommends = aiChecked
              const borderColor = checked ? '#22c55e' : aiRecommends ? '#ff4d1a44' : 'rgba(255,255,255,0.07)'
              return (
                <div key={item}
                  onClick={() => {
                    const eq = loadout.equipment ?? []
                    onUpdate({ ...loadout, equipment: checked ? eq.filter(e => e !== item) : [...eq, item] })
                  }}
                  style={{
                    display: 'flex', alignItems: 'flex-start', gap: '8px',
                    padding: '7px 9px', borderRadius: '10px', cursor: 'pointer',
                    border: `1px solid ${borderColor}`,
                    background: checked ? 'rgba(74,222,128,0.06)' : aiRecommends ? 'rgba(245,110,15,0.04)' : 'transparent',
                    transition: 'all 0.1s',
                  }}
                >
                  <div style={{
                    width: '14px', height: '14px', borderRadius: '2px', flexShrink: 0, marginTop: '1px',
                    border: `1px solid ${checked ? '#22c55e' : '#333'}`,
                    background: checked ? 'rgba(74,222,128,0.2)' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {checked && <span style={{ color: '#22c55e', fontSize: '10px', lineHeight: 1 }}>✓</span>}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: checked ? '#FBFBFB' : '#c3d0df', fontWeight: checked ? 600 : 400 }}>
                        {item}
                      </span>
                      {aiRecommends && !checked && (
                        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#ff4d1a', fontWeight: 700, letterSpacing: '0.03em' }}>⬡ TAKE</span>
                      )}
                      {!aiRecommends && checked && (
                        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '9px', color: '#8b9bb0', letterSpacing: '0.03em' }}>MANUAL</span>
                      )}
                    </div>
                    {note && (
                      <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: aiRecommends ? '#ff4d1aaa' : '#555', marginTop: '2px', lineHeight: 1.4 }}>
                        {note}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default function LoadoutConfigurator({ incident, selectedUnits, units, onConfirm, onBack }) {
  const [aiResult,   setAiResult]   = useState(null)
  const [aiLoading,  setAiLoading]  = useState(false)
  const [aiError,    setAiError]    = useState(false)
  const [overrides,     setOverrides]     = useState({})
  // Explicit set of unit IDs where AI loadout is currently applied
  const [appliedUnits,  setAppliedUnits]  = useState(new Set())

  const selectedUnitObjects = units.filter(u => selectedUnits.includes(u.id))

  // Reset on unit selection change
  useEffect(() => {
    setAiResult(null)
    setAiError(false)
    setOverrides({})
    setAppliedUnits(new Set())
    fetchAI()
  }, [selectedUnits.join(',')])  // eslint-disable-line react-hooks/exhaustive-deps

  // Find AI loadout for a unit — tolerates string/number id mismatch from Claude
  function findAiLoadout(unit) {
    return aiResult?.loadouts?.find(
      a => String(a.unit_id) === String(unit.id) ||
           a.designation === unit.designation
    ) ?? null
  }

  async function fetchAI() {
    setAiLoading(true)
    setAiError(false)
    try {
      const result = await getLoadoutAdvice(incident.id, selectedUnits)
      setAiResult(result)
      // Auto-apply: seed overrides keyed by actual unit.id (not Claude's returned unit_id)
      const seed = {}
      for (const unit of selectedUnitObjects) {
        const al = result.loadouts.find(
          a => String(a.unit_id) === String(unit.id) ||
               a.designation === unit.designation
        )
        if (al) {
          seed[unit.id] = {
            water_pct:     al.water_pct,
            foam_pct:      al.foam_pct,
            retardant_pct: al.retardant_pct,
            equipment:     al.equipment ?? [],
          }
        }
      }
      setOverrides(seed)
      setAppliedUnits(new Set(Object.keys(seed)))
    } catch {
      setAiError(true)
      // Seed defaults so sliders work even without AI
      const defaults = {}
      for (const unit of selectedUnitObjects) {
        defaults[unit.id] = { water_pct: 100, foam_pct: 0, retardant_pct: 0, equipment: [] }
      }
      setOverrides(defaults)
    } finally {
      setAiLoading(false)
    }
  }

  function applyAllAI() {
    if (!aiResult) return
    // Key by actual unit.id to guarantee match with overrides lookup
    const applied = {}
    for (const unit of selectedUnitObjects) {
      const al = findAiLoadout(unit)
      if (al) {
        applied[unit.id] = {
          water_pct:     al.water_pct,
          foam_pct:      al.foam_pct,
          retardant_pct: al.retardant_pct,
          equipment:     al.equipment ?? [],
        }
      }
    }
    setOverrides(applied)
    setAppliedUnits(new Set(Object.keys(applied)))
  }

  // Merge AI values with user overrides to get effective loadout per unit
  function getLoadout(unit) {
    const ai = findAiLoadout(unit)
    const ov = overrides[unit.id] ?? {}
    return {
      unit_id:       unit.id,
      unit_type:     unit.unit_type,
      designation:   unit.designation,
      water_pct:     ov.water_pct     ?? ai?.water_pct     ?? 100,
      foam_pct:      ov.foam_pct      ?? ai?.foam_pct      ?? 0,
      retardant_pct: ov.retardant_pct ?? ai?.retardant_pct ?? 0,
      equipment:     ov.equipment     ?? ai?.equipment     ?? [],
    }
  }

  const finalLoadouts = selectedUnitObjects.map(getLoadout)

  return createPortal(
    <div style={{
      position: 'fixed', inset: 0, zIndex: 5300,
      background: 'rgba(5,8,12,0.68)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      backdropFilter: 'blur(10px)',
    }} onClick={e => { if (e.target === e.currentTarget) onBack?.() }}>
      <div style={{
      width: 'min(760px, calc(100vw - 40px))',
      height: 'min(760px, calc(100vh - 56px))',
      background: 'rgba(20,26,36,0.97)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: '22px',
      display: 'flex', flexDirection: 'column',
      zIndex: 1100,
      animation: 'slideInUp 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
      boxShadow: '0 30px 70px rgba(0,0,0,0.55)',
      overflow: 'hidden',
      backdropFilter: 'blur(16px)',
    }}>

      {/* Header */}
      <div style={{ padding: '16px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
          <button
            onClick={onBack}
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', color: '#7a8ba0', cursor: 'pointer', fontSize: '14px', padding: '6px 10px', borderRadius: '10px' }}
          >
            ←
          </button>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '14px', color: '#d4dce8' }}>
              Loadout Configurator
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#8b9bb0' }}>
              {selectedUnitObjects.length} unit{selectedUnitObjects.length !== 1 ? 's' : ''} · {incident.name}
            </div>
          </div>
          <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.06em' }}>
            ⬡ PYRA AI
          </span>
        </div>

        {/* AI strategy banner */}
        {aiLoading && (
          <div style={{ background: 'rgba(245,110,15,0.08)', border: '1px solid #ff4d1a33', borderRadius: '3px', padding: '7px 10px', marginTop: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#ff4d1a', boxShadow: '0 0 4px #ff4d1a' }} />
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#ff4d1a' }}>
                AI analyzing incident conditions...
              </span>
            </div>
          </div>
        )}
        {aiResult?.overall_strategy && !aiLoading && (
          <div style={{ background: 'rgba(245,110,15,0.08)', border: '1px solid #ff4d1a33', borderRadius: '3px', padding: '7px 10px', marginTop: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', lineHeight: 1.5, flex: 1 }}>
                <span style={{ fontWeight: 700, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.04em' }}>⬡ AI STRATEGY · </span>
                {aiResult.overall_strategy}
              </div>
              <button
                onClick={applyAllAI}
                style={{ background: 'rgba(245,110,15,0.15)', border: '1px solid #ff4d1a', borderRadius: '3px', padding: '3px 8px', cursor: 'pointer', fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '9px', color: '#ff4d1a', letterSpacing: '0.04em', flexShrink: 0 }}
              >
                APPLY ALL
              </button>
            </div>
          </div>
        )}
        {aiError && (
          <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid #ef444433', borderRadius: '3px', padding: '7px 10px', marginTop: '8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#ef4444' }}>
              AI unavailable — defaults applied
            </span>
            <button onClick={fetchAI} style={{ background: 'none', border: '1px solid #ef444444', borderRadius: '3px', padding: '2px 8px', cursor: 'pointer', fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#ef4444' }}>
              RETRY
            </button>
          </div>
        )}
      </div>

      {/* Scrollable unit cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>
        {selectedUnitObjects.map(unit => {
          const loadout   = getLoadout(unit)
          const aiLoadout = findAiLoadout(unit)
          return (
            <UnitLoadoutCard
              key={unit.id}
              unit={unit}
              loadout={loadout}
              aiLoadout={aiLoadout}
              isAiApplied={appliedUnits.has(String(unit.id))}
              onApplyAI={() => {
                if (!aiLoadout) return
                setOverrides(prev => ({
                  ...prev,
                  [unit.id]: {
                    water_pct:     aiLoadout.water_pct,
                    foam_pct:      aiLoadout.foam_pct,
                    retardant_pct: aiLoadout.retardant_pct,
                    equipment:     aiLoadout.equipment ?? [],
                  }
                }))
                setAppliedUnits(prev => new Set([...prev, String(unit.id)]))
              }}
              onUpdate={updated => {
                setOverrides(prev => ({
                  ...prev,
                  [unit.id]: {
                    water_pct:     updated.water_pct,
                    foam_pct:      updated.foam_pct,
                    retardant_pct: updated.retardant_pct,
                    equipment:     updated.equipment,
                  }
                }))
                // User manually edited — clear AI applied badge for this unit
                setAppliedUnits(prev => {
                  const next = new Set(prev)
                  next.delete(String(unit.id))
                  return next
                })
              }}
            />
          )
        })}
      </div>

      {/* Confirm footer */}
      <div style={{ padding: '14px 18px 18px', borderTop: '1px solid rgba(255,255,255,0.08)', flexShrink: 0, background: 'rgba(255,255,255,0.03)' }}>
        <button
          onClick={() => onConfirm(finalLoadouts)}
          style={{
            width: '100%', padding: '12px',
            background: '#ff4d1a', border: 'none', borderRadius: '14px',
            cursor: 'pointer', fontFamily: 'var(--font-sans)',
            fontWeight: 700, fontSize: '13px', color: '#d4dce8',
            letterSpacing: '0.03em',
            boxShadow: '0 14px 28px rgba(255,77,26,0.28)',
          }}
        >
          CONFIRM LOADOUT & DISPATCH {selectedUnitObjects.length} UNIT{selectedUnitObjects.length !== 1 ? 'S' : ''}
        </button>
        <button
          onClick={onBack}
          style={{
            width: '100%', padding: '9px', marginTop: '6px',
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: '12px', cursor: 'pointer',
            fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#c3d0df',
          }}
        >
          ← BACK TO UNIT SELECTION
        </button>
      </div>
      </div>
    </div>
  , document.body)
}
