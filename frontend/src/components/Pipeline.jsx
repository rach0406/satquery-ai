import { duration } from '../lib/format'
import { Icon } from './Icons'

/* The seven stages the controller actually runs, in order. */
const STAGES = [
  { key: 'parse', label: 'Understand', sub: 'Intent + parameters', icon: Icon.spark },
  { key: 'validate', label: 'Validate', sub: 'Plan is executable', icon: Icon.check },
  { key: 'acquire', label: 'Retrieve', sub: 'Real satellite pixels', icon: Icon.satellite },
  { key: 'select', label: 'Select tools', sub: 'From the registry', icon: Icon.cpu },
  { key: 'execute', label: 'Measure', sub: 'Specialist models run', icon: Icon.chart },
  { key: 'ground', label: 'Verify', sub: 'Every number traced', icon: Icon.shield },
  { key: 'narrate', label: 'Explain', sub: 'Grounded narration', icon: Icon.fileText },
]

const TONE = {
  pending: 'border-paper-400 bg-paper-100 text-ink-300',
  active: 'border-orbit-400 bg-orbit-50 text-orbit-600 shadow-focus animate-pulseSoft',
  ok: 'border-signal-green/40 bg-signal-green/10 text-signal-green',
  no_data: 'border-signal-amber/40 bg-signal-amber/10 text-signal-amber',
  needs_clarification: 'border-signal-amber/40 bg-signal-amber/10 text-signal-amber',
  error: 'border-signal-red/40 bg-signal-red/10 text-signal-red',
}

const LABEL_TONE = {
  pending: 'text-ink-400',
  active: 'text-orbit-700',
  ok: 'text-ink-800',
  no_data: 'text-signal-amber',
  needs_clarification: 'text-signal-amber',
  error: 'text-signal-red',
}

export default function Pipeline({ stages = {}, running, tools = [] }) {
  return (
    <section className="panel overflow-hidden">
      <div className="panel-head">
        <div>
          <span className="panel-title">Analysis pipeline</span>
          <p className="mt-1 text-tiny text-ink-400">
            Natural language → understanding → data → measurement → verified insight
          </p>
        </div>
        {running && (
          <span className="chip-brand">
            <span className="h-1.5 w-1.5 animate-pulseSoft rounded-full bg-orbit-500" />
            running
          </span>
        )}
      </div>

      <div className="overflow-x-auto px-5 py-6">
        <ol className="flex min-w-max items-start gap-1">
          {STAGES.map((s, i) => {
            const st = stages[s.key]
            const state = st?.status || (running && st?.started ? 'active' : 'pending')
            const I = s.icon
            return (
              <li key={s.key} className="flex items-start">
                <div className="flex w-[122px] flex-col items-center text-center">
                  <div
                    className={`flex h-11 w-11 items-center justify-center rounded-xl border transition-all duration-300 ${
                      TONE[state] || TONE.pending
                    }`}
                  >
                    <I size={19} />
                  </div>
                  <div
                    className={`mt-2.5 text-small font-semibold transition-colors ${
                      LABEL_TONE[state] || LABEL_TONE.pending
                    }`}
                  >
                    {s.label}
                  </div>
                  <div className="mt-1 text-micro leading-snug text-ink-400">{s.sub}</div>
                  {st?.ms !== undefined && (
                    <div className="mono mt-1 text-ink-400">{duration(st.ms)}</div>
                  )}
                </div>
                {i < STAGES.length - 1 && (
                  <div
                    className={`mt-[22px] h-0.5 w-5 rounded-full transition-colors duration-500 ${
                      stages[STAGES[i + 1].key]?.status ? 'bg-orbit-400' : 'bg-paper-400'
                    }`}
                  />
                )}
              </li>
            )
          })}
        </ol>
      </div>

      {tools.length > 0 && (
        <div className="border-t border-paper-200 bg-paper-50 px-5 py-4">
          <div className="mb-2.5 text-micro font-semibold uppercase tracking-[0.13em] text-ink-400">
            Specialist tools executed
          </div>
          <div className="flex flex-wrap gap-2">
            {tools.map((t, i) => (
              <span
                key={`${t.tool}-${i}`}
                title={t.message || ''}
                className={`chip ${
                  t.status === 'ok'
                    ? 'chip-ok'
                    : t.status === 'skipped'
                      ? 'chip-neutral'
                      : t.status === 'no_data'
                        ? 'chip-warn'
                        : 'chip-bad'
                }`}
              >
                {t.status === 'ok' ? <Icon.check size={11} /> : <Icon.x size={11} />}
                <span className="mono">{t.tool}</span>
                {t.ms !== undefined && <span className="opacity-65">{duration(t.ms)}</span>}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

export { STAGES }
