export type Mode = 'naive' | 'tiered'

export interface Status {
  providers: {
    cortex: string
    everos: string
    ledger: string
    model: string
  }
  live: boolean
  pricing: {
    input_per_mtok: number
    output_per_mtok: number
    cache_read_per_mtok: number
    cache_write_per_mtok: number
  }
  limits: {
    min_cacheable_tokens: number
    max_breakpoints: number
    cache_ttl_seconds: number
  }
}

export interface Student {
  user_id: string
  display_name: string
  grade_level: string
  subjects: string[]
  memory_count: number
}

export interface SessionMetrics {
  calls?: number
  cost_usd?: number
  baseline_cost_usd?: number
  saved_usd?: number
  cache_hit_rate?: number
}

export interface DonePayload {
  call_id: string
  mode: Mode
  input_tokens?: number
  output_tokens?: number
  cached_tokens?: number
  cache_write_tokens?: number
  cost_usd?: number
  baseline_cost_usd?: number
  saved_usd?: number
  cache_hit_rate?: number
  latency_ms?: number
  breakpoint_count?: number
  memories_injected?: number
  tier_tokens?: Record<string, number>
  tier_cached?: Record<string, boolean>
  session?: SessionMetrics
}

export interface TranscriptMessage {
  id: string
  role: 'user' | 'assistant' | 'error'
  text: string
  receipt?: DonePayload
}

export interface InspectBlock {
  index: number
  kind: string
  label: string
  tier: number
  tokens?: number
  cumulative_tokens?: number
  memory_ids: string[]
  is_breakpoint: boolean
  cacheable: boolean
  preview: string
}

export interface InspectMessage {
  index: number
  role: string
  tokens?: number
  is_breakpoint: boolean
  cacheable: boolean
  preview: string
}

export interface InspectMode {
  mode: Mode
  breakpoint_count?: number
  total_tokens?: number
  memory_tokens?: number
  blocks: InspectBlock[]
  messages: InspectMessage[]
}

export interface InspectResponse {
  message: string
  memory_count?: number
  modes: {
    naive: InspectMode
    tiered: InspectMode
  }
}

export interface CallCost {
  id: string
  mode: Mode
  cost?: number
}
