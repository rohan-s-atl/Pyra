import { useState, useCallback, useEffect } from 'react'

let _addToast = null

export function useToastProvider() {
  const [toasts, setToasts] = useState([])

  const addToast = useCallback((message, type = 'success', duration = 3000) => {
    const id = Date.now() + Math.random()
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration)
  }, [])

  useEffect(() => {
    _addToast = addToast
    return () => {
      if (_addToast === addToast) _addToast = null
    }
  }, [addToast])

  return { toasts, addToast }
}

export function toast(message, type = 'success', duration = 3000) {
  if (_addToast) _addToast(message, type, duration)
}

const TYPE_STYLE = {
  success: { border: '#4ade80', icon: '✓', color: '#4ade80' },
  error: { border: '#ef4444', icon: '✕', color: '#ef4444' },
  info: { border: '#60a5fa', icon: '⬡', color: '#60a5fa' },
  warning: { border: '#facc15', icon: '⚠', color: '#facc15' },
}

export function ToastContainer({ toasts }) {
  return (
    <div style={{
      position: 'fixed', bottom: '80px', left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex', flexDirection: 'column', gap: '8px',
      zIndex: 9999, pointerEvents: 'none',
      alignItems: 'center',
    }}>
      {toasts.map(t => {
        const s = TYPE_STYLE[t.type] ?? TYPE_STYLE.info
        return (
          <div key={t.id} style={{
            background: '#1B1B1E',
            border: `1px solid ${s.border}`,
            borderRadius: '4px',
            padding: '8px 16px',
            display: 'flex', alignItems: 'center', gap: '8px',
            boxShadow: `0 4px 16px rgba(0,0,0,0.4), 0 0 0 1px ${s.border}22`,
            animation: 'toastIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
            fontFamily: 'Inter, sans-serif', fontSize: '12px',
            fontWeight: 500, color: '#FBFBFB',
            letterSpacing: '0.02em',
            whiteSpace: 'nowrap',
          }}>
            <span style={{ color: s.color, fontWeight: 700 }}>{s.icon}</span>
            {t.message}
          </div>
        )
      })}

    </div>
  )
}