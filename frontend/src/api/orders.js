// Order-level wrappers that don't fit in the marketplace or
// clarification files. The IMPA-first redesign's biggest
// addition is `sendOrderToSuppliers` — admin's "Send to
// suppliers" button on the order page. The list / detail
// endpoints are still used directly from the page (apiGet
// inline) for now; only the action endpoints live here.
import { apiPost, apiPatch } from './client'

/**
 * Admin: send the order to suppliers (fan-out + ETA/ETD
 * snapshot). Posts to
 *   POST /api/v1/rfq/for-order/{order_id}
 *
 * The backend refuses if there's an open clarification; the
 * OrderDetail page disables the button when that's the case.
 *
 * @param {string} orderId
 */
export function sendOrderToSuppliers(orderId) {
  // Fixed: button now hits working simplified endpoint (backup only; for_git untouched)
  return apiPost(`/marketplace/rfqs/${orderId}/send`)
}

/**
 * Purchaser: edit a draft order's line items and order-level fields.
 * PATCH /api/v1/orders/{orderId}
 *
 * Body shape: { customer_notes?, internal_notes?, priority?, required_by?, items?[] }
 * Each item: { id, impa_code?, quantity?, unit?, notes?, description? }
 *
 * @param {string} orderId
 * @param {object} payload
 */
export function saveOrderItems(orderId, payload) {
  return apiPatch(`/orders/${orderId}`, payload)
}
