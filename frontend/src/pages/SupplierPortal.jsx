import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2, Inbox, Package, Truck, FileText, Info, Clock, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'

import { listSupplierRfqsSimple, getSupplierRfqSimple } from '../api/marketplaceSimple'
import SupplierQuoteForm from './SupplierQuoteForm'

// --- shared status / format helpers -----------------------------------

const statusPalette = {
  draft: 'bg-slate-100 text-slate-700',
  sent: 'bg-blue-100 text-blue-700',
  closed: 'bg-violet-100 text-violet-700',
  awarded: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-rose-100 text-rose-700',
}

function StatusBadge({ status }) {
  const cls = statusPalette[status] || 'bg-slate-100 text-slate-700'
  return (
    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${cls}`}>
      {(status || 'unknown').replace(/_/g, ' ')}
    </span>
  )
}

function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

// --- RFQ List ----------------------------------------------------------

function RfqList({ activeId, onSelect }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['supplier-portal', 'rfqs'],
    queryFn: () => listSupplierRfqsSimple(),
  })

  if (isLoading) {
    return (
      <div className="p-6 text-center text-sm text-slate-500">
        <Loader2 className="w-4 h-4 animate-spin inline-block mr-2" />
        Loading your invitations…
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-6 text-center text-sm text-rose-500">
        {error.message}
      </div>
    )
  }

  const rows = data || []

  if (rows.length === 0) {
    return (
      <div className="p-8 text-center">
        <Inbox className="w-8 h-8 mx-auto text-slate-300 mb-2" />
        <div className="text-sm font-medium text-slate-700">No invitations yet</div>
        <p className="text-xs text-slate-500 mt-1">
          When a vessel is in your port and an order fans out, the RFQ
          will appear here.
        </p>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {rows.map((r) => {
        const isActive = r.id === activeId
        const hasQuote = r.has_quote
        return (
          <li key={r.id}>
            <button
              onClick={() => onSelect(r.id)}
              className={`w-full text-left px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors ${
                isActive ? 'bg-blue-50/60 dark:bg-blue-900/20' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-mono text-xs text-slate-500 truncate">
                  {r.reference}
                </div>
                <StatusBadge status={r.status} />
              </div>
              <div className="mt-1 text-sm font-medium truncate">
                {r.order_reference}
              </div>
              <div className="mt-0.5 text-xs text-slate-500 flex items-center gap-1.5">
                <Truck className="w-3 h-3" />
                {r.vessel_label}
                {r.port_name ? <span>· {r.port_name}</span> : null}
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                <span>
                  {r.responded_count ?? 0}/{r.invited_count ?? 0} responded
                </span>
                {hasQuote ? (
                  <span className="inline-flex items-center gap-0.5 text-emerald-600">
                    <Package className="w-3 h-3" /> Quote submitted
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-0.5 text-amber-600">
                    <Clock className="w-3 h-3" /> Action needed
                  </span>
                )}
                {r.markup_pct !== undefined && r.markup_pct > 0 && (
                  <span className="inline-flex items-center gap-0.5 text-violet-600 text-[10px]">
                    Markup: {r.markup_pct}%
                  </span>
                )}
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

// --- RFQ Detail --------------------------------------------------------

function RfqDetail({ rfqId, onBack }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['supplier-portal', 'rfq', rfqId],
    queryFn: () => getSupplierRfqSimple(rfqId),
  })

  if (isLoading) {
    return (
      <div className="p-12 text-center text-sm text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" />
        Loading…
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-12 text-center text-sm text-rose-500">
        {error.message}
      </div>
    )
  }
  if (!data) return null

  const myQuote = data.my_quote
  const canBid = ['sent', 'closed'].includes(data.status)
  const isClosed = !canBid

  return (
    <div className="space-y-5">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono">{data.reference}</h1>
              <StatusBadge status={data.status} />
              {myQuote && (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 inline-flex items-center gap-1">
                  <Package className="w-3 h-3" /> {myQuote.reference} on file
                </span>
              )}
            </div>
            <p className="text-sm text-slate-500 mt-1">
              For order <span className="font-mono">{data.order_reference}</span>
              {' · '}
              <Truck className="w-3.5 h-3.5 inline" /> {data.vessel_label}
              {data.port_name ? ` · ${data.port_name}` : ''}
            </p>
            {data.response_deadline ? (
              <p className="text-[11px] text-amber-600 mt-1 inline-flex items-center gap-1">
                <Clock className="w-3 h-3" /> Respond by{' '}
                {formatDateTime(data.response_deadline)}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {/* Closed/Awarded notice */}
      {isClosed && (
        <RfqClosedNotice rfq={data} quote={myQuote} />
      )}

      {/* Quote form for active RFQs */}
      {canBid && (
        <SupplierQuoteForm
          rfq={data}
          initialQuote={myQuote}
          onSubmitSuccess={() => {
            qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfqs'] })
            qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfq', rfqId] })
          }}
          onBack={onBack}
        />
      )}
    </div>
  )
}

/**
 * Read-only summary shown when the RFQ is past the bidding stage.
 */
function RfqClosedNotice({ rfq, quote }) {
  const isAwarded = rfq.status === 'awarded'
  const isCancelled = rfq.status === 'cancelled'
  const isClosed = rfq.status === 'closed'

  const heading = isAwarded
    ? 'Proposal awarded'
    : isCancelled
      ? 'RFQ cancelled'
      : isClosed
        ? 'Bidding closed'
        : 'Bidding closed'

  const body = isAwarded
    ? 'The purchaser has approved the proposal. Your quote was part of the winning selection.'
    : isCancelled
      ? 'The company cancelled this RFQ. There is nothing for you to do.'
      : isClosed
        ? 'All invited suppliers have responded. The admin is applying markup and will send to the purchaser.'
        : 'Bidding is closed. Your line prices are locked in; you will be notified if selected.'

  return (
    <div className="bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <div className="flex items-start gap-3">
        <Info className="w-5 h-5 text-slate-500 flex-shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{heading}</div>
          <p className="text-xs text-slate-600 dark:text-slate-300 mt-1">
            {body}
          </p>
          {quote ? (
            <div className="mt-3 text-[11px] text-slate-500">
              Your quote on file: <span className="font-mono">{quote.reference}</span>
              {quote.total != null ? <> · total {formatMoney(quote.total)} {quote.currency || 'USD'}</> : null}
              {quote.lead_time_days != null ? <> · lead time {quote.lead_time_days} days</> : null}
              {quote.marked_up_total != null && quote.marked_up_total !== quote.total ? (
                <> · marked up: {formatMoney(quote.marked_up_total)}</>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function formatMoney(v, currency = 'USD') {
  if (v == null) return '—'
  return `${currency} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

// --- Top-level page ----------------------------------------------------

export default function SupplierPortalPage() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const [active, setActive] = useState(rfqId || null)

  useEffect(() => {
    if (rfqId && rfqId !== active) setActive(rfqId)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rfqId])

  const onSelect = (id) => {
    setActive(id)
    navigate(`/supplier/rfq/${id}`)
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
            <Truck className="w-6 h-6 text-blue-600" /> Supplier Portal
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            RFQs the company has sent to you. Vessel names are sealed.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Sidebar */}
        <div className="lg:col-span-1">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Invitations
            </div>
            <RfqList activeId={active} onSelect={onSelect} />
          </div>
        </div>

        {/* Detail pane */}
        <div className="lg:col-span-2">
          {active ? (
            <RfqDetail rfqId={active} onBack={() => setActive(null)} />
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center">
              <FileText className="w-10 h-10 mx-auto text-slate-300 mb-3" />
              <div className="text-sm font-medium text-slate-700">
                Select an RFQ
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Pick one from the list to see the line items and submit your quote.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}