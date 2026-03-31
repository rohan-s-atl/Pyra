import { useEffect, useState, useCallback, useRef } from 'react'
import { AuthContext } from './context/AuthContext'
import TopBar from './components/TopBar'
import IncidentMap from './components/IncidentMap'
import LeftSidebar from './components/LeftSidebar'
import { FireGrowthLegend } from './components/FireGrowthOverlay'
import { EvacZonesPanel, exportEvacZones } from './components/EvacZonesOverlay'
import RightPanel from './components/RightPanel'
import IncidentDetailPanel from './components/IncidentDetailPanel'
import LoginScreen from './components/LoginScreen'
import AuditLogPanel from './components/AuditLogPanel'
import MultiIncidentPanel from './components/MultiIncidentPanel'
import { ToastContainer, useToastProvider } from './components/Toast'
import SettingsPanel from './components/SettingsPanel'
import WeatherPanel from './components/WeatherPanel'
import { api, setAuthToken } from './api/client'

export default function App() {
  const [auth,            setAuth]            = useState(null)
  const [incidents,       setIncidents]       = useState([])
  const [alerts,          setAlerts]          = useState([])
  const [units,           setUnits]           = useState([])
  const [selectedId,      setSelectedId]      = useState(null)
  // Containment modal — shown when a fire reaches 100% containment
  const [containmentModal, setContainmentModal] = useState(null) // { incidentName, alertId }
  const _seenContainmentAlerts = useRef(new Set())
  const [activeView,      setActiveView]      = useState('live')
  const [detailOpen,      setDetailOpen]      = useState(false)
  const [focusedUnit,     setFocusedUnit]     = useState(null)
  const [focusedIncident, setFocusedIncident] = useState(null)
  const [unitRoutes,      setUnitRoutes]      = useState([])
  const [showPerimeters,  setShowPerimeters]  = useState(false)
  const [showHeatmap,     setShowHeatmap]     = useState(false)
  const [showAudit,       setShowAudit]       = useState(false)
  const [showCommand,     setShowCommand]     = useState(false)
  const [showSettings,    setShowSettings]    = useState(false)
  const [showWeather,     setShowWeather]     = useState(false)
  const [showSatellite,   setShowSatellite]   = useState(false)
  const [showFireGrowth,  setShowFireGrowth]  = useState(false)
  const [fireGrowthData,  setFireGrowthData]  = useState(null)
  const [fireGrowthTimeMode, setFireGrowthTimeMode] = useState('standard')  // 'standard' | 'short'
  const [showEvacZones,   setShowEvacZones]   = useState(false)
  const [evacZonesData,   setEvacZonesData]   = useState(null)
  const [evacZonesLoading, setEvacZonesLoading] = useState(false)
  const [activeEvacZones, setActiveEvacZones] = useState({ order: true, warning: true, watch: true })
  const [showWaterSources, setShowWaterSources] = useState(false)
  const [waterSourceStatus, setWaterSourceStatus] = useState(null) // {loading, noResults, count}
  const selectedIncidentForGrowth = incidents.find(i => i.id === selectedId) ?? null
  const selectedFireGrowthKey = selectedIncidentForGrowth
    ? [
        selectedIncidentForGrowth.id,
        selectedIncidentForGrowth.fire_type,
        selectedIncidentForGrowth.wind_speed_mph,
        selectedIncidentForGrowth.humidity_percent,
        selectedIncidentForGrowth.slope_percent,
        selectedIncidentForGrowth.spread_risk,
        selectedIncidentForGrowth.aqi,
        selectedIncidentForGrowth.spread_direction,
        selectedIncidentForGrowth.acres_burned,
      ].join(':')
    : ''

  // Fetch evac zones data whenever toggle turns on or incident changes
  useEffect(() => {
    if (!showEvacZones || !selectedId) { setEvacZonesData(null); return }
    setEvacZonesLoading(true)
    api.evacZones(selectedId)
      .then(d => { setEvacZonesData(d); setEvacZonesLoading(false) })
      .catch(() => { setEvacZonesData(null); setEvacZonesLoading(false) })
  }, [showEvacZones, selectedId])

  // Fetch fire growth data whenever the toggle turns on or selected incident changes
  useEffect(() => {
    if (!showFireGrowth || !selectedId) { setFireGrowthData(null); return }
    const minutes = fireGrowthTimeMode === 'short' ? 60 : null
    api.fireGrowth(selectedId, minutes)
      .then(setFireGrowthData)
      .catch(() => setFireGrowthData(null))
  }, [showFireGrowth, selectedId, fireGrowthTimeMode, selectedFireGrowthKey])
  const [loading,         setLoading]         = useState(false)
  const [error,           setError]           = useState(null)
  const [windowWidth,     setWindowWidth]     = useState(window.innerWidth)
  const { toasts } = useToastProvider()

  // ── Track window resize for responsive scaling ───────────────────────────
  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // ── Auth ─────────────────────────────────────────────────────────────────
  function handleLogin(data) {
    setAuth(data)
    setAuthToken(data.access_token)
  }

  function handleLogout() {
    setAuth(null)
    setAuthToken(null)
    setIncidents([])
    setAlerts([])
    setUnits([])
    setSelectedId(null)
    setError(null)
  }

  // ── Stable refresh callbacks (no stale closure in polling interval) ──────
  const refreshAlerts    = useCallback(() => api.alerts().then(newAlerts => {
    setAlerts(newAlerts)
    // Detect new containment_complete alerts and trigger modal
    for (const alert of newAlerts) {
      if (
        alert.alert_type === 'containment_complete' &&
        !alert.is_acknowledged &&
        !_seenContainmentAlerts.current.has(alert.id)
      ) {
        _seenContainmentAlerts.current.add(alert.id)
        const incident = incidents.find(i => i.id === alert.incident_id)
        setContainmentModal({
          incidentName: incident?.name ?? alert.title,
          alertId: alert.id,
        })
        break  // show one modal at a time
      }
    }
  }).catch(() => {}), [incidents])
  const refreshUnits = useCallback(() =>
    api.units().then(newUnits => {
      setUnits(newUnits)
      // Clear loadout when unit starts returning (resources expended on scene)
      // or when it becomes available again — either way it's empty
      setConfirmedLoadouts(prev => {
        const next = { ...prev }
        let changed = false
        for (const unit of newUnits) {
          if ((unit.status === 'available' || unit.status === 'returning') && next[String(unit.id)]) {
            delete next[String(unit.id)]
            changed = true
          }
        }
        return changed ? next : prev
      })
    }).catch(() => {}),
  [])
  const refreshIncidents = useCallback(() => api.incidents().then(setIncidents).catch(() => {}), [])

  // Debounced alert refresh — prevents multiple in-flight requests when dispatch
  // events fire rapidly (e.g. bulk dispatch triggers several onAlertsChanged calls)
  const refreshAlertsDebounced = useCallback(() => {
    if (refreshAlertsDebounced._timer) clearTimeout(refreshAlertsDebounced._timer)
    refreshAlertsDebounced._timer = setTimeout(() => {
      refreshAlerts()
      refreshAlertsDebounced._timer = null
    }, 800)
  }, [refreshAlerts])

  // ── Initial load — only run AFTER auth ───────────────────────────────────
  useEffect(() => {
    if (!auth) return

    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [inc, alt, unt] = await Promise.all([
          api.incidents(), api.alerts(), api.units(),
        ])
        if (cancelled) return
        setIncidents(inc)
        setAlerts(alt)
        setUnits(unt)
        setSelectedId(prev => (prev == null && inc.length > 0 ? inc[0].id : prev))
      } catch {
        if (!cancelled) setError('Could not connect to the Pyra backend.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [auth])

  // ── Polling — only run AFTER auth ────────────────────────────────────────
  useEffect(() => {
    if (!auth) return

    // Stagger polling: units fast (map movement), incidents medium, alerts slow
    // IncidentMap no longer has its own poll — units come from here only.
    const unitId     = setInterval(refreshUnits,     4_000)   // unit positions every 4s
    const incidentId = setInterval(refreshIncidents, 10_000)  // incidents every 10s
    const alertId    = setInterval(refreshAlerts,    30_000)  // alerts every 30s
    const id = { clear: () => { clearInterval(unitId); clearInterval(incidentId); clearInterval(alertId) } }
    return () => id.clear()
  }, [auth, refreshAlerts, refreshUnits, refreshIncidents])

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    function onKey(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      if (e.key === 'Escape') {
        setDetailOpen(false)
        setShowAudit(false)
        setShowCommand(false)
        setUnitRoutes([])
      }
      if (e.key === 'c' || e.key === 'C') setShowCommand(v => !v)
      if (e.key === 'm' || e.key === 'M') setShowSatellite(v => !v)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ── Handlers ─────────────────────────────────────────────────────────────
  function handleSelectIncident(id) {
    setSelectedId(id)
    setDetailOpen(true)
    setUnitRoutes([])
    const inc = incidents.find(i => i.id === id)
    if (inc) setFocusedIncident({ ...inc, _ts: Date.now() })
  }

  // Loadout data confirmed in LoadoutConfigurator — persisted so panels can show what each unit carries
  const [confirmedLoadouts, setConfirmedLoadouts] = useState({}) // unit_id -> loadout

  function handleConfirmLoadouts(loadouts) {
    setConfirmedLoadouts(prev => {
      const next = { ...prev }
      for (const l of loadouts) next[String(l.unit_id)] = l
      return next
    })
  }

  function handleDispatchSuccess() { refreshUnits() }
  function handleUnitClick(unit)   { setFocusedUnit({ ...unit, _ts: Date.now() }) }

  const selectedIncident = incidents.find(i => i.id === selectedId) ?? null

  // ── Responsive scaling using CSS transform (works in all browsers) ───────
  // Base design is 1440px wide. Scale between 0.7 and 1.0
  const uiScale = Math.min(1, Math.max(0.7, windowWidth / 1440))
  
  // For very small screens, hide sidebars
  const isCompact = windowWidth < 1024
  const showLeftSidebar = !isCompact
  const showRightPanel = !isCompact || !detailOpen

  // ── Auth gate (MUST come first) ──────────────────────────────────────────
  if (!auth) return <LoginScreen onLogin={handleLogin} />

  if (loading) return (
    <div style={{ height: '100vh', width: '100vw', background: '#0d0f11', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '16px' }}>
      <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'linear-gradient(135deg, #ff4d1a, #c0320a)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 24px rgba(255,77,26,0.4)' }}>
        <span style={{ color: '#fff', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '14px' }}>P</span>
      </div>
      <div style={{ color: '#3a4558', fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.12em', animation: 'status-blink 1.5s ease-in-out infinite' }}>
        INITIALIZING PYRA…
      </div>
    </div>
  )

  if (error) return (
    <div style={{ height: '100vh', width: '100vw', background: '#0d0f11', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ color: '#ef4444', fontFamily: 'var(--font-mono)', fontSize: '11px', textAlign: 'center', padding: '0 2rem', letterSpacing: '0.06em' }}>
        {error}
      </div>
    </div>
  )

  return (
    <AuthContext.Provider value={{ ...auth, logout: handleLogout }}>
      <div 
        style={{ 
          height: '100vh', 
          width: '100vw', 
          background: 'radial-gradient(1300px 700px at 50% -200px, rgba(56,189,248,0.08), transparent 60%), #0d0f11',
          display: 'flex', 
          flexDirection: 'column', 
          overflow: 'hidden',
          '--ui-scale': uiScale,
        }}
      >

        <TopBar
          incidents={incidents}
          units={units}
          showEvacZones={showEvacZones}
          onToggleEvacZones={() => setShowEvacZones(v => !v)}
          showFireGrowth={showFireGrowth}
          onToggleFireGrowth={() => setShowFireGrowth(v => !v)}
          showPerimeters={showPerimeters}
          onTogglePerimeters={() => setShowPerimeters(v => !v)}
          showHeatmap={showHeatmap}
          onToggleHeatmap={() => setShowHeatmap(v => !v)}
          showCommand={showCommand}
          onToggleCommand={() => setShowCommand(v => !v)}
          showSatellite={showSatellite}
          onToggleSatellite={() => setShowSatellite(v => !v)}
          showWeather={showWeather}
          onToggleWeather={() => setShowWeather(v => !v)}
          showWaterSources={showWaterSources}
          onToggleWaterSources={() => { setShowWaterSources(v => !v); setWaterSourceStatus(null) }}
          auth={auth}
          onLogout={handleLogout}
          onToggleAudit={() => setShowAudit(v => !v)}
          onToggleSettings={() => setShowSettings(v => !v)}
        />

        <div style={{ flex: 1, minHeight: 0, padding: '12px 14px 14px' }}>
          <div style={{
            position: 'relative',
            width: '100%',
            height: '100%',
            borderRadius: '24px',
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,0.1)',
            boxShadow: '0 30px 70px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06)',
          }}>
            <IncidentMap
              incidents={incidents}
              units={units}
              selectedId={selectedId}
              onSelect={handleSelectIncident}
              mapView={activeView}
              focusedUnit={focusedUnit}
              focusedIncident={focusedIncident}
              unitRoutes={unitRoutes}
              selectedIncident={selectedIncident}
              showEvacZones={showEvacZones}
              evacZonesData={evacZonesData}
              activeEvacZones={activeEvacZones}
              showFireGrowth={showFireGrowth}
              fireGrowthTimeMode={fireGrowthTimeMode}
              showPerimeters={showPerimeters}
              showHeatmap={showHeatmap}
              showCommand={showCommand}
              showSatellite={showSatellite}
              showWaterSources={showWaterSources}
              onWaterSourceStatus={setWaterSourceStatus}
            />

            {showEvacZones && (
              <EvacZonesPanel
                data={evacZonesData}
                visible={showEvacZones}
                loading={evacZonesLoading}
                onClose={() => setShowEvacZones(false)}
                onExport={(data, zones) => exportEvacZones(data, zones)}
                activeZones={activeEvacZones}
                onToggleZone={ztype => setActiveEvacZones(prev => ({ ...prev, [ztype]: !prev[ztype] }))}
              />
            )}

            {showFireGrowth && (
              <FireGrowthLegend
                data={fireGrowthData}
                visible={showFireGrowth}
                onClose={() => setShowFireGrowth(false)}
                timeMode={fireGrowthTimeMode}
                onTimeModeChange={setFireGrowthTimeMode}
              />
            )}

            {showWaterSources && waterSourceStatus && (waterSourceStatus.loading || waterSourceStatus.noResults) && (
              <div style={{
                position: 'absolute', top: '18px', left: '50%', transform: 'translateX(-50%)',
                zIndex: 1000, pointerEvents: 'none',
                background: 'rgba(13,15,17,0.82)', border: '1px solid rgba(56,189,248,0.3)',
                borderRadius: '999px', padding: '6px 16px',
                fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.07em',
                color: waterSourceStatus.loading ? '#38bdf8' : '#7a8ba0',
                backdropFilter: 'blur(12px)', whiteSpace: 'nowrap',
                boxShadow: '0 8px 18px rgba(0,0,0,0.35)',
              }}>
                {waterSourceStatus.loading ? '◎ SEARCHING WATER SOURCES…' : '◎ NO WATER SOURCES WITHIN 8 KM'}
              </div>
            )}

            {showLeftSidebar && (
              <div style={{ position: 'absolute', top: '16px', left: '16px', bottom: '16px', zIndex: 1300 }}>
                <LeftSidebar
                  units={units}
                  activeView={activeView}
                  onViewChange={setActiveView}
                  selectedIncidentId={selectedId}
                  onUnitClick={handleUnitClick}
                  confirmedLoadouts={confirmedLoadouts}
                />
              </div>
            )}

            {showRightPanel && (
              <div style={{ position: 'absolute', top: '16px', right: '16px', bottom: '16px', zIndex: 1300 }}>
                <RightPanel
                  alerts={alerts}
                  units={units}
                  incidents={incidents}
                  selectedIncidentId={selectedId}
                  onUnitClick={handleUnitClick}
                  onAlertsChanged={refreshAlertsDebounced}
                  confirmedLoadouts={confirmedLoadouts}
                />
              </div>
            )}

            {detailOpen && selectedIncident && (
              <IncidentDetailPanel
                incident={selectedIncident}
                units={units}
                allIncidents={incidents}
                onClose={() => { setDetailOpen(false); setUnitRoutes([]) }}
                onDispatchSuccess={handleDispatchSuccess}
                onUnitRoutesChange={setUnitRoutes}
                onPreviewUnits={() => {}}
                onUnitClick={handleUnitClick}
                onConfirmLoadouts={handleConfirmLoadouts}
                rightOffset={(showCommand ? 160 : 0) + (showRightPanel ? 380 : 0)}
              />
            )}
          </div>
        </div>

        {showAudit && <AuditLogPanel onClose={() => setShowAudit(false)} />}

        {showWeather && (
          <WeatherPanel incidents={incidents} onClose={() => setShowWeather(false)} />
        )}

        {showCommand && (
          <MultiIncidentPanel
            incidents={incidents}
            units={units}
            alerts={alerts}
            selectedId={selectedId}
            onSelect={handleSelectIncident}
            onClose={() => setShowCommand(false)}
          />
        )}

        <ToastContainer toasts={toasts} />
        {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}

        {/* Containment modal */}
        {containmentModal && (
          <div style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(8px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <div style={{
              background: 'rgba(13,15,17,0.96)',
              border: '1px solid rgba(34,197,94,0.35)',
              borderRadius: '12px', padding: '32px 36px', maxWidth: '380px', width: '90vw',
              boxShadow: '0 0 60px rgba(34,197,94,0.12), 0 16px 48px rgba(0,0,0,0.6)',
              backdropFilter: 'blur(16px)',
              fontFamily: 'var(--font-sans)', textAlign: 'center',
              animation: 'fade-up 0.3s ease-out',
            }}>
              <div style={{ width: '48px', height: '48px', borderRadius: '50%', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', boxShadow: '0 0 24px rgba(34,197,94,0.2)' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', color: '#22c55e' }}>✓</span>
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '12px', color: '#22c55e', letterSpacing: '0.1em', marginBottom: '10px' }}>
                FIRE FULLY CONTAINED
              </div>
              <div style={{ fontWeight: 600, fontSize: '15px', color: '#d4dce8', marginBottom: '8px' }}>
                {containmentModal.incidentName}
              </div>
              <div style={{ fontSize: '12px', color: '#5a6878', marginBottom: '24px', lineHeight: 1.6 }}>
                This incident has reached 100% containment. All units are being recalled to home stations.
              </div>
              <button
                onClick={() => {
                  if (containmentModal.alertId) api.acknowledgeAlert(containmentModal.alertId).catch(() => {})
                  setContainmentModal(null)
                  refreshAlertsDebounced()
                  refreshIncidents()
                }}
                style={{
                  background: '#22c55e', border: 'none', borderRadius: '6px',
                  padding: '11px 36px', cursor: 'pointer',
                  fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '11px',
                  color: '#0a0f0a', letterSpacing: '0.08em',
                  boxShadow: '0 0 20px rgba(34,197,94,0.3)', transition: 'all 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = '#16a34a'}
                onMouseLeave={e => e.currentTarget.style.background = '#22c55e'}
              >
                ACKNOWLEDGE
              </button>
            </div>
          </div>
        )}

      </div>
    </AuthContext.Provider>
  )
}
