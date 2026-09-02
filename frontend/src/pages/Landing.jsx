import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth.jsx'
import { Icon } from '../components/Icons'
import { Logo, OrbitVisual, SectionHead, Starfield, Wordmark } from '../components/Brand'

/* ------------------------------------------------------------------ data */
const STEPS = [
  {
    icon: Icon.spark,
    title: 'Ask in plain English',
    body: 'No GIS training, no band maths, no product codes. Type the question the way you would ask a colleague.',
    detail: '"What changed around Chennai between January and October 2025?"',
  },
  {
    icon: Icon.cpu,
    title: 'The agent plans',
    body: 'It classifies the task, extracts the area, dates and target classes, and picks specialists from a closed registry.',
    detail: 'change_detection · bi-temporal pair · Chennai · NDVI, MNDWI',
  },
  {
    icon: Icon.satellite,
    title: 'Real pixels retrieved',
    body: 'It probes what the satellites actually observed — coverage, cloud, empty tiles — and takes the usable acquisitions.',
    detail: '42 archive availability probes · 2 scenes selected',
  },
  {
    icon: Icon.chart,
    title: 'Specialists measure',
    body: 'Spectral indices, segmentation, change vector analysis, SAR backscatter and cross-modal fusion run on the retrieved arrays.',
    detail: 'Every value carries its method and sample size',
  },
  {
    icon: Icon.shield,
    title: 'Every number verified',
    body: 'The narration is scanned and each numeral is traced back to a measurement. Untraceable numbers are rejected.',
    detail: '19 / 19 claims traced to measured facts',
  },
  {
    icon: Icon.map,
    title: 'Evidence, not just an answer',
    body: 'Maps, charts, tables, the full execution trace, source URLs and a downloadable report.',
    detail: '17 artifacts · 55 facts · 2 sources',
  },
]

const FEATURES = [
  {
    icon: Icon.spark,
    title: 'Natural-language queries',
    body: 'Intent, area, dates, target classes and indices are extracted into a typed, validated plan.',
  },
  {
    icon: Icon.satellite,
    title: 'Real satellite imagery',
    body: 'MODIS, VIIRS and Sentinel-1 SAR straight from NASA GIBS over open WMS — no credentials to expire.',
  },
  {
    icon: Icon.layers,
    title: 'Optical + SAR fusion',
    body: 'Co-registration is asserted, then radar recovers surface water that cloud hides from the optical sensor.',
  },
  {
    icon: Icon.gitCompare,
    title: 'Bi-temporal change',
    body: 'Change vector analysis with a class transition matrix and geo-referenced change regions.',
  },
  {
    icon: Icon.crosshair,
    title: 'Text-guided grounding',
    body: 'A phrase in your question resolves to a pixel mask, then to ranked regions with real areas.',
  },
  {
    icon: Icon.cpu,
    title: 'Remote-sensing model',
    body: 'A classifier adapted here on 27,000 labelled Sentinel-2 patches — and it knows when it is out of domain.',
  },
  {
    icon: Icon.map,
    title: 'Interactive geospatial output',
    body: 'Raster overlays on a real map with opacity, layer switching, legends and clickable regions.',
  },
  {
    icon: Icon.shield,
    title: 'Auditable by design',
    body: 'Full execution trace, per-fact provenance, and the exact archive URL behind every pixel.',
  },
]

const TECH = [
  { group: 'Frontend', items: ['React 18', 'Vite', 'Tailwind CSS', 'Leaflet', 'Plotly'] },
  { group: 'Backend', items: ['Python 3.12', 'FastAPI', 'Uvicorn', 'Pydantic', 'SSE streaming'] },
  { group: 'Processing', items: ['NumPy', 'SciPy', 'Pillow', 'Otsu / CVA', 'Lee speckle filter'] },
  { group: 'AI / ML', items: ['scikit-learn', 'EuroSAT adaptation', 'Structured tool calling', 'Grounding verifier'] },
  { group: 'Data', items: ['NASA GIBS WMS', 'MODIS · VIIRS', 'Sentinel-1 OPERA RTC', 'OpenStreetMap'] },
  { group: 'Delivery', items: ['Docker', 'REST + OpenAPI', 'Disk cache', 'Offline mode'] },
]

