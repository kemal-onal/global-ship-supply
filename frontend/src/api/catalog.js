// IMPA code helpers — used by the order-create / order-detail / supplier
// quote pages to translate the 6-digit vessel-typed code into a human
// name. The IMPA-first redesign makes this the "company-as-bridge"
// surface: the platform looks the name up so neither the vessel nor
// the supplier has to know them.
import { apiGet, apiPost } from './client'

/**
 * Single-code IMPA search. Returns an array of matches (name + group)
 * for a substring. Used by the typeahead in OrderCreate.
 *
 * @param {string} q
 * @param {{ limit?: number, group?: string }} [opts]
 */
export function searchImpa(q, opts = {}) {
  return apiGet('/catalog/impa', { query: { q, limit: opts.limit ?? 20, group: opts.group } })
}

/**
 * Bulk IMPA name lookup. Accepts a list of codes, returns one entry
 * per code in the same order, with `name: null` for unknown codes.
 * This is the "translate the codes the vessel typed into names
 * everyone can read" call — used by all three order/quote surfaces.
 *
 * @param {string[]} codes
 * @returns {Promise<Array<{ code: string, name: string | null, group: string | null }>>}
 */
export function lookupImpa(codes) {
  return apiPost('/catalog/impa/lookup', { codes })
}
