import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Gavel, Loader2, Package, ShieldAlert, ShieldCheck, Truck, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost } from '../api/client'

const palette = {
  draft: 'bg-slate-100 text-slate-700',
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

const severityColor = {
  info: 'bg-slate-100 text-slate-700',
  warning: 'bg-amber-100 text-amber-700',
  restricted: 'bg-orange-100 text-orange-700',
  prohibited: 'bg-rose-100 text-rose-700',
  blocking: 'bg-rose-600 text-white',
}

export default function OrderDetailPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: order, isLoading, error } = useQuery({
    queryKey: ['order', id],
    queryFn: () => apiGet(`/orders/${id}`),
  })
  const { data: regulations } = useQuery({
    queryKey: ['order', id, 'regulations'],
    queryFn: () => apiGet(`/customs/evaluate/${id}`),
    enabled: !!id,
    retry: false,
  })
  const { data: rfqs } = useQuery({
    queryKey: ['order', id, 'rfqs'],
    queryFn: () => apiGet('/rfq', { query: { order_id: id } }),
  })

  const createRfq = useMutation({
    mutationFn: () => apiPost(`/rfq/for-order/${id}`, null),
    onSuccess: () => {
      toast.success('RFQ sent to suppliers')
      qc.invalidateQueries({ queryKey: ['order', id] })
      qc.invalidateQueries({ queryKey: ['order', id, 'rfqs'] })
      qc.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (e) => toast.error(e.message),
  })

  if (isLoading) return (
    <div className="p-12 text-center">
      <Loader2 className="w-6 h-6 animate-spin inline-block" />
    </div>
  )
  if (error) return <div className="p-12 text-center text-rose-500">{error.message}</div>
  if (!order) return null

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-6xl mx-auto">
      <Link to="/orders" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to orders
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold font-mono">{order.reference}</h1>
            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${palette[order.status]}`}>
              {order.status.replace(/_/g, ' ')}
            </span>
          </div>
          <p className="text-slate-500 text-sm mt-1">
            {order.vessel_name} · {order.port_name} · {new Date(order.order_date).toLocaleString()}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Grand total</div>
          <div className="text-2xl font-bold">
            {order.currency} {order.grand_total?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Items */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-3">Line items ({order.items.length})</h2>
            <div className="overflow-x-auto -mx-2">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-2 py-2 text-left">SKU / Name</th>
                    <th className="px-2 py-2 text-right">Qty</th>
                    <th className="px-2 py-2 text-right">Unit price</th>
                    <th className="px-2 py-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {order.items.map(it => (
                    <tr key={it.id} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="px-2 py-2.5">
                        <div className="font-mono text-xs text-slate-500">{it.product_sku}</div>
                        <div className="text-sm">{it.product_name}</div>
                      </td>
                      <td className="px-2 py-2.5 text-right">{it.quantity} {it.unit}</td>
                      <td className="px-2 py-2.5 text-right">{order.currency} {it.unit_price}</td>
                      <td className="px-2 py-2.5 text-right font-medium">{order.currency} {it.line_total}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-slate-200 dark:border-slate-700">
                    <td colSpan={3} className="px-2 py-2.5 text-right text-sm font-medium">Subtotal</td>
                    <td className="px-2 py-2.5 text-right font-bold">{order.currency} {order.subtotal}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* RFQs */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Gavel className="w-4 h-4" /> RFQ pipeline
              </h2>
              {order.status === 'draft' || order.status === 'pending_approval' ? (
                <button
                  onClick={() => createRfq.mutate()}
                  disabled={createRfq.isPending}
                  className="text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium disabled:opacity-50"
                >
                  {createRfq.isPending ? 'Sending…' : 'Send RFQ to suppliers'}
                </button>
              ) : null}
            </div>
            {(rfqs || []).length === 0 ? (
              <p className="text-sm text-slate-500">No RFQ sent yet</p>
            ) : (
              <div className="space-y-2">
                {rfqs.map(r => (
                  <Link
                    key={r.id}
                    to={`/rfq`}
                    className="block p-3 border border-slate-200 dark:border-slate-700 rounded-lg hover:border-blue-500"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-mono text-xs">{r.reference}</div>
                        <div className="text-xs text-slate-500">
                          {r.invited_count} invited · {r.responded_count} responded
                        </div>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${palette[r.status]}`}>
                        {r.status}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Customs */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4" /> Customs check
            </h2>
            {!regulations ? (
              <p className="text-xs text-slate-500">Loading…</p>
            ) : regulations.issues.length === 0 ? (
              <div className="text-center py-4">
                <ShieldCheck className="w-8 h-8 text-emerald-500 mx-auto mb-1" />
                <p className="text-xs text-slate-500">No issues found for {order.port_name}</p>
              </div>
            ) : (
              <div className="space-y-2">
                {regulations.blocking && (
                  <div className="p-2.5 rounded-lg bg-rose-50 dark:bg-rose-900/20 text-rose-700 text-xs flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4 flex-shrink-0" />
                    Blocking issue detected
                  </div>
                )}
                {regulations.issues.map((i, idx) => (
                  <div key={idx} className="p-2.5 border border-slate-200 dark:border-slate-700 rounded-lg">
                    <div className="flex items-center gap-2">
                      <span className={`px-1.5 py-0.5 text-[10px] font-semibold rounded ${severityColor[i.severity]}`}>
                        {i.severity}
                      </span>
                      <div className="text-sm font-medium">{i.title}</div>
                    </div>
                    <p className="text-xs text-slate-500 mt-1">{i.description}</p>
                    {i.requires_permit && (
                      <p className="text-xs text-amber-600 mt-1">
                        ⚠ Permit required ({i.permit_authority || 'see port authority'})
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <Truck className="w-4 h-4" /> Delivery
            </h2>
            <div className="text-sm space-y-1.5">
              <div className="flex justify-between">
                <span className="text-slate-500">Required by</span>
                <span>{order.required_by ? new Date(order.required_by).toLocaleDateString() : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Est. delivery</span>
                <span>{order.estimated_delivery ? new Date(order.estimated_delivery).toLocaleDateString() : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Source</span>
                <span className="font-mono text-xs">{order.source}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
