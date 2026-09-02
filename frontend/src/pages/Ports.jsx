import { useQuery } from '@tanstack/react-query'
import { MapPin, Anchor, Loader2, Wrench, Droplet, Utensils } from 'lucide-react'

import { apiGet } from '../api/client'

export default function PortsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['ports'],
    queryFn: () => apiGet('/ports', { query: { limit: 200 } }),
  })

  if (isLoading) return (
    <div className="p-12 text-center">
      <Loader2 className="w-6 h-6 animate-spin inline-block" />
    </div>
  )

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Ports</h1>
        <p className="text-slate-500 text-sm">Worldwide port network and facilities</p>
      </header>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left font-semibold">UN/LOCODE</th>
              <th className="px-4 py-3 text-left font-semibold">Name</th>
              <th className="px-4 py-3 text-left font-semibold">Country</th>
              <th className="px-4 py-3 text-left font-semibold">Type</th>
              <th className="px-4 py-3 text-center font-semibold">Services</th>
              <th className="px-4 py-3 text-right font-semibold">Max draft</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map(p => (
              <tr key={p.id} className="border-t border-slate-100 dark:border-slate-800 data-grid-row">
                <td className="px-4 py-2.5 font-mono text-xs">{p.unlocode}</td>
                <td className="px-4 py-2.5 font-medium">{p.name}</td>
                <td className="px-4 py-2.5 text-slate-500">{p.country_name}</td>
                <td className="px-4 py-2.5 text-slate-500 capitalize">{p.port_type.replace(/_/g, ' ')}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-1.5 justify-center">
                    {p.has_bunkering && <span title="Bunkering" className="text-amber-500">⛽</span>}
                    {p.has_fresh_water && <span title="Fresh water" className="text-blue-500">💧</span>}
                    {p.has_provisions && <span title="Provisions" className="text-emerald-500">🥕</span>}
                    {p.has_repair && <span title="Repair" className="text-slate-500">🔧</span>}
                    {p.has_medical && <span title="Medical" className="text-rose-500">➕</span>}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-right text-slate-500 text-xs">
                  {p.max_draft ? `${p.max_draft}m` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
