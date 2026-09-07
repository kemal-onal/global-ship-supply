// IMPA-name cache hook.
//
// The IMPA-first redesign renders a line-item table on the order
// create / order detail / supplier quote pages. Each row shows a
// 6-digit code (typed by the vessel) and the platform translates it
// into the IMPA's human name so the supplier can read it. We don't
// want 30 round trips for 30 lines, so:
//
//   1. Each page collects its row's `impa_code` strings.
//   2. Calls `useImpaNames(codes)`.
//   3. The hook batches them in a single POST /catalog/impa/lookup.
//   4. The result is cached in a module-level Map by sorted-joined
//      key, so re-renders / sibling components on the same page
//      share one fetch.
//
// The cache is intentionally non-reactive: components subscribe to
// *their* slice, not the whole Map. We use a tiny pub/sub on the
// cache so a second component with overlapping codes reuses the
// pending request.
import { useEffect, useMemo, useState } from 'react'
import { lookupImpa } from '../api/catalog'

// In-flight promises keyed by sorted-joined code set. Two components
// on the same page asking for the same codes get the same promise.
const inflight = new Map()

// Resolved results keyed by code → { name, group }. Once a code has
// been looked up, every component gets the answer immediately.
const resolved = new Map()

const subscribers = new Set()

function notify() {
  for (const cb of subscribers) {
    try { cb() } catch { /* ignore */ }
  }
}

function keyFor(codes) {
  return [...codes].filter(Boolean).sort().join(',')
}

async function ensureLoaded(codes) {
  const missing = codes.filter((c) => c && !resolved.has(c))
  if (missing.length === 0) return
  const key = keyFor(missing)
  if (inflight.has(key)) return inflight.get(key)
  const p = (async () => {
    const rows = await lookupImpa(missing)
    for (const row of rows) {
      if (row && row.code) {
        resolved.set(row.code, { name: row.name, group: row.group })
      }
    }
    inflight.delete(key)
    notify()
  })()
  inflight.set(key, p)
  return p
}

/**
 * Resolve a list of IMPA codes to their human names.
 *
 * @param {string[]} codes — may include empty / null / undefined values,
 *   which are silently skipped (the IMPA column is optional).
 * @returns {{
 *   get: (code: string) => { name: string | null, group: string | null } | undefined,
 *   loading: boolean,
 * }}
 */
export function useImpaNames(codes) {
  const [, setTick] = useState(0)
  const uniqueCodes = useMemo(
    () => Array.from(new Set((codes || []).filter(Boolean))),
    [codes],
  )
  const key = keyFor(uniqueCodes)
  // Anything missing from `resolved` for `uniqueCodes` is still loading.
  const loading = uniqueCodes.length > 0 && uniqueCodes.some((c) => !resolved.has(c))

  useEffect(() => {
    if (uniqueCodes.length === 0) return
    ensureLoaded(uniqueCodes)
    const cb = () => setTick((n) => n + 1)
    subscribers.add(cb)
    return () => { subscribers.delete(cb) }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  return {
    get(code) {
      if (!code) return undefined
      return resolved.get(code)
    },
    loading,
  }
}
