import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import {
  LayoutDashboard,
  ClipboardList,
  Ship,
  Map,
  MapPin,
  UtensilsCrossed,
  Gavel,
  BriefcaseBusiness,
  Truck,
  ShieldCheck,
  RefreshCw,
  Settings,
  KeyRound,
  LogOut,
  Wifi,
  WifiOff,
  Moon,
  Sun,
  Search,
  Bell,
  ChevronDown,
  Anchor,
} from 'lucide-react'

import { useAuthStore } from '../store/auth'
import { useNetworkStore } from '../store/network'
import { useThemeStore } from '../store/theme'
import { useNotificationsStore } from '../store/notifications'
import NotificationsPanel from './NotificationsPanel'
import clsx from 'clsx'

/**
 * Sidebar nav. Each entry may declare `roles` (any-of match) and/or
 * `permissions` (every-of match) to hide itself from callers who
 * can't use it. The /permissions page is the exception: it has
 * neither gate, because every authenticated user can see their own
 * role/permission view (and admins get the matrix on top of that).
 */
const nav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  // IMPA-first redesign: the catalog is folded into the order
  // page (the IMPA typeahead inside OrderCreate.jsx). The
  // standalone /catalog page is a deprecation stub. The sidebar
  // entry is dropped; users navigate to the order page directly.
  { to: '/orders', label: 'Orders', icon: ClipboardList },
  { to: '/vessels', label: 'Vessels', icon: Ship },
  { to: '/fleet-map', label: 'Live Fleet Map', icon: Map, roles: ['super_admin', 'fleet_admin'] },
  { to: '/ports', label: 'Ports', icon: MapPin },
  { to: '/catering', label: 'Catering & Provisioning', icon: UtensilsCrossed, roles: ['super_admin', 'fleet_admin', 'vessel_captain', 'chief_steward'] },
  { to: '/rfq', label: 'RFQ & Bidding', icon: Gavel },
  {
    to: '/marketplace',
    label: 'Marketplace',
    icon: BriefcaseBusiness,
    // The admin's per-line compose step. Admin + fleet_admin
    // (super_admin role covers it via the any-of match).
    permissions: [['marketplace', 'compose', 'global']],
  },
  {
    to: '/supplier',
    label: 'Supplier Portal',
    icon: Truck,
    roles: ['supplier'],
  },
  { to: '/customs', label: 'Customs & Regulations', icon: ShieldCheck },
  { to: '/sync', label: 'Offline Sync', icon: RefreshCw },
  // Permissions — everyone sees their own; admins see the matrix
  // on top. No `roles` or `permissions` gate so it never hides.
  { to: '/permissions', label: 'Permissions', icon: KeyRound },
]

