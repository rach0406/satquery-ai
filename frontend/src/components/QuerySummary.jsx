import { Icon } from './Icons'

/* The short digest that answers three questions in one glance:
 * what did I ask, what did the system do, and what did it find.
 *
 * Everything rendered here comes from `result.summary`, which the backend
 * builds from the facts it actually measured. This component adds no data of
 * its own — it only lays the sections out and decides which get emphasis.
 * Sections the backend omitted are simply absent, which is why there is no
 * "not available" placeholder logic anywhere below. */

const KIND_STYLE = {
  understanding: { icon: Icon.spark, tone: 'text-orbit-700', bg: 'bg-orbit-100', dot: 'bg-orbit-600', lead: true },
  scope: { icon: Icon.alert, tone: 'text-signal-amber', bg: 'bg-signal-amber/15', dot: 'bg-signal-amber', lead: true },
  performed: { icon: Icon.cpu, tone: 'text-signal-violet', bg: 'bg-signal-violet/12', dot: 'bg-signal-violet', lead: true },
  findings: { icon: Icon.chart, tone: 'text-signal-green', bg: 'bg-signal-green/12', dot: 'bg-signal-green', lead: true },
  detected: { icon: Icon.eye, tone: 'text-signal-green', bg: 'bg-signal-green/12', dot: 'bg-signal-green' },
  measure: { icon: Icon.activity, tone: 'text-signal-amber', bg: 'bg-signal-amber/12', dot: 'bg-signal-amber' },
  location: { icon: Icon.map, tone: 'text-signal-teal', bg: 'bg-signal-teal/12', dot: 'bg-signal-teal' },
  geo: { icon: Icon.crosshair, tone: 'text-signal-teal', bg: 'bg-signal-teal/12', dot: 'bg-signal-teal' },
  'geo-none': { icon: Icon.info, tone: 'text-ink-400', bg: 'bg-paper-200', dot: 'bg-ink-300' },
  image: { icon: Icon.layers, tone: 'text-signal-violet', bg: 'bg-signal-violet/12', dot: 'bg-signal-violet' },
  quality: { icon: Icon.shield, tone: 'text-signal-green', bg: 'bg-signal-green/12', dot: 'bg-signal-green' },
  outcome: { icon: Icon.alert, tone: 'text-signal-amber', bg: 'bg-signal-amber/12', dot: 'bg-signal-amber' },
  query: { icon: Icon.spark, tone: 'text-orbit-600', bg: 'bg-orbit-50', dot: 'bg-orbit-600' },
  info: { icon: Icon.info, tone: 'text-ink-400', bg: 'bg-paper-200', dot: 'bg-ink-300' },
}

function Card({ section, wide }) {
  const style = KIND_STYLE[section.kind] || KIND_STYLE.info
  const I = style.icon || Icon.info
  return (
    <div className={`px-7 py-6 ${wide ? 'sm:col-span-2' : ''}`}>
      <div className="mb-3.5 flex items-center gap-2.5">
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${style.bg} ${style.tone}`}
        >
          <I size={14} />
        </span>
        <h4 className="text-small font-bold uppercase tracking-[0.1em] text-ink-500">
          {section.title}
        </h4>
      </div>
      <ul className="flex flex-col gap-2.5">
        {section.points.map((p, j) => (
          <li key={j} className="flex items-start gap-2.5">
            {/* Tailwind only sees class names that appear literally in the
                source, so the dot colour is a field on the style table rather
                than a string derived from `tone` at runtime. */}
            <span
              className={`mt-[0.5rem] h-1.5 w-1.5 shrink-0 rounded-full ${style.dot || 'bg-ink-300'}`}
            />
            <span className="min-w-0 break-words text-base leading-relaxed text-ink-700">{p}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function QuerySummary({ summary = [] }) {
  if (!summary.length) return null

  // The narrative sections — how the query was read, what was measured — get
  // the full width. The supporting detail pairs up beneath them.
  const lead = summary.filter((s) => KIND_STYLE[s.kind]?.lead)
  const rest = summary.filter((s) => !KIND_STYLE[s.kind]?.lead)

  return (
    <section className="panel overflow-hidden" aria-label="Query summary" data-testid="query-summary">
      <div className="flex items-center gap-3.5 border-b border-paper-200 bg-gradient-to-r from-orbit-50 to-transparent px-7 py-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-orbit-600 text-white">
          <Icon.list size={17} />
        </span>
        <div className="min-w-0">
          <h3 className="text-h5 font-bold text-ink-900">Query summary</h3>
          <p className="mt-1 text-small text-ink-400">
            What SatQuery AI understood, what it did, and what it found
          </p>
        </div>
      </div>

      <div className="divide-y divide-paper-200">
        {lead.map((s, i) => (
          <Card key={`${s.title}-${i}`} section={s} />
        ))}
      </div>

      {rest.length > 0 && (
        <div className="grid gap-px border-t border-paper-200 bg-paper-200 sm:grid-cols-2">
          {rest.map((s, i) => (
            <div
              key={`${s.title}-${i}`}
              /* An odd count would otherwise leave a bare grey cell at the
                 end of the grid, so the last card takes the full row. */
              className={`bg-white ${
                rest.length % 2 === 1 && i === rest.length - 1 ? 'sm:col-span-2' : ''
              }`}
            >
              <Card section={s} />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
