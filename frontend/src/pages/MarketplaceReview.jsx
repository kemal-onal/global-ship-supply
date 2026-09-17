import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2, Send, CheckCircle, AlertCircle, Clock, Eye, User, Shield } from 'lucide-react'
import toast from 'react-hot-toast'

import { getQuotesForPurchaser } from '../api/marketplaceSimple'

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

// --- Quote card for review ---------------------------------------------

function QuoteCard({ quote, index, totalQuotes, onToggleExpand }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      {/* Quote header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
            <span className="text-sm font-bold text-blue-700 dark:text-blue-400">
              {String.fromCharCode(65 + index)}
            </span>
          </div>
          <div>
            <div className="font-medium text-slate-700 dark:text-slate-300">
              {quote.supplier_alias}
            </div>
            <div className="text-[11px] text-slate-500 flex items-center gap-3">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" /> {quote.lead_time_days} days
              </span>
              {quote.payment_terms && (
                <span className="flex items-center gap-1">
                  <Shield className="w-3 h-3" /> {quote.payment_terms}
                </span>
              )}
              <span className="flex items-center gap-1">
                <User className="w-3 h-3" /> Submitted: {formatDateTime(quote.submitted_at)}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-right">
            <div className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              {formatMoney(quote.customer_facing_total)}
            </div>
            <div className="text-[10px] text-slate-500">Customer Total</div>
          </div>
          <button
            onClick={() => onToggleExpand(quote.quote_id)}
            className="px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          >
            {expanded ? 'Hide lines' : 'Show lines'}
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
                <th className="px-3 py-2 text-left">IMPA</th>
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
                    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                      item.line_status === 'full' ? 'bg-emerald-100 text-emerald-700' :
                      item.line_status === 'partial' ? 'bg-amber-100 text-amber-700' :
                      'bg-slate-100 text-slate-500'
                    }`}>
                      {item.line_status === 'full' ? 'Full' : item.line_status === 'partial' ? `Partial (${item.quoted_quantity})` : 'No bid'}
                    </span>
                  </td>
                </tr>
              ))}
              <tr className="bg-slate-50/50 dark:bg-slate-800/30">
                <td colSpan={4} className="px-3 py-2 text-right font-medium">Supplier Subtotal:</td>
                <td className="px-3 py-2 text-right font-semibold">{formatMoney(quote.subtotal)}</td>
                <td className="px-3 py-2"></td>
              </tr>
              <tr className="bg-slate-50/50 dark:bg-slate-800/30">
                <td colSpan={4} className="px-3 py-2 text-right font-medium">Marked-up Total:</td>
                <td className="px-3 py-2 text-right font-semibold text-violet-600 dark:text-violet-400">{formatMoney(quote.marked_up_total)}</td>
                <td className="px-3 py-2"></td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// --- Summary comparison table ------------------------------------------

function SummaryTable({ quotes }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
        <div className="text-sm font-semibold text-slate-700 dark:text-slate-300">Quick Comparison</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0 z-10">
            <tr>
              <th className="px-3 py-2 text-left text-xs uppercase text-slate-500 sticky left-0 bg-slate-50 dark:bg-slate-800/50 z-10 min-w-[160px]">
                Supplier
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Lines Bid
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Lead Time
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[120px]">
                Payment Terms
              </th>
              <th className="px-3 py-2 text-right text-xs uppercase text-slate-500 min-w-[140px]">
                Customer Total
              </th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((quote, idx) => (
              <tr key={quote.quote_id} className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50/50 dark:hover:bg-slate-800/50">
                <td className="px-3 py-2 sticky left-0 bg-white dark:bg-slate-900 z-10">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <span className="text-xs font-bold text-blue-700 dark:text-blue-400">
                        {String.fromCharCode(65 + idx)}
                      </span>
                    </div>
                    <span className="font-medium">{quote.supplier_alias}</span>
                  </div>
                </td>
                <td className="px-3 py-2 text-center">
                  {quote.items?.filter(i => i.line_status !== 'none').length || 0} / {quote.items?.length || 0}
                </td>
                <td className="px-3 py-2 text-center">{quote.lead_time_days} days</td>
                <td className="px-3 py-2 text-center">{quote.payment_terms || '—'}</td>
                <td className="px-3 py-2 text-right font-semibold text-violet-600 dark:text-violet-400">
                  {formatMoney(quote.customer_facing_total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// --- Top-level page ----------------------------------------------------

export default function MarketplaceReviewPage() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const [expandedQuotes, setExpandedQuotes] = useState(new Set())

  const { data: quotes, isLoading, error } = useQuery({
    queryKey: ['rfq', rfqId, 'quotes-for-purchaser'],
    queryFn: () => getQuotesForPurchaser(rfqId),
    enabled: !!rfqId,
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

  if (isLoading) {
    return (
      <div className="p-12 text-center text-sm text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" />
        Loading quotes for review…
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
        onClick={() => navigate('/marketplace/send')}
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Send RFQ
      </button>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Send className="w-6 h-6 text-violet-600" /> Review & Send to Purchaser
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Review all supplier quotes with markup applied. Supplier identities are
            anonymized for fairness. Click "Send to Purchaser" when ready.
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
              totalQuotes={quotes.length}
              onToggleExpand={handleToggleExpand}
            />
          ))}
        </div>

        {/* Action */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Ready to send to purchaser
              </div>
              <div className="text-xs text-slate-500 mt-1">
                The purchaser will see these same quotes with supplier identities
                anonymized (Supplier A, B, C...). They will approve or reject the
                entire proposal.
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <div className="text-xs text-slate-500">Quotes</div>
                <div className="text-lg font-bold text-slate-700 dark:text-slate-300">{quotes.length}</div>
              </div>
              <button
                onClick={() => navigate(`/marketplace/markup/${rfqId}`)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg"
              >
                Back to Markup
              </button>
              <button
                onClick={() => {
                  // This would call the submitToPurchaser API
                  // For now just navigate - in real implementation, call the API first
                  navigate(`/marketplace/decide/${rfqId}`)
                }}
                className="px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium rounded-lg inline-flex items-center gap-2"
              >
                <Send className="w-4 h-4" /> Send to Purchaser
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}