const USE_CASES = [
  {
    icon: Icon.flame,
    title: 'Disaster management',
    body: 'Map flood extent during monsoon cloud cover using radar, and quantify the affected area in km² within minutes.',
    tag: 'Government',
  },
  {
    icon: Icon.leaf,
    title: 'Environmental monitoring',
    body: 'Track deforestation, water-body shrinkage and vegetation stress with measured trends, not impressions.',
    tag: 'Environment',
  },
  {
    icon: Icon.fileText,
    title: 'Research & science',
    body: 'Get defensible statistics with the method, sample size and source behind every figure — ready to cite.',
    tag: 'Academia',
  },
  {
    icon: Icon.building,
    title: 'Planning & decisions',
    body: 'Evidence for land-use change and urban growth questions, without a GIS analyst in the loop.',
    tag: 'Policy',
  },
]

/* ------------------------------------------------------------------- nav */
function Nav() {
  const { isAuthenticated, user } = useAuth()
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const links = [
    ['#what', 'What it is'],
    ['#how', 'How it works'],
    ['#features', 'Features'],
    ['#demo', 'Demo'],
    ['#tech', 'Technology'],
  ]

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
        scrolled ? 'border-b border-white/10 bg-night-950/85 backdrop-blur-md' : 'bg-transparent'
      }`}
    >
      <nav className="shell-wide flex h-18 items-center gap-8 py-4">
        <Wordmark to="/" tone="dark" />

        <div className="ml-auto hidden items-center gap-1 lg:flex">
          {links.map(([href, label]) => (
            <a
              key={href}
              href={href}
              className="rounded-lg px-3.5 py-2 text-small font-medium text-paper-300/80 transition-colors hover:bg-white/10 hover:text-white"
            >
              {label}
            </a>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2.5 lg:ml-0">
          {isAuthenticated ? (
            <Link to="/app" className="btn-primary">
              <Icon.grid size={15} /> Open console
            </Link>
          ) : (
            <>
              <Link to="/login" className="btn-invert hidden sm:inline-flex">
                Sign in
              </Link>
              <Link to="/login?mode=signup" className="btn-primary">
                Get started <Icon.chevron size={15} />
              </Link>
            </>
          )}
          <button
            onClick={() => setOpen((v) => !v)}
            className="rounded-lg p-2 text-paper-200 hover:bg-white/10 lg:hidden"
            aria-label="Menu"
          >
            <Icon.list size={20} />
          </button>
        </div>
      </nav>

      {open && (
        <div className="animate-fadeIn border-t border-white/10 bg-night-950/95 px-6 py-3 backdrop-blur lg:hidden">
          {links.map(([href, label]) => (
            <a
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className="block rounded-lg px-3 py-2.5 text-small font-medium text-paper-300 hover:bg-white/10"
            >
              {label}
            </a>
          ))}
        </div>
      )}
    </header>
  )
}

/* ------------------------------------------------------------------ hero */
function Hero({ health }) {
  const acc = health?.rs_model?.test_accuracy
  return (
    <section className="relative overflow-hidden bg-night-sky pt-18">
      <Starfield />
      <div className="absolute inset-0 night-grid opacity-60" />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-32"
        style={{ background: 'linear-gradient(to bottom, transparent, #f5f8fc)' }}
      />

      <div className="shell-wide relative grid items-center gap-14 py-20 lg:grid-cols-[1.08fr_0.92fr] lg:py-28">
        <div className="animate-floatUp">
          <span className="inline-flex items-center gap-2 rounded-pill border border-white/15 bg-white/10 px-3.5 py-1.5 text-micro font-semibold tracking-wide text-paper-200 backdrop-blur">
            <span className="h-1.5 w-1.5 animate-pulseSoft rounded-full bg-orbit-300" />
            Smart India Hackathon 2026 · SIH26167 · ISRO
          </span>

          <h1 className="mt-6 text-[2.5rem] leading-[1.12] text-white sm:text-display lg:text-hero">
            Ask the planet
            <br />
            a question.
          </h1>

          <p className="mt-6 max-w-xl text-lead text-paper-300/85">
            SatQuery AI turns plain English into a complete remote-sensing workflow — retrieving
            real satellite imagery, running specialist models, and answering with{' '}
            <span className="font-semibold text-white">measurements it can prove</span>.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link to="/login?mode=signup" className="btn-primary btn-lg">
              <Icon.satellite size={17} /> Explore SatQuery AI
            </Link>
            <a href="#how" className="btn-invert btn-lg">
              See how it works
            </a>
          </div>

          <dl className="mt-12 grid max-w-lg grid-cols-3 gap-6 border-t border-white/10 pt-7">
            {[
              ['10', 'specialist tools'],
              [acc ? `${(acc * 100).toFixed(1)}%` : '85.9%', 'model accuracy'],
              ['0', 'invented numbers'],
            ].map(([v, k]) => (
              <div key={k}>
                <dt className="font-display text-h3 font-bold text-white">{v}</dt>
                <dd className="mt-1 text-tiny text-paper-300/70">{k}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="relative animate-fadeIn">
          <OrbitVisual className="mx-auto w-full max-w-[460px] drop-shadow-2xl" />
          <div className="absolute -bottom-2 left-1/2 w-[min(92%,420px)] -translate-x-1/2 rounded-card border border-white/12 bg-night-850/85 p-4 shadow-float backdrop-blur-md">
            <p className="mono text-orbit-300">satquery ▸ live query</p>
            <p className="mt-2 text-small font-medium leading-relaxed text-paper-200">
              “How much of Chilika Lake is covered by water right now?”
            </p>
            <div className="mt-3 flex items-center gap-2 border-t border-white/10 pt-3">
              <Icon.check size={13} className="shrink-0 text-signal-green" />
              <span className="text-tiny text-paper-300/80">
                Water share <span className="num font-semibold text-white">55.70%</span> · traced to
                145,276 measured pixels
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ page */
export default function Landing() {
  const [health, setHealth] = useState(null)
  const [samples, setSamples] = useState([])

  useEffect(() => {
    api.health().then(setHealth).catch(() => {})
    api
      .samples()
      .then((d) => setSamples(d.samples.slice(0, 6)))
      .catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-paper-100">
      <Nav />
      <Hero health={health} />

      {/* ---------------------------------------------------- what it is */}
      <section id="what" className="section bg-paper-100 bg-paper-wash">
        <div className="shell">
          <SectionHead
            center
            eyebrow="What is SatQuery AI"
            title="Satellite analysis without the satellite expertise"
            lede="Answering a question with satellite data normally means knowing which sensor to use, which product to download, how to reproject it, and which band maths applies. SatQuery AI does that reasoning for you — and shows its work."
          />

          <div className="mt-14 grid gap-6 lg:grid-cols-3">
            {[
              {
                icon: Icon.help,
                eyebrow: 'The problem',
                title: 'Satellite data is locked behind expertise',
                body: 'Remote-sensing tools are built for one task at a time and assume you already understand sensors, GIS workflows and product formats. Most people who need the answers cannot get them.',
              },
              {
                icon: Icon.spark,
                eyebrow: 'The solution',
                title: 'An agent that plans and measures',
                body: 'One natural-language interface routes your question to the right specialist models, retrieves the right imagery, and returns maps, charts and a written explanation together.',
              },
              {
                icon: Icon.shield,
                eyebrow: 'The difference',
                title: 'Answers you can audit',
                body: 'A general chatbot will invent a confident percentage. Here, only measurement tools can produce a number, and every figure in the text is traced back to the pixels behind it.',
              },
            ].map((c) => (
              <article key={c.title} className="card card-hover p-7">
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-card bg-orbit-50 text-orbit-600">
                  <c.icon size={20} />
                </span>
                <p className="mt-5 text-micro font-semibold uppercase tracking-[0.13em] text-ink-400">
                  {c.eyebrow}
                </p>
                <h3 className="mt-2 text-h5">{c.title}</h3>
                <p className="mt-3 text-base leading-relaxed text-ink-500">{c.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- how it works */}
      <section id="how" className="section border-y border-paper-300 bg-white">
        <div className="shell">
          <SectionHead
            center
            eyebrow="How it works"
            title="From a sentence to verified evidence"
            lede="Six stages run on every query. The console streams them live, with the real measured timing of each."
          />

          <ol className="mt-14 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="group relative">
                <article className="card card-hover h-full p-6">
                  <div className="flex items-center gap-3">
                    <span className="inline-flex h-10 w-10 items-center justify-center rounded-card bg-gradient-to-br from-orbit-600 to-signal-teal text-white shadow-sm">
                      <s.icon size={18} />
                    </span>
                    <span className="num rounded-pill bg-paper-200 px-2.5 py-1 text-micro font-bold text-ink-400">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                  </div>
                  <h3 className="mt-5 text-h5">{s.title}</h3>
                  <p className="mt-2.5 text-base leading-relaxed text-ink-500">{s.body}</p>
                  <p className="mono mt-4 rounded-lg bg-paper-100 px-3 py-2.5 leading-relaxed text-ink-500">
                    {s.detail}
                  </p>
                </article>
                {i < STEPS.length - 1 && (
                  <span className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-paper-400 lg:block">
                    <Icon.chevron size={18} />
                  </span>
                )}
              </li>
            ))}
          </ol>

          <div className="mt-12 flex flex-wrap items-center justify-center gap-x-3 gap-y-3 rounded-panel border border-paper-300 bg-paper-50 px-6 py-6">
            {[
              'Natural language',
              'AI understanding',
              'Satellite selection',
              'Geospatial analysis',
              'Maps · charts · insight',
            ].map((label, i, arr) => (
              <span key={label} className="flex items-center gap-3">
                <span className="rounded-pill border border-paper-400 bg-white px-4 py-2 text-small font-semibold text-ink-700 shadow-sm">
                  {label}
                </span>
                {i < arr.length - 1 && <Icon.chevron size={15} className="text-orbit-500" />}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- features */}
      <section id="features" className="section bg-paper-100">
        <div className="shell">
          <SectionHead
            center
            eyebrow="Capabilities"
            title="Everything the problem statement asks for"
            lede="Single-image VQA, captioning, grounding, bi-temporal change, cross-modal optical–SAR analysis, remote-sensing adaptation and agentic orchestration — all implemented and running."
          />
          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f) => (
              <article key={f.title} className="card card-hover p-6">
                <span className="inline-flex h-10 w-10 items-center justify-center rounded-card bg-orbit-50 text-orbit-600">
                  <f.icon size={18} />
                </span>
                <h3 className="mt-4 text-h5 leading-snug">{f.title}</h3>
                <p className="mt-2.5 text-small leading-relaxed text-ink-500">{f.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- demo */}
      <section id="demo" className="section border-y border-paper-300 bg-white">
        <div className="shell">
          <SectionHead
            center
            eyebrow="See it running"
            title="Watch the pipeline work"
            lede="Every stage streams live — plan, retrieval, measurement, verification — with the real timings, not a scripted animation."
          />

          <div className="mt-12 overflow-hidden rounded-panel border border-paper-300 shadow-raised">
            {/* Video placeholder — drop a file at public/demo.mp4 or set the
                src below to a hosted URL and this becomes a real player. */}
            <div className="relative aspect-video bg-night-sky">
              <Starfield />
              <div className="absolute inset-0 night-grid opacity-50" />
              <div className="relative flex h-full flex-col items-center justify-center px-6 text-center">
                <button
                  type="button"
                  className="group inline-flex h-20 w-20 items-center justify-center rounded-full border border-white/25 bg-white/10 backdrop-blur transition-all hover:scale-105 hover:bg-white/20"
                  aria-label="Demo video placeholder"
                >
                  <svg width="26" height="30" viewBox="0 0 26 30" aria-hidden="true">
                    <path d="M2 2l22 13L2 28z" fill="#fff" />
                  </svg>
                </button>
                <p className="mt-7 font-display text-h4 text-white">Demo video</p>
                <p className="mt-2 max-w-md text-small leading-relaxed text-paper-300/75">
                  Add your recording to{' '}
                  <code className="mono rounded bg-white/10 px-1.5 py-0.5 text-paper-200">
                    frontend/public/demo.mp4
                  </code>{' '}
                  and it will play here.
                </p>
                <Link to="/login?mode=signup" className="btn-invert mt-7">
                  Or try it live now <Icon.chevron size={14} />
                </Link>
              </div>
            </div>
          </div>

          {samples.length > 0 && (
            <>
              <p className="mt-12 text-center text-small font-semibold uppercase tracking-[0.13em] text-ink-400">
                Questions you can ask
              </p>
              <div className="mx-auto mt-6 flex max-w-4xl flex-wrap justify-center gap-2.5">
                {samples.map((s) => (
                  <span
                    key={s.id}
                    className="rounded-pill border border-paper-300 bg-paper-50 px-4 py-2.5 text-small text-ink-600"
                  >
                    “{s.query.length > 74 ? `${s.query.slice(0, 74)}…` : s.query}”
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </section>

      {/* ---------------------------------------------------- use cases */}
      <section id="impact" className="section bg-paper-100 bg-paper-wash">
        <div className="shell">
          <SectionHead
            center
            eyebrow="Impact"
            title="Who this is for"
            lede="Anyone who needs an answer from satellite data but should not need a remote-sensing degree to get one."
          />
          <div className="mt-14 grid gap-5 sm:grid-cols-2">
            {USE_CASES.map((u) => (
              <article key={u.title} className="card card-hover flex gap-5 p-7">
                <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-card bg-gradient-to-br from-orbit-600 to-signal-teal text-white">
                  <u.icon size={21} />
                </span>
                <div>
                  <span className="chip-brand">{u.tag}</span>
                  <h3 className="mt-3 text-h5">{u.title}</h3>
                  <p className="mt-2.5 text-base leading-relaxed text-ink-500">{u.body}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- technology */}
      <section id="tech" className="section border-y border-paper-300 bg-white">
        <div className="shell">
          <SectionHead
            center
            eyebrow="Technology"
            title="Built on open, dependable foundations"
            lede="Nothing in the demo path needs an API key or a paid tier. The satellite archive is public, and the models run on CPU."
          />
          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {TECH.map((t) => (
              <div key={t.group} className="card p-6">
                <h3 className="text-micro font-semibold uppercase tracking-[0.13em] text-orbit-600">
                  {t.group}
                </h3>
                <ul className="mt-4 flex flex-wrap gap-2">
                  {t.items.map((i) => (
                    <li
                      key={i}
                      className="rounded-lg border border-paper-300 bg-paper-50 px-3 py-1.5 text-tiny font-medium text-ink-600"
                    >
                      {i}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- final CTA */}
      <section className="relative overflow-hidden bg-night-sky">
        <Starfield />
        <div className="absolute inset-0 night-grid opacity-50" />
        <div className="shell relative py-20 text-center lg:py-24">
          <Logo size={54} className="mx-auto" />
          <h2 className="mt-7 text-h2 text-white lg:text-[2.5rem] lg:leading-[3rem]">
            Point it at anywhere on Earth.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-lead text-paper-300/80">
            Sign in and ask your first question. A demo account is ready — no setup, no API key.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <Link to="/login?mode=signup" className="btn-primary btn-lg">
              Create an account
            </Link>
            <Link to="/login" className="btn-invert btn-lg">
              Sign in with the demo account
            </Link>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- footer */}
      <footer className="bg-night-950 py-14 text-paper-300">
        <div className="shell-wide">
          <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
            <div>
              <Wordmark to={null} tone="dark" />
              <p className="mt-5 max-w-sm text-small leading-relaxed text-paper-300/65">
                An agentic vision-language assistant for multimodal remote-sensing analysis.
                Built for Smart India Hackathon 2026, problem statement SIH26167.
              </p>
            </div>
            {[
              {
                head: 'Product',
                links: [
                  ['#what', 'What it is'],
                  ['#how', 'How it works'],
                  ['#features', 'Features'],
                  ['#demo', 'Demo'],
                ],
              },
              {
                head: 'Technical',
                links: [
                  ['/docs', 'API reference'],
                  ['/api/health', 'System status'],
                  ['/api/registry', 'Tool registry'],
                  ['/api/model', 'Model card'],
                ],
              },
              {
                head: 'Data sources',
                links: [
                  ['https://gibs.earthdata.nasa.gov', 'NASA GIBS'],
                  ['https://www.earthdata.nasa.gov', 'NASA Earthdata'],
                  ['https://dataspace.copernicus.eu', 'Copernicus'],
                  ['https://www.openstreetmap.org', 'OpenStreetMap'],
                ],
              },
            ].map((col) => (
              <div key={col.head}>
                <h3 className="text-micro font-semibold uppercase tracking-[0.13em] text-white/80">
                  {col.head}
                </h3>
                <ul className="mt-4 space-y-2.5">
                  {col.links.map(([href, label]) => (
                    <li key={label}>
                      <a
                        href={href}
                        target={href.startsWith('http') ? '_blank' : undefined}
                        rel="noreferrer"
                        className="text-small text-paper-300/65 transition-colors hover:text-white"
                      >
                        {label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-12 flex flex-col gap-3 border-t border-white/10 pt-7 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-tiny text-paper-300/55">
              © 2026 Team Avengers · Smart India Hackathon · SIH26167 (ISRO / Department of Space)
            </p>
            <p className="text-tiny text-paper-300/55">
              Imagery courtesy of NASA EOSDIS GIBS · EuroSAT (Helber et al., 2019)
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
