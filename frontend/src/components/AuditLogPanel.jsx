import { useState, useEffect } from 'react'
import { api, BASE_URL } from '../api/client'
import { formatTimestamp } from '../utils/timeUtils'
import { useAuth } from '../context/AuthContext'

const ACTION_COLOR = {
  DISPATCH:       '#ff4d1a',
  ALERT_DISPATCH: '#38bdf8',
  LOGIN:          '#22c55e',
  LOGOUT:         '#878787',
}

// formatTimestamp from timeUtils — uses browser-local timezone (override with VITE_DISPLAY_TIMEZONE)

export default function AuditLogPanel({ onClose }) {
  const [entries,   setEntries]   = useState([])
  const [loading,   setLoading]   = useState(true)
  const [total,     setTotal]     = useState(0)
  const [integrity, setIntegrity] = useState(null)
  const auth = useAuth()

  useEffect(() => {
    setLoading(true)
    api.auditLog()
      .then(data => {
        setEntries(data.entries ?? [])
        setTotal(data.total ?? 0)
      })
      .catch(err => console.error('Audit log fetch failed:', err))
      .finally(() => setLoading(false))

    // Run integrity check for commanders
    if (auth?.role === 'commander') {
      api.auditVerify()
        .then(setIntegrity)
        .catch(() => {})
    }
  }, [])

  function handleExport() {
    fetch(`${BASE_URL}/api/audit/export.csv`, {
      headers: { 'Authorization': `Bearer ${auth?.access_token}` },
    })
      .then(res => res.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a   = document.createElement('a')
        a.href     = url
        a.download = 'pyra_audit_log.csv'
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch(err => console.error('CSV export failed:', err))
  }

  return (
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0,
      width: '480px', background: 'linear-gradient(180deg, rgba(26,34,48,0.96) 0%, rgba(18,24,34,0.98) 100%)',
      borderLeft: '1px solid rgba(255,255,255,0.1)',
      zIndex: 3000, display: 'flex', flexDirection: 'column',
      boxShadow: '-14px 0 42px rgba(0,0,0,0.42)',
      animation: 'slideInRight 0.22s cubic-bezier(0.16, 1, 0.3, 1)',
      backdropFilter: 'blur(14px)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 16px', borderBottom: '1px solid #262626', flexShrink: 0,
      }}>
        <div>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '13px', color: '#d4dce8', letterSpacing: '0.04em' }}>
            AUDIT LOG
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#5a6878', marginTop: '2px' }}>
            {total} entries · tamper-evident
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {/* Integrity badge */}
          {integrity && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '5px',
              background: integrity.integrity === 'PASS' ? 'rgba(74,222,128,0.1)' : 'rgba(239,68,68,0.1)',
              border: `1px solid ${integrity.integrity === 'PASS' ? '#22c55e' : '#ef4444'}`,
              borderRadius: '3px', padding: '3px 8px',
            }}>
              <div style={{
                width: '5px', height: '5px', borderRadius: '50%',
                background: integrity.integrity === 'PASS' ? '#22c55e' : '#ef4444',
              }} />
              <span style={{
                fontFamily: 'var(--font-sans)', fontSize: '10px', fontWeight: 600,
                color: integrity.integrity === 'PASS' ? '#22c55e' : '#ef4444',
                letterSpacing: '0.04em',
              }}>
                INTEGRITY {integrity.integrity}
              </span>
            </div>
          )}
          <button
            onClick={handleExport}
            style={{
              background: 'transparent', border: '1px solid #333',
              borderRadius: '3px', padding: '4px 10px', cursor: 'pointer',
              fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#5a6878',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#ff4d1a'; e.currentTarget.style.color = '#ff4d1a' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = '#333'; e.currentTarget.style.color = '#878787' }}
          >
            EXPORT CSV
          </button>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#555', fontSize: '16px', padding: '2px 4px' }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Entries */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        {loading && (
          <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {[80, 60, 90, 50, 75].map((w, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '6px', paddingBottom: '10px', borderBottom: '1px solid #1e1e22' }}>
                <div className="pyra-skeleton" style={{ height: '10px', width: `${w}%` }} />
                <div className="pyra-skeleton" style={{ height: '10px', width: `${Math.round(w * 0.6)}%` }} />
              </div>
            ))}
          </div>
        )}
        {!loading && entries.length === 0 && (
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: '#5a6878', padding: '20px 16px' }}>
            No audit entries yet. Dispatch actions will appear here.
          </div>
        )}
        {!loading && entries.map(entry => (
          <div key={entry.id} style={{
            padding: '10px 16px',
            borderBottom: '1px solid #1e1e22',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: '10px',
                  color: ACTION_COLOR[entry.action] ?? '#878787',
                  letterSpacing: '0.06em',
                }}>
                  {entry.action.replace('_', ' ')}
                </span>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', fontWeight: 600 }}>
                  {entry.actor}
                </span>
                <span style={{
                  fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#5a6878',
                  background: 'rgba(255,255,255,0.07)', borderRadius: '2px', padding: '1px 5px',
                }}>
                  {entry.actor_role}
                </span>
              </div>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#555' }}>
                {formatTimestamp(entry.timestamp)}
              </span>
            </div>

            {entry.incident_name && (
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#aaaaaa', marginBottom: '3px' }}>
                {entry.incident_name}
              </div>
            )}

            {entry.details && (
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d4dce8', marginBottom: '4px' }}>
                {entry.details}
              </div>
            )}

            {entry.unit_ids?.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '6px' }}>
                {entry.unit_ids.map(uid => (
                  <span key={uid} style={{
                    fontFamily: 'var(--font-sans)', fontSize: '10px', color: '#d4dce8',
                    background: 'rgba(255,255,255,0.07)', border: '1px solid #3a3a3a',
                    borderRadius: '2px', padding: '2px 6px', fontWeight: 500,
                  }}>
                    {uid}
                  </span>
                ))}
              </div>
            )}

            <div style={{
              fontFamily: 'var(--font-sans)', fontSize: '10px',
              color: '#5a6878', letterSpacing: '0.01em', marginTop: '2px',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              <span style={{ color: '#555', marginRight: '4px' }}>SHA-256</span>
              {entry.checksum}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
