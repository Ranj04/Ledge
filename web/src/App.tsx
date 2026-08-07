import { useCallback, useEffect, useRef, useState } from 'react'
import { getStatus, getStudents, inspectPrompt, streamChat } from './api'
import type {
  CallCost,
  DonePayload,
  InspectBlock,
  InspectMessage,
  InspectMode,
  InspectResponse,
  Mode,
  Status,
  Student,
  TranscriptMessage,
} from './types'

const STARTER_PROMPTS = [
  'Can you help me with limiting reagents? i always just pick the smaller grams',
  'ok for 2Al + 3Cl2 -> 2AlCl3, I have 5.4g Al and 12.0g Cl2. where do i start',
  'I got .20 mol Al and .17 mol chlorine so chlorine limits right?',
  'wait why are we calculating product from BOTH, isnt comparing moles enough',
]

const TIER_NAMES = ['Frozen', 'Durable', 'Slow', 'Volatile']

function makeId(prefix: string) {
  return `${prefix}_${crypto.randomUUID()}`
}

function formatInteger(value?: number) {
  return value === undefined ? '—' : Math.round(value).toLocaleString('en-US')
}

function formatMoney(value?: number, places = 4) {
  return value === undefined ? '—' : `$${value.toFixed(places)}`
}

function formatPercent(value?: number) {
  return value === undefined ? '—' : `${Math.round(value * 100)}%`
}

function useAnimatedNumber(value?: number, duration = 460) {
  const [display, setDisplay] = useState<number | undefined>(value)
  const previous = useRef(value)

  useEffect(() => {
    if (value === undefined) {
      previous.current = undefined
      setDisplay(undefined)
      return
    }
    const startValue = previous.current ?? 0
    const started = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / duration)
      const eased = 1 - (1 - progress) ** 3
      setDisplay(startValue + (value - startValue) * eased)
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    previous.current = value
    return () => cancelAnimationFrame(frame)
  }, [duration, value])

  return display
}

function ProviderChip({ status, error }: { status?: Status; error?: string }) {
  if (error) {
    return (
      <span className="provider-chip provider-chip--error" title={error}>
        PROVIDER STATUS UNAVAILABLE
      </span>
    )
  }
  if (!status) return <span className="provider-chip provider-chip--loading">CHECKING PROVIDERS</span>
  if (!status.live) {
    return (
      <span
        className="provider-chip provider-chip--sim"
        title="cache accounting is computed from the real billing rule; model responses are simulated."
      >
        <span className="chip-dot" aria-hidden="true" />
        SIMULATED PROVIDERS
      </span>
    )
  }
  return (
    <span className="provider-chip provider-chip--live" title={`${status.providers.cortex} · ${status.providers.model}`}>
      <span className="chip-dot" aria-hidden="true" />
      LIVE PROVIDERS
    </span>
  )
}

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (mode: Mode) => void }) {
  return (
    <div className="mode-control" aria-label="Prompt assembly mode">
      <span className="mode-label">Next message</span>
      <div className="mode-toggle">
        <button
          type="button"
          aria-pressed={mode === 'naive'}
          className={mode === 'naive' ? 'active naive' : ''}
          title="Memories at the front of the prompt in relevance order, no cache breakpoints. The default shape of a memory-augmented agent."
          onClick={() => onChange('naive')}
        >
          Naive
        </button>
        <button
          type="button"
          aria-pressed={mode === 'tiered'}
          className={mode === 'tiered' ? 'active tiered' : ''}
          title="Memories grouped by how often they change, stable first, with cache breakpoints at the tier boundaries. Same memories, same answer."
          onClick={() => onChange('tiered')}
        >
          Tiered
        </button>
      </div>
    </div>
  )
}

function Receipt({ data }: { data: DonePayload }) {
  return (
    <div className="receipt" aria-label="Call receipt">
      <span className={`receipt-mode receipt-mode--${data.mode}`}>{data.mode}</span>
      <span>{formatInteger(data.input_tokens)} tok</span>
      <span aria-hidden="true">·</span>
      <span>{formatInteger(data.cached_tokens)} cached</span>
      <span aria-hidden="true">·</span>
      <span>{formatMoney(data.cost_usd)}</span>
      <span aria-hidden="true">·</span>
      <span>{data.latency_ms === undefined ? '—' : `${Math.round(data.latency_ms).toLocaleString('en-US')} ms`}</span>
    </div>
  )
}

