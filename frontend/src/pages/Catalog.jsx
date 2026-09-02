import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Filter,
  Loader2,
  Package,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'

import { apiGet } from '../api/client'
import { cacheProducts } from '../offline/db'
import { useNetworkStore } from '../store/network'

export default function CatalogPage() {
  const [q, setQ] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [inStock, setInStock] = useState(true)
  const [sort, setSort] = useState('relevance')
  const [page, setPage] = useState(1)
  const limit = 50

  const queryClient = useQueryClient()
  const { online } = useNetworkStore()

  const { data: categories } = useQuery({
    queryKey: ['catalog', 'categories'],
    queryFn: () => apiGet('/catalog/categories'),
    staleTime: 5 * 60_000,
  })

  const { data, isFetching, isError, error } = useQuery({
    queryKey: ['catalog', 'search', { q, categoryId, inStock, sort, page, limit }],
    queryFn: () => apiGet('/catalog/products', {
      query: { q, category_id: categoryId, in_stock: inStock || undefined, sort, limit, offset: (page - 1) * limit },
    }),
    enabled: online,
    placeholderData: (prev) => prev,
  })

  // Cache last viewed batch to IndexedDB so it's available offline
  useEffect(() => {
    if (data?.items?.length) {
      cacheProducts(data.items)
    }
  }, [data])

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const items = data?.items || []

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Product Catalog</h1>
          <p className="text-slate-500 text-sm">
            Search the IMPA/ISSA catalog of {(total || 0).toLocaleString()} marine products
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data?.took_ms !== undefined && (
            <span className="text-xs text-slate-500">
              {data.took_ms}ms
            </span>
          )}
        </div>
      </header>

      {/* Search bar */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 mb-4">
        <div className="flex flex-col lg:flex-row gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="search"
              value={q}
              onChange={e => { setQ(e.target.value); setPage(1) }}
              placeholder="Search by name, SKU, IMPA, ISSA, manufacturer…"
              className="w-full pl-10 pr-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {q && (
              <button onClick={() => setQ('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          <select
            value={categoryId}
            onChange={e => { setCategoryId(e.target.value); setPage(1) }}
            className="px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
          >
            <option value="">All categories</option>
            {(categories || []).map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>

          <select
            value={sort}
            onChange={e => setSort(e.target.value)}
            className="px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
          >
            <option value="relevance">Relevance</option>
            <option value="name">Name (A→Z)</option>
            <option value="price_asc">Price (low→high)</option>
            <option value="price_desc">Price (high→low)</option>
            <option value="newest">Newest</option>
          </select>

          <label className="flex items-center gap-2 px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={inStock}
              onChange={e => setInStock(e.target.checked)}
              className="rounded"
            />
            In stock only
          </label>
        </div>
      </div>

      {/* Results */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        {isError ? (
          <ErrorState error={error} />
        ) : isFetching && !data ? (
          <div className="p-12 text-center text-slate-500">
            <Loader2 className="w-6 h-6 animate-spin inline-block" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left font-semibold w-32">SKU</th>
                    <th className="px-4 py-3 text-left font-semibold">Name</th>
                    <th className="px-4 py-3 text-left font-semibold w-32">IMPA</th>
                    <th className="px-4 py-3 text-left font-semibold w-32">ISSA</th>
                    <th className="px-4 py-3 text-right font-semibold w-32">Unit Price</th>
                    <th className="px-4 py-3 text-center font-semibold w-24">Stock</th>
                    <th className="px-4 py-3 text-center font-semibold w-24">Lead</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(p => (
                    <tr key={p.id} className="border-t border-slate-100 dark:border-slate-800 data-grid-row">
                      <td className="px-4 py-2.5 font-mono text-xs">
                        <Link to={`/catalog/${p.id}`} className="text-blue-600 hover:underline">
                          {p.sku}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5">
                        <Link to={`/catalog/${p.id}`} className="font-medium text-slate-900 dark:text-white hover:text-blue-600">
                          {p.name}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-slate-500">
                        {p.impa_code_id ? '✓' : '—'}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-slate-500">
                        {p.issa_code_id ? '✓' : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium">
                        {p.currency} {parseFloat(p.unit_price).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        {p.in_stock ? (
                          <span className="inline-flex items-center gap-1 text-emerald-600">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            <span className="text-xs">{p.stock_qty}</span>
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">Out</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-center text-xs text-slate-500">
                        {p.lead_time_days}d
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />
          </>
        )}
      </div>
    </div>
  )
}

function Pagination({ page, totalPages, total, onChange }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-800 text-sm">
      <div className="text-slate-500">
        Showing page <span className="font-medium text-slate-700 dark:text-slate-300">{page}</span> of {totalPages}
        {' · '}
        <span className="font-medium text-slate-700 dark:text-slate-300">{total.toLocaleString()}</span> products
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(Math.max(1, page - 1))}
          disabled={page === 1}
          className="p-1.5 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-50 hover:bg-slate-50 dark:hover:bg-slate-800"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <button
          onClick={() => onChange(Math.min(totalPages, page + 1))}
          disabled={page === totalPages}
          className="p-1.5 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-50 hover:bg-slate-50 dark:hover:bg-slate-800"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="p-12 text-center">
      <Package className="w-10 h-10 text-slate-300 mx-auto mb-3" />
      <p className="text-slate-500">No products match your filters.</p>
    </div>
  )
}

function ErrorState({ error }) {
  return (
    <div className="p-12 text-center">
      <p className="text-rose-500 text-sm">{error?.message || 'Failed to load'}</p>
    </div>
  )
}
