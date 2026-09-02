import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  Anchor,
  ArrowUpRight,
  Boxes,
  ClipboardList,
  Package,
  ShieldAlert,
  Ship,
  TrendingUp,
  Truck,
  Users,
  Zap,
} from 'lucide-react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts'

import { apiGet } from '../api/client'

export default function DashboardPage() {
  const { data: overview, isLoading } = useQuery({
    queryKey: ['dashboard', 'overview'],
    queryFn: () => apiGet('/dashboard/overview'),
    refetchInterval: 30_000,
  })
  const { data: recent } = useQuery({
    queryKey: ['dashboard', 'recent'],
    queryFn: () => apiGet('/dashboard/recent-orders', { query: { limit: 8 } }),
  })
  const { data: leaders } = useQuery({
    queryKey: ['dashboard', 'leaders'],
    queryFn: () => apiGet('/dashboard/quote-leaderboard', { query: { limit: 5 } }),
  })

  if (isLoading) return <PageSkeleton />

  const kpis = [
    {
      label: 'Active orders',
      value: (overview?.orders?.by_status?.pending_approval || 0) +
             (overview?.orders?.by_status?.rfq_in_progress || 0) +
             (overview?.orders?.by_status?.bidding || 0) +
             (overview?.orders?.by_status?.awaiting_confirmation || 0) +
             (overview?.orders?.by_status?.confirmed || 0),
      sub: `${overview?.orders?.today || 0} new today`,
      icon: ClipboardList,
      color: 'blue',
    },
    {
      label: 'Vessels in fleet',
      value: overview?.vessels?.active || 0,
      sub: `${overview?.vessels?.total || 0} total registered`,
      icon: Ship,
      color: 'cyan',
    },
    {
      label: 'Catalog products',
      value: (overview?.catalog?.products || 0).toLocaleString(),
      sub: `${overview?.catalog?.out_of_stock || 0} out of stock`,
      icon: Boxes,
      color: 'emerald',
    },
    {
      label: 'RFQ pipeline',
      value: overview?.rfq_pipeline?.open || 0,
      sub: 'Open for bidding',
      icon: Truck,
      color: 'amber',
    },
    {
      label: 'Sync health',
      value: overview?.sync?.pending || 0,
      sub: `${overview?.sync?.failed || 0} failed (24h)`,
      icon: Zap,
      color: 'violet',
    },
    {
      label: 'Security events',
      value: overview?.security?.high_or_critical_24h || 0,
      sub: 'High / critical (24h)',
      icon: ShieldAlert,
      color: 'rose',
    },
  ]

  // Status distribution chart data
  const statusData = Object.entries(overview?.orders?.by_status || {}).map(([s, c]) => ({
    name: s.replace(/_/g, ' '),
    count: c,
  }))

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Operations Overview</h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">
            Real-time picture of your fleet, orders and supply chain
          </p>
        </div>
        <Link
          to="/orders/new"
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg"
        >
          <ClipboardList className="w-4 h-4" /> New order
        </Link>
      </header>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {kpis.map(k => (
          <div key={k.label} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div className={`w-9 h-9 rounded-lg bg-${k.color}-100 dark:bg-${k.color}-900/30 flex items-center justify-center`}>
                <k.icon className={`w-4 h-4 text-${k.color}-600 dark:text-${k.color}-400`} />
              </div>
            </div>
            <div className="mt-3 text-2xl font-bold text-slate-900 dark:text-white">{k.value}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{k.label}</div>
            <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-2">{k.sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Status chart */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Order status distribution</h2>
            <Link to="/orders" className="text-xs text-blue-600 hover:underline flex items-center gap-1">
              View all <ArrowUpRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusData} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: '#0f172a',
                    border: 'none',
                    borderRadius: 8,
                    color: '#f1f5f9',
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top suppliers */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-500" /> Top suppliers
          </h2>
          <div className="space-y-3">
            {(leaders || []).map((s, i) => (
              <div key={s.id} className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-cyan-500 text-white text-xs font-bold flex items-center justify-center">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{s.name}</div>
                  <div className="text-[11px] text-slate-500">
                    ★ {s.rating_overall?.toFixed(1)} · {s.rating_count} reviews · {s.on_time_pct?.toFixed(0)}% on time
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent orders */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Activity className="w-4 h-4 text-blue-500" /> Recent orders
          </h2>
          <Link to="/orders" className="text-xs text-blue-600 hover:underline">All orders →</Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-900/50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-5 py-3 text-left">Reference</th>
                <th className="px-5 py-3 text-left">Vessel</th>
                <th className="px-5 py-3 text-left">Port</th>
                <th className="px-5 py-3 text-left">Status</th>
                <th className="px-5 py-3 text-left">Date</th>
                <th className="px-5 py-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {(recent || []).map(o => (
                <tr key={o.id} className="border-t border-slate-100 dark:border-slate-800 data-grid-row">
                  <td className="px-5 py-3 font-mono text-xs">
                    <Link to={`/orders/${o.id}`} className="text-blue-600 hover:underline">
                      {o.reference}
                    </Link>
                  </td>
                  <td className="px-5 py-3">{o.vessel_name}</td>
                  <td className="px-5 py-3 text-slate-500">{o.port_name}</td>
                  <td className="px-5 py-3">
                    <StatusBadge status={o.status} />
                  </td>
                  <td className="px-5 py-3 text-slate-500 text-xs">
                    {new Date(o.order_date).toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right font-medium">
                    {o.currency} {o.grand_total?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }) {
  const palette = {
    draft: 'bg-slate-100 text-slate-700',
    pending_approval: 'bg-amber-100 text-amber-700',
    rfq_in_progress: 'bg-blue-100 text-blue-700',
    bidding: 'bg-violet-100 text-violet-700',
    awaiting_confirmation: 'bg-cyan-100 text-cyan-700',
    confirmed: 'bg-emerald-100 text-emerald-700',
    in_transit: 'bg-indigo-100 text-indigo-700',
    delivered: 'bg-teal-100 text-teal-700',
    completed: 'bg-emerald-100 text-emerald-700',
    cancelled: 'bg-slate-100 text-slate-500',
    rejected: 'bg-rose-100 text-rose-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${palette[status] || 'bg-slate-100 text-slate-700'}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function PageSkeleton() {
  return (
    <div className="p-8 max-w-7xl mx-auto space-y-4">
      <div className="h-8 w-48 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
      <div className="grid grid-cols-6 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-28 bg-slate-200 dark:bg-slate-800 rounded-xl animate-pulse" />
        ))}
      </div>
    </div>
  )
}
