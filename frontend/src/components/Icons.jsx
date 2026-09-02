/* Minimal inline icon set — no external icon package, so the bundle stays
   self-contained and nothing has to load at demo time. */
const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Svg({ size = 16, children, className = '', viewBox = '0 0 24 24' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      className={className}
      aria-hidden="true"
      {...base}
    >
      {children}
    </svg>
  )
}

export const Icon = {
  satellite: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="3" />
      <circle cx="12" cy="12" r="7.5" />
      <path d="M4.2 4.2l2.6 2.6M19.8 4.2l-2.6 2.6M4.2 19.8l2.6-2.6M19.8 19.8l-2.6-2.6" />
    </Svg>
  ),
  send: (p) => (
    <Svg {...p}>
      <path d="M4 12l16-8-6 8 6 8z" />
    </Svg>
  ),
  droplet: (p) => (
    <Svg {...p}>
      <path d="M12 3s6 6.4 6 10.2A6 6 0 016 13.2C6 9.4 12 3 12 3z" />
    </Svg>
  ),
  leaf: (p) => (
    <Svg {...p}>
      <path d="M4 20c8 1 15-4 16-16-9 0-15 3-16 10-.4 3 0 6 0 6z" />
      <path d="M4 20c3-5 7-8 12-10" />
    </Svg>
  ),
  layers: (p) => (
    <Svg {...p}>
      <path d="M12 3l9 5-9 5-9-5 9-5z" />
      <path d="M3 13l9 5 9-5M3 17l9 5 9-5" />
    </Svg>
  ),
  radar: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <path d="M12 12l6-4" />
    </Svg>
  ),
  gitCompare: (p) => (
    <Svg {...p}>
      <circle cx="6" cy="18" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <path d="M6 15.5V9a3 3 0 013-3h6M18 8.5V15a3 3 0 01-3 3H9" />
    </Svg>
  ),
  crosshair: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
    </Svg>
  ),
  map: (p) => (
    <Svg {...p}>
      <path d="M9 4L3 6.5v14L9 18l6 2.5 6-2.5v-14L15 6.5 9 4z" />
      <path d="M9 4v14M15 6.5v14" />
    </Svg>
  ),
  chart: (p) => (
    <Svg {...p}>
      <path d="M3 21h18" />
      <path d="M6 17V9M11 17V5M16 17v-6M21 17v-3" />
    </Svg>
  ),
  table: (p) => (
    <Svg {...p}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M3 15h18M9.5 4v16" />
    </Svg>
  ),
  shield: (p) => (
    <Svg {...p}>
      <path d="M12 3l7.5 3v5.5c0 5-3.2 8.4-7.5 9.5-4.3-1.1-7.5-4.5-7.5-9.5V6L12 3z" />
      <path d="M9 12l2 2 4-4" />
    </Svg>
  ),
  cpu: (p) => (
    <Svg {...p}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="10" y="10" width="4" height="4" rx="1" />
      <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
    </Svg>
  ),
  list: (p) => (
    <Svg {...p}>
      <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
    </Svg>
  ),
  db: (p) => (
    <Svg {...p}>
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </Svg>
  ),
  upload: (p) => (
    <Svg {...p}>
      <path d="M12 16V4M8 8l4-4 4 4" />
      <path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
    </Svg>
  ),
  download: (p) => (
    <Svg {...p}>
      <path d="M12 4v12M8 12l4 4 4-4" />
      <path d="M4 18v1a2 2 0 002 2h12a2 2 0 002-2v-1" />
    </Svg>
  ),
  alert: (p) => (
    <Svg {...p}>
      <path d="M12 4l9 16H3l9-16z" />
      <path d="M12 10v4M12 17h.01" />
    </Svg>
  ),
  help: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 013.9-2c1.4.9 1 2.6-.4 3.4-.7.4-1 .9-1 1.6M12 17h.01" />
    </Svg>
  ),
  check: (p) => (
    <Svg {...p}>
      <path d="M4 12.5l5 5L20 6.5" />
    </Svg>
  ),
  x: (p) => (
    <Svg {...p}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
  ),
  clock: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.3l3.4 2" />
    </Svg>
  ),
  spark: (p) => (
    <Svg {...p}>
      <path d="M12 3l2.1 5.6L20 10.5l-5.2 2.4L12 19l-2.8-6.1L4 10.5l5.9-1.9L12 3z" />
    </Svg>
  ),
  flame: (p) => (
    <Svg {...p}>
      <path d="M12 21a6 6 0 006-6c0-4-4-5.5-4-9 0 0-3 1.5-3 5 0 1.5-1 2-1 2s-1-1-1-2.5C7 12 6 13 6 15a6 6 0 006 6z" />
    </Svg>
  ),
  activity: (p) => (
    <Svg {...p}>
      <path d="M3 12h4l3 8 4-16 3 8h4" />
    </Svg>
  ),
  building: (p) => (
    <Svg {...p}>
      <rect x="4" y="3" width="16" height="18" rx="1.5" />
      <path d="M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01M10.5 21v-3h3v3" />
    </Svg>
  ),
  grid: (p) => (
    <Svg {...p}>
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
    </Svg>
  ),
  waves: (p) => (
    <Svg {...p}>
      <path d="M3 8c2.5-2 4.5 2 7 0s4.5-2 7 0M3 14c2.5-2 4.5 2 7 0s4.5-2 7 0M3 20c2.5-2 4.5 2 7 0s4.5-2 7 0" />
    </Svg>
  ),
  trendingUp: (p) => (
    <Svg {...p}>
      <path d="M3 17l6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </Svg>
  ),
  fileText: (p) => (
    <Svg {...p}>
      <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </Svg>
  ),
  sun: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
  ),
  chevron: (p) => (
    <Svg {...p}>
      <path d="M9 6l6 6-6 6" />
    </Svg>
  ),
  refresh: (p) => (
    <Svg {...p}>
      <path d="M20 11a8 8 0 10-2.3 6.1" />
      <path d="M20 5v6h-6" />
    </Svg>
  ),
  info: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </Svg>
  ),
  eye: (p) => (
    <Svg {...p}>
      <path d="M2 12s3.8-6.5 10-6.5S22 12 22 12s-3.8 6.5-10 6.5S2 12 2 12z" />
      <circle cx="12" cy="12" r="2.75" />
    </Svg>
  ),
  link: (p) => (
    <Svg {...p}>
      <path d="M10.5 13.5a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1.4 1.4" />
      <path d="M13.5 10.5a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1.4-1.4" />
    </Svg>
  ),
}

export const ICON_BY_NAME = {
  droplet: Icon.droplet,
  leaf: Icon.leaf,
  'file-text': Icon.fileText,
  sun: Icon.sun,
  crosshair: Icon.crosshair,
  building: Icon.building,
  'git-compare': Icon.gitCompare,
  waves: Icon.waves,
  'trending-up': Icon.trendingUp,
  layers: Icon.layers,
  radar: Icon.radar,
  grid: Icon.grid,
  flame: Icon.flame,
  activity: Icon.activity,
  'alert-triangle': Icon.alert,
  'help-circle': Icon.help,
}
