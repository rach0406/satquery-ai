import { useMemo, useRef, useState } from 'react'
import { Icon, ICON_BY_NAME } from './Icons'

/* Sixteen worked examples are genuinely useful and take genuinely too much
   room. Previously they filled a permanent left rail and were the first thing
   the eye landed on, which put the demo content ahead of the user's own
   question.

   So: collapsed by default, one line of chips when open, and a horizontal rail
   of cards behind a category filter. The question box keeps the focus; the
   examples are one click away when someone wants them. */

export default function SuggestedQueries({ samples = [], onRun, busy }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('All')
  const railRef = useRef(null)

  const categories = useMemo(
    () => ['All', ...Array.from(new Set(samples.map((s) => s.category)))],
    [samples]
  )
  const shown = filter === 'All' ? samples : samples.filter((s) => s.category === filter)

  if (!samples.length) return null

  const scroll = (dir) =>
    railRef.current?.scrollBy({ left: dir * 340, behavior: 'smooth' })

  return (
    <section className="rounded-panel border border-paper-300 bg-white/70">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-6 py-4 text-left transition-colors hover:bg-paper-50"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-orbit-50 text-orbit-600">
          <Icon.spark size={16} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-base font-semibold text-ink-800">
            Need a starting point?
          </span>
          <span className="mt-0.5 block text-small text-ink-400">
            {samples.length} worked examples, each verified to have real archive coverage
          </span>
        </span>
        <span className="hidden shrink-0 text-small font-semibold text-orbit-600 sm:block">
          {open ? 'Hide' : 'Browse'}
        </span>
        <Icon.chevron
          size={16}
          className={`shrink-0 text-ink-300 transition-transform duration-200 ${
            open ? 'rotate-90' : ''
          }`}
        />
      </button>

      {open && (
        <div className="animate-fadeIn border-t border-paper-200 px-6 pb-6 pt-5">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {categories.map((c) => (
              <button
                key={c}
                onClick={() => setFilter(c)}
                className={`rounded-pill px-3.5 py-1.5 text-small font-medium transition-colors ${
                  filter === c
                    ? 'bg-orbit-600 text-white'
                    : 'bg-paper-200 text-ink-500 hover:bg-paper-300 hover:text-ink-800'
                }`}
              >
                {c}
              </button>
            ))}
            <span className="ml-auto hidden items-center gap-1.5 lg:flex">
              <button
                onClick={() => scroll(-1)}
                aria-label="Scroll examples left"
                className="rounded-lg border border-paper-300 p-2 text-ink-400 transition-colors hover:bg-paper-100 hover:text-ink-700"
              >
                <span className="block rotate-180">
                  <Icon.chevron size={14} />
                </span>
              </button>
              <button
                onClick={() => scroll(1)}
                aria-label="Scroll examples right"
                className="rounded-lg border border-paper-300 p-2 text-ink-400 transition-colors hover:bg-paper-100 hover:text-ink-700"
              >
                <Icon.chevron size={14} />
              </button>
            </span>
          </div>

          <div
            ref={railRef}
            className="no-scrollbar -mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto px-1 pb-2"
          >
            {shown.map((s) => {
              const I = ICON_BY_NAME[s.icon] || Icon.spark
              return (
                <button
                  key={s.id}
                  disabled={busy}
                  onClick={() => onRun(s.query)}
                  className="group w-[19rem] shrink-0 snap-start rounded-card border border-paper-300 bg-paper-50 p-5 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-orbit-200 hover:bg-white hover:shadow-card disabled:pointer-events-none disabled:opacity-45"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-orbit-50 text-orbit-600 transition-colors group-hover:bg-orbit-100">
                      <I size={15} />
                    </span>
                    <span className="chip-neutral truncate">{s.category}</span>
                    {s.eta_seconds && (
                      <span className="mono ml-auto shrink-0 text-ink-400">
                        ~{s.eta_seconds}s
                      </span>
                    )}
                  </div>
                  <div className="mt-3.5 text-base font-medium leading-snug text-ink-800">
                    {s.query}
                  </div>
                  <div className="mt-2.5 text-small leading-relaxed text-ink-400">{s.why}</div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
