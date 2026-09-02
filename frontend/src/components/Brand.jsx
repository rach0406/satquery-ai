import { Link } from 'react-router-dom'

/* ------------------------------------------------------------------ logo */
export function Logo({ size = 34, className = '' }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} className={className} aria-hidden="true">
      <defs>
        <linearGradient id="sq-logo-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#3b78f6" />
          <stop offset="100%" stopColor="#0d7d8a" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="10" fill="url(#sq-logo-g)" />
      <ellipse
        cx="20" cy="20" rx="13" ry="6.2"
        fill="none" stroke="#ffffff" strokeOpacity=".55" strokeWidth="1.6"
        transform="rotate(-28 20 20)"
      />
      <circle cx="20" cy="20" r="5.6" fill="#ffffff" fillOpacity=".95" />
      <circle cx="20" cy="20" r="2.4" fill="#1d5bb8" />
      <circle cx="31.4" cy="13.4" r="2.5" fill="#ffffff" />
    </svg>
  )
}

export function Wordmark({ to = '/', tone = 'light', compact = false }) {
  const dark = tone === 'dark'
  const inner = (
    <span className="flex items-center gap-2.5">
      <Logo size={compact ? 30 : 34} />
      <span className="leading-none">
        <span
          className={`block font-display text-[1.0625rem] font-bold tracking-tight ${
            dark ? 'text-white' : 'text-ink-900'
          }`}
        >
          SatQuery&nbsp;AI
        </span>
        {!compact && (
          <span
            className={`mt-0.5 block text-[0.6875rem] font-medium tracking-wide ${
              dark ? 'text-paper-300/70' : 'text-ink-400'
            }`}
          >
            Agentic Remote-Sensing Analysis
          </span>
        )}
      </span>
    </span>
  )
  return to ? (
    <Link to={to} className="rounded-lg" aria-label="SatQuery AI home">
      {inner}
    </Link>
  ) : (
    inner
  )
}

/* ---------------------------------------------------------------- starfield */
const STARS = Array.from({ length: 64 }, (_, i) => {
  // Deterministic pseudo-random so the field never reflows between renders.
  const a = Math.sin(i * 12.9898) * 43758.5453
  const b = Math.sin(i * 78.233) * 12345.6789
  return {
    x: (a - Math.floor(a)) * 100,
    y: (b - Math.floor(b)) * 100,
    r: 0.5 + ((a - Math.floor(a)) * 1.3),
    d: 2 + ((b - Math.floor(b)) * 4),
  }
})

export function Starfield({ className = '' }) {
  return (
    <svg
      className={`pointer-events-none absolute inset-0 h-full w-full ${className}`}
      aria-hidden="true"
      preserveAspectRatio="none"
      viewBox="0 0 100 100"
    >
      {STARS.map((s, i) => (
        <circle
          key={i}
          cx={s.x}
          cy={s.y}
          r={s.r * 0.09}
          fill="#cfe0ff"
          opacity="0.5"
          style={{ animation: `twinkle ${s.d}s ease-in-out ${(i % 7) * 0.4}s infinite` }}
        />
      ))}
    </svg>
  )
}

/* ------------------------------------------------------------ orbit visual */
export function OrbitVisual({ className = '' }) {
  return (
    <svg viewBox="0 0 420 420" className={className} aria-hidden="true">
      <defs>
        <radialGradient id="sq-earth" cx="38%" cy="32%">
          <stop offset="0%" stopColor="#3b78f6" />
          <stop offset="55%" stopColor="#1d5bb8" />
          <stop offset="100%" stopColor="#0a1424" />
        </radialGradient>
        <linearGradient id="sq-ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#93bbfd" stopOpacity=".85" />
          <stop offset="60%" stopColor="#0d7d8a" stopOpacity=".35" />
          <stop offset="100%" stopColor="#93bbfd" stopOpacity=".1" />
        </linearGradient>
        <linearGradient id="sq-beam" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#93bbfd" stopOpacity=".55" />
          <stop offset="100%" stopColor="#93bbfd" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* planet */}
      <circle cx="210" cy="232" r="118" fill="url(#sq-earth)" />
      {/* continents, abstract */}
      <g fill="#12855c" opacity=".55">
        <path d="M158 186c22-12 46-6 60 6s34 10 44 24-10 26-30 24-30 10-48 2-38-18-38-32 6-18 12-24z" />
        <path d="M232 288c16-8 34-4 42 6s-2 22-18 26-34 2-38-10 4-18 14-22z" />
        <path d="M136 250c12-4 22 2 24 12s-8 18-20 16-16-10-14-18 4-8 10-10z" />
      </g>
      {/* latitude sweep */}
      <g opacity=".35" stroke="#cfe0ff" strokeWidth="1" fill="none">
        <ellipse cx="210" cy="232" rx="118" ry="34" />
        <ellipse cx="210" cy="232" rx="118" ry="68" />
        <path d="M210 114v236" />
      </g>

      {/* orbital ring + satellite */}
      <g style={{ transformOrigin: '210px 232px', animation: 'orbitSpin 26s linear infinite' }}>
        <ellipse
          cx="210" cy="232" rx="176" ry="72"
          fill="none" stroke="url(#sq-ring)" strokeWidth="2.5"
          transform="rotate(-24 210 232)"
        />
        <g transform="translate(370 190) rotate(-24)">
          <rect x="-7" y="-6" width="14" height="12" rx="2.5" fill="#eef3f9" />
          <rect x="-22" y="-3.5" width="13" height="7" rx="1.5" fill="#6096fa" />
          <rect x="9" y="-3.5" width="13" height="7" rx="1.5" fill="#6096fa" />
          <path d="M0 6 L-13 44 L13 44 Z" fill="url(#sq-beam)" />
        </g>
      </g>

      {/* second, faster orbit */}
      <g style={{ transformOrigin: '210px 232px', animation: 'orbitSpin 16s linear infinite reverse' }}>
        <ellipse
          cx="210" cy="232" rx="150" ry="50"
          fill="none" stroke="#0d7d8a" strokeOpacity=".3" strokeWidth="1.5"
          transform="rotate(28 210 232)"
        />
        <circle cx="60" cy="255" r="4" fill="#5eead4" />
      </g>
    </svg>
  )
}

/* ------------------------------------------------------------- section head */
export function SectionHead({ eyebrow, title, lede, center = false, className = '' }) {
  return (
    <div className={`${center ? 'mx-auto text-center' : ''} max-w-3xl ${className}`}>
      {eyebrow && (
        <p className={`eyebrow ${center ? 'justify-center' : ''}`}>
          <span className="h-1 w-1 rounded-full bg-orbit-500" />
          {eyebrow}
        </p>
      )}
      <h2 className="text-h2 lg:text-[2.25rem] lg:leading-[2.75rem]">{title}</h2>
      {lede && <p className={`lede mt-4 ${center ? 'mx-auto' : ''}`}>{lede}</p>}
    </div>
  )
}
