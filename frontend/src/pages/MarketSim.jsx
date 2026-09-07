/**
 * Marketplace Simulator — the sealed-bid auction.
 *
 * The marketplace redesign replaced this flow. The bid-war engine
 * (backend/app/services/market_sim.py) is still importable for the
 * 309 existing tests; the UI page at /market-sim is gone.
 *
 * This stub stays so anyone navigating to /market-sim sees a clear
 * pointer to the new page rather than a 404. The full original
 * implementation is preserved as `MarketSim.jsx.removed` for any
 * future "compare the two" demo.
 */
import { ArrowRight, BriefcaseBusiness, Truck, Gavel } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/auth'

export default function MarketSimPage() {
  const hasRole = useAuthStore((s) => s.hasRole)
  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-2xl mx-auto">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-8 text-center">
        <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-4">
          <BriefcaseBusiness className="w-6 h-6 text-slate-400" />
        </div>
        <h1 className="text-xl font-bold mb-2">This page has been removed</h1>
        <p className="text-sm text-slate-500 mb-6">
          The sealed-bid auction has been replaced by the marketplace
          redesign: fan-out, per-line decisions, 24h supplier
          acceptance window. The new flow ships at{' '}
          <span className="font-mono">/marketplace</span> (company) and{' '}
          <span className="font-mono">/supplier</span> (suppliers).
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-md mx-auto">
          {hasRole('super_admin', 'fleet_admin') ? (
            <Link
              to="/marketplace"
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg"
            >
              <Gavel className="w-4 h-4" /> Open Marketplace
              <ArrowRight className="w-4 h-4" />
            </Link>
          ) : null}
          {hasRole('supplier') ? (
            <Link
              to="/supplier"
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg"
            >
              <Truck className="w-4 h-4" /> Open Supplier Portal
              <ArrowRight className="w-4 h-4" />
            </Link>
          ) : null}
        </div>
        <p className="text-[11px] text-slate-400 mt-6">
          The bid-war engine remains in{' '}
          <code className="font-mono">app/services/market_sim.py</code>.
          The original page is at{' '}
          <code className="font-mono">MarketSim.jsx.removed</code>.
        </p>
      </div>
    </div>
  )
}
