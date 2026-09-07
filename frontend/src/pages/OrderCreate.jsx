import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronDown, ChevronRight, Plus, Search, Trash2, WifiOff, Loader2, Hash, AlertCircle, BookOpen, Check } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useNetworkStore } from '../store/network'
import { enqueueAction } from '../offline/sync'
import { useImpaNames } from '../hooks/useImpaNames'

/**
 * Order create — IMPA-first redesign.
 *
 * The order line carries no price. The purchaser types an IMPA
 * code (or picks it from a typeahead against the existing
 * ImpaCode table) and adds a description, quantity, and notes.
 * The catalog cross-reference is gone; the supplier is the
 * source of truth for whether the IMPA maps to a real product.
 *
 * Two IMPA-pick modes:
 *   1. Typeahead (default) — text input that queries
 *      /catalog/impa?q=... and shows matches as "IMPA_CODE — name".
 *      The user picks one or types a free-text fallback (any
 *      6-digit string works, even one not in the seed).
 *   2. "Add by description" — adds a blank line the user fills
 *      in manually.
 */
export default function OrderCreatePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user, vesselId } = useAuthStore()
  const { online } = useNetworkStore()

  const { data: vessels } = useQuery({
    queryKey: ['vessels', 'list'],
    queryFn: () => apiGet('/vessels'),
  })
  const { data: ports } = useQuery({
    queryKey: ['ports', 'list'],
    queryFn: () => apiGet('/ports'),
  })

  const [vesselSel, setVesselSel] = useState(vesselId || '')
  const [portSel, setPortSel] = useState('')
  const [priority, setPriority] = useState('normal')
  const [notes, setNotes] = useState('')
  const [items, setItems] = useState([])
  const [submitting, setSubmitting] = useState(false)

  // IMPA typeahead state — a single input that both queries the
  // catalog and accepts free-text fallback. The free-text path
  // is the new default: the user types an IMPA and either
  // selects a name from the dropdown or just hits Enter to
  // commit the typed value (and adds a description below).
  const [impaTerm, setImpaTerm] = useState('')
  const { data: impaResults } = useQuery({
    queryKey: ['impa-search', impaTerm],
    queryFn: () => apiGet('/catalog/impa', { query: { q: impaTerm, limit: 20 } }),
    enabled: impaTerm.length >= 2,
    staleTime: 30_000,
  })

  // Look up IMPA names for every line the user has typed. The hook
  // batches them into a single /catalog/impa/lookup call and caches
  // results in a module-level Map, so all rows share one fetch.
  // The visible benefit: a small caption under the IMPA code field
  // shows "Safety Boots Steel Toe Size 16" (or "—" if the typed
  // code isn't in the seed catalog) so the purchaser — and anyone
  // who later opens the order — doesn't have to memorise codes.
  const impaNames = useImpaNames(items.map((it) => it.impa_code))

  // Read-only IMPA catalog browser — answers the purchaser's
  // "is this random 6-digit code in the seed?" question without
  // leaving the page. The IMPA typeahead above only shows matches
  // as the user types; it can't verify a code that's already
  // sitting in a blank line (which is how "not in catalog" gets
  // shown under a row). This panel makes the catalog browseable.
  //
  // Same /catalog/impa endpoint the typeahead uses, just with a
  // larger limit and a longer debounce — we don't need keystroke
  // responsiveness here, and 5000 rows of JSON is small enough
  // that we just ask the server and let it filter. Group filter
  // is the 2-digit IMPA section prefix (e.g. "30" for safety
  // gear, "33" for paint, etc.); the seed spans 30..89.
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [catalogTerm, setCatalogTerm] = useState('')
  const [catalogGroup, setCatalogGroup] = useState('')
  // debounce: only fire /catalog/impa after the user stops typing
  // for ~250ms. The typeahead fires on every keystroke; the
  // browser can wait, and a 500-row response on every char would
  // be wasteful.
  const [catalogDebounced, setCatalogDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setCatalogDebounced(catalogTerm.trim()), 250)
    return () => clearTimeout(t)
  }, [catalogTerm])
  const { data: catalogRows, isFetching: catalogLoading } = useQuery({
    queryKey: ['impa-catalog', catalogDebounced, catalogGroup],
    queryFn: () => apiGet('/catalog/impa', {
      query: { q: catalogDebounced || undefined, group: catalogGroup || undefined, limit: 500 },
    }),
    enabled: catalogOpen, // only fetch when the panel is expanded
    staleTime: 30_000,
  })
  const catalogList = Array.isArray(catalogRows) ? catalogRows : (catalogRows?.items || [])
  // Group list — derive from a small unfiltered probe query so we
  // don't hardcode groups the seed doesn't have. We only fetch
  // when the panel is first opened, and we cache the result.
  const { data: groupProbe } = useQuery({
    queryKey: ['impa-catalog', 'groups-probe'],
    queryFn: () => apiGet('/catalog/impa', { query: { limit: 500 } }),
    enabled: catalogOpen,
    staleTime: 5 * 60_000, // groups don't change at runtime
  })
  const groupOptions = useMemo(() => {
    const probe = Array.isArray(groupProbe) ? groupProbe : (groupProbe?.items || [])
    return Array.from(new Set(probe.map((r) => r.group).filter(Boolean))).sort()
  }, [groupProbe])
  // Build a Set of codes the user has typed in line items. We
  // use it to highlight the matching row in the catalog so the
  // purchaser can see "yes, 124356 is in there / no, it isn't"
  // at a glance.
  const typedCodes = useMemo(
    () => new Set(items.map((it) => it.impa_code.trim()).filter(Boolean)),
    [items],
  )

  const addItem = ({ impa_code, name }) => {
    if (items.find(i => i.impa_code === impa_code && impa_code)) {
      toast.error('Already in cart')
      return
    }
    setItems(prev => [...prev, {
      impa_code: impa_code || '',
      // The "name" from the typeahead is the human-readable IMPA
      // description ("Television", "Boot", etc.). The user can
      // override it below — IMPA codes don't always tell the
      // full story (e.g. "632121" is just "TV").
      name: name || '',
      description: '',
      quantity: 1,
      unit: 'pcs',
      notes: '',
    }])
    setImpaTerm('')
  }

  const addBlankItem = () => {
    setItems(prev => [...prev, {
      impa_code: '',
      name: '',
      description: '',
      quantity: 1,
      unit: 'pcs',
      notes: '',
    }])
  }

  const updateItem = (idx, patch) => {
    setItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))
  }
  const removeItem = (idx) => {
    setItems(prev => prev.filter((_, i) => i !== idx))
  }

  const submit = async () => {
    if (!vesselSel || !portSel) {
      toast.error('Pick a vessel and a port')
      return
    }
    if (items.length === 0) {
      toast.error('Add at least one line')
      return
    }
    // Each line must have at least an impa_code (typed) or a
    // description. The IMPA is the cross-reference; the
    // description is the human-readable supplement.
    for (const [i, it] of items.entries()) {
      if (!it.impa_code.trim() && !it.description.trim()) {
        toast.error(`Line ${i + 1}: need an IMPA code or a description`)
        return
      }
      if (it.quantity < 1) {
        toast.error(`Line ${i + 1}: quantity must be ≥ 1`)
        return
      }
    }
    setSubmitting(true)
    // IMPA-first: the order line carries no price. unit_price
    // is sent as 0; the server ignores it (always 0 now).
    const payload = {
      vessel_id: vesselSel,
      port_id: portSel,
      priority,
      customer_notes: notes || undefined,
      source: online ? 'web' : 'offline',
      // Back-compat flag for analytics — the new flow is IMPA
      // by definition, but we keep the field so existing audit
      // log consumers don't break.
      search_by_impa: true,
      items: items.map(({ impa_code, description, quantity, unit, notes: lineNotes }) => ({
        impa_code: impa_code.trim() || null,
        description: description.trim() || null,
        quantity,
        unit,
        unit_price: 0,
        notes: lineNotes.trim() || null,
      })),
    }

    try {
      if (online) {
        const created = await apiPost('/orders', payload)
        toast.success(`Order ${created.reference} created`)
        qc.invalidateQueries({ queryKey: ['orders'] })
        navigate(`/orders/${created.id}`)
      } else {
        // Offline: enqueue and go back
        await enqueueAction({
          resource: 'orders',
          action: 'create',
          payload,
        })
        toast.success('Offline: order queued and will sync when VSAT returns')
        navigate('/orders')
      }
    } catch (err) {
      toast.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  // Whether the typeahead dropdown should be open. Show on
  // ≥ 2 chars of input AND there are results to render.
  // Note: GET /catalog/impa returns a flat array, NOT {items: [...]}.
  // The defensive Array.isArray check handles either shape so a
  // future backend change to wrap the response won't break us.
  const impaList = Array.isArray(impaResults) ? impaResults : (impaResults?.items || [])
  const dropdownOpen = impaTerm.length >= 2 && impaList.length > 0

  // The free-text "commit" button is shown when the user has
  // typed something that doesn't exactly match a typeahead hit.
  // They can still add the line as-is.
  const canCommitFreeText =
    impaTerm.trim().length > 0 &&
    !impaList.some(i => i.code === impaTerm.trim())

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-6xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      <h1 className="text-2xl font-bold mb-1">New order</h1>
      <p className="text-slate-500 text-sm mb-6">
        Type an IMPA code (or pick it from the typeahead). For each line, add a
        description, quantity, and notes. The order carries no price — the
        supplier quotes after you send it to them.
        {!online && (
          <span className="ml-2 inline-flex items-center gap-1 text-amber-600">
            <WifiOff className="w-3.5 h-3.5" /> You're offline — order will queue for sync
          </span>
        )}
      </p>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
        <h2 className="text-sm font-semibold mb-3">Order details</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Vessel">
            <select
              value={vesselSel}
              onChange={e => setVesselSel(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            >
              <option value="">Select vessel…</option>
              {(vessels || []).map(v => (
                <option key={v.id} value={v.id}>{v.name} ({v.imo_number})</option>
              ))}
            </select>
          </Field>
          <Field label="Destination port">
            <select
              value={portSel}
              onChange={e => setPortSel(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            >
              <option value="">Select port…</option>
              {(ports || []).map(p => (
                <option key={p.id} value={p.id}>{p.name} ({p.unlocode}) — {p.country}</option>
              ))}
            </select>
          </Field>
          <Field label="Priority">
            <select
              value={priority}
              onChange={e => setPriority(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </Field>
          <Field label="Notes">
            <input
              type="text"
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Optional — visible to the company"
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </Field>
        </div>
      </div>

      {/* Line items */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
        <h2 className="text-sm font-semibold mb-3">Line items</h2>

        {/* IMPA typeahead */}
        <div className="mb-4">
          <Field label="Add by IMPA code">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="search"
                value={impaTerm}
                onChange={e => setImpaTerm(e.target.value)}
                onKeyDown={e => {
                  // Enter on a typed-but-not-in-list value
                  // commits it as a free-text IMPA. Same as
                  // clicking the "Add as-is" button.
                  if (e.key === 'Enter' && canCommitFreeText) {
                    e.preventDefault()
                    addItem({ impa_code: impaTerm.trim(), name: '' })
                  }
                }}
                placeholder="Type IMPA code (e.g. 632121) or name (TV, boot…)"
                className="w-full pl-10 pr-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
              />
              {dropdownOpen && (
                <div className="absolute z-10 top-full mt-1 left-0 right-0 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                  {impaList.map(i => (
                    <button
                      key={i.code}
                      onClick={() => addItem({ impa_code: i.code, name: i.name })}
                      className="w-full text-left px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800 border-b border-slate-100 dark:border-slate-800 last:border-b-0 text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-slate-500 inline-flex items-center gap-0.5">
                          <Hash className="w-3 h-3" />{i.code}
                        </span>
                        <span className="font-medium">{i.name}</span>
                      </div>
                      {i.group && (
                        <div className="text-[10px] text-slate-400 ml-5">{i.group}</div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 mt-2">
              {canCommitFreeText && (
                <button
                  onClick={() => addItem({ impa_code: impaTerm.trim(), name: '' })}
                  className="px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-md border border-slate-200 dark:border-slate-700 inline-flex items-center gap-1.5"
                >
                  <Plus className="w-3 h-3" /> Add "{impaTerm.trim()}" as-is
                </button>
              )}
              <button
                onClick={addBlankItem}
                className="px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-md border border-slate-200 dark:border-slate-700 inline-flex items-center gap-1.5"
                title="Add a line with no IMPA — useful when you'll fill in the description only"
              >
                <Plus className="w-3 h-3" /> Add blank line
              </button>
              <span className="text-[11px] text-slate-500 inline-flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                The IMPA code is a free-text string. The supplier tells you what it maps to.
              </span>
            </div>
          </Field>
        </div>

        {/* Line items table */}
        {items.length === 0 ? (
          <div className="text-center py-6 text-sm text-slate-500 border border-dashed border-slate-200 dark:border-slate-700 rounded-lg">
            No items yet — type an IMPA code above and press Enter, or pick from the typeahead.
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((it, idx) => (
              <div
                key={idx}
                className="grid grid-cols-12 gap-2 items-start p-2.5 border border-slate-200 dark:border-slate-700 rounded-lg"
              >
                <div className="col-span-2">
                  <input
                    type="text"
                    value={it.impa_code}
                    onChange={e => updateItem(idx, { impa_code: e.target.value })}
                    placeholder="IMPA"
                    className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm font-mono"
                  />
                  <ImpaNameCaption code={it.impa_code} cached={it.name} lookup={impaNames.get(it.impa_code)} />
                </div>
                <div className="col-span-4">
                  <input
                    type="text"
                    value={it.description}
                    onChange={e => updateItem(idx, { description: e.target.value })}
                    placeholder="Description (e.g. 32 inch, black, OLED)"
                    className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
                    title="The IMPA code doesn't tell the full story (e.g. '632121' is just 'TV'). Add a description so the supplier quotes the right thing."
                  />
                  {it.name && !it.description && (
                    <div className="text-[10px] text-slate-400 mt-0.5 italic">
                      from typeahead: {it.name}
                    </div>
                  )}
                </div>
                <div className="col-span-1">
                  <input
                    type="number"
                    min="1"
                    value={it.quantity}
                    onChange={e => updateItem(idx, { quantity: parseInt(e.target.value) || 1 })}
                    className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
                  />
                </div>
                <div className="col-span-1">
                  <input
                    type="text"
                    value={it.unit}
                    onChange={e => updateItem(idx, { unit: e.target.value })}
                    placeholder="pcs"
                    className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
                  />
                </div>
                <div className="col-span-3">
                  <input
                    type="text"
                    value={it.notes}
                    onChange={e => updateItem(idx, { notes: e.target.value })}
                    placeholder="Notes (optional)"
                    className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-xs"
                  />
                </div>
                <div className="col-span-1 flex justify-end">
                  <button
                    onClick={() => removeItem(idx)}
                    className="p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 rounded"
                    title="Remove this line"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Read-only IMPA catalog browser.
          Why: a vessel-typed random code (e.g. "124356") shows
          "not in catalog" under the line, and there's nowhere on
          the page to verify whether that code really exists in
          the seed without leaving and re-searching. This panel
          keeps the catalog in view, one click away. The IMPA
          typeahead above is for picking codes to add; this is
          for checking codes the user already typed (or just
          scrolling the seed for what we have). */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl mb-4">
        <button
          type="button"
          onClick={() => setCatalogOpen((v) => !v)}
          className="w-full flex items-center justify-between gap-2 px-5 py-3 text-left"
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            {catalogOpen
              ? <ChevronDown className="w-4 h-4 text-slate-500" />
              : <ChevronRight className="w-4 h-4 text-slate-500" />}
            <BookOpen className="w-4 h-4 text-slate-500" />
            <span>IMPA catalog browser</span>
            <span className="text-[11px] text-slate-500 font-normal">
              — check whether a code is in the seed (read-only)
            </span>
          </div>
          {typedCodes.size > 0 && (
            <span className="text-[11px] text-slate-500">
              {typedCodes.size} code{typedCodes.size === 1 ? '' : 's'} typed
            </span>
          )}
        </button>

        {catalogOpen && (
          <div className="px-5 pb-5">
            <div className="flex flex-col sm:flex-row gap-2 mb-3">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="search"
                  value={catalogTerm}
                  onChange={(e) => setCatalogTerm(e.target.value)}
                  placeholder="Search by code (e.g. 303817) or name (e.g. glove, TV, paint…)"
                  className="w-full pl-10 pr-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
                />
              </div>
              <select
                value={catalogGroup}
                onChange={(e) => setCatalogGroup(e.target.value)}
                className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm min-w-[120px]"
                title="IMPA group (the 2-digit section prefix)"
              >
                <option value="">All groups</option>
                {groupOptions.map((g) => (
                  <option key={g} value={g}>Group {g}</option>
                ))}
              </select>
            </div>

            <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden">
              <div className="max-h-72 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800 text-slate-500 text-[11px] uppercase tracking-wide">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium w-24">Code</th>
                      <th className="text-left px-3 py-2 font-medium">Name</th>
                      <th className="text-left px-3 py-2 font-medium w-16">Group</th>
                      <th className="text-right px-3 py-2 font-medium w-16"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalogLoading && catalogList.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-3 py-6 text-center text-slate-500">
                          <Loader2 className="w-4 h-4 inline animate-spin mr-1.5" />
                          Loading catalog…
                        </td>
                      </tr>
                    )}
                    {!catalogLoading && catalogList.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-3 py-6 text-center text-slate-500">
                          {catalogDebounced
                            ? <>No IMPA codes match "<span className="font-mono">{catalogDebounced}</span>"{catalogGroup && <> in group {catalogGroup}</>}.</>
                            : <>No codes in the catalog.</>}
                        </td>
                      </tr>
                    )}
                    {catalogList.map((row) => {
                      const isTyped = typedCodes.has(row.code)
                      return (
                        <tr
                          key={row.code}
                          className={
                            'border-t border-slate-100 dark:border-slate-800 ' +
                            (isTyped
                              ? 'bg-emerald-50 dark:bg-emerald-900/20 ring-1 ring-inset ring-emerald-300 dark:ring-emerald-700'
                              : 'hover:bg-slate-50 dark:hover:bg-slate-800/50')
                          }
                        >
                          <td className="px-3 py-1.5 font-mono text-xs text-slate-600 dark:text-slate-300">
                            <span className="inline-flex items-center gap-1">
                              {isTyped && <Check className="w-3 h-3 text-emerald-600" />}
                              {row.code}
                            </span>
                          </td>
                          <td className="px-3 py-1.5 text-slate-700 dark:text-slate-200">
                            {row.name}
                          </td>
                          <td className="px-3 py-1.5 text-[11px] text-slate-500">
                            {row.group}
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            <button
                              type="button"
                              onClick={() => {
                                // Drop the code into the typeahead so
                                // the user can press Enter (or pick a
                                // different match) to add it. We do NOT
                                // auto-add — that would surprise anyone
                                // browsing; adding must stay a deliberate
                                // act via the typeahead's Enter / "Add
                                // as-is" button so the same focus /
                                // quantity / notes row is preserved.
                                setImpaTerm(row.code)
                                toast.success(`Code ${row.code} ready in the search above — press Enter to add`)
                                // Scroll the typeahead into view so the
                                // user doesn't have to hunt.
                                document
                                  .querySelector('input[type="search"][placeholder^="Type IMPA"]')
                                  ?.focus()
                              }}
                              className="text-[11px] text-blue-600 hover:text-blue-700"
                              title="Copy this code into the search box above"
                            >
                              Use →
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="px-3 py-1.5 text-[10px] text-slate-400 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
                {catalogList.length > 0
                  ? <>Showing {catalogList.length} code{catalogList.length === 1 ? '' : 's'}{catalogDebounced && <> matching "{catalogDebounced}"</>}{catalogGroup && <> in group {catalogGroup}</>}.</>
                  : <>Click a column header to sort (coming soon). Browse the full 5000-code seed by clearing the search.</>}
              </div>
            </div>
            <p className="text-[11px] text-slate-500 mt-2">
              Rows highlighted in green match codes you've typed above. The
              "Use →" link drops the code into the typeahead at the top so
              you can add it on the next line.
            </p>
          </div>
        )}
      </div>

      {/* Sticky footer */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-xs text-slate-500">
            {items.length} line{items.length === 1 ? '' : 's'} · {items.reduce((s, it) => s + (it.quantity || 0), 0)} units total
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5">
            No prices on the order — suppliers will quote after you send it.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/orders')}
            className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            {online ? 'Create order' : 'Queue order'}
          </button>
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

/**
 * Small caption under the IMPA code input that shows the human
 * name. Sources of truth, in priority:
 *   1. `lookup` — the live `/catalog/impa/lookup` result for the
 *      current typed code. Wins if present (the user may have
 *      edited the code after picking from the typeahead).
 *   2. `cached` — the `name` captured at typeahead-pick time.
 *      Survives a hook re-fetch when the lookup result is still
 *      missing for a code the user just typed.
 *   3. Nothing — a blank line. The caption reserves the row
 *      height so the table doesn't jump when a name arrives.
 *
 * This is the "company-as-bridge" affordance: a vessel-typed
 * 6-digit code becomes "Safety Boots Steel Toe Size 16" so the
 * purchaser (and later the admin / supplier) can read what was
 * ordered without an IMPA cheat-sheet.
 */
function ImpaNameCaption({ code, cached, lookup }) {
  if (!code) {
    return <div className="h-3 mt-0.5" />
  }
  if (lookup && lookup.name) {
    return (
      <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5 leading-tight">
        {lookup.name}
        {lookup.group && <span className="text-slate-400 ml-1">· {lookup.group}</span>}
      </div>
    )
  }
  if (cached) {
    return (
      <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5 leading-tight">
        {cached}
      </div>
    )
  }
  return (
    <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5 leading-tight italic">
      not in catalog
    </div>
  )
}
