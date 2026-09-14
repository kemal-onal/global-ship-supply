import React, { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2, Percent, Calculator, Send, CheckCircle, AlertCircle, Clock } from 'lucide-react'
import toast from 'react-hot-toast'

import { getRfqDetail, applyMarkup, submitToPurchaser } from '../api/marketplaceSimple'

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

const statusColor = (status) => {
  switch (status) {
    case 'sent': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'closed': return 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400'
    case 'awarded': return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    case 'cancelled': return 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400'
    default: return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-400'
  }
}

// --- Quote comparison table --------------------------------------------

function QuoteComparisonTable({ quotes, rfq, markup, onMarkupChange, markupMutation, submitMutation, showSubmit }) {
  const lineStatusColor = (status) => {
    switch (status) {
      case 'full': return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
      case 'partial': return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
      case 'none': return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500'
      default: return 'bg-slate-100 text-slate-700'
    }
  }

  // Collect all unique products across quotes for comparison
  const allProducts = new Map()
  quotes.forEach((quote) => {
    quote.items?.forEach((item) => {
      if (!allProducts.has(item.product_id)) {
        allProducts.set(item.product_id, {
          product_id: item.product_id,
          description: item.description || '—',
          impa_code: item.impa_code || '—',
        })
      }
    })
  })

  const products = Array.from(allProducts.values())

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      {/* Markup control */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Percent className="w-5 h-5 text-slate-500" />
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Markup %</span>
          </div>
          <input
            type="number"
            min="0"
            max="100"
            step="0.5"
            value={markup}
            onChange={(e) => onMarkupChange(parseFloat(e.target.value) || 0)}
            disabled={markupMutation.isPending}
            className="w-20 px-2 py-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-sm font-mono text-right"
          />
          <span className="text-sm text-slate-500">applied to all quotes</span>
        </div>
        {showSubmit && (
          <button
            onClick={() => submitMutation.mutate(rfq.id)}
            disabled={submitMutation.isPending}
            className="px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg inline-flex items-center gap-2"
          >
            {submitMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            Send to Purchaser
          </button>
        )}
      </div>

      {/* Comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0 z-10">
            <tr>
              <th className="px-3 py-2 text-left text-xs uppercase text-slate-500 sticky left-0 bg-slate-50 dark:bg-slate-800/50 z-10 min-w-[180px]">
                Line / Supplier
              </th>
              {quotes.map((quote) => (
                <th key={quote.id} className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[140px]">
                  <div className="font-semibold truncate" title={quote.supplier_alias}>
                    {quote.supplier_alias}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    {quote.lead_time_days}d · {formatMoney(quote.customer_facing_total, 'USD')}
                  </div>
                </th>
              ))}
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Best Price
              </th>
            </tr>
          </thead>
          <tbody>
            {products.map((product) => (
              <React.Fragment key={product.product_id}>
                {/* Line header */}
                <tr className="bg-slate-50/50 dark:bg-slate-800/30 border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2 sticky left-0 bg-slate-50/50 dark:bg-slate-800/30 z-10">
                    <div className="font-mono text-[11px] text-slate-500">IMPA {product.impa_code}</div>
                    <div className="text-sm font-medium truncate max-w-[200px]" title={product.description}>
                      {product.description}
                    </div>
                  </td>
                  {quotes.map((quote) => {
                    const item = quote.items?.find(i => i.product_id === product.product_id)
                    if (!item) {
                      return <td key={quote.id} className="px-3 py-2 text-center text-slate-300 text-[11px]">—</td>
                    }
                    return (
                      <td key={quote.id} className="px-3 py-2 text-center">
                        <div className={`px-2 py-1 rounded text-[11px] font-semibold ${lineStatusColor(item.line_status)}`}>
                          {item.line_status === 'none' ? 'No bid' : item.line_status}
                        </div>
                        {item.line_status !== 'none' && (
                          <div className="text-[10px] opacity-80 mt-0.5">
                            {item.line_status === 'partial' && item.quoted_quantity
                              ? `${item.quoted_quantity} × `
                              : ''}
                            {formatMoney(item.unit_price, quote.currency || 'USD')}
                          </div>
                        )}
                      </td>
                    )
                  })}
                  <td className="px-3 py-2 text-center">
                    {(() => {
                      const validItems = quotes
                        .flatMap(q => q.items || [])
                        .filter(i => i.product_id === product.product_id && i.line_status !== 'none')
                      if (validItems.length === 0) return <span className="text-slate-400 text-[11px]">—</span>
                      const best = validItems.reduce((a, b) => a.unit_price < b.unit_price ? a : b)
                      return <span className="text-emerald-600 dark:text-emerald-400 font-semibold text-[11px]">{formatMoney(best.unit_price, best.currency || 'USD')}</span>
                    })()}
                  </td>
                </tr>
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// --- RFQ Header --------------------------------------------------------

function RfqHeader({ rfq, onBack }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold font-mono">{rfq.reference}</h1>
            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${statusColor(rfq.status)}`}>
              {rfq.status}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1 flex items-center gap-4 flex-wrap">
            <span>Order: <span className="font-mono">{rfq.order_reference || rfq.order_id}</span></span>
            <span>{rfq.invited_count} invited · {rfq.responded_count} responded</span>
            <span><Clock className="w-3 h-3 inline" /> Deadline: {formatDateTime(rfq.response_deadline)}</span>
            {rfq.closed_at && <span><CheckCircle className="w-3 h-3 inline text-emerald-500" /> Closed: {formatDateTime(rfq.closed_at)}</span>}
          </p>
        </div>
        <button
          onClick={onBack}
          className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg inline-flex items-center gap-1.5"
        >
          <ArrowLeft className="w-4 h-4" /> Back
        </button>
      </div>
    </div>
  )
}

// --- Top-level page ----------------------------------------------------

export default function MarketplaceMarkupPage() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [markup, setMarkup] = useState(0)

  const { data: rfq, isLoading, error } = useQuery({
    queryKey: ['rfq', rfqId, 'detail'],
    queryFn: () => getRfqDetail(rfqId),
    enabled: !!rfqId,
  })

  const markupMutation = useMutation({
    mutationFn: ({ rfqId, markupPct }) => applyMarkup(rfqId, markupPct),
    onSuccess: (updatedRfq) => {
      toast.success(`Markup ${updatedRfq.markup_pct}% applied to all quotes`)
      qc.invalidateQueries({ queryKey: ['rfq', rfqId, 'detail'] })
      setMarkup(parseFloat(updatedRfq.markup_pct))
    },
    onError: (e) => toast.error(e.message || 'Failed to apply markup'),
  })

  const submitMutation = useMutation({
    mutationFn: (rfqId) => submitToPurchaser(rfqId),
    onSuccess: (rfq) => {
      toast.success(`Quotes sent to purchaser (RFQ: ${rfq.status})`)
      qc.invalidateQueries({ queryKey: ['rfq', rfqId, 'detail'] })
      navigate(`/marketplace/review/${rfqId}`)
    },
    onError: (e) => toast.error(e.message || 'Failed to send to purchaser'),
  })

  const handleMarkupChange = (value) => {
    setMarkup(value)
    // Debounce the API call
    clearTimeout(window._markupTimeout)
    window._markupTimeout = setTimeout(() => {
      if (rfq) {
        markupMutation.mutate({ rfqId: rfq.id, markupPct: value })
      }
    }, 500)
  }

  if (isLoading) {
    return (
      <div className="p-12 text-center text-sm text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" />
        Loading RFQ…
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
  if (!rfq) return null

  const quotes = rfq.quotes || []
  const allResponded = rfq.responded_count >= rfq.invited_count && rfq.invited_count > 0
  const showSubmit = rfq.status === 'sent' && quotes.length > 0

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      {rfq && <RfqHeader rfq={rfq} onBack={() => navigate('/marketplace/send')} />}

      <div className="space-y-4">
        {/* Status info */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wide">RFQ Status</div>
              <div className="font-medium capitalize">{rfq.status}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wide">Markup Applied</div>
              <div className="font-medium">{rfq.markup_pct}%</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wide">Quotes Received</div>
              <div className="font-medium">{quotes.length} / {rfq.invited_count}</div>
            </div>
          </div>
        </div>

        {/* Quotes comparison */}
        {quotes.length > 0 ? (
          <QuoteComparisonTable
            quotes={quotes}
            rfq={rfq}
            markup={markup}
            onMarkupChange={handleMarkupChange}
            markupMutation={markupMutation}
            submitMutation={submitMutation}
            showSubmit={showSubmit}
          />
        ) : (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center">
            <Loader2 className="w-10 h-10 mx-auto text-slate-300 animate-spin mb-3" />
            <div className="text-sm font-medium text-slate-700">Waiting for supplier quotes</div>
            <p className="text-xs text-slate-500 mt-1">
              {rfq.responded_count}/{rfq.invited_count} suppliers have responded.
              {allResponded ? ' All quotes received — ready for markup.' : ' Check back when more suppliers respond.'}
            </p>
          </div>
        )}

        {/* Help text */}
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
          <div className="flex items-start gap-2">
            <Calculator className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5" />
            <div className="text-sm text-blue-700 dark:text-blue-300">
              <strong>How it works:</strong> The markup percentage is applied uniformly to all supplier quotes.
              The supplier's original total is multiplied by (1 + markup%/100) to get the customer-facing total.
              The purchaser will see the marked-up totals without knowing which supplier they came from.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}