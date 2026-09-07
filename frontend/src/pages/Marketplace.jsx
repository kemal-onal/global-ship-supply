import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Check,
  Clock,
  Gavel,
  LayoutGrid,
  Loader2,
  Send,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import {
  composeProposal,
  getRfqLattice,
  getOrderProposal,
  listRfqsForCompose,
} from '../api/marketplace'

// --- shared helpers ---------------------------------------------------

const cellPalette = {
  full: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800',
  partial: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800',
  none: 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-800/50 dark:text-slate-500 dark:border-slate-700',
}

const cellLabel = {
  full: 'Full',
  partial: 'Partial',
  none: 'No bid',
}

function formatMoney(v, currency = 'USD') {
  if (v == null) return '—'
  return `${currency} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function formatEta(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString()
}

// --- RFQ picker (left rail) -------------------------------------------

function RfqPicker({ activeId, onSelect }) {
  // The marketplace is for RFQs whose order is ready to compose.
  // The dedicated /marketplace/rfqs-for-compose endpoint filters
  // by **order status** (ready_for_compose + the legacy sealed-bid
  // predecessors that the compose self-heal handles), which is
  // the right semantic — querying the generic /rfq by status
  // loses the order-level "is this compose-eligible?" predicate
  // (an RFQ with status=open might belong to a draft order; an
  // RFQ with status=closed is the canonical "ready to compose"
  // state). The endpoint is the source of truth; no client-side
  // filtering needed.
  const { data, isLoading, error } = useQuery({
    queryKey: ['marketplace', 'rfqs-for-compose'],
    queryFn: () => listRfqsForCompose(),
  })

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-slate-500">
        <Loader2 className="w-4 h-4 animate-spin inline-block mr-2" /> Loading…
      </div>
    )
  }
  if (error) {
    return <div className="p-4 text-sm text-rose-500">{error.message}</div>
  }

  const rows = data || []

  if (rows.length === 0) {
    return (
      <div className="p-6 text-center">
        <LayoutGrid className="w-8 h-8 mx-auto text-slate-300 mb-2" />
        <div className="text-sm font-medium text-slate-700">No RFQs to compose</div>
        <p className="text-xs text-slate-500 mt-1">
          When an order has had all its invited suppliers respond
          (or its RFQ deadline passes), it shows up here for the
          per-line decision step.
        </p>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {rows.map((r) => {
        const isActive = r.id === activeId
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
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                    r.status === 'closed'
                      ? 'bg-violet-100 text-violet-700'
                      : 'bg-blue-100 text-blue-700'
                  }`}
                >
                  {r.status.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="mt-1 text-sm font-medium truncate">
                {r.order_reference || r.id}
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                {r.responded_count}/{r.invited_count} responded
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

// --- proposal preview (sent state) -----------------------------------

function ProposalPreview({ proposal, marginPct }) {
  const hidePrices = false // admin view
  if (!proposal) {
    return (
      <div className="p-6 text-center text-sm text-slate-500">
        Submit the proposal to see the customer-facing preview here.
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500">
        Customer-facing subtotal{' '}
        <span className="font-semibold text-slate-700">
          {formatMoney(proposal.customer_facing_subtotal || 0)}
        </span>{' '}
        (margin {marginPct}%).
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th className="px-2 py-1 text-left">Line</th>
            <th className="px-2 py-1 text-left">Supplier</th>
            <th className="px-2 py-1 text-left">Decision</th>
            <th className="px-2 py-1 text-right">Qty</th>
            <th className="px-2 py-1 text-right">Unit</th>
            <th className="px-2 py-1 text-right">Line</th>
            <th className="px-2 py-1 text-right">Customer</th>
          </tr>
        </thead>
        <tbody>
          {(proposal.lines || []).map((l) => (
            <tr
              key={l.rfq_item_id}
              className="border-t border-slate-100 dark:border-slate-800"
            >
              <td className="px-2 py-1.5 font-mono text-[11px] text-slate-500">
                {l.rfq_item_id.slice(0, 8)}
              </td>
              <td className="px-2 py-1.5">{l.supplier_name || '—'}</td>
              <td className="px-2 py-1.5">
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                    l.decision === 'use_full'
                      ? 'bg-emerald-100 text-emerald-700'
                      : l.decision === 'use_half'
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-rose-100 text-rose-700'
                  }`}
                >
                  {l.decision.replace(/_/g, ' ')}
                </span>
              </td>
              <td className="px-2 py-1.5 text-right">{l.used_quantity}</td>
              <td className="px-2 py-1.5 text-right">
                {hidePrices ? '—' : formatMoney(l.unit_price)}
              </td>
              <td className="px-2 py-1.5 text-right">
                {hidePrices ? '—' : formatMoney(l.line_total)}
              </td>
              <td className="px-2 py-1.5 text-right font-semibold">
                {formatMoney(l.customer_facing_total)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- lattice view + compose form -------------------------------------

function LatticeView({ rfqId, onComposed }) {
  const qc = useQueryClient()
  const { data: lattice, isLoading, error } = useQuery({
    queryKey: ['rfq', rfqId, 'lattice'],
    queryFn: () => getRfqLattice(rfqId),
    enabled: !!rfqId,
  })

  // Per-line decision state. We keep it as a map of rfq_item_id
  // -> { decision, supplier_id, quote_id } (the compose endpoint
  // wants all three). Initial state: no decisions made.
  const [decisions, setDecisions] = useState({})
  const [margin, setMargin] = useState(8.0)

  // Reset the form when the lattice changes (e.g. user picks
  // another RFQ).
  useEffect(() => {
    setDecisions({})
    setMargin(8.0)
  }, [rfqId])

  const decide = (rfqItemId, cell, supplier) => {
    setDecisions((prev) => ({
      ...prev,
      [rfqItemId]: {
        rfq_item_id: rfqItemId,
        supplier_id: supplier.supplier_id,
        quote_id: supplier.quote_id,
        decision: cell.line_status === 'full' ? 'use_full' : 'use_half',
        cell_line_status: cell.line_status,
      },
    }))
  }
  const undecide = (rfqItemId) => {
    setDecisions((prev) => {
      const next = { ...prev }
      delete next[rfqItemId]
      return next
    })
  }
  const drop = (rfqItemId) => {
    setDecisions((prev) => ({
      ...prev,
      [rfqItemId]: {
        rfq_item_id: rfqItemId,
        decision: 'drop',
      },
    }))
  }

  const submit = useMutation({
    mutationFn: () => {
      const decisionsList = Object.values(decisions)
        // Drop is an explicit choice; the compose endpoint needs a
        // supplier_id + quote_id even for a drop though, since
        // decide() also takes one. Workaround: skip rows that are
        // "drop" with no supplier (set above via the Drop button).
        .filter((d) => d.decision !== 'drop' || d.supplier_id)
        .map((d) => ({
          rfq_item_id: d.rfq_item_id,
          supplier_id: d.supplier_id,
          quote_id: d.quote_id,
          decision: d.decision,
        }))
      return composeProposal(rfqId, {
        decisions: decisionsList,
        margin_pct: margin,
      })
    },
    onSuccess: (res) => {
      toast.success(
        `Proposal composed (${res.decisions.length} decisions, status: ${res.status})`
      )
      qc.invalidateQueries({ queryKey: ['orders'] })
      onComposed?.(res)
    },
    onError: (e) => toast.error(e.message),
  })

  // After compose, refetch the proposal so the right pane can
  // render the customer-facing preview.
  const orderId = lattice?.order_id
  const { data: proposal, isLoading: proposalLoading } = useQuery({
    queryKey: ['order', orderId, 'proposal'],
    queryFn: () => getOrderProposal(orderId),
    enabled: !!orderId && submit.isSuccess,
  })

  if (isLoading) {
    return (
      <div className="p-12 text-center text-sm text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin inline-block mr-2" />
        Loading lattice…
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
  if (!lattice) return null

  const allDecided =
    (lattice.items || []).length > 0 &&
    (lattice.items || []).every((it) => decisions[it.rfq_item_id])
  const decisionCount = Object.keys(decisions).length
  const itemCount = (lattice.items || []).length

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono">
                {lattice.reference}
              </h1>
              <span className="text-xs text-slate-500">
                for order{' '}
                <span className="font-mono">
                  {lattice.order_reference}
                </span>
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {lattice.responded_count}/{lattice.invited_count} suppliers
              responded · {itemCount} line(s) · {lattice.suppliers.length}{' '}
              active bidder(s)
              {lattice.eta_at_port ? (
                <span className="ml-2 inline-flex items-center gap-1 text-emerald-600">
                  <Clock className="w-3 h-3" /> ETA{' '}
                  {formatEta(lattice.eta_at_port)}
                </span>
              ) : (
                <span
                  className="ml-2 inline-flex items-center gap-1 text-amber-600"
                  title="No recent AIS report matching this order's port"
                >
                  <Clock className="w-3 h-3" /> no AIS ETA snapshot
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Field label="Margin %">
              <input
                type="number"
                min="0"
                max="100"
                step="0.5"
                value={margin}
                onChange={(e) => setMargin(parseFloat(e.target.value) || 0)}
                className="w-20 px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
              />
            </Field>
            <button
              onClick={() => submit.mutate()}
              disabled={!allDecided || submit.isPending}
              title={
                allDecided
                  ? 'Send proposal to purchaser'
                  : `Decide all ${itemCount} lines first (${decisionCount} done)`
              }
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
            >
              {submit.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
              Send to purchaser
            </button>
          </div>
        </div>
      </div>

      {/* Lattice */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr>
              <th className="text-left text-xs uppercase text-slate-500 px-2 py-2 sticky left-0 bg-white dark:bg-slate-900 z-10 min-w-[180px]">
                Line
              </th>
              {(lattice.suppliers || []).map((s) => (
                <th
                  key={s.supplier_id}
                  className="text-center text-xs px-2 py-2 min-w-[110px]"
                >
                  <div className="font-semibold truncate" title={s.supplier_name}>
                    {s.supplier_name}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    {s.lead_time_days}d · {s.currency}{' '}
                    {Number(s.total).toFixed(0)}
                  </div>
                </th>
              ))}
              <th className="text-center text-xs uppercase text-slate-500 px-2 py-2 min-w-[120px]">
                Decision
              </th>
            </tr>
          </thead>
          <tbody>
            {(lattice.items || []).map((it) => {
              const d = decisions[it.rfq_item_id]
              return (
                <tr
                  key={it.rfq_item_id}
                  className="border-t border-slate-100 dark:border-slate-800"
                >
                  <td className="px-2 py-2 sticky left-0 bg-white dark:bg-slate-900 z-10">
                    <div className="text-sm font-medium">
                      {it.description || it.product_id.slice(0, 8)}
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono">
                      {it.impa_code
                        ? `IMPA ${it.impa_code} · `
                        : ''}
                      {it.quantity} {it.unit}
                    </div>
                  </td>
                  {(lattice.suppliers || []).map((s) => {
                    const cell = it.cells?.[s.supplier_id]
                    const isPicked = d && d.supplier_id === s.supplier_id
                    return (
                      <td key={s.supplier_id} className="px-2 py-2 text-center">
                        {cell == null ? (
                          <div className="text-slate-300 text-[11px]">—</div>
                        ) : (
                          <button
                            onClick={() => decide(it.rfq_item_id, cell, s)}
                            disabled={cell.line_status === 'none'}
                            title={
                              cell.line_status === 'none'
                                ? 'Supplier did not bid on this line'
                                : `Click to pick ${s.supplier_name} (${cellLabel[cell.line_status]})`
                            }
                            className={`w-full px-2 py-1.5 rounded text-[11px] font-semibold border transition ${
                              cellPalette[cell.line_status]
                            } ${
                              isPicked
                                ? 'ring-2 ring-blue-500 ring-offset-1 dark:ring-offset-slate-900'
                                : ''
                            } ${
                              cell.line_status === 'none'
                                ? 'cursor-not-allowed opacity-60'
                                : 'hover:brightness-95'
                            }`}
                          >
                            <div>{cellLabel[cell.line_status]}</div>
                            {cell.line_status !== 'none' ? (
                              <div className="text-[10px] opacity-80 mt-0.5">
                                {cell.line_status === 'partial' && cell.quoted_quantity
                                  ? `${cell.quoted_quantity} × `
                                  : ''}
                                {formatMoney(cell.unit_price, s.currency)}
                              </div>
                            ) : null}
                          </button>
                        )}
                      </td>
                    )
                  })}
                  <td className="px-2 py-2 text-center">
                    {d ? (
                      <div className="inline-flex items-center gap-1">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                            d.decision === 'drop'
                              ? 'bg-rose-100 text-rose-700'
                              : d.cell_line_status === 'partial'
                                ? 'bg-amber-100 text-amber-700'
                                : 'bg-emerald-100 text-emerald-700'
                          }`}
                        >
                          {d.decision === 'drop'
                            ? 'Dropped'
                            : d.cell_line_status === 'partial'
                              ? 'use_half'
                              : 'use_full'}
                        </span>
                        {d.decision !== 'drop' ? (
                          <button
                            onClick={() => undecide(it.rfq_item_id)}
                            className="p-0.5 text-slate-400 hover:text-slate-700"
                            title="Clear"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        ) : null}
                      </div>
                    ) : (
                      <button
                        onClick={() => drop(it.rfq_item_id)}
                        className="text-[11px] text-rose-600 hover:text-rose-800 underline"
                        title="Mark this line as not fulfilled"
                      >
                        drop line
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Customer-facing preview (after compose) */}
      {submit.isSuccess ? (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Check className="w-4 h-4 text-emerald-500" /> Proposal sent to
            purchaser
          </h2>
          {proposalLoading ? (
            <Loader2 className="w-4 h-4 animate-spin inline-block" />
          ) : (
            <ProposalPreview
              proposal={proposal}
              marginPct={margin}
            />
          )}
        </div>
      ) : null}
    </div>
  )
}

// --- top-level page ---------------------------------------------------

export default function MarketplacePage() {
  const { rfqId: paramId } = useParams()
  const navigate = useNavigate()
  const [active, setActive] = useState(paramId || null)

  useEffect(() => {
    if (paramId && paramId !== active) setActive(paramId)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramId])

  const onSelect = (id) => {
    setActive(id)
    navigate(`/marketplace/${id}`)
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
            <Gavel className="w-6 h-6 text-blue-600" /> Marketplace
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Per-line decisions: pick which supplier fulfils each line,
            set the company margin, and send the composed proposal to
            the purchaser for approval.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* RFQ picker */}
        <div className="lg:col-span-1">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-2.5 border-b border-slate-200 dark:border-slate-800 text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Ready to compose
            </div>
            <RfqPicker activeId={active} onSelect={onSelect} />
          </div>
        </div>

        {/* Lattice / detail */}
        <div className="lg:col-span-2">
          {active ? (
            <LatticeView
              rfqId={active}
              onComposed={() => {
                // After compose, the RFQ is no longer ready_for_compose.
                // Refresh the picker so the next user interaction sees
                // the updated list.
                setTimeout(() => navigate('/marketplace'), 1500)
              }}
            />
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center">
              <LayoutGrid className="w-10 h-10 mx-auto text-slate-300 mb-3" />
              <div className="text-sm font-medium text-slate-700">
                Select an RFQ
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Pick one from the list to see the supplier lattice and
                start composing the proposal.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-[10px] font-semibold uppercase text-slate-500 mb-1">
        {label}
      </label>
      {children}
    </div>
  )
}
