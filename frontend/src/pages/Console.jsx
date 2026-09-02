import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, streamQuery } from '../lib/api'
import { useAuth } from '../lib/auth.jsx'
import { CONFIG_LABELS, downloadJSON, duration, STATUS_META, TASK_LABELS } from '../lib/format'
import { Icon } from '../components/Icons'
import { Logo } from '../components/Brand'
import Globe from '../components/Globe'
import Pipeline from '../components/Pipeline'
import QuerySummary from '../components/QuerySummary'
import ReferenceDrawer from '../components/ReferenceDrawer'
import SuggestedQueries from '../components/SuggestedQueries'
import UploadPanel from '../components/UploadPanel'
import {
  ChartsPanel,
  Empty,
  GroundingPanel,
  MapPanel,
  OriginBadge,
  TablesPanel,
  TracePanel,
} from '../components/Panels'

/* The workspace.
 *
 * One question drives the layout: what is the user doing right now?
 *
 *   Nothing yet  → the question box owns the screen. Everything reference-ish
 *                  (registry, sensor catalogue, place list, status detail) is
 *                  one click away in a drawer instead of stacked down the side.
 *   Running      → the pipeline, honestly timed, and nothing else.
 *   Finished     → a fixed reading order: how the query was read → what was
 *                  done → what was found → the map → the supporting detail.
 *
 * Nothing was dropped in the reorganisation. Every panel that existed still
 * exists; the difference is that they are no longer all on screen at once. */

const DETAIL_TABS = [
  { key: 'charts', label: 'Charts', icon: Icon.chart },
  { key: 'tables', label: 'Data', icon: Icon.table },
  { key: 'grounding', label: 'Grounding', icon: Icon.shield },
  { key: 'trace', label: 'Trace', icon: Icon.list },
]

