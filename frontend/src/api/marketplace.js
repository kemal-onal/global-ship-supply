// Thin wrapper around apiGet / apiPost for the marketplace redesign
// endpoints. The supplier portal and the company marketplace page
// both call into these. The server is the source of truth for
// identity sealing — this file is just shapes and URLs.
import { apiGet, apiPost } from './client'

// --- supplier portal ---------------------------------------------------

/**
 * List RFQs the current supplier is invited to. The backend filters
 * by `User.email == Supplier.contact_email` and the RFQ's
 * `extra.invited_supplier_ids` list.
 *
 * Returns an array of RFQ summaries; the `vessel_label` field is the
 * anonymized "Vessel #N" the supplier is allowed to see.
 */
export function listSupplierRfqs() {
  return apiGet('/supplier-portal/rfqs')
}

/**
 * Get one RFQ the supplier is invited to. Vessel name is sealed.
 *
 * @param {string} rfqId
 */
export function getSupplierRfq(rfqId) {
  return apiGet(`/supplier-portal/rfqs/${rfqId}`)
}

/**
 * Submit a quote for an RFQ. The same endpoint handles three
 * modes (decided by `can_deliver_in_window` + `lines`):
 *   1. The IMPA-first "can you deliver?" gate:
 *      { can_deliver_in_window: true|false, decline_reason?: string,
 *        lines: [] } → creates a quote with the decision only.
 *   2. A real quote with prices:
 *      { can_deliver_in_window: true, lead_time_days, lines: [...] }.
 *   3. Resubmission: same payload, server upserts the existing
 *      quote (responded_count is adjusted if the gate changed).
 *
 * @param {string} rfqId
 * @param {{
 *   can_deliver_in_window?: boolean,
 *   decline_reason?: string,
 *   lead_time_days?: number,
 *   payment_terms?: string,
 *   notes?: string,
 *   source?: string,
 *   lines: Array<{
 *     rfq_item_id: string,
 *     line_status: 'full' | 'partial' | 'none',
 *     unit_price?: number | null,
 *     quoted_quantity?: number | null,
 *   }>,
 * }} payload
 */
export function submitSupplierQuote(rfqId, payload) {
  return apiPost(`/supplier-portal/rfqs/${rfqId}/quote`, payload)
}

/**
 * Accept all pending line assignments for one quote within the
 * 24h preparation window.
 *
 * @param {string} quoteId
 */
export function acceptSupplierSlice(quoteId) {
  return apiPost(`/supplier-portal/quotes/${quoteId}/accept`)
}

/**
 * List the supplier's accepted slices (line assignments).
 */
export function listSupplierAssignments() {
  return apiGet('/supplier-portal/assignments')
}

// --- company marketplace -----------------------------------------------

/**
 * List the RFQs whose orders are eligible for the admin to
 * compose a proposal on. The marketplace composer's left-rail
 * picker calls this. The backend filters by **order status**
 * (ready_for_compose + the legacy sealed-bid predecessors that
 * the compose self-heal handles) — not by RFQ.status — because
 * the picker wants the orders the admin can act on, not the
 * raw RFQ lifecycle.
 *
 * Returns an array of RFQ summaries with the same shape the
 * picker has always rendered: id, reference, order_id,
 * order_reference, port_id, status, invited_count,
 * responded_count, items.
 */
export function listRfqsForCompose() {
  return apiGet('/rfqs-for-compose')
}

/**
 * Get the composed proposal for an order. Purchaser view has
 * supplier identity sealed (no supplier_id, no supplier_name,
 * line_total is null, customer_facing_total is the total *with*
 * margin applied). Admin view shows everything.
 *
 * @param {string} orderId
 */
export function getOrderProposal(orderId) {
  return apiGet(`/orders/${orderId}/proposal`)
}

/**
 * Admin-only: the per-line × per-supplier lattice the marketplace
 * page renders. Returns:
 *   { rfq_id, suppliers: [...], items: [{ rfq_item_id, product_id, quantity, cells: { supplier_id: {...} } }] }
 * The cell is null if that supplier didn't bid on that line.
 *
 * @param {string} rfqId
 */
export function getRfqLattice(rfqId) {
  return apiGet(`/rfq/${rfqId}/lattice`)
}

/**
 * Company decision step: for each line pick a supplier + decision,
 * set the margin %. Returns the composed proposal (admin view).
 *
 * @param {string} rfqId
 * @param {{
 *   decisions: Array<{
 *     rfq_item_id: string,
 *     supplier_id: string,
 *     quote_id: string,
 *     decision: 'use_full' | 'use_half' | 'drop',
 *   }>,
 *   margin_pct: number,
 * }} payload
 */
export function composeProposal(rfqId, payload) {
  return apiPost(`/rfq/${rfqId}/compose`, payload)
}

/**
 * Purchaser approval / rejection of the composed proposal.
 *
 * @param {string} orderId
 * @param {{ approve: boolean, reason?: string }} payload
 */
export function approveProposal(orderId, payload) {
  return apiPost(`/orders/${orderId}/approve-proposal`, payload)
}

/**
 * Admin manual drop of a slow supplier on a confirmed order.
 *
 * @param {string} orderId
 * @param {{ supplier_id: string, reason?: string }} payload
 */
export function dropSupplier(orderId, payload) {
  return apiPost(`/orders/${orderId}/drop-supplier`, payload)
}

/**
 * Admin view: the slices on a confirmed order. One row per
 * OrderDecision. Used by the OrderDetail preparation-status panel
 * to render the green/red supplier list.
 *
 * @param {string} orderId
 */
export function listOrderAssignments(orderId) {
  return apiGet(`/orders/${orderId}/assignments`)
}
