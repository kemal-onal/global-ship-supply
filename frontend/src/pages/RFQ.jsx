import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Gavel, Loader2, TrendingUp, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost } from '../api/client'

const STATUS_COLORS = {
  draft: 'bg-slate-100 text-slate-700',
  open: 'bg-blue-100 text-blue-700',
  closed: 'bg-slate-100 text-slate-500',
  awarded: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-rose-100 text-rose-700',
}

export default function RFQPage() {
  const qc = useQueryClient()
  const { data: rfqs, isLoading } = useQuery({
    queryKey: ['rfqs'],
    queryFn: () => apiGet('/rfq', { query: { limit: 50 } }),
  })
  const { data: orders } = useQuery({
    queryKey: ['rfq-create-orders'],
    queryFn: () => apiGet('/orders', { query: { status: 'pending_approval', limit: 20 } }),
  })

  const [orderId, setOrderId] = useState('')
  const [weights, setWeights] = useState({ price: 0.4, lead_time: 0.2, reliability: 0.2, quality: 0.2 })

  const createRfq = useMutation({
    mutationFn: (oid) => apiPost(`/rfq/for-order/${oid}`, null),
    onSuccess: () => {
      toast.success('RFQ created and invitations sent')
      qc.invalidateQueries({ queryKey: ['rfqs'] })
      qc.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (e) => toast.error(e.message),
  })

  const compareRfq = useMutation({
    mutationFn: (rid) => apiPost(`/rfq/${rid}/compare`, { weights }),
    onSuccess: () => {
      toast.success('Bid comparison complete')
      qc.invalidateQueries({ queryKey: ['rfqs'] })
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Gavel className="w-6 h-6" /> RFQ & supplier bidding
        </h1>
        <p className="text-slate-500 text-sm">
          Send request-for-quote to suppliers, collect bids, run weighted comparison
        </p>
      </header>

      {/* Create new RFQ */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
        <h2 className="text-sm font-semibold mb-3">Send new RFQ</h2>
        <div className="flex flex-col md:flex-row gap-3">
          <select
            value={orderId}
            onChange={e => setOrderId(e.target.value)}
            className="flex-1 px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
          >
            <option value="">Pick a pending-approval order…</option>
            {(orders || []).map(o => (
              <option key={o.id} value={o.id}>
                {o.reference} — {o.vessel_name} → {o.port_name} ({o.items?.length || 0} items)
              </option>
            ))}
          </select>
          <button
            onClick={() => orderId && createRfq.mutate(orderId)}
            disabled={!orderId || createRfq.isPending}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            {createRfq.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Send RFQ
          </button>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          Suppliers at the destination port will receive an email invitation with a private quote link.
        </p>
      </div>

      {/* Weight presets */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4" /> Comparison weights
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(weights).map(([k, v]) => (
            <div key={k}>
              <label className="block text-xs text-slate-500 mb-1 capitalize">{k.replace(/_/g, ' ')}</label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={v}
                onChange={e => setWeights(prev => ({ ...prev, [k]: parseFloat(e.target.value) || 0 }))}
                className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
              />
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-500 mt-2">
          Weights must sum to ~1.0. Applied when running bid comparison.
        </p>
      </div>

      {/* RFQ list */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Active RFQs</h2>
        </div>
        {isLoading ? (
          <div className="p-12 text-center">
            <Loader2 className="w-6 h-6 animate-spin inline-block" />
          </div>
        ) : (rfqs || []).length === 0 ? (
          <div className="p-12 text-center text-sm text-slate-500">No RFQs yet</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">Reference</th>
                <th className="px-4 py-3 text-left font-semibold">Order</th>
                <th className="px-4 py-3 text-center font-semibold">Invited</th>
                <th className="px-4 py-3 text-center font-semibold">Responded</th>
                <th className="px-4 py-3 text-left font-semibold">Status</th>
                <th className="px-4 py-3 text-right font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {(rfqs || []).map(r => (
                <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-4 py-2.5 font-mono text-xs">{r.reference}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{r.order_reference}</td>
                  <td className="px-4 py-2.5 text-center">{r.invited_count}</td>
                  <td className="px-4 py-2.5 text-center">{r.responded_count}</td>
                  <td className="px-4 py-2.5">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${STATUS_COLORS[r.status] || 'bg-slate-100 text-slate-700'}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      onClick={() => compareRfq.mutate(r.id)}
                      disabled={compareRfq.isPending}
                      className="text-xs px-3 py-1.5 border border-blue-300 text-blue-700 rounded hover:bg-blue-50 inline-flex items-center gap-1"
                    >
                      Compare bids <ChevronRight className="w-3 h-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
