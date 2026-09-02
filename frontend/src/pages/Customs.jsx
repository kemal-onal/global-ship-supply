import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Shield, ShieldAlert, ShieldCheck, Loader2, FileText } from 'lucide-react'

import { apiGet } from '../api/client'

const SEVERITY_COLORS = {
  info: 'bg-slate-100 text-slate-700',
  warning: 'bg-amber-100 text-amber-700',
  restricted: 'bg-orange-100 text-orange-700',
  prohibited: 'bg-rose-100 text-rose-700',
  blocking: 'bg-rose-600 text-white',
}

export default function CustomsPage() {
  const { data: countries } = useQuery({
    queryKey: ['customs', 'countries'],
    queryFn: () => apiGet('/customs/countries', { query: { limit: 100 } }),
  })
  const { data: rules } = useQuery({
    queryKey: ['customs', 'rules'],
    queryFn: () => apiGet('/customs/rules', { query: { limit: 100 } }),
  })
  const { data: ports } = useQuery({
    queryKey: ['customs', 'ports'],
    queryFn: () => apiGet('/ports', { query: { limit: 200 } }),
  })

  const [selectedCountry, setSelectedCountry] = useState('')
  const [selectedPort, setSelectedPort] = useState('')

  const countryRules = (rules || []).filter(r => !selectedCountry || r.country_code === selectedCountry)
  const filteredPorts = (ports || []).filter(p => !selectedCountry || p.country === selectedCountry)

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Shield className="w-6 h-6" /> Customs & port regulations
        </h1>
        <p className="text-slate-500 text-sm">
          Country-level import rules, restricted items, and permit requirements
        </p>
      </header>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">Filter by country</label>
            <select
              value={selectedCountry}
              onChange={e => setSelectedCountry(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            >
              <option value="">All countries</option>
              {(countries || []).map(c => (
                <option key={c.code} value={c.code}>{c.name} ({c.code})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">Filter by port</label>
            <select
              value={selectedPort}
              onChange={e => setSelectedPort(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            >
              <option value="">All ports</option>
              {filteredPorts.map(p => (
                <option key={p.id} value={p.id}>{p.name} ({p.unlocode})</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Rules */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
          <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <FileText className="w-4 h-4" /> Rules
            </h2>
            <span className="text-xs text-slate-500">{countryRules.length} rules</span>
          </div>
          <div className="max-h-[600px] overflow-y-auto p-2 space-y-2">
            {countryRules.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">No rules for this country</div>
            ) : countryRules.map(r => (
              <div key={r.id} className="p-3 border border-slate-200 dark:border-slate-700 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-1.5 py-0.5 text-[10px] font-semibold rounded ${SEVERITY_COLORS[r.severity] || 'bg-slate-100 text-slate-700'}`}>
                    {r.severity}
                  </span>
                  <span className="text-xs font-mono text-slate-500">{r.country_code}</span>
                </div>
                <div className="text-sm font-medium">{r.name}</div>
                <p className="text-xs text-slate-500 mt-1">{r.description}</p>
                {r.requires_permit && (
                  <p className="text-xs text-amber-600 mt-1">⚠ Permit required — {r.permit_authority || 'see port authority'}</p>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Port regulations */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
          <div className="p-5 border-b border-slate-200 dark:border-slate-800">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <ShieldCheck className="w-4 h-4" /> Port-specific notes
            </h2>
          </div>
          <div className="max-h-[600px] overflow-y-auto p-2 space-y-2">
            {filteredPorts.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">No ports</div>
            ) : filteredPorts.map(p => (
              <div key={p.id} className="p-3 border border-slate-200 dark:border-slate-700 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-sm">{p.name}</div>
                    <div className="text-xs text-slate-500 font-mono">{p.unlocode} · {p.country_name}</div>
                  </div>
                  <div className="flex items-center gap-1">
                    {p.has_bunkering && <span title="Bunkering">⛽</span>}
                    {p.has_fresh_water && <span title="Fresh water">💧</span>}
                    {p.has_provisions && <span title="Provisions">🥕</span>}
                    {p.has_repair && <span title="Repair">🔧</span>}
                    {p.has_medical && <span title="Medical">➕</span>}
                  </div>
                </div>
                {p.notes && (
                  <p className="text-xs text-slate-500 mt-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                    {p.notes}
                  </p>
                )}
                {p.requires_advance_notice_hours && (
                  <p className="text-xs text-amber-600 mt-1">
                    ⚠ Advance notice: {p.requires_advance_notice_hours}h
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl text-sm text-blue-900 dark:text-blue-200">
        <ShieldAlert className="w-4 h-4 inline mr-1.5" />
        Every order you create is automatically evaluated against these rules. Violations appear in
        the order detail page; <strong>blocking</strong> issues prevent RFQ creation.
      </div>
    </div>
  )
}
