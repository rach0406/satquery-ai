import { useRef, useState } from 'react'
import { Icon } from './Icons'

const ACCEPT = '.tif,.tiff,.geotiff,.png,.jpg,.jpeg,.bmp,.webp'
const EXT_RE = /\.(tiff?|geotiff|png|jpe?g|bmp|webp)$/i

/* Image analysis as a first-class way in, not an accessory to the text box.
 *
 * Uploading a scene *is* a complete request — "here is an image, tell me what
 * is in it" — so this panel runs the analysis on its own with no question
 * typed. What it reports back is only what the file actually contained: a
 * GeoTIFF with a CRS gets areas in km², an ordinary photograph gets pixels and
 * says so. Neither is treated as a failure. */

function Line({ tone = 'info', children }) {
  const mark = tone === 'bad' ? '✕' : tone === 'ok' ? '✓' : 'ℹ'
  const colour =
    tone === 'bad' ? 'text-signal-red' : tone === 'ok' ? 'text-signal-green' : 'text-orbit-600'
  const text =
    tone === 'bad' ? 'text-signal-red' : tone === 'ok' ? 'text-ink-700' : 'text-ink-600'
  return (
    <li className="flex items-start gap-2">
      <span className={`mt-px shrink-0 font-semibold ${colour}`} aria-hidden="true">
        {mark}
      </span>
      <span className={`leading-relaxed ${text}`}>{children}</span>
    </li>
  )
}

