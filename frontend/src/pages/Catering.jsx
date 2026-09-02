import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChefHat, Flame, Loader2, Sparkles, Users } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost } from '../api/client'

export default function CateringPage() {
  const { data: nationalities } = useQuery({
    queryKey: ['catering', 'nationalities'],
    queryFn: () => apiGet('/catering/nationalities'),
  })
  const { data: vessels } = useQuery({
    queryKey: ['vessels', 'list'],
    queryFn: () => apiGet('/vessels'),
  })

  const [vesselId, setVesselId] = useState('')
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    return d.toISOString().slice(0, 10)
  })
  const [endDate, setEndDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() + 14)
    return d.toISOString().slice(0, 10)
  })
  const [crewBreakdown, setCrewBreakdown] = useState({})
  const [plan, setPlan] = useState(null)

  const generate = useMutation({
    mutationFn: () => apiPost('/catering/plan', {
      vessel_id: vesselId,
      start_date: startDate,
      end_date: endDate,
      crew_by_nationality: crewBreakdown,
    }),
    onSuccess: (data) => {
      setPlan(data)
      toast.success('Provisioning plan generated')
    },
    onError: (e) => toast.error(e.message),
  })

  const updateCrew = (code, value) => {
    setCrewBreakdown(prev => ({ ...prev, [code]: parseInt(value) || 0 }))
  }

  const totalCrew = Object.values(crewBreakdown).reduce((s, n) => s + n, 0)

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-6xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ChefHat className="w-6 h-6" /> Catering & provisioning
        </h1>
        <p className="text-slate-500 text-sm">
          Generate voyage provisioning plans with per-nationality calorie targets and menu templates
        </p>
      </header>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
        <h2 className="text-sm font-semibold mb-4">Plan parameters</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">Vessel</label>
            <select
              value={vesselId}
              onChange={e => {
                setVesselId(e.target.value)
                const v = (vessels || []).find(x => x.id === e.target.value)
                if (v) {
                  // seed crew breakdown with one nationality
                  const nat = (nationalities || [])[0]
                  if (nat) setCrewBreakdown({ [nat.code]: v.crew_capacity })
                }
              }}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            >
              <option value="">Select vessel…</option>
              {(vessels || []).map(v => (
                <option key={v.id} value={v.id}>{v.name} ({v.crew_capacity} crew)</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">Voyage start</label>
            <input
              type="date"
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">Voyage end</label>
            <input
              type="date"
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </div>
        </div>

        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold uppercase text-slate-500">Crew by nationality</h3>
            <div className="text-xs text-slate-500 flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5" /> Total: {totalCrew}
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {(nationalities || []).map(n => (
              <div key={n.code} className="p-2 border border-slate-200 dark:border-slate-700 rounded-lg">
                <div className="text-xs font-medium">{n.name}</div>
                <div className="text-[10px] text-slate-500">{n.code} · {n.daily_calorie_target} kcal</div>
                <input
                  type="number"
                  min="0"
                  value={crewBreakdown[n.code] || 0}
                  onChange={e => updateCrew(n.code, e.target.value)}
                  className="w-full mt-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-sm"
                />
              </div>
            ))}
          </div>
        </div>

        <div className="mt-5 flex justify-end">
          <button
            onClick={() => generate.mutate()}
            disabled={!vesselId || totalCrew === 0 || generate.isPending}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            {generate.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            Generate plan
          </button>
        </div>
      </div>

      {plan && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Stat
              icon={<Flame className="w-4 h-4" />}
              label="Total calories"
              value={plan.total_calories?.toLocaleString() || 0}
              sub={`${plan.daily_average?.toLocaleString() || 0} kcal/day`}
            />
            <Stat
              icon={<Users className="w-4 h-4" />}
              label="Crew / days"
              value={`${plan.total_crew} × ${plan.days}`}
              sub={`${totalCrew} active`}
            />
            <Stat
              icon={<ChefHat className="w-4 h-4" />}
              label="Products required"
              value={plan.items?.length || 0}
              sub="SKUs to provision"
            />
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <div className="p-5 border-b border-slate-200 dark:border-slate-800">
              <h2 className="text-sm font-semibold">Provisioning basket</h2>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold">SKU</th>
                  <th className="px-4 py-3 text-left font-semibold">Product</th>
                  <th className="px-4 py-3 text-left font-semibold">Category</th>
                  <th className="px-4 py-3 text-right font-semibold">Total qty</th>
                  <th className="px-4 py-3 text-right font-semibold">Est. cost</th>
                </tr>
              </thead>
              <tbody>
                {(plan.items || []).map((it, idx) => (
                  <tr key={idx} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="px-4 py-2.5 font-mono text-xs">{it.sku}</td>
                    <td className="px-4 py-2.5 font-medium">{it.name}</td>
                    <td className="px-4 py-2.5 text-slate-500 capitalize">{it.category?.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2.5 text-right">{it.quantity} {it.unit}</td>
                    <td className="px-4 py-2.5 text-right">{it.currency} {it.estimated_cost?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-200 dark:border-slate-700">
                  <td colSpan={4} className="px-4 py-3 text-right text-sm font-medium">Total</td>
                  <td className="px-4 py-3 text-right font-bold">
                    USD {plan.items?.reduce((s, it) => s + (it.estimated_cost || 0), 0).toFixed(2)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ icon, label, value, sub }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}{label}
      </div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}
