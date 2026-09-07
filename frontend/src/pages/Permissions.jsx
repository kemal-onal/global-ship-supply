/**
 * Permissions — RBAC self-view + (admin-only) full role × permission matrix.
 *
 * Everyone with a JWT lands here and sees the "Your permissions" section
 * (their own role(s), vessel, and the permission strings currently in
 * their token). Super_admin / fleet_admin additionally see the full
 * governance grid: every role from SYSTEM_ROLES × every permission
 * from SYSTEM_PERMISSIONS, with green checks where the DB has a grant.
 *
 * The page is read-only — no user-management UI. The intent is the
 * "governance slide" for the department-head demo: prove that the
 * RBAC shape is real, that the caller's scope is what the backend
 * enforces, and that the matrix isn't a fiction.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShieldCheck,
  Key,
  Ship,
  Check,
  X,
  Copy,
  Loader2,
  AlertCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet } from '../api/client'
import { useAuthStore } from '../store/auth'

export default function PermissionsPage() {
  const hasRole = useAuthStore(s => s.hasRole)
  const isAdmin = hasRole('super_admin', 'fleet_admin')

  // /permissions/me — open to every authenticated caller.
  const { data: me, isLoading: meLoading, error: meError } = useQuery({
    queryKey: ['permissions-me'],
    queryFn: () => apiGet('/permissions/me'),
    staleTime: 60_000,
  })

  // /permissions/matrix — admin only. We call it for admins and
  // gracefully let the 403 surface as an error for non-admins (so
  // we can show the right "admin-only" empty state).
  const matrixEnabled = isAdmin
  const { data: matrix, isLoading: matrixLoading, error: matrixError } = useQuery({
    queryKey: ['permissions-matrix'],
    queryFn: () => apiGet('/permissions/matrix'),
    enabled: matrixEnabled,
    staleTime: 5 * 60_000,
  })

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto space-y-4">
      {/* ============ Header ============ */}
      <header>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldCheck className="w-6 h-6" /> Permissions
        </h1>
        <p className="text-slate-500 text-sm">
          Your roles, your scope, and the role × permission matrix that
          the backend enforces on every API call.
        </p>
      </header>

      {/* ============ 1. Identity header ============ */}
      <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Key className="w-4 h-4" /> You
        </h2>
        {meLoading ? (
          <p className="text-sm text-slate-500 inline-flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
          </p>
        ) : meError ? (
          <p className="text-sm text-rose-600 inline-flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5" /> {String(meError.message)}
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">User ID</div>
              <div className="font-mono text-xs break-all">
                {me?.user?.sub || '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">Vessel scope</div>
              <div className="flex items-center gap-1.5">
                <Ship className="w-3.5 h-3.5 text-slate-400" />
                <span className="font-mono text-xs">
                  {me?.user?.vessel_id || 'No vessel (cross-vessel admin or external)'}
                </span>
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">Roles</div>
              <div className="flex flex-wrap gap-1.5 mt-0.5">
                {(me?.user?.roles || []).length === 0 ? (
                  <span className="text-xs text-slate-400">No roles assigned</span>
                ) : (
                  me.user.roles.map(r => (
                    <span
                      key={r}
                      className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200 capitalize"
                    >
                      {r.replace('_', ' ')}
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ============ 2. Your permissions (everyone) ============ */}
      <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Key className="w-4 h-4" /> Your permissions
          <span className="ml-auto text-[10px] uppercase tracking-wide text-slate-500 font-semibold">
            {me?.permissions?.length ?? 0} granted
          </span>
        </h2>
        {meLoading ? (
          <p className="text-sm text-slate-500 inline-flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
          </p>
        ) : (me?.permissions || []).length === 0 ? (
          <p className="text-sm text-slate-500">
            You have no permissions assigned. The backend will return 403
            on every protected route until a role grant is added.
          </p>
        ) : (
          <PermissionsByResource permissions={me.permissions} />
        )}
      </section>

      {/* ============ 3. Role × permission matrix (admin only) ============ */}
      <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between gap-2 mb-3">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <ShieldCheck className="w-4 h-4" /> Role × permission matrix
            <span className="ml-2 text-[10px] uppercase tracking-wide text-slate-500 font-semibold">
              Admin view
            </span>
          </h2>
          {matrix && <CopyAsMarkdownButton matrix={matrix} />}
        </div>

        {!isAdmin ? (
          <div className="text-sm text-slate-500 bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4">
            <p className="font-medium text-slate-700 dark:text-slate-200 mb-1">
              Admin-only view
            </p>
            <p>
              The full role × permission matrix is only visible to
              <code className="px-1 mx-1 bg-slate-200 dark:bg-slate-700 rounded font-mono text-[11px]">
                super_admin
              </code>
              and
              <code className="px-1 mx-1 bg-slate-200 dark:bg-slate-700 rounded font-mono text-[11px]">
                fleet_admin
              </code>
              — the existence of the role hierarchy is not a secret,
              but the actual DB-backed grants are.
            </p>
          </div>
        ) : matrixLoading ? (
          <p className="text-sm text-slate-500 inline-flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading matrix…
          </p>
        ) : matrixError ? (
          <p className="text-sm text-rose-600 inline-flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5" /> {String(matrixError.message)}
          </p>
        ) : matrix ? (
          <RolePermissionMatrix matrix={matrix} />
        ) : null}
      </section>

      {/* ============ 4. Sealed-bid explainer (everyone) ============ */}
      <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-3">How sealed bids work</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          On the marketplace simulator, a <code className="px-1 bg-slate-100 dark:bg-slate-800 rounded text-[11px] font-mono">purchasing_officer</code> sees
          ranked <b>Bidder 1, Bidder 2, …</b> labels — the winner's
          total and lead time, and the score ranking. Supplier
          identities, individual prices, reliability and quality
          ratings, and subscore breakdowns are hidden until the
          award is committed by an admin.
        </p>
        <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
          Counter-offer terms (target prices, lead-time squeeze) are
          classified procurement information. They are visible only
          to the winning supplier — other bidders see a redacted
          &quot;Counter-offer sent to winner&quot; stub on the audit log.
        </p>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          <code className="px-1 bg-slate-100 dark:bg-slate-800 rounded text-[11px] font-mono">super_admin</code> and <code className="px-1 bg-slate-100 dark:bg-slate-800 rounded text-[11px] font-mono">fleet_admin</code> see the
          full leaderboard, all per-supplier metrics, and the
          counter-offer payload — by design, since they have to
          commit the award.
        </p>
      </section>
    </div>
  )
}

// =====================================================================
// Sub-components
// =====================================================================

/**
 * Group a flat permission list by the `resource` part of
 * `resource:action:scope`. Within each group, sort alphabetically.
 * Used for the "Your permissions" view.
 */
function PermissionsByResource({ permissions }) {
  const grouped = permissions.reduce((acc, p) => {
    const [resource] = p.split(':')
    if (!acc[resource]) acc[resource] = []
    acc[resource].push(p)
    return acc
  }, {})
  const resources = Object.keys(grouped).sort()
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {resources.map(resource => (
        <div key={resource} className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold mb-2">
            {resource}
          </div>
          <ul className="space-y-1">
            {grouped[resource].map(p => (
              <li key={p} className="text-xs font-mono flex items-center gap-1.5">
                <Check className="w-3 h-3 text-emerald-500 flex-shrink-0" />
                <span className="truncate" title={p}>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

/**
 * Full role × permission matrix. One column per role (sorted by
 * priority desc, then name), one row per permission (sorted
 * alphabetically). A green check = the DB has a `role_permissions`
 * grant for that role + permission; a red x = not granted.
 */
function RolePermissionMatrix({ matrix }) {
  // Roles are already sorted by priority desc from the API, but
  // re-sort defensively in case the order changes.
  const roles = [...(matrix.roles || [])].sort((a, b) =>
    (b.priority - a.priority) || a.name.localeCompare(b.name)
  )
  const permissions = [...(matrix.permissions || [])].sort((a, b) =>
    a.name.localeCompare(b.name)
  )
  const grants = matrix.role_permissions || {}

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-white dark:bg-slate-900 px-2 py-2 text-left font-semibold text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-800 min-w-[220px]">
              Permission
            </th>
            {roles.map(r => (
              <th
                key={r.name}
                className="px-2 py-2 text-center font-semibold border-b border-slate-200 dark:border-slate-800 min-w-[90px]"
                title={r.description}
              >
                <div className="text-[11px] text-slate-700 dark:text-slate-200 capitalize">
                  {r.name.replace('_', ' ')}
                </div>
                <div className="text-[9px] text-slate-400 font-normal">
                  P{r.priority}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {permissions.map(perm => (
            <tr
              key={perm.name}
              className="border-t border-slate-100 dark:border-slate-800/60 hover:bg-slate-50/50 dark:hover:bg-slate-800/30"
            >
              <td className="sticky left-0 bg-white dark:bg-slate-900 px-2 py-1.5 font-mono text-[11px] text-slate-700 dark:text-slate-300">
                {perm.name}
              </td>
              {roles.map(r => {
                const granted = (grants[r.name] || []).includes(perm.name)
                return (
                  <td key={r.name} className="px-2 py-1.5 text-center">
                    {granted ? (
                      <Check className="w-3.5 h-3.5 text-emerald-500 inline-block" />
                    ) : (
                      <X className="w-3.5 h-3.5 text-rose-300 dark:text-rose-800 inline-block" />
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-slate-500 mt-2">
        Green = granted. Red = not granted. Hover a role header for its
        description. Permissions are sorted alphabetically; roles are
        sorted by priority (highest first).
      </p>
    </div>
  )
}

/**
 * One-click "Copy as markdown" so the demo audience can grab the
 * matrix straight from the slide. Plain `navigator.clipboard.writeText`
 * is fine here — no secrets, just a public-by-admin grid.
 */
function CopyAsMarkdownButton({ matrix }) {
  const [copied, setCopied] = useState(false)

  const buildMarkdown = () => {
    const roles = [...(matrix.roles || [])].sort((a, b) =>
      (b.priority - a.priority) || a.name.localeCompare(b.name)
    )
    const permissions = [...(matrix.permissions || [])].sort((a, b) =>
      a.name.localeCompare(b.name)
    )
    const grants = matrix.role_permissions || {}

    const headerCells = ['Permission', ...roles.map(r => r.name)]
    const lines = []
    lines.push(`| ${headerCells.join(' | ')} |`)
    lines.push(`| ${headerCells.map(() => '---').join(' | ') } |`)
    for (const p of permissions) {
      const cells = [p.name, ...roles.map(r =>
        (grants[r.name] || []).includes(p.name) ? '✓' : '·'
      )]
      lines.push(`| ${cells.join(' | ')} |`)
    }
    return lines.join('\n')
  }

  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(buildMarkdown())
      setCopied(true)
      toast.success('Matrix copied as markdown')
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      toast.error(`Copy failed: ${e.message}`)
    }
  }

  return (
    <button
      onClick={onClick}
      className="px-2.5 py-1 text-xs bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-md inline-flex items-center gap-1.5"
      title="Copy the matrix as a markdown table (paste into slides or docs)"
    >
      <Copy className="w-3 h-3" />
      {copied ? 'Copied' : 'Copy as markdown'}
    </button>
  )
}
