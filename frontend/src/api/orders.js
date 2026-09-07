// Order-level wrappers that don't fit in the marketplace or
// clarification files. The IMPA-first redesign's biggest
// addition is `sendOrderToSuppliers` — admin's "Send to
// suppliers" button on the order page. The list / detail
// endpoints are still used directly from the page (apiGet
// inline) for now; only the action endpoints live here.
import { apiPost } from './client'

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
  return apiPost(`/rfq/for-order/${orderId}`)
}
