// Simplified Marketplace API Client
// New flow: fan-out -> quote -> markup -> send to purchaser -> decide
import { apiGet, apiPost } from './client'

// --- Admin marketplace endpoints ------------------------------------------

/**
 * Admin: Fan out RFQ to all active suppliers at the port.
 * POST /api/v1/marketplace/rfqs/{rfq_id}/send
 */
export function sendRfq(rfqId) {
  return apiPost(`/marketplace/rfqs/${rfqId}/send`)
}

/**
 * Admin: Apply uniform markup % to all quotes in the RFQ.
 * POST /api/v1/marketplace/rfqs/{rfq_id}/markup
 * @param {string} rfqId
 * @param {number} markupPct - Markup percentage (0-100)
 */
export function applyMarkup(rfqId, markupPct) {
  return apiPost(`/marketplace/rfqs/${rfqId}/markup`, { markup_pct: markupPct })
}

/**
 * Admin: Send marked-up quotes to purchaser (RFQ -> CLOSED).
 * POST /api/v1/marketplace/rfqs/{rfq_id}/submit
 */
export function submitToPurchaser(rfqId) {
  return apiPost(`/marketplace/rfqs/${rfqId}/submit`)
}

/**
 * Purchaser: View all quotes with markup applied.
 * GET /api/v1/marketplace/rfqs/{rfq_id}/quotes
 */
export function getQuotesForPurchaser(rfqId) {
  return apiGet(`/marketplace/rfqs/${rfqId}/quotes`)
}

/**
 * Purchaser: Approve or reject the entire proposal.
 * POST /api/v1/marketplace/rfqs/{rfq_id}/decide
 * @param {string} rfqId
 * @param {{ approve: boolean, reason?: string }} payload
 */
export function purchaserDecide(rfqId, payload) {
  return apiPost(`/marketplace/rfqs/${rfqId}/decide`, payload)
}

/**
 * Get RFQ detail (admin view).
 * GET /api/v1/marketplace/rfqs/{rfq_id}
 */
export function getRfqDetail(rfqId) {
  return apiGet(`/marketplace/rfqs/${rfqId}`)
}

// --- Supplier Portal (Simplified) ------------------------------------------

/**
 * Supplier: List RFQs this supplier was invited to.
 * GET /api/v1/supplier-portal/rfqs
 */
export function listSupplierRfqsSimple() {
  return apiGet('/supplier-portal/rfqs')
}

/**
 * Supplier: View RFQ detail.
 * GET /api/v1/supplier-portal/rfqs/{rfq_id}
 */
export function getSupplierRfqSimple(rfqId) {
  return apiGet(`/supplier-portal/rfqs/${rfqId}`)
}

/**
 * Supplier: Submit complete quote (single form).
 * POST /api/v1/supplier-portal/rfqs/{rfq_id}/quote
 * @param {string} rfqId
 * @param {{
 *   lines: Array<{
 *     rfq_item_id: string,
 *     line_status: 'full' | 'partial' | 'none',
 *     unit_price?: number | null,
 *     quoted_quantity?: number | null,
 *   }>,
 *   lead_time_days: number,
 *   payment_terms?: string,
 *   notes?: string,
 *   source?: string,
 * }} payload
 */
export function submitSupplierQuoteSimple(rfqId, payload) {
  return apiPost(`/supplier-portal/rfqs/${rfqId}/quote`, payload)
}