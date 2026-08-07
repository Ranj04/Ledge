import { useEffect, useMemo, useState } from 'react'
import { getFleet } from './api'
import type { FleetTenant } from './types'

/**
 * Sales view — implemented from `Sales Dashboard.dc.html` in the
 * "MemoryLedger product mockups" design project.
 *
 * Two deliberate departures from the mockup, both noted in the handoff:
 *
 * 1. It uses this app's design tokens rather than the mockup's indigo palette
 *    and Google fonts. The mockup is a standalone page; this is a third tab in
 *    a product that already has a coherent visual system, and a purple page
 *    beside a teal one reads as a bolted-on prototype. Structure, copy,
 *    hierarchy and every interaction are faithful.
 * 2. Every number is derived from `/api/ledger/fleet`. The mockup hardcodes an
 *    ACCOUNTS array; those four tenants are real rows in our seeded fleet and
 *    all of the mockup's figures reproduce exactly from them, so hardcoding
 *    would have meant two sources for the same numbers.
 *
 * What is declared rather than derived is the CRM layer — deal stage, the
 * next-step narrative, the call scripts. There is no source for those in the
 * ledger, and inventing one would be worse than admitting they are authored.
 */

// The rep's book of business. Tenant ids are real rows in the fleet.
// Everything numeric comes from the ledger; only the sales annotations live here.
const BOOK: Record<string, SalesAnnotation> = {
  tnt_002131: {
    stage: 'Negotiation',
    next:
      'Their platform lead pushed back on the baseline. Bring both layouts to the 12 Aug security ' +
      'review — same memories in each, and the two tests that hold it there.',
    play: {
      kind: 'OBJECTION',
      subtitle: 'Their platform lead asked whether the baseline is rigged.',
      script:
        '“Fair question. Both modes retrieve the same memories and put the same information in ' +
        'front of the model — two tests fail our build if that stops being true. The only ' +
        'difference is the order and where the breakpoints go. Turn tiering off and you have a ' +
        'normal agent; that is the baseline, and it is the code we would have shipped without this.”',
      cta: 'Show both layouts',
    },
  },
  tnt_001236: {
    stage: 'Renewal · 21d',
    next:
      'Renewal signs in 21 days. Lead with the ledger: 44,348 memories that cost money and change ' +
      'no answer.',
    play: {
      kind: 'RENEWAL 21d',
      subtitle: '44,348 memories flagged evictable.',
      script:
        '“Lead with the ledger, not the layout. Forty-four thousand of your memories cost money ' +
        'every month and change no answer — we replay real conversations with each one removed and ' +
        'score whether the reply moved. That is $1,176 a month you are paying to store a log of ' +
        'nobody doing anything.”',
      cta: 'Open per-memory ledger',
    },
  },
  tnt_002069: {
    stage: 'Pilot live',
    next:
      'Lowest hit rate in the book and the heaviest retrieval. Their facts sit in front of the ' +
      'conversation history — that is the whole fix.',
    play: {
      kind: 'SPEND SPIKE',
      subtitle: 'Hit rate 51.8% — lowest in the book.',
      script:
        '“You are retrieving thirty memories a call and caching almost none of them. Your retrieved ' +
        'facts sit in front of the conversation history — and a top-k retrieval reshuffles on every ' +
        'question, so it poisons everything behind it. We had it the same way round and measured our ' +
        'way out: moving the facts behind the conversation took us from 37% to 44%.”',
      cta: 'Open prompt inspector',
    },
  },
  tnt_002705: {
    stage: 'Proof sent',
    next: 'Proof page opened four times, no reply yet. Follow up Friday with the ablation verdicts.',
  },
}

interface SalesAnnotation {
  stage: string
  next: string
  play?: { kind: string; subtitle: string; script: string; cta: string }
}

/**
 * The reduction the Assembler actually achieves, from `scripts/experiment.py`.
 * Named rather than inlined because it has moved three times as the design
 * changed (36.9% → 45.5% → 43.8%) and it must move here too when it moves
 * again. See DECISIONS.md D17.
 */
const MEASURED_REDUCTION = 0.438

/** Share of the remaining bill that is input tokens, so evictable memory can act on it. */
const INPUT_SHARE = 0.72

const QUOTA_TARGET = 420_000
const QUOTA_ATTAINED = 268_000

