/**
 * Marketplace Simulator — the bid-war view.
 *
 * Lives at /market-sim (and deep-links to /market-sim/:rfqId). Lets a
 * purchasing officer hit a button to spin up a sim, watch the bid
 * war unfold as a timeline, see the ranked leaderboard with subscore
 * breakdown, understand "why this winner" via the weighted-stack bar,
 * play with the what-if weight sliders (which re-runs the same sim
 * with different weights — but in this MVP we re-fetch), and trigger
 * a round-2 counter-offer that re-bids in-contention suppliers.
 *
 * Mirrors the visual language of the rest of the app: rounded-xl
 * cards, slate borders, dark-mode aware, lucide-react icons.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import {
  BriefcaseBusiness,
  ChevronDown,
  ChevronRight,
  Crown,
  Gavel,
  Hand,
  Loader2,
  Play,
  RotateCw,
  Sliders,
  Sparkles,
  Trophy,
  Zap,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { apiGet, apiPost } from '../api/client'
import { runMarketSim } from '../api/marketSim'

// Stable palette for supplier chips (round-robin).
const SUPPLIER_COLORS = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ec4899', // pink
  '#8b5cf6', // violet
  '#14b8a6', // teal
  '#f43f5e', // rose
  '#84cc16', // lime
  '#0ea5e9', // sky
  '#a855f7', // purple
]

const STRATEGY_BADGE = {
  aggressive:      { label: 'Aggressive',  color: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300' },
  balanced:        { label: 'Balanced',    color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300' },
  premium:         { label: 'Premium',     color: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300' },
  slow_but_cheap:  { label: 'Slow/Cheap',  color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' },
}

const EVENT_ICONS = {
  run_start:    Play,
  bid_arrived:  Gavel,
  round_close:  Trophy,
  counter_offer: Hand,
  run_end:      Sparkles,
}

const DEFAULT_WEIGHTS = { price: 0.4, lead_time: 0.2, reliability: 0.2, quality: 0.2 }

export default function MarketSimPage() {
  const { rfqId: urlRfqId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  // Pull the list of open RFQs so the user can pick one (or pick
  // from the URL deep-link). We bias the dropdown to "open" status
  // Pull the list of RFQs so the user can pick one (or pick from the
  // URL deep-link). We surface anything that can be bid on: real RFQs
  // start in "sent", and the sim auto-promotes closed/awarded to "open".
  // The only statuses that mean "no bids possible" are cancelled and
  // expired, which we exclude.
  const { data: rfqs, isLoading: rfqsLoading } = useQuery({
    queryKey: ['rfqs-for-sim'],
    queryFn: () => apiGet('/rfq', { query: { limit: 50 } }),
  })
  const openRfqs = useMemo(
    () => (rfqs || []).filter(r => r.status !== 'cancelled' && r.status !== 'expired'),
    [rfqs]
  )

  const [selectedRfqId, setSelectedRfqId] = useState(urlRfqId || '')
  useEffect(() => {
    if (urlRfqId) setSelectedRfqId(urlRfqId)
  }, [urlRfqId])

  const [weights, setWeights] = useState(DEFAULT_WEIGHTS)
  const [counterOpen, setCounterOpen] = useState(false)
  const [counterTerms, setCounterTerms] = useState({ lead_days: 3, price_cap: '' })

  // Re-runnable on demand. We don't auto-poll: a sim is a deliberate
  // user action.
  const sim = useMutation({
    mutationFn: (opts) => runMarketSim(selectedRfqId, {
      seed: 42,
      weights,
      ...opts,
    }),
    onSuccess: (data) => {
      toast.success(`Round ${data.round} complete — ${data.results.length} bid${data.results.length === 1 ? '' : 's'}`)
      qc.invalidateQueries({ queryKey: ['market-sim', selectedRfqId] })
    },
    onError: (e) => toast.error(e.message || 'Sim failed'),
  })

  const result = sim.data
  const results = result?.results || []
  const events = result?.events || []
  const winner = results.find(r => r.supplier_id === result?.winner)
  const roundN = result?.round

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto space-y-4">
      {/* ============ Header ============ */}
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BriefcaseBusiness className="w-6 h-6" />
            Marketplace Simulator
          </h1>
          <p className="text-slate-500 text-sm">
            Spin up a sim bid war on an open RFQ. Same supplier pool, deterministic per seed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedRfqId}
            onChange={e => {
              setSelectedRfqId(e.target.value)
              if (e.target.value) navigate(`/market-sim/${e.target.value}`)
            }}
            className="px-3 py-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-sm min-w-[280px]"
          >
            <option value="">Pick an RFQ…</option>
            {openRfqs.map(r => (
              <option key={r.id} value={r.id}>
                {r.reference} — {r.order_reference}
              </option>
            ))}
          </select>
          <button
            onClick={() => sim.mutate({})}
            disabled={!selectedRfqId || sim.isPending}
            className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            {sim.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {result ? 'Re-run' : 'Run simulation'}
          </button>
          {result && (
            <button
              onClick={() => setCounterOpen(true)}
              className="px-4 py-2.5 bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium rounded-lg inline-flex items-center gap-2"
            >
              <Hand className="w-4 h-4" /> Counter-offer
            </button>
          )}
        </div>
      </header>

      {!selectedRfqId && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center text-slate-500">
          <BriefcaseBusiness className="w-10 h-10 mx-auto mb-3 text-slate-300" />
          <p>Pick an RFQ above to run a marketplace sim.</p>
          {rfqsLoading && <p className="text-xs mt-1">Loading RFQs…</p>}
          {openRfqs.length === 0 && !rfqsLoading && (
            <p className="text-xs mt-2 text-slate-400">
              No open RFQs yet. Go to <a href="/rfq" className="text-blue-600 underline">RFQ & Bidding</a> and create one.
            </p>
          )}
        </div>
      )}

      {selectedRfqId && !result && !sim.isPending && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center text-slate-500">
          <Play className="w-10 h-10 mx-auto mb-3 text-slate-300" />
          <p>Click <b>Run simulation</b> to spin up the bid war.</p>
        </div>
      )}

      {sim.isPending && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center text-slate-500">
          <Loader2 className="w-10 h-10 mx-auto mb-3 text-blue-400 animate-spin" />
          <p>Simulating bid war…</p>
        </div>
      )}

      {result && (
        <>
          {/* Status pill row */}
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2.5 py-1 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200 font-semibold inline-flex items-center gap-1">
              <RotateCw className="w-3 h-3" /> Round {roundN}
            </span>
            <span className={`px-2.5 py-1 rounded-full font-semibold ${
              result.dry_run
                ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200'
                : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200'
            }`}>
              {result.dry_run ? 'Dry run (ephemeral)' : 'Committed'}
            </span>
            <span className="px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 font-semibold">
              {results.length} bid{results.length === 1 ? '' : 's'}
            </span>
            {winner && (
              <span className="px-2.5 py-1 rounded-full bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200 font-semibold inline-flex items-center gap-1">
                <Crown className="w-3 h-3" /> Winner: {winner.supplier_name}
              </span>
            )}
          </div>

          {/* ============ 1. Bid-war timeline ============ */}
          <BidWarTimeline events={events} results={results} />

          {/* ============ 2. Leaderboard + subscores ============ */}
          <Leaderboard results={results} winnerId={result.winner} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* ============ 3. Why this winner ============ */}
            <WhyThisWinner
              winner={winner}
              weights={result.weights || weights}
            />

            {/* ============ 4. What-if weight sliders ============ */}
            <WhatIfSliders
              weights={weights}
              onChange={setWeights}
              onApply={() => sim.mutate({ weights })}
              isPending={sim.isPending}
            />
          </div>

          {/* ============ 5. Price × lead-time scatter ============ */}
          <PriceLeadScatter results={results} winnerId={result.winner} />
        </>
      )}

      {/* ============ Counter-offer modal ============ */}
      {counterOpen && (
        <CounterOfferModal
          initialLead={counterTerms.lead_days}
          initialPriceCap={counterTerms.price_cap}
          onClose={() => setCounterOpen(false)}
          onSubmit={({ lead_days, price_cap }) => {
            const terms = {}
            if (lead_days) terms.lead_days = Number(lead_days)
            // price_cap is a free-text per-product cap, optional; we
            // support a single cap for the demo (multi-product would
            // need a row per item).
            sim.mutate({ counter_offer_terms: terms })
            setCounterOpen(false)
          }}
        />
      )}
    </div>
  )
}

