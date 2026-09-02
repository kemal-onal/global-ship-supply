/**
 * NotificationsPanel — the dropdown that opens when the bell is clicked.
 *
 * Anchored as an absolute child of a `relative` wrapper in Layout.
 * Click outside / Escape closes it (the store's `closePanel` is wired
 * to those events here).
 */
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Check, CheckCheck, Loader2, Package } from 'lucide-react'

import { useNotificationsStore } from '../store/notifications'

// Tiny relative-time formatter — keeps the panel dependency-free.
function relativeTime(iso) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffSec = Math.round((now - then) / 1000)
  if (diffSec < 60) return 'just now'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

function iconFor(type) {
  // The project uses lucide icons; map known types to one. Unknown
  // types fall back to a generic bell.
  switch (type) {
    case 'order_transition':
      return Package
    default:
      return Bell
  }
}

export default function NotificationsPanel() {
  const {
    items,
    loading,
    unreadCount,
    markRead,
    markAllRead,
    closePanel,
  } = useNotificationsStore()
  const navigate = useNavigate()
  const ref = useRef(null)

  // Close on outside click + Escape.
  useEffect(() => {
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) closePanel()
    }
    const onKey = (e) => {
      if (e.key === 'Escape') closePanel()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [closePanel])

  const handleRowClick = (n) => {
    // Mark as read first, then navigate if we know where to go.
    if (!n.read_at) markRead(n.id)
    const orderId = n?.data?.order_id
    if (orderId) {
      closePanel()
      navigate(`/orders/${orderId}`)
    }
  }

  return (
    <div
      ref={ref}
      className="absolute right-0 top-full mt-2 w-96 max-w-[calc(100vw-2rem)] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-xl z-30 overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
        <div>
          <div className="text-sm font-semibold">Notifications</div>
          <div className="text-xs text-slate-500">
            {unreadCount > 0 ? `${unreadCount} unread` : 'All caught up'}
          </div>
        </div>
        <button
          onClick={markAllRead}
          disabled={unreadCount === 0}
          className="flex items-center gap-1 text-xs font-medium text-blue-600 dark:text-blue-400 disabled:text-slate-400 disabled:cursor-not-allowed hover:underline"
        >
          <CheckCheck className="w-3.5 h-3.5" />
          Mark all read
        </button>
      </div>

      {/* Body */}
      <div className="max-h-96 overflow-y-auto">
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-slate-500">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-slate-500">
            You're all caught up.
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {items.map(n => {
              const Icon = iconFor(n.type)
              const unread = !n.read_at
              return (
                <li key={n.id}>
                  <button
                    onClick={() => handleRowClick(n)}
                    className={`w-full text-left flex gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors ${
                      unread ? 'bg-blue-50/40 dark:bg-blue-900/10' : ''
                    }`}
                  >
                    <div
                      className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                        unread
                          ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-300'
                          : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div
                          className={`text-sm ${unread ? 'font-semibold' : 'font-medium'} text-slate-900 dark:text-slate-100`}
                        >
                          {n.title}
                        </div>
                        {unread && (
                          <span
                            className="flex-shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-500"
                            aria-label="Unread"
                          />
                        )}
                      </div>
                      {n.body && (
                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
                          {n.body}
                        </div>
                      )}
                      <div className="text-[10px] text-slate-400 mt-1 flex items-center gap-2">
                        <span>{relativeTime(n.created_at)}</span>
                        {n.read_at && (
                          <span className="flex items-center gap-0.5">
                            <Check className="w-3 h-3" /> read
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
