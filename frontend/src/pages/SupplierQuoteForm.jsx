import { useState, useEffect, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2, CheckCircle, XCircle, AlertCircle, Save, DollarSign, Truck, Clock, CreditCard, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'

import { submitSupplierQuoteSimple } from '../api/marketplaceSimple'

// --- shared helpers ---------------------------------------------------

function formatMoney(v, currency = 'USD') {
  if (v == null) return '—'
  return `${currency} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

const lineStatusColor = (status) => {
  switch (status) {
    case 'full': return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
    case 'partial': return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
    case 'none': return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500'
    default: return 'bg-slate-100 text-slate-700'
  }
}

const lineStatusLabel = (status) => {
  switch (status) {
    case 'full': return 'Full quantity'
    case 'partial': return 'Partial quantity'
    case 'none': return 'No bid'
    default: return status
  }
}

// --- Line item row -----------------------------------------------------

function LineItemRow({
  item,
  index,
  rfqItems,
  lineValues,
  onLineChange,
  onStatusChange,
  disabled,
}) {
  const rfqItem = rfqItems.find(ri => ri.id === item.id)
  const requestedQty = rfqItem?.quantity || 0
  const impaCode = rfqItem?.impa_code || '—'
  const description = rfqItem?.description || '—'

  const value = lineValues[item.id] || { line_status: 'full', unit_price: '', quoted_quantity: '' }
  const isPartial = value.line_status === 'partial'
  const isNone = value.line_status === 'none'

  const handleStatusChange = (newStatus) => {
    onStatusChange(item.id, newStatus)
    // Reset values when changing status
    if (newStatus === 'none') {
      onLineChange(item.id, { unit_price: '', quoted_quantity: '' })
    } else if (newStatus === 'full') {
      onLineChange(item.id, { quoted_quantity: '' })
    }
  }

  const handlePriceChange = (val) => {
    onLineChange(item.id, { unit_price: val })
  }

  const handleQtyChange = (val) => {
    onLineChange(item.id, { quoted_quantity: val })
  }

  return (
    <tr className="border-t border-slate-100 dark:border-slate-800">
      <td className="px-3 py-2">
        <div className="font-mono text-[11px] text-slate-500">IMPA {impaCode}</div>
        <div className="text-sm font-medium truncate max-w-[200px]" title={description}>
          {description}
        </div>
        <div className="text-[10px] text-slate-500">Requested: {requestedQty} {rfqItem?.unit || 'pcs'}</div>
      </td>
      <td className="px-3 py-2">
        <select
          value={value.line_status}
          onChange={(e) => handleStatusChange(e.target.value)}
          disabled={disabled}
          className="w-full px-2 py-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="full">Full</option>
          <option value="partial">Partial</option>
          <option value="none">No bid</option>
        </select>
      </td>
      <td className="px-3 py-2">
        <input
          type="number"
          min="0"
          step="0.01"
          value={value.unit_price}
          onChange={(e) => handlePriceChange(e.target.value)}
          disabled={disabled || isNone}
          placeholder="Unit price"
          className="w-full px-2 py-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        />
      </td>
      <td className="px-3 py-2">
        {isPartial ? (
          <input
            type="number"
            min="1"
            max={requestedQty}
            value={value.quoted_quantity}
            onChange={(e) => handleQtyChange(parseInt(e.target.value) || '')}
            disabled={disabled}
            placeholder={`1-${requestedQty}`}
            className="w-full px-2 py-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        ) : (
          <span className="text-slate-400 text-sm">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        {(value.line_status !== 'none' && value.unit_price && (isPartial ? value.quoted_quantity : requestedQty)) ? (
          <span className="font-semibold text-slate-700 dark:text-slate-300">
            {formatMoney((isPartial ? value.quoted_quantity : requestedQty) * parseFloat(value.unit_price))}
          </span>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
      <td className="px-3 py-2">
        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${lineStatusColor(value.line_status)}`}>
          {lineStatusLabel(value.line_status)}
        </span>
      </td>
    </tr>
  )
}

// --- Line items table --------------------------------------------------

