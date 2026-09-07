import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Check,
  ClipboardList,
  ClipboardCheck,
  Clock,
  FileText,
  Inbox,
  Loader2,
  Package,
  Send,
  ShieldCheck,
  Truck,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { useImpaNames } from '../hooks/useImpaNames'

import {
  acceptSupplierSlice,
  getSupplierRfq,
  listSupplierAssignments,
  listSupplierRfqs,
  submitSupplierQuote,
} from '../api/marketplace'

// --- shared status / format helpers -----------------------------------

const statusPalette = {
  draft: 'bg-slate-100 text-slate-700',
  sent: 'bg-blue-100 text-blue-700',
  quoting: 'bg-blue-100 text-blue-700',
  closed: 'bg-slate-100 text-slate-700',
  ready_for_compose: 'bg-violet-100 text-violet-700',
  awaiting_purchaser_approval: 'bg-amber-100 text-amber-700',
  confirmed: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-slate-100 text-slate-500',
  expired: 'bg-slate-100 text-slate-500',
}

const assignmentPalette = {
  pending: 'bg-amber-100 text-amber-700',
  confirmed: 'bg-emerald-100 text-emerald-700',
  dropped: 'bg-rose-100 text-rose-700',
}

function StatusBadge({ status }) {
  const cls = statusPalette[status] || 'bg-slate-100 text-slate-700'
  return (
    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${cls}`}>
      {(status || 'unknown').replace(/_/g, ' ')}
    </span>
  )
}

function formatDeadline(d) {
  if (!d) return null
  const dt = new Date(d)
  if (Number.isNaN(dt.getTime())) return null
  return dt.toLocaleString()
}

function hoursUntil(d) {
  if (!d) return null
  const dt = new Date(d)
  if (Number.isNaN(dt.getTime())) return null
  const ms = dt.getTime() - Date.now()
  return Math.round(ms / 3_600_000)
}

// --- list view --------------------------------------------------------

function RfqList({ activeId, onSelect }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['supplier-portal', 'rfqs'],
    queryFn: () => listSupplierRfqs(),
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
                {r.has_quote ? (
                  <span className="inline-flex items-center gap-0.5 text-emerald-600">
                    <Check className="w-3 h-3" /> quoted
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-0.5 text-amber-600">
                    <Clock className="w-3 h-3" /> action needed
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

/**
 * DeliveryWindowGate — the IMPA-first supplier gate.
 *
 * Before the supplier can fill in line prices, they decide
 * whether the package as a whole can be delivered between the
 * vessel's ETA at the port and its ETD. This is a yes/no with
 * an optional reason on "no".
 *
 * Three states (driven by `quote.can_deliver_in_window`):
 *   - null  → not yet decided. Show the gate + reason box.
 *   - true  → can deliver. Hide the gate; show the QuoteForm.
 *   - false → declined. Show the gate with the recorded reason
 *            and a "Change my decision" link.
 *
 * The "Change my decision" path is the same gate; resubmitting
 * the same answer is a no-op server-side.
 */
function DeliveryWindowGate({ rfq, quote, onDecision, deciding }) {
  const [decision, setDecision] = useState(quote?.can_deliver_in_window ?? null)
  const [reason, setReason] = useState(quote?.decline_reason || '')
  const [editing, setEditing] = useState(quote?.can_deliver_in_window == null)

  // Reset the local form when the RFQ / quote identity changes
  // (user clicks a different row).
  useEffect(() => {
    setDecision(quote?.can_deliver_in_window ?? null)
    setReason(quote?.decline_reason || '')
    setEditing(quote?.can_deliver_in_window == null)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rfq.id, quote?.id])

  const eta = rfq.eta_at_port
  const etd = rfq.etd_at_port
  const hasWindow = !!(eta || etd)
  const alreadyDecided = quote?.can_deliver_in_window != null

  // The window-hr gap (informational; helps the supplier sanity
  // check whether their lead time fits). ETD - ETA in hours.
  const windowHours = (eta && etd)
    ? Math.round((new Date(etd).getTime() - new Date(eta).getTime()) / 3_600_000)
    : null

  if (alreadyDecided && !editing) {
    return (
      <div className={`p-4 rounded-xl border ${
        decision
          ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
          : 'bg-rose-50 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800'
      }`}>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            {decision ? (
              <Check className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
            ) : (
              <X className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
            )}
            <div className="min-w-0">
              <div className="text-sm font-semibold">
                {decision
                  ? 'You can deliver the package in this window'
                  : 'You declined this RFQ'}
              </div>
              {!decision && quote?.decline_reason ? (
                <div className="text-xs text-rose-700 dark:text-rose-300 mt-0.5">
                  Reason: {quote.decline_reason}
                </div>
              ) : null}
              {decision && hasWindow ? (
                <div className="text-[11px] text-slate-600 dark:text-slate-300 mt-0.5">
                  ETA {new Date(eta).toLocaleString()} · ETD {new Date(etd).toLocaleString()}
                  {windowHours != null ? ` · ${windowHours}h window` : ''}
                </div>
              ) : null}
              {quote?.declined_at ? (
                <div className="text-[10px] text-slate-500 mt-0.5">
                  Declined {new Date(quote.declined_at).toLocaleString()}
                </div>
              ) : null}
            </div>
          </div>
          <button
            onClick={() => setEditing(true)}
            className="text-[11px] px-2 py-1 bg-white/60 dark:bg-slate-900/40 hover:bg-white dark:hover:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded text-slate-700 dark:text-slate-200"
            title="Change your delivery decision"
          >
            Change
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-2 flex items-center gap-2">
        <Truck className="w-4 h-4" /> Can you deliver in this window?
      </h2>
      {hasWindow ? (
        <div className="text-xs text-slate-600 dark:text-slate-300 mb-3">
          <div className="inline-flex items-center gap-3 flex-wrap">
            {eta ? (
              <span><span className="text-slate-500">Vessel ETA at port:</span> {new Date(eta).toLocaleString()}</span>
            ) : null}
            {etd ? (
              <span><span className="text-slate-500">ETD:</span> {new Date(etd).toLocaleString()}</span>
            ) : null}
            {windowHours != null ? (
              <span className="text-slate-500">({windowHours}h window)</span>
            ) : null}
          </div>
          <p className="text-[11px] text-slate-500 mt-1.5">
            Compare against your lead time. If the goods can be on the
            quay between these two timestamps, answer <strong>Yes</strong>
            {' '}and fill in the per-line prices. If not, answer
            {' '}<strong>No</strong> with a reason.
          </p>
        </div>
      ) : (
        <p className="text-xs text-slate-500 mb-3">
          The vessel's ETA/ETD haven't been snapshotted yet. If the
          window is tight, decline and explain in the reason.
        </p>
      )}

      <div className="flex items-center gap-2 mb-3">
        <button
          onClick={() => setDecision(true)}
          className={`text-xs px-3 py-1.5 rounded font-medium inline-flex items-center gap-1.5 border ${
            decision === true
              ? 'bg-emerald-600 text-white border-emerald-600'
              : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-slate-200 dark:border-slate-700 hover:bg-slate-50'
          }`}
        >
          <Check className="w-3.5 h-3.5" /> Yes, I can deliver
        </button>
        <button
          onClick={() => setDecision(false)}
          className={`text-xs px-3 py-1.5 rounded font-medium inline-flex items-center gap-1.5 border ${
            decision === false
              ? 'bg-rose-600 text-white border-rose-600'
              : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-slate-200 dark:border-slate-700 hover:bg-slate-50'
          }`}
        >
          <X className="w-3.5 h-3.5" /> No, I cannot
        </button>
      </div>

      {decision === false ? (
        <div>
          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
            Reason (optional but recommended)
          </label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. lead time too short, out of stock at this port, …"
            className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
          />
        </div>
      ) : null}

      <div className="mt-4 flex items-center justify-end gap-2">
        {alreadyDecided ? (
          <button
            onClick={() => setEditing(false)}
            className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded"
          >
            Cancel
          </button>
        ) : null}
        <button
          onClick={() => {
            if (decision == null) return
            onDecision({
              can_deliver_in_window: decision,
              decline_reason: decision ? undefined : reason.trim() || undefined,
            })
          }}
          disabled={decision == null || deciding}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          {deciding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          Submit decision
        </button>
      </div>
    </div>
  )
}

// --- detail / quote-submission view -----------------------------------

function QuoteForm({ rfq, quote, onSubmitted }) {
  // Initialize per-line form state from the RFQ. We always render
  // one row per line; for lines already on a saved quote, prefill
  // from the matching `quote.lines` entry.
  const initialLines = (rfq.items || []).map((it) => {
    const existing = (quote?.lines || []).find(
      (l) => l.rfq_item_id === it.id
    )
    return {
      rfq_item_id: it.id,
      // label fields — used for display only
      product_sku: it.product_sku || it.sku || null,
      product_name: it.product_name || it.name || null,
      description: it.description || null,
      impa_code: it.impa_code || null,
      quantity: it.quantity,
      unit: it.unit,
      // form state
      line_status: existing?.line_status || 'full',
      unit_price: existing?.unit_price ?? 0,
      quoted_quantity: existing?.quoted_quantity ?? null,
    }
  })

  const [lines, setLines] = useState(initialLines)
  const [leadTime, setLeadTime] = useState(quote?.lead_time_days ?? 7)
  const [paymentTerms, setPaymentTerms] = useState(quote?.payment_terms || 'Net 30')
  const [notes, setNotes] = useState(quote?.notes || '')

  // The supplier doesn't know what the IMPA codes mean. The
  // platform bridges that — one bulk lookup turns the 6-digit
  // code into "Safety Boots Steel Toe Size 16" so the supplier
  // can quote the right thing. Cached in a module Map so all
  // rows share the fetch.
  const impaNames = useImpaNames(lines.map((l) => l.impa_code))

  // When the RFQ changes (user clicks a different row), reset the
  // local form state from the new RFQ.
  useEffect(() => {
    setLines(initialLines)
    setLeadTime(quote?.lead_time_days ?? 7)
    setPaymentTerms(quote?.payment_terms || 'Net 30')
    setNotes(quote?.notes || '')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rfq.id, quote?.id])

  const setLine = (idx, patch) =>
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)))

  const submit = useMutation({
    mutationFn: () => {
      const payload = {
        lead_time_days: Number(leadTime),
        payment_terms: paymentTerms || undefined,
        notes: notes || undefined,
        source: 'portal',
        lines: lines.map((l) => ({
          rfq_item_id: l.rfq_item_id,
          line_status: l.line_status,
          // Send nulls (not zeros) when "none" — the server uses
          // quoted_quantity to compute line totals.
          unit_price: l.line_status === 'none' ? null : Number(l.unit_price) || 0,
          quoted_quantity:
            l.line_status === 'partial'
              ? Number(l.quoted_quantity) || Math.ceil((l.quantity || 1) / 2)
              : l.line_status === 'full'
                ? Number(l.quantity)
                : null,
        })),
      }
      return submitSupplierQuote(rfq.id, payload)
    },
    onSuccess: (res) => {
      toast.success(`Quote ${res.reference} submitted`)
      onSubmitted?.(res)
    },
    onError: (e) => toast.error(e.message),
  })

  const canSubmit =
    Number(leadTime) > 0 &&
    lines.every((l) => {
      if (l.line_status === 'none') return true
      return Number(l.unit_price) > 0
    })

  return (
    <div className="space-y-5">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Package className="w-4 h-4" /> Lines
          </h2>
          {quote ? (
            <span className="text-[11px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
              <Check className="w-3 h-3" /> {quote.reference} on file
            </span>
          ) : null}
        </div>
        <div className="space-y-2">
          {lines.map((l, idx) => (
            <div
              key={l.rfq_item_id}
              className="grid grid-cols-12 gap-2 items-center p-2.5 border border-slate-200 dark:border-slate-700 rounded-lg"
            >
              <div className="col-span-5">
                {l.product_sku ? (
                  <div className="font-mono text-[11px] text-slate-500">
                    {l.product_sku}
                  </div>
                ) : null}
                <div className="text-sm font-medium truncate">
                  {l.product_name || l.rfq_item_id}
                </div>
                {l.description ? (
                  <div className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">
                    {l.description}
                  </div>
                ) : null}
                {l.impa_code ? (() => {
                  const hit = impaNames.get(l.impa_code)
                  return (
                    <div className="text-[10px] mt-0.5 text-slate-400">
                      IMPA {l.impa_code}
                      {hit?.name && (
                        <span className="ml-1 text-slate-500 dark:text-slate-400">
                          — {hit.name}
                        </span>
                      )}
                    </div>
                  )
                })() : null}
              </div>
              <div className="col-span-2 text-right text-xs text-slate-500">
                <div className="font-medium text-slate-700">
                  {l.quantity} {l.unit}
                </div>
                <div>requested</div>
              </div>
              <div className="col-span-2">
                <select
                  value={l.line_status}
                  onChange={(e) => setLine(idx, { line_status: e.target.value })}
                  className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-xs"
                >
                  <option value="full">Full</option>
                  <option value="partial">Partial</option>
                  <option value="none">No bid</option>
                </select>
              </div>
              <div className="col-span-3">
                {l.line_status === 'none' ? (
                  <div className="w-full px-2 py-1.5 bg-slate-100 dark:bg-slate-800/50 border border-dashed border-slate-300 dark:border-slate-700 rounded text-[11px] text-slate-400 text-center">
                    —
                  </div>
                ) : l.line_status === 'partial' ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      min="1"
                      value={l.quoted_quantity ?? Math.ceil((l.quantity || 1) / 2)}
                      onChange={(e) =>
                        setLine(idx, { quoted_quantity: parseInt(e.target.value) || 1 })
                      }
                      className="w-16 px-1.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-xs"
                    />
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={l.unit_price}
                      onChange={(e) =>
                        setLine(idx, { unit_price: parseFloat(e.target.value) || 0 })
                      }
                      className="flex-1 px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-xs"
                      placeholder="unit price"
                    />
                  </div>
                ) : (
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={l.unit_price}
                    onChange={(e) =>
                      setLine(idx, { unit_price: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-xs"
                    placeholder="unit price"
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-3">Quote terms</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Lead time (days)">
            <input
              type="number"
              min="1"
              value={leadTime}
              onChange={(e) => setLeadTime(parseInt(e.target.value) || 0)}
              className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </Field>
          <Field label="Payment terms">
            <input
              type="text"
              value={paymentTerms}
              onChange={(e) => setPaymentTerms(e.target.value)}
              placeholder="Net 30"
              className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </Field>
          <Field label="Notes (optional)">
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Anything the company should know"
              className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </Field>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          onClick={() => submit.mutate()}
          disabled={!canSubmit || submit.isPending}
          className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
        >
          {submit.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
          {quote ? 'Update quote' : 'Submit quote'}
        </button>
      </div>
    </div>
  )
}

function RfqDetail({ rfqId }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['supplier-portal', 'rfq', rfqId],
    queryFn: () => getSupplierRfq(rfqId),
  })
  const accept = useMutation({
    mutationFn: () => {
      const qid = data?.my_quote?.id
      if (!qid) throw new Error('No quote to accept')
      return acceptSupplierSlice(qid)
    },
    onSuccess: (res) => {
      toast.success(`Accepted ${res.accepted} line(s)`)
      qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfq', rfqId] })
      qc.invalidateQueries({ queryKey: ['supplier-portal', 'assignments'] })
    },
    onError: (e) => toast.error(e.message),
  })

  // The IMPA-first gate: a "can you deliver" decision must be on
  // file before the per-line QuoteForm is meaningful. A "no"
  // posts a declined quote (no lines); a "yes" opens the form.
  // The decision posts as a quote with `can_deliver_in_window`
  // and (for "no") `decline_reason`. The existing submit
  // endpoint handles all three states; the supplier reuses the
  // same payload shape — only the line array is empty for the
  // decline case.
  const submitGate = useMutation({
    mutationFn: ({ can_deliver_in_window, decline_reason }) =>
      submitSupplierQuote(rfqId, {
        can_deliver_in_window,
        decline_reason,
        // The form's per-line payload is filled in on the next
        // submission; the gate posts an empty `lines` array.
        lead_time_days: 0,
        lines: [],
      }),
    onSuccess: (res, vars) => {
      toast.success(
        vars.can_deliver_in_window
          ? 'Recorded: you can deliver. Fill in your line prices below.'
          : 'Recorded: you cannot deliver this package. The company is notified.'
      )
      qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfq', rfqId] })
      qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfqs'] })
    },
    onError: (e) => toast.error(e.message),
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

  // The gate's three states. `null` means "not yet decided" —
  // a placeholder quote may exist on the backend (so the
  // responded_count is unaffected) but the UI shows the gate.
  const decision = data.my_quote?.can_deliver_in_window ?? null
  const showGate = decision == null
  const showForm = decision === true
  const declined = decision === false

  return (
    <div className="space-y-5">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono">{data.reference}</h1>
              <StatusBadge status={data.status} />
              {declined ? (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-100 text-rose-700 inline-flex items-center gap-1">
                  <X className="w-3 h-3" /> declined
                </span>
              ) : null}
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
                {formatDeadline(data.response_deadline)}
              </p>
            ) : null}
          </div>
          {data.has_quote && showForm ? (
            <button
              onClick={() => accept.mutate()}
              disabled={accept.isPending}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
              title="After the company approves the proposal, click here within 24h to confirm you're preparing the goods."
            >
              {accept.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ShieldCheck className="w-4 h-4" />
              )}
              Accept my slice
            </button>
          ) : null}
        </div>
      </div>

      {showGate || declined ? (
        <DeliveryWindowGate
          rfq={data}
          quote={data.my_quote}
          onDecision={(payload) => submitGate.mutate(payload)}
          deciding={submitGate.isPending}
        />
      ) : null}

      {showForm ? (
        <QuoteForm
          rfq={data}
          quote={data.my_quote}
          onSubmitted={() => {
            qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfqs'] })
            qc.invalidateQueries({ queryKey: ['supplier-portal', 'rfq', rfqId] })
          }}
        />
      ) : null}
    </div>
  )
}

// --- assignments tab --------------------------------------------------

function AssignmentsList() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['supplier-portal', 'assignments'],
    queryFn: () => listSupplierAssignments(),
  })
  if (isLoading) {
    return (
      <div className="p-6 text-center text-sm text-slate-500">
        <Loader2 className="w-4 h-4 animate-spin inline-block mr-2" />
        Loading…
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-6 text-center text-sm text-rose-500">{error.message}</div>
    )
  }
  const rows = data || []
  if (rows.length === 0) {
    return (
      <div className="p-8 text-center">
        <ClipboardList className="w-8 h-8 mx-auto text-slate-300 mb-2" />
        <div className="text-sm font-medium text-slate-700">No accepted slices yet</div>
        <p className="text-xs text-slate-500 mt-1">
          Once the purchaser approves a proposal that includes your
          lines, they will show up here for you to confirm.
        </p>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">Order</th>
            <th className="px-3 py-2 text-left">Status</th>
            <th className="px-3 py-2 text-left">Confirmed</th>
            <th className="px-3 py-2 text-left">Deadline</th>
            <th className="px-3 py-2 text-left">Drop reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const hrs = hoursUntil(a.preparation_deadline)
            const expired = hrs !== null && hrs < 0 && a.line_status === 'pending'
            return (
              <tr
                key={a.id}
                className="border-t border-slate-100 dark:border-slate-800"
              >
                <td className="px-3 py-2.5">
                  <div className="font-mono text-xs">{a.order_reference}</div>
                  <div className="text-[11px] text-slate-500 line-clamp-1">
                    {a.product_name || a.rfq_item_id}
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                      assignmentPalette[a.line_status] || 'bg-slate-100 text-slate-700'
                    }`}
                  >
                    {a.line_status}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs">
                  {a.confirmed_at
                    ? new Date(a.confirmed_at).toLocaleString()
                    : '—'}
                </td>
                <td className="px-3 py-2.5 text-xs">
                  {a.preparation_deadline ? (
                    <span className={expired ? 'text-rose-600' : ''}>
                      {formatDeadline(a.preparation_deadline)}
                      {hrs !== null ? (
                        <span className="ml-1 text-[10px] text-slate-500">
                          ({hrs >= 0 ? `${hrs}h left` : 'past due'})
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="px-3 py-2.5 text-xs text-slate-500">
                  {a.drop_reason || '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// --- top-level page ---------------------------------------------------

export default function SupplierPortalPage() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const [active, setActive] = useState(rfqId || null)
  const [tab, setTab] = useState('rfqs') // 'rfqs' | 'assignments'

  // Keep `active` in sync with the URL when the user lands on a
  // deep link (or the back button).
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
            <Truck className="w-6 h-6 text-blue-600" /> Supplier portal
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            RFQs the company has sent to you, plus the slices you've
            already accepted. Vessel names are sealed.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Sidebar — tabbed */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <div className="flex border-b border-slate-200 dark:border-slate-800">
              <button
                onClick={() => setTab('rfqs')}
                className={`flex-1 px-3 py-2 text-xs font-semibold inline-flex items-center justify-center gap-1.5 ${
                  tab === 'rfqs'
                    ? 'bg-blue-50/60 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                <FileText className="w-3.5 h-3.5" /> Invitations
              </button>
              <button
                onClick={() => setTab('assignments')}
                className={`flex-1 px-3 py-2 text-xs font-semibold inline-flex items-center justify-center gap-1.5 ${
                  tab === 'assignments'
                    ? 'bg-blue-50/60 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                <ClipboardCheck className="w-3.5 h-3.5" /> Accepted
              </button>
            </div>
            {tab === 'rfqs' ? (
              <RfqList activeId={active} onSelect={onSelect} />
            ) : (
              <AssignmentsList />
            )}
          </div>
        </div>

        {/* Detail pane */}
        <div className="lg:col-span-2">
          {tab === 'rfqs' ? (
            active ? (
              <RfqDetail rfqId={active} />
            ) : (
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center">
                <FileText className="w-10 h-10 mx-auto text-slate-300 mb-3" />
                <div className="text-sm font-medium text-slate-700">
                  Select an RFQ
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Pick one from the list to see the line items and
                  submit your quote.
                </p>
              </div>
            )
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <ClipboardCheck className="w-4 h-4" /> Accepted slices
              </h2>
              <AssignmentsList />
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
      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
        {label}
      </label>
      {children}
    </div>
  )
}