function Transcript({
  messages,
  student,
  streaming,
  onStarter,
}: {
  messages: TranscriptMessage[]
  student?: Student
  streaming: boolean
  onStarter: (prompt: string) => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  if (!messages.length) {
    return (
      <div className="empty-transcript">
        <div className="empty-kicker">CONTEXT-READY TUTOR</div>
        <h1>{student ? `${student.display_name}’s study room` : 'Study room'}</h1>
        <p>
          {student
            ? `${student.grade_level} · ${student.subjects.join(' + ')} · ${formatInteger(student.memory_count)} memories available`
            : 'Choose a student to begin.'}
        </p>
        {student && (
          <div className="starter-list" aria-label="Starter prompts">
            {STARTER_PROMPTS.map((prompt) => (
              <button type="button" key={prompt} onClick={() => onStarter(prompt)} disabled={streaming}>
                {prompt}
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="message-list" aria-live="polite">
      {messages.map((message) => (
        <article key={message.id} className={`message message--${message.role}`}>
          <div className="message-speaker">
            {message.role === 'user' ? student?.display_name ?? 'Student' : message.role === 'error' ? 'Request error' : 'Tutor'}
          </div>
          <div className="message-text">
            {message.text || <span className="thinking">Reading the student context…</span>}
          </div>
          {message.receipt && <Receipt data={message.receipt} />}
        </article>
      ))}
      <div ref={endRef} />
    </div>
  )
}

function Composer({
  draft,
  setDraft,
  disabled,
  canSend,
  onSend,
}: {
  draft: string
  setDraft: (value: string) => void
  disabled: boolean
  canSend: boolean
  onSend: () => void
}) {
  return (
    <div className="composer">
      <textarea
        value={draft}
        disabled={disabled || !canSend}
        aria-label="Message the tutor"
        placeholder={canSend ? 'Ask a follow-up…' : 'Waiting for the student list…'}
        rows={2}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            if (draft.trim() && !disabled && canSend) onSend()
          }
        }}
      />
      <button type="button" onClick={onSend} disabled={disabled || !canSend || !draft.trim()}>
        {disabled ? 'Streaming…' : 'Send'}
      </button>
    </div>
  )
}

function CostMeter({ latest, callCosts, streaming }: { latest?: DonePayload; callCosts: CallCost[]; streaming: boolean }) {
  const session = latest?.session
  const animatedCost = useAnimatedNumber(session?.cost_usd)
  const animatedBaseline = useAnimatedNumber(session?.baseline_cost_usd)
  const animatedSaved = useAnimatedNumber(session?.saved_usd)
  const savingsPercent =
    session?.saved_usd === undefined || !session.baseline_cost_usd
      ? session?.saved_usd === 0
        ? 0
        : undefined
      : session.saved_usd / session.baseline_cost_usd
  const maxCost = Math.max(...callCosts.flatMap((call) => (call.cost === undefined ? [] : [call.cost])), 0)

  return (
    <aside className="cost-meter" aria-label="Conversation cost meter">
      <div className="meter-heading">
        <div>
          <span className="eyebrow">COST METER</span>
          <h2>This conversation</h2>
        </div>
        <span className={`meter-state ${streaming ? 'meter-state--active' : ''}`}>
          {streaming ? 'MEASURING' : latest ? `${formatInteger(session?.calls)} CALLS` : 'READY'}
        </span>
      </div>

      <div className="hero-cost">{formatMoney(animatedCost)}</div>
      <div className="cost-comparison">
        <div>
          <span>Without tiering</span>
          <strong>{formatMoney(animatedBaseline)}</strong>
        </div>
        <div className="saved-row">
          <span>Saved</span>
          <strong>
            {formatMoney(animatedSaved)} {savingsPercent === undefined ? '' : `(${Math.round(savingsPercent * 100)}%)`}
          </strong>
        </div>
      </div>

      <div className="cache-rate">
        <div className="metric-label">
          <span>Cache hit rate</span>
          <strong>{formatPercent(session?.cache_hit_rate)}</strong>
        </div>
        <div className="rate-track" aria-hidden="true">
          <span style={{ width: `${Math.max(0, Math.min(100, (session?.cache_hit_rate ?? 0) * 100))}%` }} />
        </div>
      </div>

      <div className="tier-meter">
        <div className="section-label">LATEST CALL · TOKEN LAYOUT</div>
        {latest?.tier_tokens ? (
          <>
            <div className="tier-strip" aria-label="Tokens and cache state by volatility tier">
              {[0, 1, 2, 3].map((tier) => {
                const tokens = latest.tier_tokens?.[String(tier)]
                const total = Object.values(latest.tier_tokens ?? {}).reduce((sum, value) => sum + value, 0)
                return (
                  <span
                    key={tier}
                    className={`tier-segment tier-${tier} ${latest.tier_cached?.[String(tier)] ? 'is-cached' : 'is-full-price'}`}
                    style={{ flexGrow: tokens ?? 0, width: total ? undefined : '25%' }}
                    title={`Tier ${tier} ${TIER_NAMES[tier]} · ${formatInteger(tokens)} tokens · ${latest.tier_cached?.[String(tier)] ? 'cached' : 'full price'}`}
                  />
                )
              })}
            </div>
            <div className="tier-key">
              {[0, 1, 2, 3].map((tier) => {
                const cached = latest.tier_cached?.[String(tier)]
                return (
                  <div key={tier}>
                    <span className={`tier-swatch tier-${tier} ${cached ? 'is-cached' : 'is-full-price'}`} />
                    <span>{tier} {TIER_NAMES[tier]}</span>
                    <strong>{formatInteger(latest.tier_tokens?.[String(tier)])} tok</strong>
                    <em>{cached === undefined ? '—' : cached ? 'cached' : 'full price'}</em>
                  </div>
                )
              })}
            </div>
          </>
        ) : (
          <div className="meter-placeholder">Tier measurements appear after the first call.</div>
        )}
      </div>

      <div className="cost-history">
        <div className="section-label">PER-CALL COST</div>
        {callCosts.length ? (
          <div className="bar-row" aria-label="Per-call cost history">
            {callCosts.map((call, index) => (
              <div className="bar-slot" key={call.id}>
                <span
                  className={`cost-bar cost-bar--${call.mode}`}
                  style={{ height: `${call.cost === undefined || !maxCost ? 8 : Math.max(12, (call.cost / maxCost) * 100)}%` }}
                  title={`Call ${index + 1} · ${call.mode} · ${formatMoney(call.cost)}`}
                />
                <small>{index + 1}</small>
              </div>
            ))}
          </div>
        ) : (
          <div className="history-empty">Each completed call adds a measured bar.</div>
        )}
      </div>
    </aside>
  )
}

function PromptBand({ item, total, isMessage = false }: { item: InspectBlock | InspectMessage; total?: number; isMessage?: boolean }) {
  const tokens = item.tokens
  const proportion = tokens !== undefined && total ? tokens / total : 0
  const height = Math.max(58, proportion * 320)
  const tier = isMessage ? 3 : (item as InspectBlock).tier
  const label = isMessage ? `${(item as InspectMessage).role} message` : (item as InspectBlock).label

  return (
    <>
      <div className={`prompt-band tier-${tier}`} style={{ minHeight: `${height}px` }}>
        <div className="band-heading">
          <strong>{label}</strong>
          <span>{formatInteger(tokens)} tok</span>
        </div>
        <pre>{item.preview}</pre>
      </div>
      {item.is_breakpoint && (
        <div className={`cache-boundary ${item.cacheable ? 'cache-boundary--active' : 'cache-boundary--below'}`}>
          <span>
            {item.cacheable ? 'CACHE BOUNDARY · PREFIX ELIGIBLE' : 'BELOW 1,024-TOKEN MINIMUM — NOT CACHED'}
          </span>
        </div>
      )}
    </>
  )
}

function InspectorColumn({ layout }: { layout: InspectMode }) {
  const isNaive = layout.mode === 'naive'
  return (
    <section className={`inspector-column inspector-column--${layout.mode}`}>
      <header>
        <div>
          <span className={`mode-pill mode-pill--${layout.mode}`}>{layout.mode}</span>
          <strong>{formatInteger(layout.total_tokens)} total tokens</strong>
        </div>
        <p>
          {isNaive
            ? 'Memories stay in relevance order at the front. There are no reusable prefix boundaries.'
            : 'The same memories are grouped from stable to volatile. Rules mark reusable prefixes.'}
        </p>
      </header>
      <div className="prompt-stack">
        {layout.blocks.map((block) => (
          <PromptBand key={`block-${block.index}`} item={block} total={layout.total_tokens} />
        ))}
        {layout.messages.map((message) => (
          <PromptBand key={`message-${message.index}`} item={message} total={layout.total_tokens} isMessage />
        ))}
      </div>
    </section>
  )
}

function PromptInspector({
  data,
  loading,
  error,
  sourceMessage,
  minTokens,
}: {
  data?: InspectResponse
  loading: boolean
  error?: string
  sourceMessage?: string
  minTokens?: number
}) {
  return (
    <section className="inspector-panel">
      <div className="inspector-heading">
        <div>
          <span className="eyebrow">DRY RUN · DOES NOT TOUCH THE LEDGER</span>
          <h2>Prompt inspector</h2>
        </div>
        <div className="inspector-source">
          {loading ? 'Comparing layouts…' : data ? `Same ${formatInteger(data.memory_count)} memories · same message` : 'Type or send a message to compare'}
        </div>
      </div>
      {sourceMessage && <div className="source-message" title={sourceMessage}>“{sourceMessage}”</div>}
      {error ? (
        <div className="panel-error">Inspector unavailable: {error}</div>
      ) : data ? (
        <div className={`inspector-grid ${loading ? 'is-loading' : ''}`}>
          <InspectorColumn layout={data.modes.naive} />
          <InspectorColumn layout={data.modes.tiered} />
        </div>
      ) : (
        <div className="inspector-empty">
          The comparison uses the current draft or most recent message. Cache eligibility begins at {formatInteger(minTokens)} tokens.
        </div>
      )}
    </section>
  )
}

function DashboardPlaceholder() {
  return (
    <main className="dashboard-placeholder">
      <span className="eyebrow">NEXT BUILD</span>
      <h1>Fleet cost dashboard</h1>
      <p>The tutor is live now. Tenant rollups and memory-level eviction candidates are coming in the next build.</p>
    </main>
  )
}

export default function App() {
  const [view, setView] = useState<'tutor' | 'dashboard'>('tutor')
  const [status, setStatus] = useState<Status>()
  const [statusError, setStatusError] = useState<string>()
  const [students, setStudents] = useState<Student[]>([])
  const [studentError, setStudentError] = useState<string>()
  const [selectedId, setSelectedId] = useState('')
  const [sessionId, setSessionId] = useState(() => makeId('sess'))
  const [mode, setMode] = useState<Mode>('tiered')
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [latest, setLatest] = useState<DonePayload>()
  const [callCosts, setCallCosts] = useState<CallCost[]>([])
  const [inspection, setInspection] = useState<InspectResponse>()
  const [inspectionMessage, setInspectionMessage] = useState<string>()
  const [inspectionLoading, setInspectionLoading] = useState(false)
  const [inspectionError, setInspectionError] = useState<string>()
  const inspectionAbort = useRef<AbortController | undefined>(undefined)

  const selectedStudent = students.find((student) => student.user_id === selectedId) ?? students[0]

  useEffect(() => {
    void getStatus()
      .then(setStatus)
      .catch((error: unknown) => setStatusError(error instanceof Error ? error.message : 'Status request failed.'))
    void getStudents()
      .then((result) => {
        setStudents(result)
        setSelectedId(result[0]?.user_id ?? '')
        if (!result.length) setStudentError('No students were returned by the API.')
      })
      .catch((error: unknown) => setStudentError(error instanceof Error ? error.message : 'Student request failed.'))
  }, [])

  const runInspection = useCallback(
    async (message: string) => {
      if (!selectedStudent || !message.trim()) return
      inspectionAbort.current?.abort()
      const controller = new AbortController()
      inspectionAbort.current = controller
      setInspectionLoading(true)
      setInspectionError(undefined)
      setInspectionMessage(message.trim())
      try {
        const result = await inspectPrompt(selectedStudent.user_id, message.trim(), sessionId, controller.signal)
        setInspection(result)
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setInspectionError(error instanceof Error ? error.message : 'Inspector request failed.')
      } finally {
        if (inspectionAbort.current === controller) setInspectionLoading(false)
      }
    },
    [selectedStudent, sessionId],
  )

  useEffect(() => {
    if (!draft.trim() || streaming) return
    const timeout = window.setTimeout(() => void runInspection(draft), 600)
    return () => window.clearTimeout(timeout)
  }, [draft, runInspection, streaming])

  function changeStudent(userId: string) {
    inspectionAbort.current?.abort()
    setSelectedId(userId)
    setSessionId(makeId('sess'))
    setMessages([])
    setDraft('')
    setLatest(undefined)
    setCallCosts([])
    setInspection(undefined)
    setInspectionMessage(undefined)
    setInspectionError(undefined)
  }

  async function sendMessage(prompt = draft) {
    const message = prompt.trim()
    if (!message || !selectedStudent || streaming) return
    const requestMode = mode
    const userMessage: TranscriptMessage = { id: makeId('user'), role: 'user', text: message }
    const assistantId = makeId('assistant')
    const assistantMessage: TranscriptMessage = { id: assistantId, role: 'assistant', text: '' }
    setMessages((current) => [...current, userMessage, assistantMessage])
    setDraft('')
    setStreaming(true)
    void runInspection(message)

    const updateAssistant = (update: (message: TranscriptMessage) => TranscriptMessage) => {
      setMessages((current) => current.map((item) => (item.id === assistantId ? update(item) : item)))
    }

    try {
      await streamChat(
        {
          user_id: selectedStudent.user_id,
          session_id: sessionId,
          message,
          mode: requestMode,
        },
        {
          onText: (text) => updateAssistant((item) => ({ ...item, text: item.text + text })),
          onDone: (payload) => {
            updateAssistant((item) => ({ ...item, receipt: payload }))
            setLatest(payload)
            setCallCosts((current) => [...current, { id: payload.call_id, mode: payload.mode, cost: payload.cost_usd }])
          },
          onError: (detail) => updateAssistant((item) => ({ ...item, role: 'error', text: detail })),
        },
      )
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'The chat request failed.'
      updateAssistant((item) => ({ ...item, role: 'error', text: detail }))
    } finally {
      setStreaming(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">ML</span>
          <span>MemoryLedger</span>
        </div>

        <nav className="view-tabs" aria-label="Primary views">
          <button type="button" className={view === 'tutor' ? 'active' : ''} onClick={() => setView('tutor')}>
            Tutor
          </button>
          <button type="button" className={view === 'dashboard' ? 'active' : ''} onClick={() => setView('dashboard')}>
            Dashboard
          </button>
        </nav>

        <div className="header-spacer" />
        <label className="student-select">
          <span>Student</span>
          <select
            value={selectedStudent?.user_id ?? ''}
            onChange={(event) => changeStudent(event.target.value)}
            disabled={!students.length || streaming}
          >
            {!students.length && <option>{studentError ? 'Unavailable' : 'Loading…'}</option>}
            {students.map((student) => (
              <option key={student.user_id} value={student.user_id}>{student.display_name}</option>
            ))}
          </select>
        </label>
        <ProviderChip status={status} error={statusError} />
      </header>

      {(studentError || statusError) && (
        <div className="api-alert" role="alert">
          API connection issue: {[studentError, statusError].filter(Boolean).join(' · ')}
        </div>
      )}

      {view === 'dashboard' ? (
        <DashboardPlaceholder />
      ) : (
        <main className="tutor-workspace">
          <div className="tutor-column">
            <section className="chat-panel">
              <div className="chat-toolbar">
                <div>
                  <span className="eyebrow">STUDY TUTOR</span>
                  <strong>{selectedStudent?.subjects.join(' · ') ?? 'Student context unavailable'}</strong>
                </div>
                <ModeToggle mode={mode} onChange={setMode} />
              </div>
              <div className="transcript">
                <Transcript messages={messages} student={selectedStudent} streaming={streaming} onStarter={sendMessage} />
              </div>
              <Composer
                draft={draft}
                setDraft={setDraft}
                disabled={streaming}
                canSend={Boolean(selectedStudent)}
                onSend={() => void sendMessage()}
              />
            </section>

            <PromptInspector
              data={inspection}
              loading={inspectionLoading}
              error={inspectionError}
              sourceMessage={inspectionMessage}
              minTokens={status?.limits.min_cacheable_tokens}
            />
          </div>

          <CostMeter latest={latest} callCosts={callCosts} streaming={streaming} />
        </main>
      )}
    </div>
  )
}
