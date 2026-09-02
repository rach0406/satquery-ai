import { useState } from 'react'
import Chart from './Chart'
import MapView from './MapView'
import { Icon } from './Icons'
import { duration, fmtFact, num, ORIGIN_META, titleCase } from '../lib/format'

/* ---------------------------------------------------------------- shared */
export function Empty({ icon: I = Icon.info, title, children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-panel border border-dashed border-paper-400 bg-paper-50 px-8 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-paper-200 text-ink-400">
        <I size={22} />
      </span>
      <div className="text-h5 font-semibold text-ink-700">{title}</div>
      {children && (
        <div className="max-w-prose text-small leading-relaxed text-ink-400">{children}</div>
      )}
    </div>
  )
}

export function OriginBadge({ origin }) {
  const m = ORIGIN_META[origin] || ORIGIN_META.synthetic_demo
  return (
    <span className={`chip ${m.tone}`} title={m.hint}>
      {m.real ? <Icon.check size={11} /> : <Icon.alert size={11} />}
      {m.label}
    </span>
  )
}

function DataTable({ columns, rows }) {
  if (!rows?.length) return null
  return (
    <div className="table-wrap">
      <table className="dtable">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className="whitespace-nowrap">
                  {typeof r[c.key] === 'number' ? num(r[c.key], 4) : (r[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ---------------------------------------------------------------- panels */
export function MapPanel({ result }) {
  const overlays = result.artifacts.filter((a) => a.kind === 'image_overlay' || a.kind === 'boxes')
  if (!overlays.length) {
    return (
      <Empty icon={Icon.map} title="No spatial output for this query">
        This analysis produced statistics but no georeferenced raster. Charts and tables hold the
        result.
      </Empty>
    )
  }
  return <MapView artifacts={result.artifacts} bbox={result.plan?.bbox} height={540} />
}

export function ChartsPanel({ result }) {
  const charts = result.artifacts.filter((a) => a.kind === 'chart' || a.kind === 'histogram')
  if (!charts.length) {
    return (
      <Empty icon={Icon.chart} title="No charts for this query">
        Nothing quantitative was distributed over a dimension worth plotting.
      </Empty>
    )
  }
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      {charts.map((c) => (
        <section key={c.id} className="panel overflow-hidden">
          <div className="panel-head">
            <span className="panel-title truncate">{c.title}</span>
          </div>
          <div className="px-3 pb-3 pt-5">
            <Chart spec={c.spec} height={266} />
          </div>
          {c.description && (
            <p className="border-t border-paper-200 px-5 py-3.5 text-tiny leading-relaxed text-ink-400">
              {c.description}
            </p>
          )}
        </section>
      ))}
    </div>
  )
}

export function TablesPanel({ result }) {
  const tables = result.artifacts.filter((a) => a.kind === 'table')
  if (!tables.length && !result.facts?.length) {
    return <Empty icon={Icon.table} title="No tabular output for this query" />
  }
  return (
    <div className="flex flex-col gap-6">
      {tables.map((t) => (
        <section key={t.id} className="panel overflow-hidden">
          <div className="panel-head">
            <span className="panel-title">{t.title}</span>
            <span className="mono text-ink-400">{t.spec?.row_count ?? 0} rows</span>
          </div>
          <div className="p-5">
            <DataTable columns={t.spec?.columns || []} rows={t.spec?.rows || []} />
            {t.description && (
              <p className="mt-3 text-tiny leading-relaxed text-ink-400">{t.description}</p>
            )}
          </div>
        </section>
      ))}
      <FactsTable facts={result.facts} />
    </div>
  )
}

export function FactsTable({ facts = [] }) {
  const [open, setOpen] = useState(false)
  if (!facts.length) return null
  const shown = open ? facts : facts.slice(0, 12)
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head">
        <div>
          <span className="panel-title">Fact store</span>
          <p className="mt-1 text-tiny text-ink-400">Every measured quantity, with its method</p>
        </div>
        <span className="mono text-ink-400">{facts.length} facts</span>
      </div>
      <div className="p-5">
        <div className="table-wrap">
          <table className="dtable">
            <thead>
              <tr>
                {['Quantity', 'Value', 'Measured by', 'How it was computed'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((f) => (
                <tr key={f.key}>
                  <td>
                    <div className="font-medium text-ink-800">{f.label}</div>
                    <div className="mono mt-0.5 text-ink-400">{f.key}</div>
                  </td>
                  <td className="whitespace-nowrap font-mono text-small font-semibold text-orbit-700">
                    {fmtFact(f)}
                  </td>
                  <td className="whitespace-nowrap">
                    <span className="mono text-ink-500">{f.tool}</span>
                  </td>
                  <td className="text-tiny leading-relaxed text-ink-400">{f.method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {facts.length > 12 && (
          <button onClick={() => setOpen(!open)} className="btn-secondary mt-4 w-full">
            {open ? 'Show fewer' : `Show all ${facts.length} facts`}
          </button>
        )}
      </div>
    </section>
  )
}

export function TracePanel({ result }) {
  const [openStep, setOpenStep] = useState(null)
  const trace = result.execution_trace || []
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head">
        <div>
          <span className="panel-title">Auditable execution trace</span>
          <p className="mt-1 text-tiny text-ink-400">Open any step to see the exact parameters</p>
        </div>
        <span className="mono text-ink-400">
          {trace.length} steps · {duration(result.total_duration_ms)}
        </span>
      </div>
      <div className="divide-y divide-paper-200">
        {trace.map((c) => {
          const open = openStep === c.step
          const tone =
            c.status === 'ok'
              ? 'text-signal-green'
              : c.status === 'skipped'
                ? 'text-ink-400'
                : c.status === 'no_data'
                  ? 'text-signal-amber'
                  : 'text-signal-red'
          return (
            <div key={c.step}>
              <button
                onClick={() => setOpenStep(open ? null : c.step)}
                className="flex w-full items-start gap-3.5 px-5 py-4 text-left transition-colors hover:bg-paper-50"
              >
                <span className="mono mt-0.5 w-5 shrink-0 text-ink-300">{c.step}</span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="mono text-small font-semibold text-ink-800">{c.tool}</span>
                    <span className="chip-neutral">v{c.tool_version}</span>
                    <span className={`text-micro font-bold uppercase tracking-wider ${tone}`}>
                      {c.status}
                    </span>
                    {c.confidence != null && (
                      <span className="mono text-ink-400">conf {c.confidence.toFixed(2)}</span>
                    )}
                  </span>
                  {c.message && (
                    <span className="mt-1.5 block text-small leading-relaxed text-ink-500">
                      {c.message}
                    </span>
                  )}
                </span>
                <span className="mono shrink-0 pt-0.5 text-ink-400">{duration(c.duration_ms)}</span>
                <Icon.chevron
                  size={15}
                  className={`mt-0.5 shrink-0 text-ink-300 transition-transform ${
                    open ? 'rotate-90' : ''
                  }`}
                />
              </button>
              {open && (
                <div className="animate-fadeIn bg-paper-50 px-5 pb-4 pt-1">
                  <div className="mb-2.5 flex flex-wrap gap-4 text-tiny text-ink-400">
                    {c.fact_keys?.length > 0 && <span>{c.fact_keys.length} facts produced</span>}
                    {c.artifact_ids?.length > 0 && (
                      <span>{c.artifact_ids.length} artefacts produced</span>
                    )}
                    {c.started_at && <span>started {c.started_at}</span>}
                  </div>
                  <pre className="max-h-72 overflow-auto rounded-card border border-paper-300 bg-white p-4 font-mono text-tiny leading-relaxed text-ink-600">
                    {JSON.stringify(c.parameters, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

export function GroundingPanel({ result }) {
  const g = result.grounding || {}
  const rate = g.claims_checked ? g.claims_verified / g.claims_checked : 1
  const narratorLabel = {
    template: 'Deterministic template',
    llm: 'LLM narration (verified)',
    llm_rejected_fallback_template: 'LLM output REJECTED → template used',
  }[g.narrator]

  return (
    <div className="flex flex-col gap-6">
      <section className="panel overflow-hidden">
        <div className="panel-head">
          <div>
            <span className="panel-title">Grounding verification</span>
            <p className="mt-1 text-tiny text-ink-400">
              Every numeral in the answer, checked against the fact store
            </p>
          </div>
          <span className={`chip ${g.passed ? 'chip-ok' : 'chip-bad'}`}>
            {g.passed ? <Icon.shield size={12} /> : <Icon.alert size={12} />}
            {g.passed ? 'All numbers traced' : 'Ungrounded numbers blocked'}
          </span>
        </div>

        <div className="grid gap-px bg-paper-300 sm:grid-cols-4">
          {[
            { label: 'Numeric claims', value: g.claims_checked ?? 0 },
            { label: 'Traced to a fact', value: g.claims_verified ?? 0 },
            { label: 'Facts in store', value: g.fact_count ?? 0 },
            { label: 'Sources', value: `${(result.provenance || []).length} real` },
          ].map((s) => (
            <div key={s.label} className="bg-white px-5 py-5">
              <div className="text-micro font-semibold uppercase tracking-[0.12em] text-ink-400">
                {s.label}
              </div>
              <div className="mt-2 font-mono text-h3 font-semibold tabular-nums text-ink-900">
                {s.value}
              </div>
            </div>
          ))}
        </div>

        <div className="px-5 py-5">
          <div className="mb-2 flex items-center justify-between text-small text-ink-500">
            <span className="font-medium">Verification rate</span>
            <span className="mono font-semibold text-ink-700">{(rate * 100).toFixed(0)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-paper-300">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                g.passed ? 'bg-signal-green' : 'bg-signal-red'
              }`}
              style={{ width: `${rate * 100}%` }}
            />
          </div>
          <p className="mt-4 max-w-prose text-small leading-relaxed text-ink-600">
            {g.explanation}
          </p>
          <div className="mt-3.5 flex flex-wrap gap-2">
            <span className="chip-neutral">narrator: {narratorLabel}</span>
            <span className="chip-neutral">strict mode: {g.strict_mode ? 'on' : 'off'}</span>
          </div>
        </div>

        {g.rejected_claims?.length > 0 && (
          <div className="border-t border-signal-red/20 bg-signal-red/[0.05] px-5 py-4">
            <div className="mb-2.5 text-micro font-semibold uppercase tracking-[0.13em] text-signal-red">
              Rejected — not backed by any measurement
            </div>
            <div className="flex flex-wrap gap-2">
              {g.rejected_claims.map((c, i) => (
                <span key={i} className="chip-bad">
                  <span className="mono">{c.text}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {g.verified_claims?.length > 0 && (
          <details className="border-t border-paper-200">
            <summary className="cursor-pointer px-5 py-3.5 text-micro font-semibold uppercase tracking-[0.13em] text-ink-400 transition-colors hover:text-ink-700">
              Show all {g.verified_claims.length} traced numbers
            </summary>
            <div className="px-5 pb-5">
              <div className="table-wrap">
                <table className="dtable">
                  <thead>
                    <tr>
                      {['Number in text', 'Matched fact', 'How it matched'].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {g.verified_claims.map((c, i) => (
                      <tr key={i}>
                        <td className="font-mono font-semibold text-orbit-700">{c.text}</td>
                        <td className="font-mono text-ink-600">{c.matched_fact}</td>
                        <td className="text-tiny text-ink-400">{c.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </details>
        )}
      </section>

      <ProvenancePanel result={result} />
    </div>
  )
}

export function ProvenancePanel({ result }) {
  const provs = result.provenance || []
  if (!provs.length) {
    return <Empty icon={Icon.db} title="No data source was contacted for this outcome" />
  }
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head">
        <div>
          <span className="panel-title">Data provenance</span>
          <p className="mt-1 text-tiny text-ink-400">Exactly which pixels this answer came from</p>
        </div>
        <span className="mono text-ink-400">{provs.length} source(s)</span>
      </div>
      <div className="divide-y divide-paper-200">
        {provs.map((p, i) => (
          <div key={i} className="px-5 py-5">
            <div className="mb-3 flex flex-wrap items-center gap-2.5">
              <OriginBadge origin={p.origin} />
              <span className="text-h5 font-semibold text-ink-800">{p.source}</span>
            </div>
            <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ['Platform', p.platform],
                ['Instrument', p.instrument],
                ['Modality', titleCase(p.modality)],
                ['Acquired', p.acquisition_date],
                ['Resolution', p.resolution_m ? `${p.resolution_m} m` : null],
                ['CRS', p.crs],
                ['Retrieved', p.retrieved_at],
                ['Licence', p.license],
              ]
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <div
                    key={k}
                    className="flex items-baseline justify-between gap-3 border-b border-paper-200 pb-1.5 text-tiny"
                  >
                    <span className="text-ink-400">{k}</span>
                    <span className="mono truncate text-ink-700">{v}</span>
                  </div>
                ))}
            </div>
            {p.bbox && (
              <div className="mono mt-3 text-ink-400">
                bbox [{p.bbox.map((v) => v.toFixed(4)).join(', ')}]
              </div>
            )}
            {p.notes && (
              <p className="mt-2.5 text-tiny leading-relaxed text-signal-amber">{p.notes}</p>
            )}
            {p.source_url && (
              <a
                href={p.source_url}
                target="_blank"
                rel="noreferrer"
                className="mt-2.5 inline-flex items-center gap-1.5 text-tiny font-medium text-orbit-600 hover:text-orbit-700"
              >
                <Icon.link size={12} /> exact request URL used
              </a>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