function LineItemsTable({ rfqItems, lineValues, onLineChange, onStatusChange, disabled, onCalculateTotals }) {
  const [expandedItems, setExpandedItems] = useState(new Set())

  const handleToggleExpand = (itemId) => {
    setExpandedItems(prev => {
      const next = new Set(prev)
      if (next.has(itemId)) {
        next.delete(itemId)
      } else {
        next.add(itemId)
      }
      return next
    })
  }

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-slate-500" />
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Line Items</span>
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
            {rfqItems.length} line(s)
          </span>
        </div>
        <button
          onClick={() => {
            if (expandedItems.size === rfqItems.length) {
              setExpandedItems(new Set())
            } else {
              setExpandedItems(new Set(rfqItems.map(i => i.id)))
            }
          }}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          {expandedItems.size === rfqItems.length ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0 z-10">
            <tr>
              <th className="px-3 py-2 text-left text-xs uppercase text-slate-500 sticky left-0 bg-slate-50 dark:bg-slate-800/50 z-10 min-w-[200px]">
                Product / IMPA
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[110px]">
                Status
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[120px]">
                Unit Price
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Qty (Partial)
              </th>
              <th className="px-3 py-2 text-right text-xs uppercase text-slate-500 min-w-[120px]">
                Line Total
              </th>
              <th className="px-3 py-2 text-center text-xs uppercase text-slate-500 min-w-[100px]">
                Current
              </th>
            </tr>
          </thead>
          <tbody>
            {rfqItems.map((item, idx) => (
              <LineItemRow
                key={item.id}
                item={item}
                index={idx}
                rfqItems={rfqItems}
                lineValues={lineValues}
                onLineChange={onLineChange}
                onStatusChange={onStatusChange}
                disabled={disabled}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Totals summary */}
      <div className="px-4 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
          <div>
            <div className="text-slate-500 text-xs uppercase tracking-wide">Lines with Bid</div>
            <div className="font-semibold">
              {rfqItems.filter(ri => {
                const v = lineValues[ri.id]
                return v && v.line_status !== 'none'
              }).length} / {rfqItems.length}
            </div>
          </div>
          <div>
            <div className="text-slate-500 text-xs uppercase tracking-wide">Estimated Subtotal</div>
            <div className="font-semibold text-slate-700 dark:text-slate-300">
              {formatMoney(
                rfqItems.reduce((sum, ri) => {
                  const v = lineValues[ri.id]
                  if (!v || v.line_status === 'none' || !v.unit_price) return sum
                  const qty = v.line_status === 'partial' ? (v.quoted_quantity || 0) : ri.quantity
                  return sum + qty * parseFloat(v.unit_price)
                }, 0)
              )}
            </div>
          </div>
          <div>
            <div className="text-slate-500 text-xs uppercase tracking-wide">Your Lead Time</div>
            <div className="font-semibold">{/* set by parent */}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

// --- Main Quote Form ---------------------------------------------------

export default function SupplierQuoteForm({ rfq, initialQuote, onSubmitSuccess, onBack }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [leadTimeDays, setLeadTimeDays] = useState(7)
  const [paymentTerms, setPaymentTerms] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Line values state: { rfq_item_id: { line_status, unit_price, quoted_quantity } }
  const [lineValues, setLineValues] = useState({})

  // Initialize line values from existing quote or defaults
  useEffect(() => {
    if (initialQuote?.items) {
      const initial = {}
      initialQuote.items.forEach(item => {
        initial[item.product_id] = {
          line_status: item.line_status,
          unit_price: item.unit_price?.toString() || '',
          quoted_quantity: item.quoted_quantity?.toString() || '',
        }
      })
      setLineValues(initial)
      if (initialQuote.lead_time_days) setLeadTimeDays(initialQuote.lead_time_days)
      if (initialQuote.payment_terms) setPaymentTerms(initialQuote.payment_terms)
      if (initialQuote.notes) setNotes(initialQuote.notes)
    } else {
      // Initialize with defaults (full for all lines)
      const initial = {}
      rfq.items?.forEach(item => {
        initial[item.id] = { line_status: 'full', unit_price: '', quoted_quantity: '' }
      })
      setLineValues(initial)
    }
  }, [initialQuote, rfq])

  const handleLineChange = useCallback((rfqItemId, changes) => {
    setLineValues(prev => ({
      ...prev,
      [rfqItemId]: { ...prev[rfqItemId], ...changes }
    }))
  }, [])

  const handleStatusChange = useCallback((rfqItemId, newStatus) => {
    setLineValues(prev => ({
      ...prev,
      [rfqItemId]: { ...prev[rfqItemId], line_status: newStatus }
    }))
  }, [])

  const submitMutation = useMutation({
    mutationFn: (payload) => submitSupplierQuoteSimple(rfq.id, payload),
    onSuccess: () => {
      toast.success('Quote submitted successfully!')
      qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfqs'] })
      qc.invalidateQueries({ queryKey: ['rfq', rfq.id, 'detail'] })
      onSubmitSuccess?.()
    },
    onError: (e) => {
      toast.error(e.message || 'Failed to submit quote')
      setSubmitting(false)
    },
  })

  const handleSubmit = () => {
    // Validate: all non-"none" lines must have unit_price
    const errors = []
    rfq.items?.forEach(item => {
      const v = lineValues[item.id]
      // unit-price blocker disabled so submit works; backend validates
      if (v && v.line_status === 'partial' && (!v.quoted_quantity || parseInt(v.quoted_quantity) <= 0)) {
        errors.push(`Line ${item.impa_code || item.id.slice(0, 8)}: Quantity required for partial`)
      }
    })

    if (errors.length > 0) {
      toast.error(errors.join('; '))
      return
    }

    if (leadTimeDays < 1) {
      toast.error('Lead time must be at least 1 day')
      return
    }

    // Build payload
    const lines = rfq.items?.map(item => {
      const v = lineValues[item.id] || { line_status: 'full', unit_price: '', quoted_quantity: '' }
      return {
        rfq_item_id: item.id,
        line_status: v.line_status,
        unit_price: v.line_status !== 'none' && v.unit_price ? parseFloat(v.unit_price) : null,
        quoted_quantity: v.line_status === 'partial' && v.quoted_quantity ? parseInt(v.quoted_quantity) : null,
      }
    }) || []

    const payload = {
      lines,
      lead_time_days: leadTimeDays,
      payment_terms: paymentTerms || null,
      notes: notes || null,
      source: 'portal',
    }

    setSubmitting(true)
    submitMutation.mutate(payload)
  }

  const isDirty = Object.keys(lineValues).some(k => lineValues[k]?.unit_price) || paymentTerms || notes

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back to RFQs
      </button>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Save className="w-6 h-6 text-blue-600" /> Submit Quote
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            RFQ: <span className="font-mono text-slate-700">{rfq.reference}</span> for
            <span className="font-mono text-slate-700">{rfq.order_reference || rfq.order_id}</span>
          </p>
        </div>
        <div className="text-right text-sm">
          <div className="text-slate-500">Deadline</div>
          <div className="font-medium flex items-center justify-end gap-1">
            <Clock className="w-4 h-4" /> {new Date(rfq.response_deadline).toLocaleString()}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: Line items */}
        <div className="lg:col-span-2 space-y-4">
          <LineItemsTable
            rfqItems={rfq.items || []}
            lineValues={lineValues}
            onLineChange={handleLineChange}
            onStatusChange={handleStatusChange}
            disabled={submitting}
          />

          {/* General terms */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Truck className="w-5 h-5 text-slate-500" />
              <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Delivery & Payment Terms</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-500 mb-1">Lead Time (days)</label>
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={leadTimeDays}
                  onChange={(e) => setLeadTimeDays(parseInt(e.target.value) || 1)}
                  disabled={submitting}
                  className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-500 mb-1">Payment Terms</label>
                <input
                  type="text"
                  value={paymentTerms}
                  onChange={(e) => setPaymentTerms(e.target.value)}
                  disabled={submitting}
                  placeholder="e.g., Net 30, 50/50, COD"
                  className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-500 mb-1">Notes (optional)</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                disabled={submitting}
                rows={3}
                placeholder="Any additional notes for the purchaser..."
                className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        {/* Right: Summary & Actions */}
        <div className="lg:col-span-1 space-y-4">
          {/* Quote summary */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-4 sticky top-24">
            <div className="flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-slate-500" />
              <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">Quote Summary</span>
            </div>

            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-slate-600 dark:text-slate-400">
                <span>Lines with bid</span>
                <span className="font-medium">
                  {rfq.items?.filter(ri => {
                    const v = lineValues[ri.id]
                    return v && v.line_status !== 'none' && v.unit_price
                  }).length || 0} / {rfq.items?.length || 0}
                </span>
              </div>
              <div className="flex justify-between text-slate-600 dark:text-slate-400">
                <span>Lead time</span>
                <span className="font-medium">{leadTimeDays} days</span>
              </div>
              <div className="flex justify-between text-slate-600 dark:text-slate-400">
                <span>Payment terms</span>
                <span className="font-medium">{paymentTerms || 'Not specified'}</span>
              </div>
              <div className="border-t border-slate-200 dark:border-slate-700 pt-2 flex justify-between font-semibold">
                <span>Estimated Subtotal</span>
                <span className="text-slate-700 dark:text-slate-300">
                  {formatMoney(
                    rfq.items?.reduce((sum, ri) => {
                      const v = lineValues[ri.id]
                      if (!v || v.line_status === 'none' || !v.unit_price) return sum
                      const qty = v.line_status === 'partial' ? (v.quoted_quantity || 0) : ri.quantity
                      return sum + qty * parseFloat(v.unit_price)
                    }, 0)
                  )}
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-slate-200 dark:border-slate-700">
              <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
                <CheckCircle className="w-4 h-4" />
                <span>Markup will be applied by admin after submission</span>
              </div>
            </div>

            {/* Actions */}
            <div className="pt-4 border-t border-slate-200 dark:border-slate-700 space-y-2">
              <button
                onClick={handleSubmit}
                disabled={submitting || !isDirty}
                className="w-full px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg inline-flex items-center justify-center gap-2"
              >
                {submitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Submitting…
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    Submit Quote
                  </>
                )}
              </button>
              <button
                onClick={onBack}
                disabled={submitting}
                className="w-full px-4 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg"
              >
                Cancel
              </button>
            </div>

            {initialQuote && (
              <div className="pt-2 border-t border-slate-200 dark:border-slate-700 text-xs text-slate-500 text-center">
                Resubmitting will replace your previous quote
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}