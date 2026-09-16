import { useState, useEffect, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, Check, ChevronDown, Clock, Gavel, Loader2, MessageCircle, ShieldAlert, ShieldCheck, Truck, X, Send } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost, apiPatch } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useImpaNames } from '../hooks/useImpaNames'
import {
  approveProposal,
  dropSupplier,
  getOrderProposal,
  listOrderAssignments,
} from '../api/marketplace'
import {
  askClarification,
  answerClarification,
  resolveClarification,
  getClarification,
} from '../api/clarification'
import { sendOrderToSuppliers, saveOrderItems } from '../api/orders'

const palette = {
  draft: 'bg-slate-100 text-slate-700',
  pending_approval: 'bg-amber-100 text-amber-700',
  awaiting_clarification: 'bg-amber-100 text-amber-700',
  quoting: 'bg-blue-100 text-blue-700',
  rfq_in_progress: 'bg-blue-100 text-blue-700',
  ready_for_compose: 'bg-violet-100 text-violet-700',
  bidding: 'bg-violet-100 text-violet-700',
  awaiting_purchaser_approval: 'bg-amber-100 text-amber-700',
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
  const { hasRole, hasPermission } = useAuthStore()
  // IMPA-first redesign: the order line carries no price anywhere
  // on this page. Prices only appear later — inside the supplier's
  // quote, then in the composed proposal (margin applied), then
  // the purchaser's approval view. So the per-page "hidePrices"
  // toggle that the redaction layer used to drive is gone.
  const isSupplier = hasRole('supplier')
  const isAdmin = hasPermission('marketplace', 'clarify', 'global')
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

  // Marketplace redesign: when the order reaches
  // AWAITING_PURCHASER_APPROVAL the composed proposal is the
  // canonical view. When it reaches CONFIRMED, the preparation
  // status panel is. We lazy-load them.
  const showProposal = order?.status === 'awaiting_purchaser_approval' || order?.status === 'rfq_closed'
  const showPreparation = order?.status === 'confirmed'
  const { data: proposal, isLoading: proposalLoading } = useQuery({
    queryKey: ['order', id, 'proposal'],
    queryFn: () => getOrderProposal(id),
    enabled: showProposal || showPreparation,
  })
  const { data: assignments, isLoading: assignmentsLoading } = useQuery({
    queryKey: ['order', id, 'assignments'],
    queryFn: () => listOrderAssignments(id),
    enabled: showPreparation && !isSupplier,
  })

  // Translate every line's IMPA code into its human name (one bulk
  // fetch shared across all rows). Lets admin / purchaser / supplier
  // read what was ordered without memorising 6-digit codes.
  const impaNames = useImpaNames((order?.items || []).map((it) => it.impa_code))

  // Approve / reject the proposal (purchaser)
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  const decideProposal = useMutation({
    mutationFn: (approve) =>
      approveProposal(id, { approve, reason: approve ? undefined : rejectReason || undefined }),
    onSuccess: (res, approve) => {
      toast.success(approve ? 'Proposal approved' : 'Proposal rejected')
      setShowRejectForm(false)
      setRejectReason('')
      qc.invalidateQueries({ queryKey: ['order', id] })
      qc.invalidateQueries({ queryKey: ['order', id, 'proposal'] })
      qc.invalidateQueries({ queryKey: ['order', id, 'assignments'] })
      qc.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (e) => toast.error(e.message),
  })

  // Admin manual drop (preparation)
  const dropOne = useMutation({
    mutationFn: (supplier_id) =>
      dropSupplier(id, { supplier_id, reason: 'manual_drop' }),
    onSuccess: (res) => {
      toast.success(`Dropped ${res.dropped} slice(s)`)
      qc.invalidateQueries({ queryKey: ['order', id, 'assignments'] })
    },
    onError: (e) => toast.error(e.message),
  })

  // --- IMPA-first: clarification loop (admin ↔ purchaser) -----------
  // The "Send to suppliers" button is gated on no unresolved
  // clarifications; the back-and-forth happens in this thread
  // before the order leaves the company.
  // The thread is visible to the purchaser too (so they can see
  // what's been asked and answer / see it resolved).
  const showClarification =
    isAdmin &&
    (order?.status === 'draft' || order?.status === 'awaiting_clarification')
  const { data: clarification, refetch: refetchClarification } = useQuery({
    queryKey: ['order', id, 'clarification'],
    queryFn: () => getClarification(id),
    enabled: !!id && (showClarification || hasRole('purchasing_officer')),
    refetchInterval: (q) => {
      // Refresh while the purchaser is waiting for the admin to
      // resolve — but not aggressively. 15s is enough.
      const data = q.state.data
      if (!data) return false
      if (data.status === 'awaiting_clarification') return 15_000
      return false
    },
  })

  const askQ = useMutation({
    mutationFn: (question) => askClarification(id, { question }),
    onSuccess: () => {
      toast.success('Question sent to purchaser')
      qc.invalidateQueries({ queryKey: ['order', id, 'clarification'] })
      qc.invalidateQueries({ queryKey: ['order', id] })
    },
    onError: (e) => toast.error(e.message),
  })
  const resolveQ = useMutation({
    mutationFn: (clarification_id) => resolveClarification(id, { clarification_id }),
    onSuccess: () => {
      toast.success('Marked resolved')
      qc.invalidateQueries({ queryKey: ['order', id, 'clarification'] })
      qc.invalidateQueries({ queryKey: ['order', id] })
    },
    onError: (e) => toast.error(e.message),
  })

  // Purchaser answers a question
  const answerQ = useMutation({
    mutationFn: ({ clarification_id, answer }) =>
      answerClarification(id, { clarification_id, answer }),
    onSuccess: () => {
      toast.success('Answer sent')
      qc.invalidateQueries({ queryKey: ['order', id, 'clarification'] })
      qc.invalidateQueries({ queryKey: ['order', id] })
    },
    onError: (e) => toast.error(e.message),
  })

  // Admin's "Send to suppliers" — same as before, but now gated
  // on the clarification being clean. The button is rendered by
  // the ClarificationPanel; the mutation lives here so we can
  // toast + invalidate.
  const sendToSuppliers = useMutation({
    mutationFn: () => sendOrderToSuppliers(id),
    onSuccess: () => {
      toast.success('Sent to suppliers')
      qc.invalidateQueries({ queryKey: ['order', id] })
      qc.invalidateQueries({ queryKey: ['order', id, 'rfqs'] })
      qc.invalidateQueries({ queryKey: ['order', id, 'clarification'] })
      qc.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (e) => toast.error(e.message),
  })

  const submitOrder = useMutation({
  mutationFn: () => apiPost(`/orders/${id}/submit`),
  onSuccess: () => { toast.success("Submitted for approval"); qc.invalidateQueries({ queryKey: ['order', id] }); },
  onError: (e) => toast.error(e.message || "Failed"),
});

  // --- Draft edit mode (purchaser only, DRAFT orders) -----------
  const [editing, setEditing] = useState(false);
  const [draftItems, setDraftItems] = useState(null); // null = unchanged from server

  const startEdit = () => {
    setDraftItems(order.items.map(it => ({ ...it })));
    setEditing(true);
  };

  const saveOrder = useMutation({
    mutationFn: () => saveOrderItems(id, { items: draftItems }),
    onSuccess: () => {
      toast.success("Order updated");
      setEditing(false);
      setDraftItems(null);
      qc.invalidateQueries({ queryKey: ['order', id] });
    },
    onError: (e) => toast.error(e.message || "Save failed"),
  });

  const updateDraftItem = (itemId, field, value) => {
    setDraftItems(prev => prev.map(it => it.id === itemId ? { ...it, [field]: value } : it));
  };

const canSendToSuppliers = isAdmin
    && (order?.status === 'draft')
    && (clarification?.summary?.unresolved ?? 0) === 0

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
            {order?.status === 'draft' && (
              <button onClick={() => submitOrder.mutate()} disabled={submitOrder.isPending} className="ml-3 px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">Submit for approval</button>
            )}
          </div>
          <p className="text-slate-500 text-sm mt-1">
            {/* Supplier sees "Vessel #N" — the backend redaction
                layer anonymizes the vessel for them. */}
            {isSupplier ? order.vessel_label : order.vessel_name} · {order.port_name} · {new Date(order.order_date).toLocaleString()}
          </p>
          {/* IMPA-first: the order has no grand total — the
              purchaser doesn't know what this will cost. The
              delivery window (ETA / ETD) becomes the most
              useful piece of header info instead. */}
          {(order.eta_at_port || order.etd_at_port) ? (
            <p className="text-[11px] text-slate-500 mt-1 inline-flex items-center gap-3 flex-wrap">
              {order.eta_at_port ? (
                <span className="inline-flex items-center gap-1">
                  <Clock className="w-3 h-3" /> ETA {new Date(order.eta_at_port).toLocaleString()}
                </span>
              ) : null}
              {order.etd_at_port ? (
                <span className="inline-flex items-center gap-1">
                  <Clock className="w-3 h-3" /> ETD {new Date(order.etd_at_port).toLocaleString()}
                </span>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">No price on the order</div>
          <div className="text-sm text-slate-700 dark:text-slate-300 mt-1 max-w-[16rem]">
            The supplier quotes after you send it to them.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Items */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Line items ({order.items.length})</h2>
              {order.status === 'draft' && !isSupplier && (
                editing ? (
                  <div className="flex gap-2">
                    <button onClick={() => saveOrder.mutate()} disabled={saveOrder.isPending} className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1">
                      {saveOrder.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                      Save
                    </button>
                    <button onClick={() => { setEditing(false); setDraftItems(null); }} className="px-3 py-1 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm rounded hover:bg-slate-300 dark:hover:bg-slate-600">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button onClick={startEdit} className="px-3 py-1 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 text-sm rounded hover:bg-slate-50 dark:hover:bg-slate-700">
                    Edit order
                  </button>
                )
              )}
            </div>
            <div className="overflow-x-auto -mx-2">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-2 py-2 text-left">IMPA</th>
                    <th className="px-2 py-2 text-left">Description</th>
                    <th className="px-2 py-2 text-right">Qty</th>
                    {!editing && <th className="px-2 py-2 text-left">Notes</th>}
                  </tr>
                </thead>
                <tbody>
                  {(editing ? draftItems : order.items).map(it => {
                    // IMPA code display (with name lookup) — same in both modes
                    const impaDisplay = (code) => (
                      <>
                        {code || <span className="text-slate-400">—</span>}
                        {code && (() => {
                          const hit = impaNames.get(code)
                          if (hit && hit.name) {
                            return (
                              <div className="font-sans text-[10px] text-slate-500 dark:text-slate-400 mt-0.5 leading-tight">
                                {hit.name}
                                {hit.group && <span className="text-slate-400 ml-1">· {hit.group}</span>}
                              </div>
                            )
                          }
                          return (
                            <div className="font-sans text-[10px] text-slate-400 dark:text-slate-500 mt-0.5 leading-tight italic">
                              not in catalog
                            </div>
                          )
                        })()}
                      </>
                    )
                    return (
                      <tr key={it.id} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="px-2 py-2.5 font-mono text-xs align-top">
                          {editing ? (
                            <input
                              type="text"
                              value={it.impa_code || ''}
                              onChange={e => updateDraftItem(it.id, 'impa_code', e.target.value)}
                              className="w-full bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded px-1 py-0.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="e.g. 123456-7890"
                            />
                          ) : impaDisplay(it.impa_code)}
                        </td>
                        <td className="px-2 py-2.5 text-sm">
                          {editing ? (
                            <input
                              type="text"
                              value={it.notes || ''}
                              onChange={e => updateDraftItem(it.id, 'notes', e.target.value)}
                              className="w-full bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded px-1.5 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="Description / intended use"
                            />
                          ) : (
                            it.description || <span className="text-slate-400 italic">no description</span>
                          )}
                        </td>
                        <td className="px-2 py-2.5 text-right">
                          {editing ? (
                            <div className="flex items-center justify-end gap-1">
                              <input
                                type="number"
                                min={1}
                                value={it.quantity}
                                onChange={e => updateDraftItem(it.id, 'quantity', parseInt(e.target.value) || 1)}
                                className="w-16 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded px-1 py-0.5 text-sm text-right focus:outline-none focus:ring-1 focus:ring-blue-500"
                              />
                              <input
                                type="text"
                                value={it.unit}
                                onChange={e => updateDraftItem(it.id, 'unit', e.target.value)}
                                className="w-12 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded px-1 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              />
                            </div>
                          ) : (
                            `${it.quantity} ${it.unit}`
                          )}
                        </td>
                        {!editing && (
                          <td className="px-2 py-2.5 text-xs text-slate-600 dark:text-slate-300">
                            {it.notes || <span className="text-slate-400">—</span>}
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-slate-500 mt-2">
              No prices here — the supplier quotes per line after you send the order.
            </p>
          </div>

          {/* Marketplace proposal (awaiting_purchaser_approval) */}
          {showProposal ? (
            <ProposalPanel
              proposal={proposal}
              loading={proposalLoading}
              showRejectForm={showRejectForm}
              setShowRejectForm={setShowRejectForm}
              rejectReason={rejectReason}
              setRejectReason={setRejectReason}
              decide={decideProposal}
            />
          ) : null}

          {/* Preparation status (confirmed) */}
          {showPreparation && !isSupplier ? (
            <PreparationPanel
              assignments={assignments}
              loading={assignmentsLoading}
              onDrop={(sid) => {
                if (confirm('Drop this supplier? Their lines go back to "needs another supplier".')) {
                  dropOne.mutate(sid)
                }
              }}
              dropping={dropOne.isPending}
            />
          ) : null}

          {/* Clarification panel (admin only, draft / awaiting_clarification) */}
          {showClarification ? (
            <ClarificationPanel
              order={order}
              thread={clarification}
              loading={!clarification}
              onAsk={(q) => askQ.mutate(q)}
              asking={askQ.isPending}
              onResolve={(cid) => resolveQ.mutate(cid)}
              resolving={resolveQ.isPending}
              onSend={() => {
                if (confirm('Send this order to suppliers? Once sent, the package is locked and ETA/ETD are snapshotted.')) {
                  sendToSuppliers.mutate()
                }
              }}
              canSend={canSendToSuppliers}
              sending={sendToSuppliers.isPending}
            />
          ) : null}

          {/* Purchaser's view of the clarification thread when one
              is open (so they can answer). Visible whenever the
              thread has any entries. */}
          {!showClarification &&
            (clarification?.entries?.length ?? 0) > 0 &&
            hasRole('purchasing_officer') ? (
            <PurchaserClarificationView
              thread={clarification}
              onAnswer={(cid, answer) => answerQ.mutate({ clarification_id: cid, answer })}
              answering={answerQ.isPending}
            />
          ) : null}

          {/* RFQs */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Gavel className="w-4 h-4" /> RFQ pipeline
              </h2>
              {/* The "Send to suppliers" button used to live here.
                  In the IMPA-first redesign it's the
                  ClarificationPanel's primary action — it's only
                  available to admins, and only when no
                  clarifications are unresolved. */}
            </div>
            {/* Final offer: purchaser approves/rejects the proposal directly from here */}
            {(order?.status === 'rfq_closed' || order?.status === 'awaiting_purchaser_approval') && (
              <div className="mb-3 p-4 bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-xl">
                <div className="text-sm font-semibold text-violet-800 dark:text-violet-300 mb-1">Final Offer</div>
                <div className="text-xs text-violet-700 dark:text-violet-300 font-medium mb-3">
                  Price: USD {proposal ? Number(proposal.customer_facing_subtotal || 0).toFixed(2) : '—'}, Quantity: {proposal ? (proposal.lines || []).reduce((sum, l) => sum + (l.used_quantity || 0), 0) + ' units' : '—'}
                </div>
                {/* Offer details from proposal */}
                {proposal && (
                  <div className="flex items-center gap-6 mb-3 text-sm">
                    <div>
                      <span className="text-xs text-slate-500">Final Price</span>
                      <div className="font-bold text-base text-violet-700 dark:text-violet-300">
                        USD {Number(proposal.customer_facing_subtotal || 0).toFixed(2)}
                      </div>
                    </div>
                    <div>
                      <span className="text-xs text-slate-500">Total Qty Agreed</span>
                      <div className="font-bold text-base text-slate-800 dark:text-slate-200">
                        {(proposal.lines || []).reduce((sum, l) => sum + (l.used_quantity || 0), 0)} units
                      </div>
                    </div>
                    {proposal.margin_pct != null && (
                      <div>
                        <span className="text-xs text-slate-500">Markup</span>
                        <div className="font-bold text-base text-amber-600 dark:text-amber-400">{proposal.margin_pct}%</div>
                      </div>
                    )}
                  </div>
                )}
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => decideProposal.mutate(true)}
                    disabled={decideProposal.isPending}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
                  >
                    <Check className="w-4 h-4" /> Accept the offer
                  </button>
                  <button
                    onClick={() => { setShowRejectForm(true); }}
                    disabled={decideProposal.isPending}
                    className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
                  >
                    <X className="w-4 h-4" /> Decline the offer
                  </button>
                </div>
                {showRejectForm && (
                  <div className="mt-3 p-3 border border-rose-200 dark:border-rose-800 rounded-lg bg-rose-50/50 dark:bg-rose-900/10">
                    <label className="block text-xs font-semibold text-rose-700 mb-1.5">Reason for decline</label>
                    <textarea
                      value={rejectReason}
                      onChange={e => setRejectReason(e.target.value)}
                      rows={2}
                      placeholder="Why are you declining this offer?"
                      className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-rose-200 dark:border-rose-800 rounded text-sm"
                    />
                    <div className="mt-2 flex items-center justify-end gap-2">
                      <button onClick={() => setShowRejectForm(false)} className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded">Cancel</button>
                      <button
                        onClick={() => decideProposal.mutate(false)}
                        disabled={decideProposal.isPending || !rejectReason.trim()}
                        className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium rounded disabled:opacity-50 inline-flex items-center gap-2"
                      >
                        {decideProposal.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />}
                        Confirm decline
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            {(rfqs || []).length === 0 ? (
              <p className="text-sm text-slate-500">No RFQ sent yet</p>
            ) : (
              <div className="space-y-2">
                {rfqs.map(r => (
                  <Link
                    key={r.id}
                    to={`/marketplace/markup/${r.id}`}
                    className="block p-3 border border-slate-200 dark:border-slate-700 rounded-lg hover:border-blue-500"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-mono text-xs">{r.reference}</div>
                        <div className="text-xs text-slate-500">
                          {r.invited_count} invited · {r.responded_count} responded
                        </div>
                      </div>
                      {r.status === 'rfq_closed' || r.status === 'awaiting_purchaser_approval' ? (
                  <Link
                    to={`/marketplace/decide/${r.id}`}
                    className="ml-2 inline-flex items-center gap-1 px-3 py-1.5 bg-violet-600 hover:bg-violet-700 text-white text-xs font-medium rounded-lg"
                  >
                    Make Decision
                  </Link>
                ) : null}
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

// --- marketplace redesign panels --------------------------------------

function ProposalPanel({
  proposal,
  loading,
  showRejectForm,
  setShowRejectForm,
  rejectReason,
  setRejectReason,
  decide,
}) {
  if (loading) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <Loader2 className="w-4 h-4 animate-spin inline-block" />
      </div>
    )
  }
  if (!proposal) return null
  const subtotal = proposal.customer_facing_subtotal ?? 0
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Gavel className="w-4 h-4" /> Composed proposal
        </h2>
        {proposal.margin_pct != null ? (
          <span className="text-[11px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
            margin {proposal.margin_pct}%
          </span>
        ) : null}
      </div>
      {proposal.eta_at_port ? (
        <p className="text-[11px] text-emerald-600 mb-2 inline-flex items-center gap-1">
          <Clock className="w-3 h-3" /> ETA snapshot:{' '}
          {new Date(proposal.eta_at_port).toLocaleString()}
        </p>
      ) : null}
      <div className="overflow-x-auto -mx-2">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="px-2 py-2 text-left">Line</th>
              <th className="px-2 py-2 text-left">Decision</th>
              <th className="px-2 py-2 text-right">Qty</th>
              <th className="px-2 py-2 text-right">Lead time</th>
              <th className="px-2 py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {(proposal.lines || []).map((l) => (
              <tr key={l.rfq_item_id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="px-2 py-2.5 font-mono text-[11px] text-slate-500">
                  {l.rfq_item_id.slice(0, 8)}
                </td>
                <td className="px-2 py-2.5">
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
                <td className="px-2 py-2.5 text-right">{l.used_quantity}</td>
                <td className="px-2 py-2.5 text-right text-xs text-slate-500">
                  {l.lead_time_days ? `${l.lead_time_days}d` : '—'}
                </td>
                <td className="px-2 py-2.5 text-right font-medium">
                  USD {Number(l.customer_facing_total).toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-slate-200 dark:border-slate-700">
              <td colSpan={4} className="px-2 py-2.5 text-right text-sm font-medium">
                Customer-facing total
              </td>
              <td className="px-2 py-2.5 text-right font-bold">
                USD {Number(subtotal).toFixed(2)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Approve / reject (purchaser only) */}
      {!showRejectForm ? (
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            onClick={() => setShowRejectForm(true)}
            disabled={decide.isPending}
            className="px-4 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            <X className="w-4 h-4" /> Reject
          </button>
          <button
            onClick={() => decide.mutate(true)}
            disabled={decide.isPending}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            {decide.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Approve proposal
          </button>
        </div>
      ) : (
        <div className="mt-4 p-3 border border-rose-200 dark:border-rose-800 rounded-lg bg-rose-50/50 dark:bg-rose-900/10">
          <label className="block text-xs font-semibold text-rose-700 mb-1.5">
            Reason for rejection
          </label>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows={2}
            placeholder="Why are you rejecting this proposal?"
            className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-rose-200 dark:border-rose-800 rounded text-sm"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              onClick={() => setShowRejectForm(false)}
              className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded"
            >
              Cancel
            </button>
            <button
              onClick={() => decide.mutate(false)}
              disabled={decide.isPending || !rejectReason.trim()}
              className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium rounded disabled:opacity-50 inline-flex items-center gap-2"
            >
              {decide.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <X className="w-4 h-4" />}
              Confirm reject
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function PreparationPanel({ assignments, loading, onDrop, dropping }) {
  if (loading) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <Loader2 className="w-4 h-4 animate-spin inline-block" />
      </div>
    )
  }
  const rows = assignments || []
  if (rows.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-2 flex items-center gap-2">
          <Truck className="w-4 h-4" /> Preparation status
        </h2>
        <p className="text-sm text-slate-500">No slices yet.</p>
      </div>
    )
  }
  const confirmed = rows.filter((r) => r.line_status === 'confirmed').length
  const pending = rows.filter((r) => r.line_status === 'pending').length
  const dropped = rows.filter((r) => r.line_status === 'dropped').length
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Truck className="w-4 h-4" /> Preparation status
        </h2>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
            {confirmed} confirmed
          </span>
          {pending > 0 ? (
            <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
              {pending} pending
            </span>
          ) : null}
          {dropped > 0 ? (
            <span className="px-2 py-0.5 rounded-full bg-rose-100 text-rose-700">
              {dropped} dropped
            </span>
          ) : null}
        </div>
      </div>
      <div className="overflow-x-auto -mx-2">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="px-2 py-2 text-left">Supplier</th>
              <th className="px-2 py-2 text-left">Line</th>
              <th className="px-2 py-2 text-left">Status</th>
              <th className="px-2 py-2 text-left">Deadline</th>
              <th className="px-2 py-2 text-left"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const hrs = r.preparation_deadline
                ? Math.round((new Date(r.preparation_deadline).getTime() - Date.now()) / 3_600_000)
                : null
              const expired = hrs !== null && hrs < 0 && r.line_status === 'pending'
              return (
                <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-2 py-2.5 text-sm font-medium">
                    {r.supplier_name || '—'}
                  </td>
                  <td className="px-2 py-2.5 font-mono text-[11px] text-slate-500">
                    {(r.product_id || r.rfq_item_id).slice(0, 8)}
                  </td>
                  <td className="px-2 py-2.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        r.line_status === 'confirmed'
                          ? 'bg-emerald-100 text-emerald-700'
                          : r.line_status === 'dropped'
                            ? 'bg-rose-100 text-rose-700'
                            : 'bg-amber-100 text-amber-700'
                      }`}
                    >
                      {r.line_status}
                    </span>
                    {r.confirmed_at ? (
                      <div className="text-[10px] text-slate-500 mt-0.5">
                        {new Date(r.confirmed_at).toLocaleString()}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-2 py-2.5 text-xs">
                    {r.preparation_deadline ? (
                      <span className={expired ? 'text-rose-600 font-semibold' : ''}>
                        {new Date(r.preparation_deadline).toLocaleString()}
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
                  <td className="px-2 py-2.5 text-right">
                    {r.line_status === 'pending' ? (
                      <button
                        onClick={() => onDrop(r.supplier_id)}
                        disabled={dropping}
                        className="text-[11px] px-2 py-1 bg-rose-50 hover:bg-rose-100 text-rose-700 rounded disabled:opacity-50"
                        title="Drop this supplier's slice. Their lines go back to needs-another-supplier."
                      >
                        Drop
                      </button>
                    ) : r.drop_reason ? (
                      <span className="text-[10px] text-slate-500" title={r.drop_reason}>
                        {r.drop_reason}
                      </span>
                    ) : null}
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

// --- IMPA-first: clarification thread (admin ↔ purchaser) ------------

/**
 * ClarificationPanel — admin-only surface on the order page.
 *
 * The order sits in DRAFT / AWAITING_CLARIFICATION until the
 * admin either asks the purchaser a question and gets an
 * answer, or decides to send the order to suppliers as-is.
 *
 * Two actions:
 *   1. Ask a question — opens a textarea, posts to
 *      /orders/{id}/clarify. The purchaser gets a notification.
 *   2. Send to suppliers — only enabled when the thread is
 *      clean (no unresolved entries). Posts to
 *      /rfq/for-order/{id} which fans out to suppliers and
 *      snapshots ETA + ETD on the order.
 *
 * Resolved entries are kept visible — the audit trail matters
 * for the supplier side, so we don't hide them.
 */
function ClarificationPanel({
  order,
  thread,
  loading,
  onAsk,
  asking,
  onResolve,
  resolving,
  onSend,
  canSend,
  sending,
}) {
  const [draft, setDraft] = useState('')
  const [showAskForm, setShowAskForm] = useState(false)
  const entries = thread?.entries || []
  const unresolved = thread?.summary?.unresolved ?? 0
  const unanswered = thread?.summary?.unanswered ?? 0
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <MessageCircle className="w-4 h-4" /> Clarification with purchaser
        </h2>
        <div className="flex items-center gap-1.5 text-[11px]">
          {unresolved > 0 ? (
            <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
              {unresolved} unresolved
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
              clean
            </span>
          )}
          {unanswered > 0 ? (
            <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
              {unanswered} awaiting answer
            </span>
          ) : null}
        </div>
      </div>

      {/* Thread history */}
      {loading ? (
        <p className="text-xs text-slate-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin inline-block mr-1" />
          Loading thread…
        </p>
      ) : entries.length === 0 ? (
        <p className="text-xs text-slate-500">
          No questions yet. If the order looks fine, send it to suppliers — the
          ETA/ETD window gets snapshotted and the RFQ fans out.
        </p>
      ) : (
        <ul className="space-y-2 mb-3">
          {entries.map((e) => (
            <li
              key={e.id}
              className={`p-3 rounded-lg border ${
                e.resolved_at
                  ? 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40'
                  : 'border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10'
              }`}
            >
              <div className="flex items-start gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-sm">
                    <span className="text-[10px] font-semibold uppercase text-slate-500 mr-1">Q</span>
                    {e.question}
                  </p>
                  {e.answer ? (
                    <p className="text-sm mt-2">
                      <span className="text-[10px] font-semibold uppercase text-slate-500 mr-1">A</span>
                      {e.answer}
                    </p>
                  ) : (
                    <p className="text-[11px] text-amber-600 mt-2 italic">
                      Waiting for purchaser to answer…
                    </p>
                  )}
                  <div className="text-[10px] text-slate-500 mt-1">
                    {e.asked_at ? new Date(e.asked_at).toLocaleString() : ''}
                    {e.answered_at ? ` · answered ${new Date(e.answered_at).toLocaleString()}` : ''}
                    {e.resolved_at ? ` · resolved ${new Date(e.resolved_at).toLocaleString()}` : ''}
                  </div>
                </div>
                {!e.resolved_at && e.answer ? (
                  <button
                    onClick={() => onResolve(e.id)}
                    disabled={resolving}
                    className="text-[11px] px-2 py-1 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 rounded disabled:opacity-50"
                    title="Mark this question resolved"
                  >
                    <Check className="w-3 h-3 inline-block mr-0.5" /> Resolve
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Ask form */}
      {!showAskForm ? (
        <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
          <button
            onClick={() => setShowAskForm(true)}
            disabled={order.status !== 'draft' && order.status !== 'awaiting_clarification'}
            className="text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 rounded font-medium inline-flex items-center gap-1.5 disabled:opacity-50"
          >
            <MessageCircle className="w-3 h-3" /> Ask a question
          </button>
          <button
            onClick={onSend}
            disabled={!canSend || sending}
            className="text-xs px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium disabled:opacity-50 inline-flex items-center gap-1.5"
            title={
              !canSend
                ? 'Resolve all open clarifications before sending to suppliers'
                : 'Send the order to suppliers. ETA/ETD will be snapshotted.'
            }
          >
            {sending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
            Send to suppliers
          </button>
        </div>
      ) : (
        <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
          <label className="block text-xs font-semibold text-slate-700 dark:text-slate-200 mb-1.5">
            Question for the purchaser
          </label>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            placeholder="e.g. The 32-inch TV — is OLED acceptable or do you need QLED?"
            className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
            autoFocus
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              onClick={() => {
                setShowAskForm(false)
                setDraft('')
              }}
              className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (!draft.trim()) return
                onAsk(draft.trim())
                setDraft('')
                setShowAskForm(false)
              }}
              disabled={!draft.trim() || asking}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {asking ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * PurchaserClarificationView — read-only thread with an answer
 * box on unanswered entries. Rendered for purchasing officers
 * whenever the thread has any entries (so they can answer
 * without the page needing admin role).
 */
function PurchaserClarificationView({ thread, onAnswer, answering }) {
  const entries = thread?.entries || []
  const [drafts, setDrafts] = useState({}) // clarification_id -> answer string
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <MessageCircle className="w-4 h-4" /> Questions from the company
      </h2>
      <ul className="space-y-2">
        {entries.map((e) => (
          <li
            key={e.id}
            className={`p-3 rounded-lg border ${
              e.resolved_at
                ? 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40'
                : 'border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/10'
            }`}
          >
            <p className="text-sm">
              <span className="text-[10px] font-semibold uppercase text-slate-500 mr-1">Q</span>
              {e.question}
            </p>
            {e.answer ? (
              <p className="text-sm mt-2">
                <span className="text-[10px] font-semibold uppercase text-slate-500 mr-1">A</span>
                {e.answer}
              </p>
            ) : (
              <div className="mt-2">
                <textarea
                  value={drafts[e.id] || ''}
                  onChange={(ev) =>
                    setDrafts((d) => ({ ...d, [e.id]: ev.target.value }))
                  }
                  rows={2}
                  placeholder="Your answer…"
                  className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-amber-200 dark:border-amber-800 rounded text-sm"
                />
                <div className="mt-1.5 flex items-center justify-end">
                  <button
                    onClick={() => {
                      const a = (drafts[e.id] || '').trim()
                      if (!a) return
                      onAnswer(e.id, a)
                      setDrafts((d) => ({ ...d, [e.id]: '' }))
                    }}
                    disabled={answering || !(drafts[e.id] || '').trim()}
                    className="text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium disabled:opacity-50 inline-flex items-center gap-1.5"
                  >
                    {answering ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                    Send answer
                  </button>
                </div>
              </div>
            )}
            <div className="text-[10px] text-slate-500 mt-1">
              {e.asked_at ? `asked ${new Date(e.asked_at).toLocaleString()}` : ''}
              {e.resolved_at ? ` · resolved ${new Date(e.resolved_at).toLocaleString()}` : ''}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )

  // Collapsible IMPA catalog browser — verifies codes for drafted lines
  const [catOpen, setCatOpen] = useState(false)
  const [catTerm, setCatTerm] = useState('')
  const { data: catData } = useQuery({
    queryKey: ['impa-catalog', catTerm],
    queryFn: () => apiGet('/catalog/impa', { query: { q: catTerm || undefined, limit: 200 } }),
    enabled: catOpen,
    staleTime: 30_000,
  })
  const catRows = Array.isArray(catData) ? catData : (catData?.items || [])
  const draftCodes = useMemo(() => new Set((draftItems || []).map(it => (it.impa_code || '').trim()).filter(Boolean)), [draftItems])

  return (
    <div className="mt-8 border-t pt-6">
      <button onClick={() => setCatOpen(o => !o)} className="text-sm font-medium text-blue-600 hover:underline flex items-center gap-1">
        {catOpen ? 'Hide' : 'Show'} IMPA catalog browser
        <ChevronDown className={"w-4 h-4 transition-transform " + (catOpen ? "rotate-180" : "")} />
      </button>
      {catOpen && (
        <div className="mt-3 bg-white dark:bg-slate-900 border rounded-lg p-3 shadow-sm">
          <input value={catTerm} onChange={e => setCatTerm(e.target.value)} placeholder="Search IMPA code or name…" className="w-full px-2 py-1.5 border rounded text-sm mb-2 dark:bg-slate-800" />
          <div className="max-h-60 overflow-auto text-xs space-y-1">
            {catRows.map(r => (
              <div key={r.impa_code || r.code} className={"px-2 py-1 rounded " + (draftCodes.has((r.impa_code || r.code || '').trim()) ? 'bg-green-50 dark:bg-green-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-800')}>
                <span className="font-mono font-medium">{r.impa_code || r.code}</span> — {r.name || r.product_name || ''}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
