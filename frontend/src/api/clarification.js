// Thin wrapper around the clarification-thread endpoints on an
// order. The IMPA-first redesign promotes this thread to the
// primary admin ↔ purchaser surface on the order page (the
// "Send to suppliers" button is gated on it being clean), so
// the OrderDetail page calls into these wrappers directly.
import { apiGet, apiPost } from './client'

/**
 * Read-only view of the order's clarification thread. Visible
 * to both admin and purchaser (each sees what they need to act
 * on). The response shape is:
 *   {
 *     order_id, status,
 *     entries: [{ id, question, answer, asked_at, answered_at, resolved_at, ... }],
 *     summary: { total, unanswered, unresolved, is_blocking }
 *   }
 *
 * @param {string} orderId
 */
export function getClarification(orderId) {
  return apiGet(`/orders/${orderId}/clarification`)
}

/**
 * Admin: ask a new question. Posts to
 *   POST /api/v1/orders/{order_id}/clarify
 * The order moves to AWAITING_CLARIFICATION.
 *
 * @param {string} orderId
 * @param {{ question: string }} payload
 */
export function askClarification(orderId, payload) {
  return apiPost(`/orders/${orderId}/clarify`, payload)
}

/**
 * Purchaser: answer an open question. Posts to
 *   POST /api/v1/orders/{order_id}/answer
 *
 * @param {string} orderId
 * @param {{ clarification_id: string, answer: string }} payload
 */
export function answerClarification(orderId, payload) {
  return apiPost(`/orders/${orderId}/answer`, payload)
}

/**
 * Admin: mark a thread entry resolved (the answer is good
 * enough; the order can move to QUOTING). Posts to
 *   POST /api/v1/orders/{order_id}/resolve-clarification
 *
 * @param {string} orderId
 * @param {{ clarification_id: string }} payload
 */
export function resolveClarification(orderId, payload) {
  return apiPost(`/orders/${orderId}/resolve-clarification`, payload)
}
