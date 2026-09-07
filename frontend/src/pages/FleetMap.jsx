/**
 * Live Fleet Map
 *
 * Plots synthetic AIS position reports on a Leaflet map. Polls
 * /api/v1/internal/ais/positions every 5s, groups rows by MMSI, and
 * draws:
 *   - a polyline for each vessel's historical trail
 *   - a circleMarker for each vessel's latest position
 *   - a tooltip on the marker with vessel name, SOG, COG, nav status
 *
 * No react-leaflet — the imperative Leaflet API is fine for a single
 * page with markers + polylines + a tile layer, and avoids the
 * react-leaflet wrapper's heavy dep tree.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import { Loader2, MapPin, RefreshCw, Crosshair } from 'lucide-react'

import { apiGet } from '../api/client'

const SCENARIOS = [
  { value: 'default_med', label: 'Mediterranean' },
  { value: 'suez_blockage', label: 'Suez Blockage' },
  { value: 'storm_rerouting', label: 'Storm Rerouting' },
  { value: 'quiet_harbor', label: 'Quiet Harbor' },
]

function labelForScenario(value) {
  return SCENARIOS.find(s => s.value === value)?.label ?? value
}

// Stable per-vessel color from a small palette (cycle if >8 vessels).
const VESSEL_COLORS = [
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#10b981', // emerald
  '#ef4444', // rose
  '#a855f7', // purple
  '#06b6d4', // cyan
  '#f43f5e', // pink
  '#84cc16', // lime
]

function colorForMmsi(mmsi, index) {
  return VESSEL_COLORS[index % VESSEL_COLORS.length]
}

function formatTs(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

// The default selected scenario is whatever the live sim is currently
// running (so the user sees vessels the first time they land on the page).
// ``default_med`` is the sim's own default — the backend serves whatever
// scenario its current sim process is configured with, and the dropdown
// is purely a client-side filter on top of that. We pick ``default_med``
// because if the sim is running on its default, this matches; if it's
// running another scenario the user can pick it from the dropdown to
// filter, and the page will just show "no data" until they do.
const DEFAULT_SCENARIO = 'default_med'

export default function FleetMapPage() {
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO)
  const mapElRef = useRef(null)
  const mapRef = useRef(null)
  const trailLayerRef = useRef(null)
  const markerLayerRef = useRef(null)

  // ── Query ────────────────────────────────────────────────────────────
  const { data, isLoading, isFetching, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['ais-positions', scenario],
    queryFn: () =>
      apiGet('/internal/ais/positions', {
        query: { scenario, event_type: 'position_report', limit: 1000 },
      }),
    refetchInterval: 5_000,
    refetchOnWindowFocus: false,
  })

  // ── Group rows by MMSI, sort by event_ts ascending ───────────────────
  const vessels = useMemo(() => {
    if (!data || !Array.isArray(data)) return []
    const groups = new Map()
    for (const r of data) {
      if (r.lat == null || r.lon == null) continue
      if (!groups.has(r.mmsi)) groups.set(r.mmsi, [])
      groups.get(r.mmsi).push(r)
    }
    const list = []
    let i = 0
    for (const [mmsi, rows] of groups) {
      rows.sort((a, b) => new Date(a.event_ts) - new Date(b.event_ts))
      const latest = rows[rows.length - 1]
      list.push({
        mmsi,
        name: latest.vessel_name || `MMSI ${mmsi}`,
        type: latest.vessel_type,
        trail: rows.map(r => [r.lat, r.lon]),
        latest,
        color: colorForMmsi(mmsi, i++),
      })
    }
    return list
  }, [data])

  // ── Init map once ───────────────────────────────────────────────────
  useEffect(() => {
    if (!mapElRef.current || mapRef.current) return
    const map = L.map(mapElRef.current, {
      center: [15, 50],
      zoom: 4,
      worldCopyJump: true,
      preferCanvas: true,
    })
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '© OpenStreetMap contributors',
    }).addTo(map)
    trailLayerRef.current = L.layerGroup().addTo(map)
    markerLayerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    // Force a size recalc after layout settles.
    setTimeout(() => map.invalidateSize(), 100)
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // ── Redraw markers + trails when vessels change ────────────────────
  useEffect(() => {
    const map = mapRef.current
    if (!map || !trailLayerRef.current || !markerLayerRef.current) return

    trailLayerRef.current.clearLayers()
    markerLayerRef.current.clearLayers()

    for (const v of vessels) {
      if (v.trail.length > 1) {
        L.polyline(v.trail, {
          color: v.color,
          weight: 2,
          opacity: 0.7,
        }).addTo(trailLayerRef.current)
      }
      const latest = v.latest
      const tip = `
        <div style="font-weight:600;margin-bottom:2px">${escapeHtml(v.name)}</div>
        <div style="opacity:.8">MMSI ${v.mmsi}${v.type ? ' · ' + v.type : ''}</div>
        <div style="margin-top:4px">
          SOG ${latest.sog?.toFixed?.(1) ?? '—'} kn ·
          COG ${latest.cog?.toFixed?.(0) ?? '—'}°
        </div>
        <div style="opacity:.7">${latest.nav_status || ''}</div>
        <div style="opacity:.6;margin-top:2px">${formatTs(latest.event_ts)}</div>
      `
      const m = L.circleMarker([latest.lat, latest.lon], {
        radius: 7,
        color: '#ffffff',
        weight: 2,
        fillColor: v.color,
        fillOpacity: 0.95,
      })
        .bindTooltip(tip, { className: 'vessel-tip', direction: 'top', offset: [0, -8] })
        .addTo(markerLayerRef.current)
      m.on('click', () => m.openTooltip())
    }
  }, [vessels])

  // ── "Center on fleet" handler ───────────────────────────────────────
  const centerOnFleet = () => {
    const map = mapRef.current
    if (!map || vessels.length === 0) return
    const all = vessels.flatMap(v => v.trail)
    if (all.length === 0) return
    const bounds = L.latLngBounds(all)
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 7 })
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <MapPin className="w-6 h-6 text-blue-500" />
            Live Fleet Map
          </h1>
          <p className="text-slate-500 text-sm">
            Synthetic AIS traffic from the simulator. {vessels.length > 0 && (
              <span className="font-medium text-slate-700 dark:text-slate-300">
                {vessels.length} vessel{vessels.length === 1 ? '' : 's'} ·
                {' '}last update {formatTs(dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : null)}
              </span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={scenario}
            onChange={e => setScenario(e.target.value)}
            className="px-3 py-2 text-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {SCENARIOS.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
          <button
            onClick={() => refetch()}
            className="p-2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800"
            title="Refresh now"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={centerOnFleet}
            disabled={vessels.length === 0}
            className="flex items-center gap-1.5 px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Crosshair className="w-4 h-4" />
            Center
          </button>
        </div>
      </header>

      <div className="relative">
        <div ref={mapElRef} className="map-shell" />
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-50/80 dark:bg-slate-950/80">
            <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
          </div>
        )}
        {!isLoading && vessels.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 rounded-xl px-6 py-4 text-center shadow-lg max-w-md">
              <div className="font-semibold mb-1">No position data for {labelForScenario(scenario)}</div>
              <div className="text-sm text-slate-500">
                The simulator is probably running a different scenario.
                Switch the dropdown to match what the backend is
                currently emitting, or restart the simulator with the
                <code className="px-1.5 py-0.5 mx-1 bg-slate-100 dark:bg-slate-800 rounded">{scenario}</code>
                scenario.
              </div>
            </div>
          </div>
        )}

        {vessels.length > 0 && (
          <div className="absolute bottom-3 left-3 bg-white/95 dark:bg-slate-900/95 border border-slate-200 dark:border-slate-800 rounded-lg shadow-lg p-3 text-xs max-w-xs">
            <div className="font-semibold mb-1.5 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Fleet ({vessels.length})
            </div>
            <ul className="space-y-1">
              {vessels.map(v => (
                <li key={v.mmsi} className="flex items-center gap-2">
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ background: v.color }}
                  />
                  <span className="truncate flex-1">{v.name}</span>
                  <span className="text-slate-500 tabular-nums">
                    {v.latest.sog?.toFixed?.(1) ?? '—'} kn
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]))
}
