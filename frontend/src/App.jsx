import { useEffect, useState, useCallback } from 'react'
import { AuthContext } from './context/AuthContext'
import TopBar from './components/TopBar'
import IncidentMap from './components/IncidentMap'
import LeftSidebar from './components/LeftSidebar'
import { FireGrowthLegend } from './components/FireGrowthOverlay'
import { EvacZonesPanel, exportEvacZones } from './components/EvacZonesOverlay'
import RightPanel from './components/RightPanel'
import EventTimeline from './components/EventTimeline'
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
  }, [showFireGrowth, selectedId, fireGrowthTimeMode])
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
  const refreshAlerts    = useCallback(() => api.alerts().then(setAlerts).catch(() => {}), [])
  const refreshUnits = useCallback(() =>
    api.units().then(newUnits => {
      setUnits(newUnits)
      // Clear loadout for any unit that has returned to available
      setConfirmedLoadouts(prev => {
        const next = { ...prev }
        let changed = false
        for (const unit of newUnits) {
          if (unit.status === 'available' && next[unit.id]) {
            delete next[unit.id]
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
    const unitId     = setInterval(refreshUnits,     3_000)   // unit positions every 3s
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
      for (const l of loadouts) next[l.unit_id] = l
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
    <div style={{ height: '100vh', width: '100vw', background: '#151419', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ color: '#3a4a5a', fontFamily: 'Inter, sans-serif', fontSize: '12px', letterSpacing: '0.06em' }}>
        INITIALIZING PYRA...
      </div>
    </div>
  )

  if (error) return (
    <div style={{ height: '100vh', width: '100vw', background: '#151419', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ color: '#ef4444', fontFamily: 'Inter, sans-serif', fontSize: '12px', textAlign: 'center', padding: '0 2rem' }}>
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
          background: '#151419', 
          display: 'flex', 
          flexDirection: 'column', 
          overflow: 'hidden',
          // Use CSS custom property for scale factor (components can use this)
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

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

          {showLeftSidebar && (
            <LeftSidebar
              units={units}
              activeView={activeView}
              onViewChange={setActiveView}
              selectedIncidentId={selectedId}
              onUnitClick={handleUnitClick}
              confirmedLoadouts={confirmedLoadouts}
            />
          )}

          <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
            <IncidentMap
              incidents={incidents}
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

            {/* Water source status chip */}
            {showWaterSources && waterSourceStatus && (waterSourceStatus.loading || waterSourceStatus.noResults) && (
              <div style={{
                position: 'absolute', top: '64px', left: '50%', transform: 'translateX(-50%)',
                zIndex: 1000, pointerEvents: 'none',
                background: 'rgba(21,20,25,0.92)', border: '1px solid #60a5fa44',
                borderRadius: '20px', padding: '5px 14px',
                fontFamily: 'Inter, sans-serif', fontSize: '11px',
                color: waterSourceStatus.loading ? '#60a5fa' : '#878787',
                backdropFilter: 'blur(8px)', whiteSpace: 'nowrap',
              }}>
                {waterSourceStatus.loading
                  ? '💧 Searching for water sources...'
                  : '💧 No water sources found within 8 km'}
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
                rightOffset={showCommand ? 160 : 0}
              />
            )}
          </div>

          {showRightPanel && (
            <RightPanel
              alerts={alerts}
              units={units}
              incidents={incidents}
              selectedIncidentId={selectedId}
              onUnitClick={handleUnitClick}
              onAlertsChanged={refreshAlertsDebounced}
              confirmedLoadouts={confirmedLoadouts}
            />
          )}

        </div>

        <EventTimeline
          alerts={alerts}
          incidents={incidents}
          units={units}
          onAlertsChanged={refreshAlertsDebounced}
        />

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

      </div>
    </AuthContext.Provider>
  )
}