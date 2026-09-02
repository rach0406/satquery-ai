import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { bboxToLeaflet } from '../lib/format'
import { Icon } from './Icons'

/* Leaflet's default marker icons come from the package's image assets, which
   Vite would need to resolve separately. We never place a default marker, so
   the divIcon below keeps the bundle self-contained. */
const dotIcon = (color) =>
  L.divIcon({
    className: '',
    html: `<span style="display:block;width:10px;height:10px;border-radius:9999px;
           background:${color};box-shadow:0 0 0 2px #0e1626,0 0 10px ${color}"></span>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
  })

/* All three sources are key-free and stay key-free — CARTO's dark basemap now
   watermarks every tile with "API KEY REQUIRED", which is not something to
   discover on stage. */
const BASEMAPS = {
  dark: {
    label: 'Dark',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
    className: '',
    maxZoom: 16,
  },
  osm: {
    label: 'Streets',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap contributors',
    className: 'satq-basemap',
    maxZoom: 18,
  },
  satellite: {
    label: 'Imagery',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri, Maxar, Earthstar Geographics',
    className: '',
    maxZoom: 18,
  },
}

export default function MapView({ artifacts = [], bbox, height = 480 }) {
  const holder = useRef(null)
  const map = useRef(null)
  const baseLayer = useRef(null)
  const overlays = useRef(new Map())
  const boxLayer = useRef(null)
  const aoiLayer = useRef(null)

  const [basemap, setBasemap] = useState('dark')
  const [opacity, setOpacity] = useState(0.82)
  const [tileError, setTileError] = useState(false)

  const imageLayers = useMemo(
    () => artifacts.filter((a) => a.kind === 'image_overlay' && a.url && a.bbox),
    [artifacts]
  )
  const boxSets = useMemo(() => artifacts.filter((a) => a.kind === 'boxes'), [artifacts])

  const [activeId, setActiveId] = useState(null)
  const [activeBoxes, setActiveBoxes] = useState({})

  useEffect(() => {
    if (imageLayers.length && !imageLayers.some((l) => l.id === activeId)) {
      setActiveId(imageLayers[0].id)
    }
    if (!imageLayers.length) setActiveId(null)
  }, [imageLayers, activeId])

  useEffect(() => {
    const next = {}
    boxSets.forEach((b, i) => {
      next[b.id] = i === 0
    })
    setActiveBoxes(next)
  }, [boxSets])

  /* ---- create the map once ---- */
  useEffect(() => {
    if (map.current || !holder.current) return
    map.current = L.map(holder.current, {
      zoomControl: true,
      attributionControl: true,
      // SVG rather than canvas for the vector layers. With preferCanvas the
      // region rectangles share one canvas renderer, and clearing them between
      // queries tears down its 2D context while a redraw is still queued for
      // the next animation frame - which threw "Cannot read properties of
      // undefined (reading 'clearRect')" on every result. We draw a couple of
      // dozen rectangles at most, so SVG costs nothing and has no such race.
      preferCanvas: false,
      worldCopyJump: true,
    }).setView([20.5, 79], 4)
    boxLayer.current = L.layerGroup().addTo(map.current)
    aoiLayer.current = L.layerGroup().addTo(map.current)
    return () => {
      // With preferCanvas the vector layers share one canvas renderer. If the
      // map is torn down (tab switch, new query) while that renderer still has
      // a redraw queued on the next animation frame, the frame fires after the
      // context is gone and Leaflet throws "Cannot read properties of
      // undefined (reading 'clearRect')". Emptying the layer groups first
      // cancels that pending work; the guard covers teardown races Leaflet
      // still loses internally.
      try {
        boxLayer.current?.clearLayers()
        aoiLayer.current?.clearLayers()
        overlays.current.forEach((layer) => {
          try {
            map.current?.removeLayer(layer)
          } catch {
            /* layer already detached */
          }
        })
        overlays.current.clear()
        map.current?.remove()
      } catch {
        /* Leaflet teardown race - the map is going away regardless */
      }
      map.current = null
      boxLayer.current = null
      aoiLayer.current = null
      baseLayer.current = null
    }
  }, [])

  /* ---- basemap ---- */
  useEffect(() => {
    if (!map.current) return
    if (baseLayer.current) map.current.removeLayer(baseLayer.current)
    const cfg = BASEMAPS[basemap]
    setTileError(false)
    baseLayer.current = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      className: cfg.className,
      maxZoom: cfg.maxZoom ?? 18,
      crossOrigin: true,
    })
    baseLayer.current.on('tileerror', () => setTileError(true))
    baseLayer.current.addTo(map.current)
    baseLayer.current.bringToBack()
  }, [basemap])

  /* ---- raster overlays ---- */
  useEffect(() => {
    if (!map.current) return
    const m = map.current
    overlays.current.forEach((layer) => m.removeLayer(layer))
    overlays.current.clear()

    imageLayers.forEach((a) => {
      const bounds = bboxToLeaflet(a.bbox)
      if (!bounds) return
      const layer = L.imageOverlay(a.url, bounds, {
        opacity: a.id === activeId ? opacity : 0,
        interactive: false,
        className: 'satq-overlay',
      })
      layer.addTo(m)
      overlays.current.set(a.id, layer)
    })
  }, [imageLayers, activeId, opacity])

  useEffect(() => {
    overlays.current.forEach((layer, id) => {
      layer.setOpacity(id === activeId ? opacity : 0)
    })
  }, [activeId, opacity])

  /* ---- AOI frame + fit ---- */
  useEffect(() => {
    if (!map.current || !aoiLayer.current) return
    aoiLayer.current.clearLayers()
    const bounds = bboxToLeaflet(bbox)
    if (!bounds) return
    L.rectangle(bounds, {
      color: '#3987e5',
      weight: 1.5,
      dashArray: '5,5',
      fill: false,
      interactive: false,
    }).addTo(aoiLayer.current)
    map.current.fitBounds(bounds, { padding: [26, 26], maxZoom: 12 })
  }, [bbox])

  /* ---- grounding / change boxes ---- */
  useEffect(() => {
    if (!map.current || !boxLayer.current) return
    boxLayer.current.clearLayers()
    boxSets.forEach((set) => {
      if (!activeBoxes[set.id]) return
      const regions = set.spec?.regions || []
      regions.forEach((r) => {
        const bounds = bboxToLeaflet(r.bbox)
        if (!bounds) return
        const color =
          r.direction === 'decrease' ? '#d95926' : r.direction === 'increase' ? '#3987e5' : '#c98500'
        const rect = L.rectangle(bounds, {
          color,
          weight: 2,
          fillOpacity: 0.08,
          fillColor: color,
        })
        const rows = [
          `<div style="font-weight:600;margin-bottom:4px">${set.title} · region #${r.rank}</div>`,
          // A region from a non-georeferenced image has no km² - show what was
          // actually measured rather than a zero that looks like a real area.
          r.area_km2 !== undefined && r.area_km2 !== null
            ? `<div>Area: <b>${r.area_km2.toLocaleString()} km²</b></div>`
            : '',
          `<div>Pixels: ${(r.pixels ?? 0).toLocaleString()}</div>`,
          r.direction ? `<div>Direction: <b>${r.direction}</b></div>` : '',
          r.mean_delta !== undefined ? `<div>Mean Δ: ${r.mean_delta}</div>` : '',
          `<div style="opacity:.7;margin-top:4px">centroid ${r.centroid?.[0]?.toFixed(4)}, ${r.centroid?.[1]?.toFixed(4)}</div>`,
        ].join('')
        rect.bindPopup(rows)
        rect.addTo(boxLayer.current)
        if (r.centroid) {
          L.marker([r.centroid[1], r.centroid[0]], { icon: dotIcon(color) })
            .bindPopup(rows)
            .addTo(boxLayer.current)
        }
      })
    })
  }, [boxSets, activeBoxes])

  const active = imageLayers.find((l) => l.id === activeId)

  return (
    <div className="flex flex-col gap-3">
      <div className="relative overflow-hidden rounded-panel border border-paper-300">
        <div ref={holder} style={{ height }} className="w-full" />

        {tileError && (
          <div className="pointer-events-none absolute left-3 top-3 z-[500] rounded-lg border border-signal-amber/40 bg-white/95 px-3 py-2 text-micro text-signal-amber shadow-float">
            Basemap tiles unavailable offline — analysis overlays are unaffected.
          </div>
        )}

        {imageLayers.length > 0 && (
          <div className="absolute right-3 top-3 z-[500] w-56 rounded-card border border-paper-300 bg-white/95 p-3 shadow-float backdrop-blur">
            <div className="mb-1.5 flex items-center gap-1.5 text-micro font-semibold uppercase tracking-wider text-ink-400">
              <Icon.layers size={12} /> Layer
            </div>
            <div className="flex flex-col gap-0.5">
              {imageLayers.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setActiveId(a.id)}
                  title={a.description || a.title}
                  className={`truncate rounded px-2 py-1 text-left text-micro transition-colors ${
                    a.id === activeId
                      ? 'bg-orbit-50 font-semibold text-orbit-700 ring-1 ring-orbit-300'
                      : 'text-ink-500 hover:bg-paper-100'
                  }`}
                >
                  {a.title}
                </button>
              ))}
            </div>

            <div className="mt-2.5 border-t border-paper-200 pt-2">
              <label className="mb-1 block text-micro text-ink-400">
                Opacity · {Math.round(opacity * 100)}%
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={opacity}
                onChange={(e) => setOpacity(Number(e.target.value))}
                className="h-1 w-full cursor-pointer appearance-none rounded-full bg-paper-300 accent-orbit-600"
              />
            </div>

            <div className="mt-2.5 border-t border-paper-200 pt-2">
              <div className="mb-1 text-micro text-ink-400">Basemap</div>
              <div className="flex gap-1">
                {Object.entries(BASEMAPS).map(([k, v]) => (
                  <button
                    key={k}
                    onClick={() => setBasemap(k)}
                    className={`flex-1 rounded px-1.5 py-1 text-micro transition-colors ${
                      basemap === k
                        ? 'bg-orbit-600 font-semibold text-white'
                        : 'text-ink-400 hover:bg-paper-100'
                    }`}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            </div>

            {boxSets.length > 0 && (
              <div className="mt-2.5 border-t border-paper-200 pt-2">
                <div className="mb-1 text-micro text-ink-400">Detected regions</div>
                {boxSets.map((b) => (
                  <label
                    key={b.id}
                    className="flex cursor-pointer items-center gap-1.5 py-0.5 text-micro text-ink-500"
                  >
                    <input
                      type="checkbox"
                      checked={!!activeBoxes[b.id]}
                      onChange={(e) =>
                        setActiveBoxes((s) => ({ ...s, [b.id]: e.target.checked }))
                      }
                      className="h-3 w-3 accent-orbit-600"
                    />
                    <span className="truncate">{b.title}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {active?.legend?.length > 0 && (
          <div className="absolute bottom-6 left-3 z-[500] max-w-[16rem] rounded-card border border-paper-300 bg-white/95 p-3 shadow-float backdrop-blur">
            <div className="mb-1.5 text-micro font-semibold uppercase tracking-wider text-ink-400">
              Legend
            </div>
            {active.legend.map((l, i) => (
              <div key={i} className="flex items-center justify-between gap-3 py-0.5 text-micro">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-sm ring-1 ring-ink-900/15"
                    style={{ background: l.color }}
                  />
                  <span className="truncate text-ink-600">{l.label}</span>
                </span>
                {l.value !== undefined && (
                  <span className="mono shrink-0 text-ink-500">
                    {l.value}
                    {l.unit || ''}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {active && (
        <p className="px-1 text-micro leading-relaxed text-ink-400">
          <span className="font-medium text-ink-500">{active.title}</span>
          {active.description ? ` — ${active.description}` : ''}
          {active.provenance?.source_url && (
            <>
              {' '}
              <a
                href={active.provenance.source_url}
                target="_blank"
                rel="noreferrer"
                className="text-orbit-600 underline decoration-dotted underline-offset-2 hover:text-orbit-700"
              >
                source request
              </a>
            </>
          )}
        </p>
      )}
    </div>
  )
}
