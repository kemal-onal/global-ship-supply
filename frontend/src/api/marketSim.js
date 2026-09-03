/**
 * Marketplace Simulator — API wrappers.
 *
 * Thin layer over apiPost for the marketplace-simulator endpoint.
 * The endpoint signature is:
 *   POST /api/v1/rfq/{rfq_id}/simulate
 *     body: { seed, weights, counter_offer_terms }
 *     query: { dry_run: bool }  (default true)
 *   response: { round, winner, results, events, weights, dry_run }
 *
 * The whole bid war comes back in one request, so this is just one
 * call. No incremental streaming needed for the demo.
 */
import { apiPost } from './client';

/**
 * Run a marketplace sim round for the given RFQ.
 *
 * @param {string} rfqId
 * @param {{
 *   seed?: number,
 *   weights?: { price?: number, lead_time?: number, reliability?: number, quality?: number },
 *   counter_offer_terms?: Record<string, number>,
 *   dry_run?: boolean,
 * }} [opts]
 * @returns {Promise<{
 *   round: number,
 *   winner: string|null,
 *   results: Array<{supplier_id, supplier_name, total, lead_time_days, reliability, quality, subscores, score}>,
 *   events: Array<{id, ts, round, event_type, supplier_id, payload}>,
 *   weights: object,
 *   dry_run: boolean,
 * }>}
 */
export function runMarketSim(rfqId, opts = {}) {
  const {
    seed = 42,
    weights = null,
    counter_offer_terms = null,
    dry_run = true,
  } = opts;
  return apiPost(`/rfq/${rfqId}/simulate`, {
    seed,
    weights,
    counter_offer_terms,
  }, { query: { dry_run } });
}
