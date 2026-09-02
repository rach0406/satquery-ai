import { useEffect, useState } from 'react'
import { Icon } from './Icons'
import { num, titleCase } from '../lib/format'

/* The model registry, the sensor catalogue, the resolvable places and the
   system status are all real and all worth showing — they are what makes the
   pipeline auditable rather than a black box. They are simply not what someone
   needs on screen while composing a question, and as a permanent left rail
   they crowded out the one thing that mattered.

   So they live here, in a panel that slides in on request. Nothing was
   removed; it moved one click away. */

function Section({ title, icon: I, count, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-paper-200 last:border-0">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-6 py-4 text-left transition-colors hover:bg-paper-50"
      >
        <I size={16} className="shrink-0 text-orbit-600" />
        <span className="flex-1 text-small font-semibold text-ink-800">{title}</span>
        {count !== undefined && count !== null && (
          <span className="mono rounded bg-paper-200 px-2 py-0.5 text-ink-500">{count}</span>
        )}
        <Icon.chevron
          size={15}
          className={`text-ink-300 transition-transform ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && <div className="animate-fadeIn px-6 pb-6">{children}</div>}
    </div>
  )
}

export default function ReferenceDrawer({
  open,
  onClose,
  registry,
  catalog,
  health,
  onRun,
  busy,
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  const rs = health?.rs_model

  return (
    <>
      <div
        className="animate-fadeIn fixed inset-0 z-40 bg-night-950/45 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="System reference"
        className="animate-fadeIn fixed inset-y-0 right-0 z-50 flex w-full max-w-[30rem] flex-col bg-white shadow-float"
      >
        <header className="flex shrink-0 items-center gap-4 border-b border-paper-300 px-6 py-5">
          <div className="min-w-0 flex-1">
            <h2 className="text-h4 text-ink-900">System reference</h2>
            <p className="mt-1 text-small text-ink-400">
              What this system can run, and what it runs on
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close reference panel"
            className="rounded-lg p-2.5 text-ink-400 transition-colors hover:bg-paper-200 hover:text-ink-800"
          >
            <Icon.x size={18} />
          </button>
        </header>

        <div className="scroll-y min-h-0 flex-1">
          {/* ---------------- system status ---------------- */}
          <div className="border-b border-paper-200 bg-paper-50 px-6 py-5">
            <div className="mb-3 text-micro font-semibold uppercase tracking-[0.13em] text-ink-400">
              Live status
            </div>
            <div className="grid grid-cols-2 gap-4 text-small">
              {[
                ['Backend', health ? 'online' : 'offline', health ? 'ok' : 'bad'],
                [
                  'RS classifier',
                  rs?.available ? `${(rs.test_accuracy * 100).toFixed(1)}% acc` : 'not trained',
                  rs?.available ? 'ok' : 'warn',
                ],
                [
                  'Language layer',
                  health?.llm?.available ? health.llm.model : 'rules + template',
                  'neutral',
                ],
                [
                  'Strict grounding',
                  health?.strict_grounding ? 'on' : 'off',
                  health?.strict_grounding ? 'ok' : 'warn',
                ],
              ].map(([k, v, tone]) => (
                <div key={k}>
                  <div className="text-ink-400">{k}</div>
                  <div
                    className={`mono mt-1 font-semibold ${
                      tone === 'ok'
                        ? 'text-signal-green'
                        : tone === 'bad'
                          ? 'text-signal-red'
                          : tone === 'warn'
                            ? 'text-signal-amber'
                            : 'text-ink-700'
                    }`}
                  >
                    {v}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ---------------- registry ---------------- */}
          <Section
            title="Model & tool registry"
            icon={Icon.cpu}
            count={registry?.tools?.length}
            defaultOpen
          >
            <div className="flex flex-col gap-3">
              {(registry?.tools || []).map((t) => (
                <div key={t.name} className="rounded-card border border-paper-300 bg-paper-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-small font-semibold text-ink-800">{t.title}</span>
                    <span
                      className={`chip shrink-0 ${
                        t.status === 'ready' ? 'chip-ok' : 'chip-warn'
                      }`}
                    >
                      {t.status}
                    </span>
                  </div>
                  <div className="mono mt-2 text-ink-400">
                    {t.name} v{t.version} · {t.backend}
                  </div>
                  <p className="mt-2.5 text-small leading-relaxed text-ink-500">{t.description}</p>
                  {t.adapted_on && (
                    <p className="mt-2 text-tiny text-signal-violet">Adapted on: {t.adapted_on}</p>
                  )}
                  {t.metrics?.test_accuracy != null && (
                    <p className="mono mt-2 text-signal-green">
                      held-out accuracy {(t.metrics.test_accuracy * 100).toFixed(2)}% · macro-F1{' '}
                      {t.metrics.macro_f1?.toFixed(3)}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Section>

          {/* ---------------- data sources ---------------- */}
          <Section
            title="Satellite data sources"
            icon={Icon.satellite}
            count={catalog?.layers?.length}
          >
            <div className="flex flex-col gap-2">
              {(catalog?.layers || []).map((l) => (
                <div
                  key={l.key}
                  className="rounded-card border border-paper-300 bg-paper-50 px-4 py-3"
                  title={l.description}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-small font-medium text-ink-700">{l.title}</span>
                    <span className="mono shrink-0 text-ink-400">{l.resolution_m}m</span>
                  </div>
                  <div className="mono mt-1 text-ink-400">
                    {l.platform} · {l.instrument} · {titleCase(l.modality)}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-small leading-relaxed text-ink-400">
              Every layer is served by NASA GIBS over open WMS with no credentials — nothing
              to expire mid-demo.
            </p>
          </Section>

          {/* ---------------- places ---------------- */}
          <Section title="Areas resolved offline" icon={Icon.map} count={catalog?.places?.length}>
            <div className="flex flex-wrap gap-2">
              {(catalog?.places || []).map((p) => (
                <button
                  key={p.name}
                  disabled={busy}
                  onClick={() => {
                    onRun(`Describe the land cover over ${p.name}`)
                    onClose()
                  }}
                  title={`${p.kind} · ${num(p.area_km2, 0)} km²${p.note ? ` · ${p.note}` : ''}`}
                  className="rounded-pill bg-paper-200 px-3 py-1.5 text-small text-ink-500 transition-colors hover:bg-orbit-100 hover:text-orbit-700 disabled:opacity-45"
                >
                  {p.name}
                </button>
              ))}
            </div>
            <p className="mt-4 text-small leading-relaxed text-ink-400">
              Any other place name is resolved live through OpenStreetMap Nominatim, so the
              list is a fast path rather than a limit.
            </p>
          </Section>

          {/* ---------------- the promise ---------------- */}
          <div className="border-t border-paper-200 bg-signal-green/[0.05] px-6 py-5">
            <div className="flex items-start gap-3">
              <Icon.shield size={16} className="mt-0.5 shrink-0 text-signal-green" />
              <p className="text-small leading-relaxed text-ink-600">
                <span className="font-semibold text-signal-green">Grounded by construction.</span>{' '}
                Every figure is measured from real satellite pixels. The language layer parses
                the question and phrases the answer — it never produces a number, and each
                numeral it writes is traced back to a measurement before you see it.
              </p>
            </div>
          </div>
        </div>
      </aside>
    </>
  )
}
