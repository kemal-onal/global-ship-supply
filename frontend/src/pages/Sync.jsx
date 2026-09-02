import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Wifi, WifiOff, AlertCircle, CheckCircle, Clock, Loader2 } from 'lucide-react'

import { apiGet } from '../api/client'
import { useNetworkStore } from '../store/network'
import { getPendingActions } from '../offline/db'

export default function SyncPage() {
  const { online, vsatQuality, lastSyncAt, pendingCount } = useNetworkStore()
  const { data: queue, isLoading } = useQuery({
    queryKey: ['sync', 'queue'],
    queryFn: () => apiGet('/sync/queue'),
    enabled: online,
    refetchInterval: 10000,
  })
  const { data: conflicts } = useQuery({
    queryKey: ['sync', 'conflicts'],
    queryFn: () => apiGet('/sync/conflicts'),
    enabled: online,
  })

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-5xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <RefreshCw className="w-6 h-6" /> Synchronization
        </h1>
        <p className="text-slate-500 text-sm">
          Offline queue, replay status, and conflict resolution
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <Card
          icon={online ? <Wifi className="w-4 h-4 text-emerald-500" /> : <WifiOff className="w-4 h-4 text-rose-500" />}
          label="Connection"
          value={online ? 'Online' : 'Offline'}
          sub={online ? `VSAT quality: ${vsatQuality}` : 'No network'}
        />
        <Card
          icon={<Clock className="w-4 h-4" />}
          label="Last sync"
          value={lastSyncAt ? new Date(lastSyncAt).toLocaleString() : 'Never'}
          sub="Local replay completed"
        />
        <Card
          icon={<AlertCircle className={`w-4 h-4 ${pendingCount > 0 ? 'text-amber-500' : 'text-slate-300'}`} />}
          label="Pending actions"
          value={pendingCount}
          sub="In IndexedDB queue"
        />
      </div>

      {/* Server-side queue */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden mb-4">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Server queue</h2>
          <p className="text-xs text-slate-500 mt-1">
            Items the server is still processing or has failed to process
          </p>
        </div>
        {!online ? (
          <div className="p-8 text-center text-sm text-slate-500">
            <WifiOff className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            Connect to network to see server queue
          </div>
        ) : isLoading ? (
          <div className="p-12 text-center">
            <Loader2 className="w-6 h-6 animate-spin inline-block" />
          </div>
        ) : (queue || []).length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            <CheckCircle className="w-8 h-8 mx-auto mb-2 text-emerald-400" />
            No pending server actions
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">Resource</th>
                <th className="px-4 py-3 text-left font-semibold">Action</th>
                <th className="px-4 py-3 text-left font-semibold">Status</th>
                <th className="px-4 py-3 text-left font-semibold">Queued at</th>
                <th className="px-4 py-3 text-left font-semibold">Error</th>
              </tr>
            </thead>
            <tbody>
              {queue.map(q => (
                <tr key={q.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-4 py-2.5 font-mono text-xs">{q.resource}</td>
                  <td className="px-4 py-2.5">{q.action}</td>
                  <td className="px-4 py-2.5">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                      q.status === 'completed' ? 'bg-emerald-100 text-emerald-700' :
                      q.status === 'failed' ? 'bg-rose-100 text-rose-700' :
                      'bg-amber-100 text-amber-700'
                    }`}>
                      {q.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 text-xs">
                    {new Date(q.queued_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-rose-500 text-xs">{q.error || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Conflicts */}
      {conflicts && conflicts.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold flex items-center gap-2 text-amber-900 dark:text-amber-200">
            <AlertCircle className="w-4 h-4" />
            {conflicts.length} conflict{conflicts.length === 1 ? '' : 's'} need attention
          </h2>
          <div className="mt-3 space-y-2">
            {conflicts.map(c => (
              <div key={c.id} className="p-3 bg-white dark:bg-slate-900 border border-amber-200 dark:border-amber-800 rounded-lg text-sm">
                <div className="font-mono text-xs">{c.resource}:{c.resource_id}</div>
                <div className="text-xs text-slate-500 mt-1">{c.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Card({ icon, label, value, sub }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}{label}
      </div>
      <div className="text-xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}
