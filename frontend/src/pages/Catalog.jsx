/**
 * Catalog — DEPRECATED stub.
 *
 * The IMPA-first redesign folded the catalog into the order
 * page itself (the IMPA typeahead inside OrderCreate.jsx). The
 * standalone /catalog page is gone — there's no "browse the
 * catalog" step in the new flow. Anyone navigating here gets
 * pointed at the new order page.
 *
 * The full original implementation is preserved as
 * `Catalog.jsx.removed` for reference.
 */
import { ArrowRight, Package, ShoppingCart } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function CatalogPage() {
  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-2xl mx-auto">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-8 text-center">
        <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-4">
          <Package className="w-6 h-6 text-slate-400" />
        </div>
        <h1 className="text-xl font-bold mb-2">Catalog has moved into the order page</h1>
        <p className="text-sm text-slate-500 mb-6">
          The IMPA-first redesign removed the standalone catalog. Instead of
          picking a product from a catalog and adding it to your cart, you now
          type an IMPA code (or pick it from a typeahead) directly in the
          order form. The typeahead is the catalog.
        </p>
        <Link
          to="/orders/new"
          className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg"
        >
          <ShoppingCart className="w-4 h-4" /> Open the order page
          <ArrowRight className="w-4 h-4" />
        </Link>
        <p className="text-[11px] text-slate-400 mt-6">
          The original page is at{' '}
          <code className="font-mono">Catalog.jsx.removed</code>.
        </p>
      </div>
    </div>
  )
}