export default function Layout() {
  const navigate = useNavigate()
  const { user, clear, hasRole, hasPermission } = useAuthStore()
  const { online, vsat, pendingActions } = useNetworkStore()
  const { theme, setTheme } = useThemeStore()
  const { panelOpen, togglePanel, unreadCount, refreshUnreadCount } = useNotificationsStore()
  const [userMenu, setUserMenu] = useState(false)

  // 30s polling for the bell badge. Fires immediately on mount, then
  // every 30s. We only run while there's a logged-in user.
  useEffect(() => {
    if (!user) return
    refreshUnreadCount()
    const id = setInterval(refreshUnreadCount, 30_000)
    return () => clearInterval(id)
  }, [user, refreshUnreadCount])

  // Filter the sidebar by the caller's roles + permissions. A nav
  // entry without `roles` / `permissions` is always visible; otherwise
  // it requires the matching role/permission to be present. This is
  // a UX nicety — the API still rejects requests from callers who
  // lack the permission, so this is defense-in-depth, not the
  // primary enforcement.
  const visibleNav = useMemo(() => {
    return nav.filter(item => {
      if (item.roles && !item.roles.some(r => hasRole(r))) return false
      if (item.permissions && !item.permissions.every(([res, act, sc]) => hasPermission(res, act, sc))) return false
      return true
    })
  }, [hasRole, hasPermission])

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      {/* Sidebar — always visible; the page reflows in narrow windows */}
      <aside className="flex w-16 lg:w-64 flex-col bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 border-r border-slate-200 dark:border-slate-800 transition-[width] duration-200">
        <div className="h-16 flex items-center gap-2 px-3 lg:px-5 border-b border-slate-200 dark:border-slate-800">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center flex-shrink-0">
            <Anchor className="w-5 h-5 text-white" />
          </div>
          <div className="hidden lg:block">
            <div className="font-bold tracking-tight text-base">AVS Global</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Ship Supply Ops</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto py-4 px-2 lg:px-3 space-y-0.5">
          {visibleNav.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              title={item.label}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700 dark:bg-blue-600/20 dark:text-blue-300'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white'
                )
              }
            >
              <item.icon className="w-4 h-4 flex-shrink-0" />
              <span className="hidden lg:inline">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-2 lg:p-3 border-t border-slate-200 dark:border-slate-800 space-y-1">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium',
                isActive
                  ? 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white'
                  : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800'
              )
            }
            title="Settings"
          >
            <Settings className="w-4 h-4 flex-shrink-0" /> <span className="hidden lg:inline">Settings</span>
          </NavLink>
          <button
            onClick={() => { clear(); navigate('/') }}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-500 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800"
            title="Sign out"
          >
            <LogOut className="w-4 h-4 flex-shrink-0" /> <span className="hidden lg:inline">Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center px-4 sm:px-6 gap-4">
          {/* Search */}
          <div className="flex-1 max-w-xl">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="search"
                placeholder="Search products, orders, ports…  (⌘K)"
                className="w-full pl-10 pr-3 py-2 bg-slate-100 dark:bg-slate-800 rounded-lg text-sm border border-transparent focus:bg-white dark:focus:bg-slate-900 focus:border-blue-500 outline-none"
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Theme toggle */}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              title="Toggle theme"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>

            {/* Online status */}
            <ConnectionBadge online={online} vsat={vsat} pendingActions={pendingActions} />

            {/* Notifications */}
            <div className="relative">
              <button
                onClick={togglePanel}
                className="relative p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
                title="Notifications"
                aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
              >
                <Bell className="w-4 h-4" />
                {unreadCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center text-[10px] font-semibold text-white bg-rose-500 rounded-full">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </button>
              {panelOpen && <NotificationsPanel />}
            </div>

            {/* User menu */}
            <div className="relative">
              <button
                onClick={() => setUserMenu(o => !o)}
                className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white text-xs font-semibold">
                  {user?.full_name?.[0]?.toUpperCase() || user?.email?.[0]?.toUpperCase() || 'U'}
                </div>
                <div className="text-left hidden sm:block">
                  <div className="text-xs font-medium">{user?.full_name || user?.email}</div>
                  <div className="text-[10px] text-slate-500 capitalize">
                    {user?.roles?.[0]?.replace('_', ' ') || 'User'}
                  </div>
                </div>
                <ChevronDown className="w-3 h-3 text-slate-400" />
              </button>
              {userMenu && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setUserMenu(false)} />
                  <div className="absolute right-0 top-full mt-1 w-56 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg z-20 py-1">
                    <div className="px-3 py-2 border-b border-slate-200 dark:border-slate-800">
                      <div className="text-sm font-medium">{user?.full_name}</div>
                      <div className="text-xs text-slate-500">{user?.email}</div>
                    </div>
                    {(user?.roles || []).map(r => (
                      <div key={r} className="px-3 py-1.5 text-xs text-slate-500 capitalize">
                        {r.replace('_', ' ')}
                      </div>
                    ))}
                    <div className="border-t border-slate-200 dark:border-slate-800 mt-1 pt-1">
                      <button
                        onClick={() => { clear(); navigate('/') }}
                        className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
                      >
                        Sign out
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function ConnectionBadge({ online, vsat, pendingActions }) {
  if (!online) {
    return (
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 text-xs font-medium offline-pulse">
        <WifiOff className="w-3.5 h-3.5" />
        <span>Offline{pendingActions > 0 && ` · ${pendingActions} queued`}</span>
      </div>
    )
  }
  return (
    <div className={clsx(
      'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium',
      vsat === 'good' && 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300',
      vsat === 'fair' && 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
      vsat === 'poor' && 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300',
    )}>
      <Wifi className="w-3.5 h-3.5" />
      <span className="capitalize">{vsat === 'unknown' ? 'Online' : `VSAT ${vsat}`}</span>
      {pendingActions > 0 && (
        <span className="ml-1 px-1.5 py-0.5 rounded bg-blue-500 text-white text-[10px]">
          {pendingActions}
        </span>
      )}
    </div>
  )
}
