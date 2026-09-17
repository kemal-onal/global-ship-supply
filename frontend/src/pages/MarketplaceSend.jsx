import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Send, Loader2, Clock, AlertCircle, CheckCircle } from 'lucide-react'
import toast from 'react-hot-toast'

import { sendRfq, getRfqDetail } from '../api/marketplaceSimple'

// --- shared helpers ---------------------------------------------------

function formatMoney(v, currency = 'USD') {
  if (v == null) return '—'
  return `${currency} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

// --- Order row for picker ----------------------------------------------

function OrderRow({ order, onSend, sendingId }) {
  const isSending = sendingId === order.id
  return (
    <tr className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50/50 dark:hover:bg-slate-800/50">
      <td className="px-4 py-3">
        <div className="font-mono text-sm text-slate-700 dark:text-slate-300">{order.reference}</div>
        <div className="text-[11px] text-slate-500 font-mono mt-0.5">{order.id.slice(0, 8)}</div>
      </td>
      <td className="px-4 py-3 text-sm">
        <div className="font-medium">{order.vessel_name || '—'}</div>
        <div className="text-[11px] text-slate-500">{order.port_name || '—'}</div>
      </td>
      <td className="px-4 py-3 text-sm">
        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
          order.status === 'pending_approval'
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
            : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400'
        }`}>
          {order.status.replace(/_/g, ' ')}
        </span>
      </td>
      <td className="px-4 py-3 text-sm">
        <div>{formatMoney(order.grand_total, order.currency)}</div>
        <div className="text-[11px] text-slate-500">{order.item_count} line(s)</div>
      </td>
      <td className="px-4 py-3 text-sm">
        <div>{formatDateTime(order.order_date)}</div>
        {order.required_by && (
          <div className="text-[11px] text-slate-500 flex items-center gap-1">
            <Clock className="w-3 h-3" /> Due: {formatDateTime(order.required_by)}
          </div>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <button
          onClick={() => onSend(order.id)}
          disabled={isSending}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg inline-flex items-center gap-1.5"
          title="Fan out RFQ to all active suppliers at this port"
        >
          {isSending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
          {isSending ? 'Sending…' : 'Send RFQ'}
        </button>
      </td>
    </tr>
  )
}

// --- Order picker (left rail) ------------------------------------------

function OrderPicker({ onSelect, sendingId }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['marketplace', 'orders-for-rfq'],
    queryFn: async () => {
      const res = await fetch('/api/v1/orders?status=pending_approval&limit=50')
      if (!res.ok) throw new Error('Failed to fetch orders')
      return res.json()
    },
  })

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-slate-500">
        <Loader2 className="w-4 h-4 animate-spin inline-block mr-2" /> Loading orders…
      </div>
    )
  }
  if (error) {
    return <div className="p-4 text-sm text-rose-500">{error.message}</div>
  }

  const orders = data?.items || []

  if (orders.length === 0) {
    return (
      <div className="p-6 text-center">
        <div className="w-8 h-8 mx-auto text-slate-300 mb-2">📋</div>
        <div className="text-sm font-medium text-slate-700">No orders pending</div>
        <p className="text-xs text-slate-500 mt-1">
          Orders in <code>pending_approval</code> will appear here.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-500 uppercase tracking-wide">
        Orders Ready for RFQ ({orders.length})
      </div>
      <div className="overflow-x-auto max-h-[600px]">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0 z-10">
            <tr>
              <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">Order</th>
              <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">Vessel / Port</th>
              <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">Status</th>
              <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">Total / Lines</th>
              <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">Created / Due</th>
              <th className="px-4 py-2 text-right text-xs uppercase text-slate-500">Action</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <OrderRow key={order.id} order={order} onSend={onSelect} sendingId={sendingId} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// --- RFQ detail after send ---------------------------------------------

function RfqDetailView({ rfq, onBack }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['rfq', rfq.id, 'detail'],
    queryFn: () => getRfqDetail(rfq.id),
    enabled: !!rfq,
  })

  if (isLoading) {
    return (
      <div className="p-12 text-center text-sm text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" />
        Loading RFQ detail…
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-12 text-center text-sm text-rose-500">
        <AlertCircle className="w-6 h-6 mx-auto mb-2" /> {error.message}
      </div>
    )
  }
  if (!data) return null

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono">{data.reference}</h1>
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                data.status === 'sent' ? 'bg-blue-100 text-blue-700' :
                data.status === 'closed' ? 'bg-violet-100 text-violet-700' :
                'bg-slate-100 text-slate-700'
              }`}>
                {data.status}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Order <span className="font-mono">{data.order_reference || data.order_id}</span>
              · {data.invited_count} supplier(s) invited · Deadline: {formatDateTime(data.response_deadline)}
            </p>
          </div>
          <button
            onClick={onBack}
            className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg inline-flex items-center gap-1.5"
          >
            <ArrowLeft className="w-4 h-4" /> Back to list
          </button>
        </div>
      </div>

      {/* RFQ Items */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-500 uppercase tracking-wide">
          RFQ Items ({data.items?.length || 0})
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/50">
              <tr>
                <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">IMPA Code</th>
                <th className="px-4 py-2 text-left text-xs uppercase text-slate-500">Description</th>
                <th className="px-4 py-2 text-right text-xs uppercase text-slate-500">Qty</th>
                <th className="px-4 py-2 text-right text-xs uppercase text-slate-500">Unit</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).map((item) => (
                <tr key={item.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-4 py-2 font-mono text-sm">{item.impa_code || '—'}</td>
                  <td className="px-4 py-2">{item.description || '—'}</td>
                  <td className="px-4 py-2 text-right">{item.quantity}</td>
                  <td className="px-4 py-2 text-right">{item.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Next steps */}
      <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-5">
        <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 mb-2">
          <CheckCircle className="w-5 h-5" />
          <span className="font-semibold">RFQ sent successfully!</span>
        </div>
        <p className="text-sm text-emerald-600 dark:text-emerald-400">
          Suppliers have been invited. They will submit their quotes. Once all quotes are received (or the deadline passes),
          you can proceed to <strong>Apply Markup</strong> to set your markup percentage.
        </p>
      </div>
    </div>
  )
}

// --- Top-level page ----------------------------------------------------

export default function MarketplaceSendPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [selectedOrderId, setSelectedOrderId] = useState(null)
  const [sentRfq, setSentRfq] = useState(null)

  const sendMutation = useMutation({
    mutationFn: (orderId) => sendRfq(orderId),
    onSuccess: (rfq) => {
      toast.success(`RFQ ${rfq.reference} sent to ${rfq.invited_count} supplier(s)`)
      setSentRfq(rfq)
      qc.invalidateQueries({ queryKey: ['marketplace', 'orders-for-rfq'] })
    },
    onError: (e) => toast.error(e.message || 'Failed to send RFQ'),
  })

  const handleSend = (orderId) => {
    setSelectedOrderId(orderId)
    sendMutation.mutate(orderId)
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Send className="w-6 h-6 text-blue-600" /> Send RFQ
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Select an order in <code>pending_approval</code> status to fan out an RFQ
            to all active suppliers at the destination port.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Order picker */}
        <div className="lg:col-span-1">
          <OrderPicker
            onSelect={handleSend}
            sendingId={sendMutation.isPending ? selectedOrderId : null}
          />
        </div>

        {/* Detail / confirmation */}
        <div className="lg:col-span-2">
          {sentRfq ? (
            <RfqDetailView rfq={sentRfq} onBack={() => setSentRfq(null)} />
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center">
              <Send className="w-10 h-10 mx-auto text-slate-300 mb-3" />
              <div className="text-sm font-medium text-slate-700">Select an order</div>
              <p className="text-xs text-slate-500 mt-1">
                Pick an order from the list to send an RFQ to suppliers.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}