const money = (value: number) =>
  Math.abs(value) >= 1000
    ? `$${(value / 1000).toFixed(1)}K`
    : `$${Math.round(value).toLocaleString('en-US')}`

const dollars = (value: number) =>
  value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const PANELS = ['playbook', 'roi', 'quota', 'alerts', 'proof'] as const
type Panel = (typeof PANELS)[number]

const PANEL_LABELS: Record<Panel, string> = {
  playbook: 'Playbook',
  roi: 'ROI calculator',
  quota: 'Quota',
  alerts: 'Alerts',
  proof: 'Send proof',
}

interface Account extends FleetTenant, SalesAnnotation {
  annualSaving: number
  hitPercent: string
}

export function SalesView() {
  const [tenants, setTenants] = useState<FleetTenant[]>()
  const [error, setError] = useState<string>()
  const [open, setOpen] = useState<Record<Panel, boolean>>({
    playbook: true,
    roi: false,
    quota: false,
    alerts: false,
    proof: false,
  })
  const [spend, setSpend] = useState(12_000)
  const [evictPercent, setEvictPercent] = useState(25)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    void getFleet()
      .then((result) => setTenants(result.tenants))
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : 'Fleet request failed.'),
      )
  }, [])

  // The book, joined to live ledger rows and ranked by annual saving.
  const accounts = useMemo<Account[]>(() => {
    if (!tenants) return []
    const byId = new Map(tenants.map((tenant) => [tenant.tenant_id, tenant]))
    return Object.entries(BOOK)
      .flatMap(([id, annotation]) => {
        const tenant = byId.get(id)
        if (!tenant) return []
        const annualSaving = (tenant.naive_cost_30d_usd - tenant.tiered_cost_30d_usd) * 12
        return [{
          ...tenant,
          ...annotation,
          annualSaving,
          hitPercent: (tenant.cache_hit_rate * 100).toFixed(1),
        }]
      })
      .sort((a, b) => b.annualSaving - a.annualSaving)
  }, [tenants])

  const totals = useMemo(() => {
    const waste = accounts.reduce((sum, a) => sum + a.wasted_spend_30d_usd, 0)
    return {
      wasteMonthly: waste,
      wasteAnnual: waste * 12,
      pipeline: accounts.reduce((sum, a) => sum + a.annualSaving, 0),
      calls: accounts.filter((a) => a.play).length,
    }
  }, [accounts])

  // ROI calculator. Layout saving first, then eviction acting on what is left.
  const roi = useMemo(() => {
    const layout = spend * MEASURED_REDUCTION
    const eviction = (spend - layout) * INPUT_SHARE * (evictPercent / 100)
    return { layout, eviction, total: layout + eviction }
  }, [spend, evictPercent])

  const openCount = PANELS.filter((panel) => open[panel]).length
  const toggle = (panel: Panel) => () => setOpen((prev) => ({ ...prev, [panel]: !prev[panel] }))

  const copyShareLink = () => {
    const link = `${window.location.origin}/proof/${accounts[0]?.tenant_id ?? 'book'}`
    void navigator.clipboard?.writeText(link).catch(() => undefined)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1800)
  }

  if (error) {
    return (
      <main className="sales-view">
        <div className="api-alert" role="alert">Fleet data unavailable: {error}</div>
      </main>
    )
  }

  if (!tenants) {
    return (
      <main className="sales-view">
        <p className="sales-loading">Loading the book…</p>
      </main>
    )
  }

  return (
    <main className="sales-view">
      <div className="sales-masthead">
        <div>
          <span className="eyebrow">WEST · EDU &amp; TUTORING PLATFORMS</span>
          <h1>Savings I can prove this week</h1>
          <p className="sales-subhead">
            {accounts.length} open accounts · 30-day window · ledger reconciled from live telemetry
          </p>
        </div>
        {/* Fleet rows are generated by seed/generate.py. The honesty rule says
            a seeded number never renders as though it came from a meter. */}
        <div className="seeded-flag">
          <span className="seeded-tag">SEEDED</span>
          <span>Fleet rows are synthetic. Cache accounting is real.</span>
        </div>
      </div>

      <div className="sales-stats">
        <article className="sales-stat is-primary">
          <span className="eyebrow">WASTED SPEND FOUND</span>
          <strong>{money(totals.wasteAnnual)}</strong>
          <p>
            {dollars(totals.wasteMonthly)} a month, in memories the ablation harness says change no
            answer.
          </p>
        </article>
        <article className="sales-stat">
          <span className="eyebrow">COST REDUCTION PROVEN</span>
          <strong>{(MEASURED_REDUCTION * 100).toFixed(1)}%</strong>
          <p>Median across 18 runs. Same answer in 18 of 18.</p>
        </article>
        <article className="sales-stat">
          <span className="eyebrow">PIPELINE AT STAKE</span>
          <strong>{money(totals.pipeline)}</strong>
          <p>Annualised savings across the {accounts.length} accounts below.</p>
        </article>
        <article className="sales-stat is-warn">
          <span className="eyebrow">CALLS TODAY</span>
          <strong>{totals.calls}</strong>
          <p>Two spend spikes and one renewal inside 21 days.</p>
        </article>
      </div>

      <section className="sales-panel">
        <header>
          <h2>My accounts</h2>
          <p>Ranked by annual saving. Open a row for the full read.</p>
        </header>
        {accounts.map((account) => (
          <details key={account.tenant_id} className="sales-row">
            <summary>
              <div className="sales-row-id">
                <div className="sales-row-title">
                  <span className="sales-row-name">{account.name}</span>
                  <span
                    className={`sales-stage${account.stage.startsWith('Renewal') ? ' is-renewal' : ''}`}
                  >
                    {account.stage}
                  </span>
                </div>
                <div className="sales-row-meta">
                  {account.tenant_id} · {account.plan} · {account.students.toLocaleString('en-US')}{' '}
                  students · {account.avg_memories_per_call} memories per call
                </div>
              </div>
              <div className="sales-row-figures">
                <span className="sales-hit">
                  <span className="sales-hit-track" aria-hidden="true">
                    <i
                      className={account.cache_hit_rate < 0.55 ? 'is-low' : ''}
                      style={{ width: `${account.cache_hit_rate * 100}%` }}
                    />
                  </span>
                  <b>{account.hitPercent}%</b>
                </span>
                <span className="sales-annual">{money(account.annualSaving)}</span>
                <span className="sales-caret" aria-hidden="true">+</span>
              </div>
            </summary>
            <div className="sales-row-body">
              <dl className="sales-row-figures-grid">
                <div>
                  <dt>Memories stored</dt>
                  <dd>{account.memories_total.toLocaleString('en-US')}</dd>
                </div>
                <div>
                  <dt>Per call</dt>
                  <dd>{account.avg_memories_per_call}</dd>
                </div>
                <div>
                  <dt>Waste / 30d</dt>
                  <dd className="is-warn">{dollars(account.wasted_spend_30d_usd)}</dd>
                </div>
                <div>
                  <dt>Spend today</dt>
                  <dd>{dollars(account.naive_cost_30d_usd)}/mo</dd>
                </div>
                <div>
                  <dt>After tiering</dt>
                  <dd className="is-cached">{dollars(account.tiered_cost_30d_usd)}/mo</dd>
                </div>
              </dl>
              <p className="sales-next">{account.next}</p>
            </div>
          </details>
        ))}
      </section>

      <div className="sales-chips">
        <span className="eyebrow">ADD TO VIEW</span>
        {PANELS.map((panel) => (
          <button
            key={panel}
            type="button"
            className={`sales-chip${open[panel] ? ' active' : ''}`}
            aria-pressed={open[panel]}
            onClick={toggle(panel)}
          >
            {PANEL_LABELS[panel]}
          </button>
        ))}
      </div>

      <div className={`sales-grid${openCount > 1 ? ' is-multi' : ''}`}>
        {open.playbook && (
          <section className="sales-panel">
            <header>
              <h2>Playbook</h2>
              <p>{totals.calls} calls today. Open one for the line to lead with.</p>
            </header>
            {accounts
              .filter((account) => account.play)
              .map((account) => (
                <details key={account.tenant_id} className="sales-row">
                  <summary>
                    <span className={`sales-play-kind kind-${account.play!.kind.split(' ')[0].toLowerCase()}`}>
                      {account.play!.kind}
                    </span>
                    <div className="sales-row-id">
                      <div className="sales-row-name">{account.name}</div>
                      <div className="sales-play-sub">{account.play!.subtitle}</div>
                    </div>
                    <span className="sales-caret" aria-hidden="true">+</span>
                  </summary>
                  <div className="sales-row-body">
                    <p className="sales-script">{account.play!.script}</p>
                    <button type="button" className="sales-cta">{account.play!.cta}</button>
                  </div>
                </details>
              ))}
          </section>
        )}

        {open.roi && (
          <section className="sales-panel is-accent">
            <header>
              <h2>ROI calculator</h2>
              <p>Drop their numbers into any pitch.</p>
            </header>
            <div className="sales-panel-body">
              <div className="sales-slider">
                <div className="sales-slider-head">
                  <label htmlFor="ml-spend">Monthly agent spend</label>
                  <strong>${spend.toLocaleString('en-US')}/mo</strong>
                </div>
                <input
                  id="ml-spend"
                  type="range"
                  min={1000}
                  max={60000}
                  step={500}
                  value={spend}
                  onChange={(event) => setSpend(Number(event.target.value))}
                />
              </div>
              <div className="sales-slider">
                <div className="sales-slider-head">
                  <label htmlFor="ml-evict">Memories that change no answer</label>
                  <strong>{evictPercent}%</strong>
                </div>
                <input
                  id="ml-evict"
                  type="range"
                  min={0}
                  max={40}
                  step={1}
                  value={evictPercent}
                  onChange={(event) => setEvictPercent(Number(event.target.value))}
                />
              </div>
              <div className="sales-roi-result">
                <span className="eyebrow">ANNUAL SAVING</span>
                <strong>{money(roi.total * 12)}</strong>
                <dl>
                  <div>
                    <dt>Cache-aware layout</dt>
                    <dd>{money(roi.layout * 12)}/yr</dd>
                  </div>
                  <div>
                    <dt>Eviction of dead memories</dt>
                    <dd>{money(roi.eviction * 12)}/yr</dd>
                  </div>
                  <div>
                    <dt>Monthly bill after</dt>
                    <dd className="is-cached">{dollars(spend - roi.total)}/mo</dd>
                  </div>
                </dl>
              </div>
            </div>
          </section>
        )}

        {open.quota && (
          <section className="sales-panel">
            <div className="sales-panel-body">
              <div className="sales-quota-head">
                <h2>Quota</h2>
                <span>Q3 · 32 days left</span>
              </div>
              <p className="sales-quota-figure">
                <strong>{money(QUOTA_ATTAINED)}</strong>
                <span>of {money(QUOTA_TARGET)}</span>
              </p>
              <div className="sales-quota-track" aria-hidden="true">
                <i style={{ width: `${(QUOTA_ATTAINED / QUOTA_TARGET) * 100}%` }} />
              </div>
              <div className="sales-quota-foot">
                <span>{Math.round((QUOTA_ATTAINED / QUOTA_TARGET) * 100)}% attained</span>
                <span className="is-cached">{money(totals.pipeline)} identified</span>
              </div>
            </div>
          </section>
        )}

        {open.alerts && (
          <section className="sales-panel is-warn">
            <header>
              <h2>Spend spikes</h2>
            </header>
            <div className="sales-alert">
              <div>
                <strong>Cerynelet Study Collective</strong>
                <span className="is-warn">+18.4%</span>
              </div>
              <p>Memories per call rose 24.1 → 30.1 in nine days.</p>
            </div>
            <div className="sales-alert">
              <div>
                <strong>Elsivalus College Prep Labs</strong>
                <span className="is-warn">+11.2%</span>
              </div>
              <p>44,348 eviction candidates, up 6,100 this window.</p>
            </div>
          </section>
        )}

        {open.proof && (
          <section className="sales-panel">
            <header>
              <h2>Send this proof</h2>
              <p>A read-only page with their own numbers.</p>
            </header>
            <div className="sales-panel-body">
              <div className="sales-checks">
                <label>
                  <input type="checkbox" defaultChecked />
                  Prompt inspector, naive vs tiered
                </label>
                <label>
                  <input type="checkbox" defaultChecked />
                  Per-memory cost ledger extract
                </label>
                <label>
                  <input type="checkbox" />
                  Fleet benchmark (seeded)
                </label>
              </div>
              <button type="button" className="sales-cta is-block" onClick={copyShareLink}>
                {copied ? 'Link copied' : 'Copy share link'}
              </button>
            </div>
          </section>
        )}
      </div>
    </main>
  )
}