export default function UploadPanel({
  scenes = [],
  activeScene,
  onSelectScene,
  onUpload,
  onAnalyse,
  busy,
}) {
  const fileRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [state, setState] = useState(null) // {tone, title, lines[], sceneId}
  const [uploading, setUploading] = useState(false)

  async function ingest(file) {
    if (!file) return
    if (!EXT_RE.test(file.name)) {
      setState({
        tone: 'err',
        title: file.name,
        lines: [
          {
            tone: 'bad',
            text:
              'Unsupported file type. Upload a GeoTIFF/TIFF for geospatial imagery, ' +
              'or a PNG, JPEG, BMP or WebP for an ordinary image.',
          },
        ],
      })
      return
    }
    setUploading(true)
    setState({ tone: 'info', title: file.name, lines: [{ tone: 'info', text: 'Reading the file…' }] })
    try {
      const res = await onUpload(file)
      const s = res.scene
      const meta = s.metadata || {}
      const geo = s.spatial_reference === 'georeferenced'
      const basis = s.capabilities?.band_basis
      const lines = [
        { tone: 'ok', text: `Loaded — ${s.width} × ${s.height} pixels` },
        {
          tone: 'ok',
          text: `${s.band_count} band${s.band_count === 1 ? '' : 's'}${
            basis === 'multispectral'
              ? ' (multispectral)'
              : basis === 'rgb'
                ? ' (RGB)'
                : ' (single channel)'
          }`,
        },
      ]
      if (meta.original_size) {
        lines.push({
          tone: 'info',
          text: `Downscaled from ${meta.original_size[0]} × ${meta.original_size[1]} for analysis`,
        })
      }
      if (geo) {
        lines.push({ tone: 'ok', text: `Georeferenced — CRS ${meta.crs || 'detected'}` })
        lines.push({ tone: 'ok', text: 'Results will be placed on the map, areas in km²' })
      } else {
        lines.push({
          tone: 'info',
          text:
            'No map projection in this file, so it is analysed in pixel space. ' +
            'Every image measurement still runs; sizes are reported in pixels.',
        })
      }
      const idx = s.capabilities?.available?.spectral_indices || []
      if (idx.length) lines.push({ tone: 'ok', text: `Indices available: ${idx.join(', ')}` })
      if (res.note) lines.push({ tone: 'info', text: res.note })

      setState({
        tone: geo ? 'ok' : 'info',
        title: s.name,
        lines,
        sceneId: s.scene_id,
        thumbnail: res.thumbnail,
      })
      onSelectScene?.(s.scene_id)
    } catch (err) {
      setState({
        tone: 'err',
        title: file.name,
        lines: [{ tone: 'bad', text: err.message || 'The upload failed.' }],
      })
    } finally {
      setUploading(false)
    }
  }

  const readyId = state?.sceneId || activeScene

  return (
    <div className="flex flex-col gap-6">
      {/* ------------------------------------------------ drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          ingest(e.dataTransfer.files?.[0])
        }}
        className={`rounded-panel border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragging
            ? 'border-orbit-500 bg-orbit-50'
            : 'border-paper-400 bg-paper-50 hover:border-orbit-300'
        }`}
      >
        <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-orbit-600 shadow-card">
          <Icon.upload size={24} />
        </span>
        <h3 className="mt-5 text-h4 text-ink-900">Drop a satellite image here</h3>
        <p className="mx-auto mt-2.5 max-w-md text-base leading-relaxed text-ink-500">
          GeoTIFF and TIFF keep their projection and band metadata. PNG, JPEG, BMP and
          WebP are analysed too — in pixel space rather than on the map.
        </p>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="btn-primary btn-lg mt-6"
        >
          {uploading ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Uploading…
            </>
          ) : (
            <>
              <Icon.upload size={16} /> Choose a file
            </>
          )}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          onChange={(e) => {
            ingest(e.target.files?.[0])
            e.target.value = ''
          }}
          className="hidden"
        />
        <p className="mono mt-5 text-ink-400">.tif · .tiff · .geotiff · .png · .jpg · .bmp · .webp</p>
      </div>

      {/* ------------------------------------------------ ingest report */}
      {state && (
        <div
          className={`animate-floatUp rounded-panel border p-6 ${
            state.tone === 'err'
              ? 'border-signal-red/30 bg-signal-red/[0.05]'
              : state.tone === 'info'
                ? 'border-orbit-200 bg-orbit-50/60'
                : 'border-signal-green/30 bg-signal-green/[0.05]'
          }`}
        >
          <div className="flex flex-col gap-6 sm:flex-row">
            {state.thumbnail && (
              <img
                src={state.thumbnail}
                alt="Uploaded scene preview"
                className="h-36 w-36 shrink-0 rounded-card border border-paper-300 object-cover shadow-card"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="text-micro font-semibold uppercase tracking-[0.13em] text-ink-400">
                {state.tone === 'err' ? 'Could not read this file' : 'File inspected'}
              </div>
              <div className="mt-1.5 truncate text-h5 font-semibold text-ink-900" title={state.title}>
                {state.title}
              </div>
              <ul className="mt-3.5 flex flex-col gap-1.5 text-small">
                {state.lines.map((l, i) => (
                  <Line key={i} tone={l.tone}>
                    {l.text}
                  </Line>
                ))}
              </ul>
              {state.tone !== 'err' && (
                <button
                  onClick={() => onAnalyse(state.sceneId)}
                  disabled={busy}
                  className="btn-primary btn-lg mt-6"
                >
                  {busy ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                      Analysing…
                    </>
                  ) : (
                    <>
                      <Icon.send size={16} /> Analyse this image
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------ previously loaded */}
      {scenes.length > 0 && (
        <div className="rounded-panel border border-paper-300 bg-white p-6">
          <div className="text-micro font-semibold uppercase tracking-[0.13em] text-ink-400">
            Scenes already loaded
          </div>
          <p className="mt-1.5 text-small text-ink-400">
            Select one to analyse it again — no re-upload needed.
          </p>
          <div className="mt-4 flex flex-col gap-2">
            {scenes.map((s) => {
              const active = activeScene === s.scene_id
              return (
                <div
                  key={s.scene_id + s.filename}
                  className={`flex items-center gap-3 rounded-card border px-4 py-3 transition-colors ${
                    active
                      ? 'border-orbit-300 bg-orbit-50'
                      : 'border-paper-300 bg-paper-50 hover:bg-paper-100'
                  }`}
                >
                  <Icon.layers size={15} className="shrink-0 text-ink-400" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-small font-medium text-ink-800">
                      {s.filename}
                    </span>
                    <span className="mono mt-0.5 block text-ink-400">
                      {s.modality || s.kind}
                      {s.width ? ` · ${s.width}×${s.height}` : ''}
                      {s.bbox ? ' · georeferenced' : ' · pixel space'}
                    </span>
                  </span>
                  <button
                    onClick={() => onAnalyse(s.scene_id)}
                    disabled={busy}
                    className="btn-secondary shrink-0 !py-2"
                  >
                    Analyse
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {readyId && (
        <p className="text-center text-small text-ink-400">
          Active scene <span className="mono">{readyId}</span>. You can also switch to
          &ldquo;Ask a question&rdquo; and ask something specific about it.
        </p>
      )}
    </div>
  )
}