/* -------------------------------------------------------------- user menu */
function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (!ref.current?.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const name = user?.display_name || user?.username || 'Analyst'
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 rounded-pill border border-paper-300 bg-white py-1 pl-1 pr-3.5 transition-colors hover:border-ink-200 hover:bg-paper-100"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-orbit-600 text-tiny font-bold text-white">
          {initials || 'A'}
        </span>
        <span className="hidden max-w-[9rem] truncate text-small font-semibold text-ink-700 sm:block">
          {name}
        </span>
        <Icon.chevron
          size={13}
          className={`hidden text-ink-400 transition-transform sm:block ${open ? 'rotate-90' : ''}`}
        />
      </button>

      {open && (
        <div
          role="menu"
          className="animate-fadeIn absolute right-0 z-50 mt-2 w-64 overflow-hidden rounded-card border border-paper-300 bg-white shadow-float"
        >
          <div className="border-b border-paper-200 px-5 py-4">
            <div className="text-small font-semibold text-ink-900">{name}</div>
            <div className="mono mt-1 text-ink-400">{user?.username}</div>
            {user?.organisation && (
              <div className="mt-1.5 text-tiny text-ink-500">{user.organisation}</div>
            )}
          </div>
          <Link
            to="/"
            className="flex items-center gap-2.5 px-5 py-3.5 text-small text-ink-600 transition-colors hover:bg-paper-100 hover:text-ink-900"
          >
            <Icon.grid size={14} /> Back to homepage
          </Link>
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2.5 px-5 py-3.5 text-small text-ink-600 transition-colors hover:bg-paper-100 hover:text-ink-900"
          >
            <Icon.link size={14} /> API documentation
          </a>
          <button
            onClick={logout}
            className="flex w-full items-center gap-2.5 border-t border-paper-200 px-5 py-3.5 text-left text-small font-semibold text-signal-red transition-colors hover:bg-signal-red/[0.06]"
          >
            <Icon.x size={14} /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/* --------------------------------------------------------- reading section */
function Step({ n, title, sub, children, id }) {
  return (
    <section id={id} className="scroll-mt-24">
      <div className="mb-4 flex items-baseline gap-3.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink-900 font-mono text-tiny font-bold text-white">
          {n}
        </span>
        <div className="min-w-0">
          <h2 className="text-h4 text-ink-900">{title}</h2>
          {sub && <p className="mt-1 text-base text-ink-400">{sub}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

/* ------------------------------------------------------------------ page */
export default function Console() {
  const { user } = useAuth()

  const [mode, setMode] = useState('ask') // ask | image
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [tab, setTab] = useState('charts')
  const [detailOpen, setDetailOpen] = useState(false)
  const [stages, setStages] = useState({})
  const [liveTools, setLiveTools] = useState([])
  const [history, setHistory] = useState([])

  const [health, setHealth] = useState(null)
  const [samples, setSamples] = useState([])
  const [registry, setRegistry] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [scenes, setScenes] = useState([])
  const [activeScene, setActiveScene] = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Where the globe is looking. Resolved live while typing so the planet
  // turns towards the area before any analysis starts.
  const [located, setLocated] = useState(null)

  const abortRef = useRef(null)
  const inputRef = useRef(null)
  const resultsRef = useRef(null)

  /* ---- bootstrap ---- */
  useEffect(() => {
    ;(async () => {
      const settle = async (fn, set) => {
        try {
          set(await fn())
        } catch {
          /* a missing panel must not block the console */
        }
      }
      await Promise.all([
        settle(api.health, setHealth),
        settle(async () => (await api.samples()).samples, setSamples),
        settle(api.registry, setRegistry),
        settle(api.catalog, setCatalog),
        settle(async () => (await api.scenes()).scenes, setScenes),
      ])
    })()
  }, [])

  /* ---- resolve the place while the question is being typed ----
     Debounced, cancellable, and it uses the same resolver the pipeline uses,
     so the globe can never point somewhere the analysis disagrees with. */
  useEffect(() => {
    const text = query.trim()
    if (text.length < 3 || result) return undefined
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const r = await api.locate(text)
        if (!cancelled) setLocated(r.resolved ? r : null)
      } catch {
        /* the globe simply keeps spinning */
      }
    }, 550)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [query, result])

  const refreshScenes = useCallback(async () => {
    try {
      setScenes((await api.scenes()).scenes)
    } catch {
      /* non-fatal */
    }
  }, [])

  /* ---- run a query ---- */
  const run = useCallback(
    async (text, sceneOverride) => {
      const q = (text ?? query).trim()
      const scene = sceneOverride ?? activeScene
      if (busy) return
      // A scene on its own is a complete request; the backend substitutes the
      // "describe this" question so nobody has to type one.
      if (!q && !scene) return
      if (text !== undefined && typeof text === 'string') setQuery(q)
      setBusy(true)
      setError(null)
      setNotice(null)
      setResult(null)
      setDetailOpen(false)
      setStages({ parse: { started: true } })
      setLiveTools([])

      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl

      const body = { query: q }
      if (scene) body.scene_id = scene

      try {
        const { result: res } = await streamQuery(
          body,
          (msg) => {
            if (msg.event === 'notice') {
              setNotice(msg.message)
              return
            }
            if (msg.event === 'stage') {
              setStages((s) => ({
                ...s,
                [msg.stage]: { status: msg.status, ms: msg.detail?.duration_ms },
              }))
              // As soon as the plan exists we know the real AOI, so the globe
              // stops guessing from the raw text and uses the resolved box.
              if (msg.stage === 'parse' && msg.plan?.bbox) {
                const [w, s2, e, n] = msg.plan.bbox
                setLocated({
                  resolved: true,
                  place: {
                    name: msg.plan.aoi_name || 'Area of interest',
                    center: [(w + e) / 2, (s2 + n) / 2],
                    bbox: msg.plan.bbox,
                  },
                  event: msg.plan.event,
                })
              }
            }
            if (msg.event === 'tool') {
              setStages((s) => ({ ...s, execute: { status: 'active' } }))
              setLiveTools((t) => [
                ...t,
                {
                  tool: msg.tool,
                  status: msg.status,
                  ms: msg.detail?.duration_ms,
                  message: msg.detail?.message,
                },
              ])
            }
            if (msg.event === 'error') setError(msg.message)
          },
          ctrl.signal
        )

        if (res) {
          setResult(res)
          setStages((s) => ({ ...s, execute: { status: 'ok' } }))
          setLiveTools(
            (res.execution_trace || [])
              .filter(
                (c) =>
                  ![
                    'nlu_parser',
                    'plan_validator',
                    'data_acquisition',
                    'tool_selector',
                    'grounding_verifier',
                  ].includes(c.tool)
              )
              .map((c) => ({
                tool: c.tool,
                status: c.status,
                ms: c.duration_ms,
                message: c.message,
              }))
          )
          setHistory((h) =>
            [{ q: res.query, status: res.status, at: Date.now() }, ...h].slice(0, 12)
          )
          setTab(
            res.artifacts?.some((a) => a.kind === 'chart' || a.kind === 'histogram')
              ? 'charts'
              : res.artifacts?.some((a) => a.kind === 'table')
                ? 'tables'
                : 'grounding'
          )
        }
      } catch (err) {
        if (err.name !== 'AbortError') setError(err.message || String(err))
      } finally {
        setBusy(false)
      }
    },
    [query, busy, activeScene]
  )

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setMode('ask')
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Bring the answer into view once it lands, so a long result does not open
  // below the fold with no sign that anything happened.
  useEffect(() => {
    if (result) resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [result])

  async function handleUpload(file) {
    const res = await api.upload(file)
    await refreshScenes()
    if (res.scene?.scene_id) setActiveScene(res.scene.scene_id)
    return res
  }

  function reset() {
    setResult(null)
    setError(null)
    setNotice(null)
    setStages({})
    setLiveTools([])
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const status = result?.status
  const statusMeta = STATUS_META[status]
  const realSources = (result?.provenance || []).every((p) => p.origin !== 'synthetic_demo')
  const firstName = (user?.display_name || user?.username || '').split(/\s+/)[0]

  const mapArtifacts = useMemo(
    () =>
      (result?.artifacts || []).filter(
        (a) => a.kind === 'image_overlay' || a.kind === 'boxes'
      ),
    [result]
  )
  const detailCounts = useMemo(() => {
    const a = result?.artifacts || []
    return {
      charts: a.filter((x) => x.kind === 'chart' || x.kind === 'histogram').length,
      tables: a.filter((x) => x.kind === 'table').length,
      grounding: result?.grounding?.claims_checked ?? 0,
      trace: result?.execution_trace?.length ?? 0,
    }
  }, [result])

  const focus = located?.place?.center || null

  return (
    <div className="min-h-screen bg-paper-100 bg-paper-wash">
      {/* ============================ header ============================ */}
      <header className="sticky top-0 z-30 border-b border-paper-300 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1320px] items-center gap-4 px-6 py-3.5 lg:px-10">
          <Link to="/" className="flex min-w-0 items-center gap-3 rounded-lg">
            <Logo size={34} />
            <span className="min-w-0 leading-none">
              <span className="block truncate font-display text-h5 font-bold tracking-tight text-ink-900">
                SatQuery&nbsp;AI
              </span>
              <span className="mt-1 hidden truncate text-micro font-medium text-ink-400 sm:block">
                Satellite Intelligence Workspace
              </span>
            </span>
          </Link>

          <div className="ml-auto flex items-center gap-2.5">
            <span
              className={`chip hidden md:inline-flex ${health ? 'chip-ok' : 'chip-bad'}`}
              title={health ? 'Backend reachable' : 'Backend unreachable'}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  health ? 'animate-pulseSoft bg-signal-green' : 'bg-signal-red'
                }`}
              />
              {health ? 'Systems nominal' : 'Backend offline'}
            </span>
            <button
              onClick={() => setDrawerOpen(true)}
              className="btn-secondary !py-2"
              title="Model registry, sensors and system status"
            >
              <Icon.cpu size={14} />
              <span className="hidden sm:inline">Reference</span>
            </button>
            <UserMenu />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1320px] px-6 pb-24 lg:px-10">
        {/* ======================= 1. the question ======================= */}
        <section className="relative overflow-hidden pt-12 lg:pt-16">
          {/* The globe. Atmosphere until a place is recognised, at which point
              it becomes the confirmation that the location was understood.
              Deliberately faint and edge-faded: it must never compete with the
              question box for attention, and it sits behind the content in the
              stacking order so it can never intercept a click. Hidden below
              xl, where there is no room for it beside the text. */}
          <div
            className="pointer-events-none absolute -right-20 top-4 hidden opacity-[0.38] xl:block"
            style={{
              maskImage: 'radial-gradient(circle at 50% 50%, #000 55%, transparent 78%)',
              WebkitMaskImage: 'radial-gradient(circle at 50% 50%, #000 55%, transparent 78%)',
            }}
            aria-hidden="true"
          >
            <Globe size={400} focus={focus} />
          </div>

          <div className="relative max-w-3xl">
            <p className="eyebrow">
              <span className="h-1 w-1 rounded-full bg-orbit-500" />
              {firstName ? `Welcome back, ${firstName}` : 'Ready when you are'}
            </p>
            <h1 className="text-h2 leading-tight lg:text-[2.4rem] lg:leading-[3rem]">
              What do you want to know from satellite data?
            </h1>
            <p className="lede mt-5">
              Ask in plain language — a full question or just a few words — or hand over your
              own imagery. Every figure that comes back is measured from real pixels.
            </p>

            {/* ---- mode switch ---- */}
            <div className="mt-9 inline-flex rounded-pill border border-paper-300 bg-white p-1 shadow-card">
              {[
                ['ask', 'Ask a question', Icon.spark],
                ['image', 'Analyse an image', Icon.upload],
              ].map(([key, label, I]) => (
                <button
                  key={key}
                  onClick={() => setMode(key)}
                  className={`flex items-center gap-2 rounded-pill px-5 py-2.5 text-small font-semibold transition-colors ${
                    mode === key
                      ? 'bg-orbit-600 text-white shadow-card'
                      : 'text-ink-500 hover:text-ink-800'
                  }`}
                >
                  <I size={15} />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* ---- ask mode ---- */}
          {mode === 'ask' && (
            <div className="relative mt-7 max-w-4xl">
              <div className="panel p-6 lg:p-7">
                <label htmlFor="satq-query" className="field-label">
                  Your question
                </label>
                <div className="relative">
                  <textarea
                    id="satq-query"
                    ref={inputRef}
                    rows={3}
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        run()
                      }
                    }}
                    placeholder={'Kerala floods 2025\nor: What changed around Chennai between January and October 2025?'}
                    className="field resize-none pr-16 text-lead leading-relaxed"
                  />
                  <kbd className="pointer-events-none absolute right-3.5 top-3.5 hidden rounded border border-paper-400 bg-paper-100 px-1.5 py-0.5 font-mono text-micro text-ink-400 sm:block">
                    ⌘K
                  </kbd>
                </div>

                {/* what the system has already worked out about the query */}
                <div className="mt-4 flex min-h-[2rem] flex-wrap items-center gap-2.5">
                  {located?.place ? (
                    <>
                      <span className="chip-brand">
                        <Icon.map size={12} /> {located.place.name}
                      </span>
                      {located.event && (
                        <span className="chip-neutral">
                          <Icon.spark size={11} /> {located.event}
                        </span>
                      )}
                      <span className="text-small text-ink-400">
                        recognised in your question
                      </span>
                    </>
                  ) : (
                    <span className="text-small text-ink-300">
                      Name a place, an event and a year — &ldquo;Kerala floods 2025&rdquo; is enough.
                    </span>
                  )}
                </div>

                {activeScene && (
                  <div className="mt-4 flex flex-wrap items-center gap-2 rounded-card border border-orbit-200 bg-orbit-50 px-4 py-3 text-small text-orbit-700">
                    <Icon.eye size={14} />
                    This question will be answered against your uploaded scene
                    <span className="mono rounded bg-white px-2 py-0.5">{activeScene}</span>
                    <button
                      onClick={() => setActiveScene(null)}
                      className="ml-auto font-semibold underline underline-offset-2 hover:text-orbit-800"
                    >
                      use archive imagery instead
                    </button>
                  </div>
                )}

                <div className="mt-5 flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => run()}
                    disabled={busy || (!query.trim() && !activeScene)}
                    className="btn-primary btn-lg"
                  >
                    {busy ? (
                      <>
                        <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                        Analysing…
                      </>
                    ) : (
                      <>
                        <Icon.send size={16} /> Analyse
                      </>
                    )}
                  </button>
                  {result && (
                    <button onClick={reset} className="btn-secondary btn-lg">
                      <Icon.refresh size={15} /> New query
                    </button>
                  )}
                  <span className="ml-auto hidden text-small text-ink-400 sm:block">
                    Enter to run · Shift+Enter for a new line
                  </span>
                </div>

                {history.length > 0 && !busy && (
                  <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-paper-200 pt-5">
                    <span className="text-micro font-semibold uppercase tracking-[0.13em] text-ink-400">
                      Recent
                    </span>
                    {history.slice(0, 4).map((h, i) => (
                      <button
                        key={i}
                        onClick={() => run(h.q)}
                        className="max-w-[20rem] truncate rounded-pill bg-paper-200 px-3.5 py-1.5 text-small text-ink-500 transition-colors hover:bg-paper-300 hover:text-ink-800"
                      >
                        {h.q}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="mt-5">
                <SuggestedQueries
                  samples={samples}
                  busy={busy}
                  onRun={(q) => {
                    setActiveScene(null)
                    run(q, null)
                  }}
                />
              </div>
            </div>
          )}

          {/* ---- image mode ---- */}
          {mode === 'image' && (
            <div className="relative mt-7 max-w-4xl">
              <UploadPanel
                scenes={scenes}
                activeScene={activeScene}
                onSelectScene={setActiveScene}
                onUpload={handleUpload}
                onAnalyse={(sceneId) => {
                  setActiveScene(sceneId)
                  run('', sceneId)
                }}
                busy={busy}
              />
            </div>
          )}
        </section>

        {/* ======================= status / errors ======================= */}
        <div ref={resultsRef} className="scroll-mt-24" />

        {(busy || result) && (
          <div className="mt-12">
            <Pipeline stages={stages} running={busy} tools={liveTools} />
          </div>
        )}

        {notice && (
          <div className="mt-6 flex items-start gap-3 rounded-card border border-paper-300 bg-white px-5 py-4 text-base text-ink-500">
            <Icon.info size={16} className="mt-0.5 shrink-0 text-ink-400" /> {notice}
          </div>
        )}

        {error && (
          <div className="mt-6 flex items-start gap-3.5 rounded-card border border-signal-red/30 bg-signal-red/[0.06] px-5 py-5">
            <Icon.alert size={18} className="mt-0.5 shrink-0 text-signal-red" />
            <div>
              <div className="text-h5 font-semibold text-signal-red">Request failed</div>
              <div className="mt-1.5 text-base text-ink-600">{error}</div>
              <div className="mt-2 text-small text-ink-400">
                If this says the backend is unreachable, start it with{' '}
                <span className="mono rounded bg-paper-200 px-1.5 py-0.5">
                  uvicorn app.main:app --port 8000
                </span>
              </div>
            </div>
          </div>
        )}

        {busy && !result && (
          <div className="mt-8 flex flex-col gap-6">
            <div className="skeleton h-40" />
            <div className="skeleton h-[420px]" />
          </div>
        )}

        {/* ============================ results ============================ */}
        {result && (
          <div className="animate-floatUp mt-14 flex flex-col gap-16">
            {/* ---- 1. what came back ---- */}
            <Step
              n="1"
              title="The answer"
              sub="Composed only from measurements this run produced"
            >
              <section className="panel overflow-hidden">
                <div className="flex flex-wrap items-center gap-2.5 border-b border-paper-200 bg-paper-50 px-7 py-4">
                  <span className={`chip ${statusMeta?.tone}`}>{statusMeta?.label}</span>
                  <span className="chip-neutral">
                    {TASK_LABELS[result.plan?.task] || result.plan?.task}
                  </span>
                  <span className="chip-neutral">
                    {CONFIG_LABELS[result.plan?.input_configuration]}
                  </span>
                  {result.plan?.aoi_name && (
                    <span className="chip-neutral">
                      <Icon.map size={11} /> {result.plan.aoi_name}
                    </span>
                  )}
                  {result.plan?.dates?.map((d) => (
                    <span key={d} className="chip-neutral">
                      <Icon.clock size={11} /> {d}
                    </span>
                  ))}
                  {realSources && result.provenance?.length > 0 && (
                    <OriginBadge origin={result.provenance[0].origin} />
                  )}
                  <span className="mono ml-auto text-ink-400">
                    {duration(result.total_duration_ms)}
                    {result.confidence != null && ` · conf ${result.confidence.toFixed(2)}`}
                  </span>
                </div>

                <div className="px-7 py-8 lg:px-9">
                  {result.answer && (
                    <div className="mb-6 flex items-start gap-4">
                      <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-orbit-600 text-white">
                        <Icon.spark size={16} />
                      </span>
                      <p className="font-display text-h3 font-semibold leading-snug text-ink-900">
                        {result.answer}
                      </p>
                    </div>
                  )}
                  <p className="max-w-prose text-lead leading-relaxed text-ink-600">
                    {result.explanation}
                  </p>
                </div>

                {result.warnings?.length > 0 && (
                  <details className="border-t border-signal-amber/25 bg-signal-amber/[0.05]">
                    <summary className="flex cursor-pointer items-center gap-2 px-7 py-4 text-small font-semibold text-signal-amber transition-colors hover:bg-signal-amber/[0.09]">
                      <Icon.alert size={14} />
                      {result.warnings.length} caveat
                      {result.warnings.length === 1 ? '' : 's'} the system raised about its own
                      result
                    </summary>
                    <ul className="flex flex-col gap-3 px-7 pb-6">
                      {result.warnings.map((w, i) => (
                        <li
                          key={i}
                          className="pl-5 text-base leading-relaxed text-ink-600 before:mr-2.5 before:text-signal-amber before:content-['—']"
                        >
                          {w}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            </Step>

            {/* ---- 2. the digest ---- */}
            <Step
              n="2"
              title="Query summary"
              sub="How the question was read, what ran, and the headline numbers"
            >
              <QuerySummary summary={result.summary} />
            </Step>

            {/* ---- 3. the map ---- */}
            {status === 'ok' && (
              <Step
                n="3"
                title="Map"
                sub={
                  mapArtifacts.length
                    ? 'Every layer here is a rendered measurement, placed on its real extent'
                    : 'This analysis produced statistics rather than a georeferenced raster'
                }
              >
                {mapArtifacts.length ? (
                  <MapPanel result={result} />
                ) : (
                  <Empty icon={Icon.map} title="No spatial output for this query">
                    The charts and tables below hold the result.
                  </Empty>
                )}
              </Step>
            )}

            {/* ---- 4. the detail, folded away until asked for ---- */}
            {status === 'ok' ? (
              <Step
                n="4"
                title="Detailed analysis"
                sub="Charts, the full fact store, the grounding audit and the execution trace"
              >
                <section className="panel overflow-hidden">
                  <button
                    onClick={() => setDetailOpen((v) => !v)}
                    aria-expanded={detailOpen}
                    className="flex w-full items-center gap-4 px-7 py-5 text-left transition-colors hover:bg-paper-50"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-base font-semibold text-ink-800">
                        {detailOpen ? 'Hide the supporting detail' : 'Open the supporting detail'}
                      </span>
                      <span className="mt-1 block text-small text-ink-400">
                        {detailCounts.charts} chart{detailCounts.charts === 1 ? '' : 's'} ·{' '}
                        {result.facts?.length ?? 0} measured facts ·{' '}
                        {detailCounts.grounding} numbers verified · {detailCounts.trace} pipeline
                        steps
                      </span>
                    </span>
                    <Icon.chevron
                      size={17}
                      className={`shrink-0 text-ink-300 transition-transform ${
                        detailOpen ? 'rotate-90' : ''
                      }`}
                    />
                  </button>

                  {detailOpen && (
                    <div className="animate-fadeIn border-t border-paper-200">
                      <div className="flex gap-1 overflow-x-auto border-b border-paper-300 px-5">
                        {DETAIL_TABS.map((t) => (
                          <button
                            key={t.key}
                            onClick={() => setTab(t.key)}
                            className={`tab ${tab === t.key ? 'tab-active' : ''}`}
                          >
                            <span className="flex items-center gap-2">
                              <t.icon size={14} />
                              {t.label}
                              {detailCounts[t.key] > 0 && (
                                <span
                                  className={`rounded px-1.5 py-px font-mono text-micro ${
                                    tab === t.key
                                      ? 'bg-orbit-100 text-orbit-700'
                                      : 'bg-paper-200 text-ink-400'
                                  }`}
                                >
                                  {detailCounts[t.key]}
                                </span>
                              )}
                            </span>
                          </button>
                        ))}
                      </div>
                      <div className="bg-paper-50 p-6 lg:p-8">
                        {tab === 'charts' && <ChartsPanel result={result} />}
                        {tab === 'tables' && <TablesPanel result={result} />}
                        {tab === 'grounding' && <GroundingPanel result={result} />}
                        {tab === 'trace' && <TracePanel result={result} />}
                      </div>
                    </div>
                  )}
                </section>
              </Step>
            ) : (
              <Step
                n="3"
                title={
                  status === 'needs_clarification'
                    ? 'One more detail is needed'
                    : 'No usable data for this request'
                }
                sub="The pipeline stopped rather than estimating a value"
              >
                <div className="flex flex-col gap-6">
                  <Empty
                    icon={status === 'needs_clarification' ? Icon.help : Icon.alert}
                    title={
                      status === 'needs_clarification'
                        ? 'The system needs one more detail'
                        : 'The archive had nothing usable'
                    }
                  >
                    {status === 'needs_clarification'
                      ? 'Rather than guessing an area and reporting a number for the wrong place, the controller stopped and asked.'
                      : 'The archive was queried and had nothing usable. No value was estimated or substituted — that refusal is the correct behaviour, and the trace shows exactly which dates were checked.'}
                  </Empty>
                  <TracePanel result={result} />
                </div>
              </Step>
            )}

            <div className="flex flex-wrap justify-center gap-4 border-t border-paper-300 pt-10">
              <button onClick={reset} className="btn-primary btn-lg">
                <Icon.refresh size={16} /> Ask something else
              </button>
              <button
                onClick={() => downloadJSON(result, `satquery_${result.request_id}.json`)}
                className="btn-secondary btn-lg"
                title="The full evidence record: plan, trace, facts, provenance"
              >
                <Icon.download size={16} /> Download the evidence record
              </button>
            </div>
          </div>
        )}
      </main>

      <ReferenceDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        registry={registry}
        catalog={catalog}
        health={health}
        busy={busy}
        onRun={(q) => {
          setActiveScene(null)
          setMode('ask')
          run(q, null)
        }}
      />
    </div>
  )
}