// =====================================================================
// Sub-components
// =====================================================================

function BidWarTimeline({ events, results }) {
  // Build a supplier-id → color lookup.
  const colorBySupplier = useMemo(() => {
    const m = {}
    results.forEach((r, i) => { m[r.supplier_id] = SUPPLIER_COLORS[i % SUPPLIER_COLORS.length] })
    return m
  }, [results])

  if (!events?.length) {
    return null
  }
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <Zap className="w-4 h-4" /> Bid-war timeline
      </h2>
      <ol className="space-y-1.5">
        {events.map((e, i) => {
          const Icon = EVENT_ICONS[e.event_type] || ChevronRight
          const color = e.supplier_id ? colorBySupplier[e.supplier_id] : '#64748b'
          const isBid = e.event_type === 'bid_arrived'
          const strategy = isBid ? STRATEGY_BADGE[e.payload?.strategy] : null
          return (
            <li
              key={e.id || i}
              className="flex items-start gap-3 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <div
                className="mt-0.5 w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-semibold flex-shrink-0"
                style={{ backgroundColor: color }}
              >
                <Icon className="w-3.5 h-3.5" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-mono text-slate-500">
                    {new Date(e.ts).toLocaleTimeString()}
                  </span>
                  <span className="text-xs font-semibold capitalize">
                    {e.event_type.replace('_', ' ')}
                  </span>
                  {e.supplier_id && (
                    <span className="text-xs text-slate-600 dark:text-slate-300 truncate">
                      {results.find(r => r.supplier_id === e.supplier_id)?.supplier_name || e.supplier_id.slice(0, 8)}
                    </span>
                  )}
                  {strategy && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${strategy.color}`}>
                      {strategy.label}
                    </span>
                  )}
                </div>
                {isBid && (
                  <div className="text-xs text-slate-500 mt-0.5">
                    ${Number(e.payload?.adjusted_total || 0).toFixed(2)} · {e.payload?.lead_time_days}d lead
                  </div>
                )}
                {e.event_type === 'counter_offer' && (
                  <div className="text-xs text-slate-500 mt-0.5">
                    {JSON.stringify(e.payload)}
                  </div>
                )}
                {e.event_type === 'round_close' && (
                  <div className="text-xs text-slate-500 mt-0.5">
                    {e.payload?.results?.length || 0} bid{e.payload?.results?.length === 1 ? '' : 's'} scored
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Leaderboard({ results, winnerId }) {
  if (!results?.length) return null
  // Subscore bar data: one row per supplier, with 4 stacked fields.
  const chartData = results.map(r => ({
    name: r.supplier_name,
    price: r.subscores?.price ?? 0,
    lead_time: r.subscores?.lead_time ?? 0,
    reliability: r.subscores?.reliability ?? 0,
    quality: r.subscores?.quality ?? 0,
    score: r.score,
    isWinner: r.supplier_id === winnerId,
  }))

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <Trophy className="w-4 h-4" /> Leaderboard
      </h2>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500">
                <th className="px-2 py-2 text-left font-semibold">#</th>
                <th className="px-2 py-2 text-left font-semibold">Supplier</th>
                <th className="px-2 py-2 text-right font-semibold">Total</th>
                <th className="px-2 py-2 text-right font-semibold">Lead</th>
                <th className="px-2 py-2 text-right font-semibold">Score</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr
                  key={r.supplier_id}
                  className={`border-t border-slate-100 dark:border-slate-800 ${
                    r.supplier_id === winnerId
                      ? 'bg-violet-50 dark:bg-violet-900/20'
                      : ''
                  }`}
                >
                  <td className="px-2 py-2 text-slate-400 font-mono text-xs">{i + 1}</td>
                  <td className="px-2 py-2 font-medium">
                    {r.supplier_id === winnerId && (
                      <Crown className="w-3.5 h-3.5 inline-block mr-1 text-amber-500" />
                    )}
                    {r.supplier_name}
                  </td>
                  <td className="px-2 py-2 text-right font-mono">${Number(r.total).toFixed(2)}</td>
                  <td className="px-2 py-2 text-right text-slate-500">{r.lead_time_days}d</td>
                  <td className="px-2 py-2 text-right font-mono font-semibold">
                    {Number(r.score).toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="lg:col-span-2 h-64">
          <ResponsiveContainer>
            <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 30, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" domain={[0, 1]} tick={{ fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                width={120}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{ fontSize: 12 }}
                formatter={(v, k) => [Number(v).toFixed(3), k]}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="price"        stackId="a" fill="#3b82f6" />
              <Bar dataKey="lead_time"    stackId="a" fill="#10b981" />
              <Bar dataKey="reliability"  stackId="a" fill="#f59e0b" />
              <Bar dataKey="quality"      stackId="a" fill="#ec4899" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

function WhyThisWinner({ winner, weights }) {
  if (!winner) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Crown className="w-4 h-4" /> Why this winner
        </h2>
        <p className="text-sm text-slate-500">No winner yet — run a sim first.</p>
      </div>
    )
  }
  const w = weights || DEFAULT_WEIGHTS
  // The actual contribution: weight × subscore.
  const contributions = [
    { k: 'Price',       v: w.price * (winner.subscores?.price ?? 0),       color: '#3b82f6' },
    { k: 'Lead time',   v: w.lead_time * (winner.subscores?.lead_time ?? 0), color: '#10b981' },
    { k: 'Reliability', v: w.reliability * (winner.subscores?.reliability ?? 0), color: '#f59e0b' },
    { k: 'Quality',     v: w.quality * (winner.subscores?.quality ?? 0),     color: '#ec4899' },
  ]
  const total = contributions.reduce((s, c) => s + c.v, 0)

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <Crown className="w-4 h-4" /> Why {winner.supplier_name} won
      </h2>
      <p className="text-xs text-slate-500 mb-3">
        Score = Σ (weight × subscore). The current weights sum to{' '}
        {Object.values(w).reduce((s, v) => s + Number(v || 0), 0).toFixed(2)}.
      </p>
      <div className="space-y-2">
        {contributions.map(c => (
          <div key={c.k} className="flex items-center gap-2 text-xs">
            <div className="w-24 text-slate-600 dark:text-slate-300">{c.k}</div>
            <div className="flex-1 h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${(c.v / Math.max(total, 1e-9)) * 100}%`,
                  backgroundColor: c.color,
                }}
              />
            </div>
            <div className="w-20 text-right font-mono">
              {c.v.toFixed(3)}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-sm">
        <span className="text-slate-500">Total score</span>
        <span className="font-mono font-semibold">{Number(winner.score).toFixed(4)}</span>
      </div>
    </div>
  )
}

function WhatIfSliders({ weights, onChange, onApply, isPending }) {
  const sum = Object.values(weights).reduce((s, v) => s + Number(v || 0), 0)
  const setW = (k, v) => onChange({ ...weights, [k]: Number(v) })

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <Sliders className="w-4 h-4" /> What-if weights
        <span className={`ml-auto text-xs ${Math.abs(sum - 1) < 0.01 ? 'text-emerald-600' : 'text-amber-600'}`}>
          Σ = {sum.toFixed(2)}
        </span>
      </h2>
      <div className="space-y-2.5">
        {[
          { k: 'price',       label: 'Price' },
          { k: 'lead_time',   label: 'Lead time' },
          { k: 'reliability', label: 'Reliability' },
          { k: 'quality',     label: 'Quality' },
        ].map(({ k, label }) => (
          <div key={k} className="flex items-center gap-3 text-xs">
            <div className="w-24 text-slate-600 dark:text-slate-300">{label}</div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={weights[k]}
              onChange={e => setW(k, e.target.value)}
              className="flex-1 accent-blue-600"
            />
            <div className="w-12 text-right font-mono">{Number(weights[k]).toFixed(2)}</div>
          </div>
        ))}
      </div>
      <button
        onClick={onApply}
        disabled={isPending}
        className="mt-4 w-full px-3 py-2 bg-slate-900 hover:bg-slate-800 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center justify-center gap-2"
      >
        {isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
        Re-rank with these weights
      </button>
    </div>
  )
}

function PriceLeadScatter({ results, winnerId }) {
  if (!results?.length) return null
  const data = results.map(r => ({
    name: r.supplier_name,
    x: Number(r.total),
    y: r.lead_time_days,
    z: (r.subscores?.reliability ?? 0) * 100,
    isWinner: r.supplier_id === winnerId,
  }))
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3">Price × lead-time scatter</h2>
      <div className="h-72">
        <ResponsiveContainer>
          <ScatterChart margin={{ left: 20, right: 20, top: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              type="number"
              dataKey="x"
              name="Total"
              tickFormatter={(v) => `$${v.toFixed(0)}`}
              tick={{ fontSize: 11 }}
              label={{ value: 'Total ($)', position: 'insideBottom', offset: -5, fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="Lead"
              unit="d"
              tick={{ fontSize: 11 }}
              label={{ value: 'Lead (days)', angle: -90, position: 'insideLeft', fontSize: 11 }}
            />
            <ZAxis type="number" dataKey="z" range={[60, 400]} />
            <Tooltip
              contentStyle={{ fontSize: 12 }}
              formatter={(v, k) => k === 'x' ? [`$${Number(v).toFixed(2)}`, 'Total'] : [v, k]}
              labelFormatter={(_, payload) => payload?.[0]?.payload?.name}
            />
            <Scatter data={data}>
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.isWinner ? '#a855f7' : '#3b82f6'}
                  fillOpacity={d.isWinner ? 1 : 0.6}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-slate-500 mt-1">
        Purple = winner. Bubble size = reliability subscore.
      </p>
    </div>
  )
}

function CounterOfferModal({ initialLead, initialPriceCap, onClose, onSubmit }) {
  const [leadDays, setLeadDays] = useState(initialLead || '')
  const [priceCap, setPriceCap] = useState(initialPriceCap || '')

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl w-full max-w-md p-5">
        <h2 className="text-base font-bold mb-1">Counter-offer</h2>
        <p className="text-xs text-slate-500 mb-4">
          Squeeze the round-1 contenders into a round-2 re-bid. Lead-time cap is the most
          useful in the demo.
        </p>
        <div className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-600 dark:text-slate-300">New lead-time target (days)</span>
            <input
              type="number"
              min="1"
              value={leadDays}
              onChange={e => setLeadDays(e.target.value)}
              className="mt-1 w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600 dark:text-slate-300">Price cap (optional, single product)</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={priceCap}
              onChange={e => setPriceCap(e.target.value)}
              className="mt-1 w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
            />
          </label>
        </div>
        <div className="flex items-center justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            className="px-3 py-2 text-sm text-slate-600 hover:text-slate-900"
          >
            Cancel
          </button>
          <button
            onClick={() => onSubmit({ lead_days: leadDays, price_cap: priceCap })}
            disabled={!leadDays && !priceCap}
            className="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium rounded-lg disabled:opacity-50 inline-flex items-center gap-2"
          >
            <Hand className="w-4 h-4" /> Send counter-offer
          </button>
        </div>
      </div>
    </div>
  )
}
