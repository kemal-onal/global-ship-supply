import { useQuery } from '@tanstack/react-query'
import { Ship, Users, MapPin, Loader2 } from 'lucide-react'

import { apiGet } from '../api/client'

export default function VesselsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['vessels'],
    queryFn: () => apiGet('/vessels'),
  })

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Vessels</h1>
        <p className="text-slate-500 text-sm">Fleet overview and current assignments</p>
      </header>

      {isLoading ? (
        <div className="p-12 text-center">
          <Loader2 className="w-6 h-6 animate-spin inline-block" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(data || []).map(v => (
            <div key={v.id} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                    <Ship className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <div className="font-semibold">{v.name}</div>
                    <div className="text-xs text-slate-500 font-mono">IMO {v.imo_number}</div>
                  </div>
                </div>
                <span className={`text-[11px] px-2 py-0.5 rounded-full ${
                  v.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
                }`}>
                  {v.status}
                </span>
              </div>
              <div className="mt-4 space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 flex items-center gap-1.5"><Users className="w-3.5 h-3.5" /> Crew</span>
                  <span className="font-medium">{v.current_crew_count}/{v.crew_capacity}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Type</span>
                  <span className="font-medium capitalize">{v.vessel_type.replace(/_/g, ' ')}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Flag</span>
                  <span className="font-medium">{v.flag_state || '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Owner</span>
                  <span className="font-medium truncate max-w-[140px]">{v.owner || '—'}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
