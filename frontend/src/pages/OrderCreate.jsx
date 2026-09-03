import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Search, Trash2, WifiOff, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useNetworkStore } from '../store/network'
import { enqueueAction } from '../offline/sync'

export default function OrderCreatePage() {
  const [search] = useSearchParams()
  const presetProduct = search.get('product')
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
  const { data: products } = useQuery({
    queryKey: ['products', 'rfq-eligible'],
    queryFn: () => apiGet('/catalog/rfq-eligible', { query: { limit: 100 } }),
  })

  const [vesselSel, setVesselSel] = useState(vesselId || '')
  const [portSel, setPortSel] = useState('')
  const [priority, setPriority] = useState('normal')
  const [notes, setNotes] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [items, setItems] = useState(() => {
    if (presetProduct) {
      return [{ product_id: presetProduct, quantity: 1, unit: 'pcs', unit_price: 0 }]
    }
    return []
  })
  const [submitting, setSubmitting] = useState(false)

  // Filter products for the picker
  const filteredProducts = (products?.items || []).filter(p => {
    if (!searchTerm) return true
    const t = searchTerm.toLowerCase()
    return p.name?.toLowerCase().includes(t) || p.sku?.toLowerCase().includes(t)
  }).slice(0, 50)

  const addItem = (p) => {
    if (items.find(i => i.product_id === p.id)) {
      toast.error('Already in cart')
      return
    }
    setItems(prev => [...prev, {
      product_id: p.id,
      product_name: p.name,
      product_sku: p.sku,
      quantity: 1,
      unit: p.unit,
      unit_price: parseFloat(p.unit_price),
    }])
    setSearchTerm('')
  }

  const updateItem = (idx, patch) => {
    setItems(prev => prev.map((it, i) => i === idx ? { ...it, ...patch } : it))
  }
  const removeItem = (idx) => {
    setItems(prev => prev.filter((_, i) => i !== idx))
  }

  const subtotal = items.reduce((s, it) => s + it.unit_price * it.quantity, 0)

  const submit = async () => {
    if (!vesselSel || !portSel) {
      toast.error('Pick a vessel and a port')
      return
    }
    if (items.length === 0) {
      toast.error('Add at least one product')
      return
    }
    setSubmitting(true)
    const payload = {
      vessel_id: vesselSel,
      port_id: portSel,
      priority,
      customer_notes: notes || undefined,
      source: online ? 'web' : 'offline',
      items: items.map(({ product_id, quantity, unit, unit_price }) => ({
        product_id, quantity, unit, unit_price,
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
        Create a supply order for a vessel at a destination port.
        {!online && (
          <span className="ml-2 inline-flex items-center gap-1 text-amber-600">
            <WifiOff className="w-3.5 h-3.5" /> You're offline — order will queue for sync
          </span>
        )}
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Form */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
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
                  placeholder="Optional"
                  className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
                />
              </Field>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <h2 className="text-sm font-semibold mb-3">Line items</h2>
            {items.length === 0 ? (
              <div className="text-center py-6 text-sm text-slate-500">
                No items yet — add products from the right panel
              </div>
            ) : (
              <div className="space-y-2">
                {items.map((it, idx) => (
                  <div key={it.product_id} className="grid grid-cols-12 gap-2 items-center p-2.5 border border-slate-200 dark:border-slate-700 rounded-lg">
                    <div className="col-span-6">
                      <div className="font-mono text-xs text-slate-500">{it.product_sku}</div>
                      <div className="text-sm font-medium truncate">{it.product_name || it.product_id}</div>
                    </div>
                    <div className="col-span-2">
                      <input
                        type="number"
                        min="1"
                        value={it.quantity}
                        onChange={e => updateItem(idx, { quantity: parseInt(e.target.value) || 1 })}
                        className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
                      />
                    </div>
                    <div className="col-span-3">
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={it.unit_price}
                        onChange={e => updateItem(idx, { unit_price: parseFloat(e.target.value) || 0 })}
                        className="w-full px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
                      />
                    </div>
                    <div className="col-span-1 flex justify-end">
                      <button onClick={() => removeItem(idx)} className="p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 rounded">
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Product picker */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 h-fit lg:sticky lg:top-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Add product</h2>
            {products?.total > 0 && (
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                title="Products with at least 2 active suppliers — these can actually trigger a bid war"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                {products.total} bid-eligible
              </span>
            )}
          </div>
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="search"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              placeholder="Search by name or SKU…"
              className="w-full pl-10 pr-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </div>
          <div className="max-h-96 overflow-y-auto -mx-2">
            {filteredProducts.length === 0 ? (
              <div className="p-4 text-center text-xs text-slate-500">No products</div>
            ) : filteredProducts.map(p => (
              <button
                key={p.id}
                onClick={() => addItem(p)}
                className="w-full text-left px-2 py-2 hover:bg-slate-50 dark:hover:bg-slate-800 rounded text-xs"
              >
                <div className="flex items-center justify-between">
                  <div className="font-mono text-slate-500">{p.sku}</div>
                  <div className="flex items-center gap-1.5">
                    <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                      {p.supplier_count}<span className="opacity-60">bidders</span>
                    </span>
                    <Plus className="w-3 h-3 text-blue-500" />
                  </div>
                </div>
                <div className="text-sm font-medium truncate">{p.name}</div>
                <div className="text-slate-500">{p.currency} {parseFloat(p.unit_price).toFixed(2)}</div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Sticky footer */}
      <div className="mt-6 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-xs text-slate-500">Subtotal</div>
          <div className="text-2xl font-bold">USD {subtotal.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
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
