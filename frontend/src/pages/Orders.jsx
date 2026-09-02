import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { ClipboardList, Plus, Search, Loader2 } from 'lucide-react'

import { apiGet } from '../api/client'

const STATUSES = [
  { value: '', label: 'All statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'pending_approval', label: 'Pending approval' },
  { value: 'rfq_in_progress', label: 'RFQ in progress' },
  { value: 'bidding', label: 'Bidding' },
  { value: 'awaiting_confirmation', label: 'Awaiting confirmation' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'in_transit', label: 'In transit' },
  { value: 'delivered', label: 'Delivered' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'rejected', label: 'Rejected' },
]

const palette = {
  draft: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  pending_approval: 'bg-amber-100 text-amber-700',
  rfq_in_progress: 'bg-blue-100 text-blue-700',
  bidding: 'bg-violet-100 text-violet-700',
  awaiting_confirmation: 'bg-cyan-100 text-cyan-700',
  confirmed: 'bg-emerald-100 text-emerald-700',
  in_transit: 'bg-indigo-100 text-indigo-700',
  delivered: 'bg-teal-100 text-teal-700',
  completed: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-slate-100 text-slate-500',
  rejected: 'bg-rose-100 text-rose-700',
}

export default function OrdersPage() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const limit = 25

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['orders', { q, status, page }],
    queryFn: () => apiGet('/orders', {
      query: { q, status: status || undefined, limit, offset: (page - 1) * limit },
    }),
    placeholderData: p => p,
  })

  const items = data || []
  const hasMore = items.length === limit

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Orders</h1>
          <p className="text-slate-500 text-sm">
            Vessel supply orders across the fleet
          </p>
        </div>
        <Link
          to="/orders/new"
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg"
        >
          <Plus className="w-4 h-4" /> New order
        </Link>
      </header>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 mb-4">
        <div className="flex flex-col md:flex-row gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="search"
              value={q}
              onChange={e => { setQ(e.target.value); setPage(1) }}
              placeholder="Search by reference or notes…"
              className="w-full pl-10 pr-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <select
            value={status}
            onChange={e => { setStatus(e.target.value); setPage(1) }}
            className="px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
          >
            {STATUSES.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center">
            <Loader2 className="w-6 h-6 animate-spin inline-block" />
          </div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center">
            <ClipboardList className="w-10 h-10 text-slate-300 mx-auto mb-3" />
            <p className="text-slate-500">No orders yet</p>
            <Link to="/orders/new" className="text-blue-600 text-sm hover:underline">Create your first order →</Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold">Reference</th>
                  <th className="px-4 py-3 text-left font-semibold">Vessel</th>
                  <th className="px-4 py-3 text-left font-semibold">Port</th>
                  <th className="px-4 py-3 text-left font-semibold">Status</th>
                  <th className="px-4 py-3 text-left font-semibold">Priority</th>
                  <th className="px-4 py-3 text-left font-semibold">Date</th>
                  <th className="px-4 py-3 text-right font-semibold">Total</th>
                  <th className="px-4 py-3 text-center font-semibold">Items</th>
                </tr>
              </thead>
              <tbody>
                {items.map(o => (
                  <tr key={o.id} className="border-t border-slate-100 dark:border-slate-800 data-grid-row">
                    <td className="px-4 py-3 font-mono text-xs">
                      <Link to={`/orders/${o.id}`} className="text-blue-600 hover:underline">
                        {o.reference}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{o.vessel_name || '—'}</td>
                    <td className="px-4 py-3 text-slate-500">{o.port_name || '—'}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${palette[o.status]}`}>
                        {o.status.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <PriorityBadge priority={o.priority} />
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">
                      {new Date(o.order_date).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      {o.currency} {o.grand_total?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </td>
                    <td className="px-4 py-3 text-center text-xs text-slate-500">
                      {o.items?.length || 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-800 text-sm">
              <div className="text-slate-500">Page {page}</div>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1.5 border border-slate-200 dark:border-slate-700 rounded text-xs disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(p => p + 1)}
                  disabled={!hasMore}
                  className="px-3 py-1.5 border border-slate-200 dark:border-slate-700 rounded text-xs disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PriorityBadge({ priority }) {
  const palette = {
    low: 'bg-slate-100 text-slate-600',
    normal: 'bg-blue-100 text-blue-700',
    high: 'bg-amber-100 text-amber-700',
    urgent: 'bg-rose-100 text-rose-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${palette[priority]}`}>
      {priority}
    </span>
  )
}
