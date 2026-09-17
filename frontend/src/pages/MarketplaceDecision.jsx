import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2, CheckCircle, XCircle, AlertCircle, Clock, Shield, User, Eye, CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { getQuotesForPurchaser, purchaserDecide } from '../api/marketplaceSimple'

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

const lineStatusColor = (status) => {
  switch (status) {
    case 'full': return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    case 'partial': return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
    case 'none': return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500'
    default: return 'bg-slate-100 text-slate-700'
  }
}

// --- Quote card for purchaser ------------------------------------------

function QuoteCard({ quote, index, onToggleExpand }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      {/* Quote header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
            <span className="text-sm font-bold text-violet-700 dark:text-violet-400">
              {String.fromCharCode(65 + index)}
            </span>
          </div>
          <div>
            <div className="font-medium text-slate-700 dark:text-slate-300">
              {quote.supplier_alias}
            </div>
            <div className="text-[11px] text-slate-500 flex items-center gap-3">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" /> {quote.lead_time_days} days delivery
              </span>
              {quote.payment_terms && (
                <span className="flex items-center gap-1">
                  <Shield className="w-3 h-3" /> {quote.payment_terms}
                </span>
              )}
              <span className="flex items-center gap-1">
                <User className="w-3 h-3" /> Quoted: {formatDateTime(quote.submitted_at)}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-right">
            <div className="text-sm font-semibold text-violet-600 dark:text-violet-400">
              {formatMoney(quote.customer_facing_total)}
            </div>
            <div className="text-[10px] text-slate-500">Total (with markup)</div>
          </div>
          <button
            onClick={() => onToggleExpand(quote.quote_id)}
            className="px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          >
            {expanded ? 'Hide details' : 'Show details'}
            <Eye className={`w-4 h-4 ml-1 ${expanded ? 'rotate-180' : ''}`} />
          </button>
        </div>
      </div>

      {/* Expanded lines */}
      {expanded && (
        <div className="overflow-x-auto px-4 py-3">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">Product</th>
                <th className="px-3 py-2 text-left">IMPA Code</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Unit Price</th>
                <th className="px-3 py-2 text-right">Line Total</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {quote.items.map((item) => (
                <tr key={item.product_id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2">
                    <div className="font-medium">{item.description || 'Product'}</div>
                    <div className="text-[10px] text-slate-500 font-mono">{item.product_id.slice(0, 8)}</div>
                  </td>
                  <td className="px-3 py-2 font-mono text-sm">IMPA {item.impa_code || '—'}</td>
                  <td className="px-3 py-2 text-right">{item.quantity}</td>
                  <td className="px-3 py-2 text-right font-mono">{formatMoney(item.unit_price)}</td>
                  <td className="px-3 py-2 text-right font-semibold">{formatMoney(item.line_total)}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${lineStatusColor(item.line_status)}`}>
                      {item.line_status === 'full' ? 'Full' : item.line_status === 'partial' ? `Partial (${item.quoted_quantity})` : 'No bid'}
                    </span>
                  </td>
                </tr>
              ))}
              <tr className="bg-slate-50/50 dark:bg-slate-800/30 border-t-2 border-slate-200 dark:border-slate-700">
                <td colSpan={4} className="px-3 py-2 text-right font-medium">Supplier Subtotal:</td>
                <td className="px-3 py-2 text-right font-semibold">{formatMoney(quote.subtotal)}</td>
                <td className="px-3 py-2"></td>
              </tr>
              <tr className="bg-violet-50 dark:bg-violet-900/20">
                <td colSpan={4} className="px-3 py-2 text-right font-medium">With Markup:</td>
                <td className="px-3 py-2 text-right font-bold text-violet-600 dark:text-violet-400">{formatMoney(quote.customer_facing_total)}</td>
                <td className="px-3 py-2"></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// --- Summary table -----------------------------------------------------

function SummaryTable({ quotes }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
        <div className="text-sm font-semibold text-slate-700 dark:text-slate-300">Supplier Comparison</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0 z-10">
            <tr>
              <th className="px-3 py-2 text-left text-xs uppercase text-slate-500 sticky left-0 bg-slate-50 dark:bg-slate-800/50 z-10 min-w-[160px]">
                Supplier
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Lines Fulfilled
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Lead Time
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[120px]">
                Payment Terms
              </th>
              <th className="px-3 py-2 text-right text-xs uppercase text-slate-500 min-w-[140px]">
                Total (w/ Markup)
              </th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((quote, idx) => {
              const fulfilledLines = quote.items?.filter(i => i.line_status !== 'none').length || 0
              const totalLines = quote.items?.length || 0
              return (
                <tr key={quote.quote_id} className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50/50 dark:hover:bg-slate-800/50">
                  <td className="px-3 py-2 sticky left-0 bg-white dark:bg-slate-900 z-10">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
                        <span className="text-xs font-bold text-violet-700 dark:text-violet-400">
                          {String.fromCharCode(65 + idx)}
                        </span>
                      </div>
                      <span className="font-medium">{quote.supplier_alias}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={fulfilledLines === totalLines ? 'text-emerald-600 font-semibold' : 'text-amber-600'}>
                      {fulfilledLines} / {totalLines}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">{quote.lead_time_days} days</td>
                  <td className="px-3 py-2 text-center">{quote.payment_terms || '—'}</td>
                  <td className="px-3 py-2 text-right font-semibold text-violet-600 dark:text-violet-400">
                    {formatMoney(quote.customer_facing_total)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// --- Decision modal ----------------------------------------------------

function DecisionModal({ isOpen, onClose, onDecide, deciding }) {
  const [approve, setApprove] = useState(true)
  const [reason, setReason] = useState('')

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-900 rounded-xl p-6 max-w-md w-full shadow-xl">
        <div className="flex items-center gap-3 mb-4">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
            approve ? 'bg-emerald-100 dark:bg-emerald-900/30' : 'bg-rose-100 dark:bg-rose-900/30'
          }`}>
            {approve ? (
              <CheckCircle2 className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <XCircle className="w-6 h-6 text-rose-600 dark:text-rose-400" />
            )}
          </div>
          <h2 className="text-lg font-semibold">
            {approve ? 'Approve Proposal' : 'Reject Proposal'}
          </h2>
        </div>

        <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
          {approve
            ? 'This will approve ALL supplier quotes and move the order to APPROVED status. The RFQ will be marked as AWARDED.'
            : 'This will reject ALL supplier quotes and return the order to DRAFT status. You can edit and re-submit the order.'}
        </p>

        {!approve && (
          <div className="mb-4">
            <label className="block text-xs font-semibold text-slate-500 mb-1">
              Rejection Reason (required)
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Explain why you're rejecting..."
              required
            />
          </div>
        )}

        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            disabled={deciding}
            className="px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={() => onDecide(approve, reason)}
            disabled={deciding || (!approve && !reason.trim())}
            className={`px-4 py-2 text-sm font-medium rounded-lg inline-flex items-center gap-2 ${
              approve
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                : 'bg-rose-600 hover:bg-rose-700 text-white'
            } ${deciding ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {deciding ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : approve ? (
              <>
                <CheckCircle className="w-4 h-4" /> Approve All
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4" /> Reject All
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// --- Top-level page ----------------------------------------------------

export default function MarketplaceDecisionPage() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [expandedQuotes, setExpandedQuotes] = useState(new Set())
  const [showModal, setShowModal] = useState(false)
  const [deciding, setDeciding] = useState(false)

  const { data: quotes, isLoading, error } = useQuery({
    queryKey: ['rfq', rfqId, 'quotes-for-purchaser'],
    queryFn: () => getQuotesForPurchaser(rfqId),
    enabled: !!rfqId,
  })

  const decideMutation = useMutation({
    mutationFn: ({ approve, reason }) => purchaserDecide(rfqId, { approve, reason }),
    onSuccess: (result) => {
      toast.success(result.message)
      qc.invalidateQueries({ queryKey: ['orders'] })
      setShowModal(false)
      setDeciding(false)
      // Navigate to order detail
      setTimeout(() => navigate(`/orders/${result.order_id}`), 1500)
    },
    onError: (e) => {
      toast.error(e.message || 'Decision failed')
      setDeciding(false)
    },
  })

  const handleToggleExpand = (quoteId) => {
    setExpandedQuotes(prev => {
      const next = new Set(prev)
      if (next.has(quoteId)) {
        next.delete(quoteId)
      } else {
        next.add(quoteId)
      }
      return next
    })
  }

  const handleDecide = (approve, reason) => {
    if (!approve && !reason.trim()) {
      toast.error('Please provide a rejection reason')
      return
    }
    setDeciding(true)
    decideMutation.mutate({ approve, reason })
  }

  if (isLoading) {
    return (
      <div className="p-12 text-center text-sm text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" />
        Loading quotes for decision…
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
  if (!quotes || quotes.length === 0) {
    return (
      <div className="p-12 text-center">
        <AlertCircle className="w-10 h-10 mx-auto text-amber-500 mb-3" />
        <div className="text-sm font-medium text-slate-700">No quotes to review</div>
        <p className="text-xs text-slate-500 mt-1">This RFQ has no supplier quotes yet.</p>
      </div>
    )
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
            <CheckCircle2 className="w-6 h-6 text-violet-600" /> Approve or Reject Quotes
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Review all supplier quotes with markup applied. Make one decision for the entire proposal.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Summary table */}
        <SummaryTable quotes={quotes} />

        {/* Detailed quote cards */}
        <div className="space-y-3">
          {quotes.map((quote, idx) => (
            <QuoteCard
              key={quote.quote_id}
              quote={quote}
              index={idx}
              onToggleExpand={handleToggleExpand}
            />
          ))}
        </div>

        {/* Decision buttons */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Make your decision
              </div>
              <div className="text-xs text-slate-500 mt-1">
                {quotes.length} supplier quote(s) received. Your decision applies to the entire proposal.
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => { setApprove(true); setShowModal(true); }}
                disabled={deciding}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg inline-flex items-center gap-2"
              >
                <CheckCircle className="w-4 h-4" /> Approve All
              </button>
              <button
                onClick={() => { setApprove(false); setShowModal(true); }}
                disabled={deciding}
                className="px-4 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg inline-flex items-center gap-2"
              >
                <XCircle className="w-4 h-4" /> Reject All
              </button>
            </div>
          </div>
        </div>

        {/* Info box */}
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
          <div className="flex items-start gap-2">
            <div className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5">ℹ️</div>
            <div className="text-sm text-blue-700 dark:text-blue-300">
              <strong>What happens next:</strong>
              <ul className="list-disc list-inside mt-1 space-y-1">
                <li><strong>Approve:</strong> Order → <code className="bg-white dark:bg-slate-800 px-1 rounded">APPROVED</code>, RFQ → <code className="bg-white dark:bg-slate-800 px-1 rounded">AWARDED</code></li>
                <li><strong>Reject:</strong> Order → <code className="bg-white dark:bg-slate-800 px-1 rounded">DRAFT</code>, RFQ → <code className="bg-white dark:bg-slate-800 px-1 rounded">CANCELLED</code> (you can edit and re-submit)</li>
                <li>Supplier identities remain anonymized throughout</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <DecisionModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        onDecide={handleDecide}
        deciding={deciding}
      />
    </div>
  )
}