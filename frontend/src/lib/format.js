export const NBSP = ' '

export function num(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (typeof v !== 'number') return String(v)
  const abs = Math.abs(v)
  if (abs !== 0 && abs < 0.001) return v.toExponential(2)
  return v.toLocaleString(undefined, {
    minimumFractionDigits: Number.isInteger(v) && abs >= 1000 ? 0 : digits,
    maximumFractionDigits: digits,
  })
}

export function pct(v, digits = 2) {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function fmtFact(fact) {
  const { value, unit } = fact
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  switch (unit) {
    case 'fraction':
      return pct(value)
    case 'percent':
      return `${value > 0 ? '+' : ''}${num(value)}%`
    case 'km2':
      return `${num(value)}${NBSP}km²`
    case 'pixels':
      return `${num(value, 0)}${NBSP}px`
    case 'probability':
      return num(value, 3)
    case 'dates':
    case 'regions':
    case 'tiles':
    case 'scenes':
      return `${num(value, 0)}${NBSP}${unit}`
    default:
      return num(value, 4)
  }
}

export function duration(ms) {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)}${NBSP}ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}${NBSP}s`
}

export function titleCase(s) {
  return String(s || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export const ORIGIN_META = {
  live_satellite: {
    label: 'Live satellite',
    tone: 'text-signal-green border-signal-green/40 bg-signal-green/10',
    real: true,
    hint: 'Fetched now from a public NASA archive.',
  },
  cached_satellite: {
    label: 'Cached satellite',
    tone: 'text-signal-teal border-signal-teal/40 bg-signal-teal/10',
    real: true,
    hint: 'Real archive imagery served from the local disk cache.',
  },
  user_upload: {
    label: 'User upload',
    tone: 'text-orbit-700 border-orbit-200 bg-orbit-50',
    real: true,
    hint: 'Imagery you supplied.',
  },
  bundled_sample: {
    label: 'Bundled sample',
    tone: 'text-signal-violet border-signal-violet/40 bg-signal-violet/10',
    real: true,
    hint: 'Real imagery shipped with the repository.',
  },
  synthetic_demo: {
    label: 'SIMULATED — not real data',
    tone: 'text-signal-red border-signal-red/50 bg-signal-red/15',
    real: false,
    hint: 'Synthetic fallback. Never presented as a measurement of the real world.',
  },
}

export const STATUS_META = {
  ok: { label: 'OK', tone: 'text-signal-green border-signal-green/40 bg-signal-green/10' },
  no_data: { label: 'No data', tone: 'text-signal-amber border-signal-amber/40 bg-signal-amber/10' },
  needs_clarification: {
    label: 'Needs clarification',
    tone: 'text-signal-amber border-signal-amber/40 bg-signal-amber/10',
  },
  error: { label: 'Error', tone: 'text-signal-red border-signal-red/40 bg-signal-red/10' },
  skipped: { label: 'Skipped', tone: 'text-ink-500 border-paper-400 bg-paper-100' },
  unsupported: { label: 'Unsupported', tone: 'text-ink-500 border-paper-400 bg-paper-100' },
}

export const TASK_LABELS = {
  vqa: 'Visual question answering',
  caption: 'Scene description',
  grounding: 'Text-guided grounding',
  change_detection: 'Bi-temporal change detection',
  change_vqa: 'Change-based VQA',
  optical_sar_fusion: 'Optical–SAR fusion',
  landcover: 'Land-cover analysis',
  index_analysis: 'Spectral index analysis',
  time_series: 'Index time series',
  unsupported: 'Unsupported',
}

export const CONFIG_LABELS = {
  single_image: 'Single image',
  bitemporal_pair: 'Bi-temporal pair',
  cross_modal_pair: 'Cross-modal pair (optical + SAR)',
  no_image: 'Multi-date retrieval',
}

export function bboxCenter(bbox) {
  if (!bbox || bbox.length !== 4) return null
  return [(bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2]
}

export function bboxToLeaflet(bbox) {
  if (!bbox || bbox.length !== 4) return null
  return [
    [bbox[1], bbox[0]],
    [bbox[3], bbox[2]],
  ]
}

export function downloadJSON(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
