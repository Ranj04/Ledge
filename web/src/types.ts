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

export interface MemoryCost {
  memory_id: string
  user_id: string
  memory_type: string
  tier: number
  injections: number
  total_tokens: number
  tokens: number
  cost_usd: number
  cache_hit_rate: number
  first_seen?: string
  last_seen?: string
  content_hash?: string
  stable_calls?: number
  monthly_cost_usd: number
}

export interface MemoryBody {
  memory_id: string
  content: string
  memory_type: string
  natural_tier: number
  tokens: number
  updated_at?: string
  metadata: Record<string, unknown>
}

export interface CacheTierRow {
  mode: Mode
  tier: number
  injections: number
  tokens: number
  cache_hit_rate: number
  cost_usd: number
  tier_name: string
}

export interface AblationRow {
  ablation_id: string
  memory_id: string
  ts?: string
  similarity?: number | null
  verdict: 'evict' | 'keep' | 'inconclusive'
  tokens_saved: number
  monthly_cost_usd: number
  prompt?: string
  baseline_answer?: string
  ablated_answer?: string
}

export interface AblationResponse {
  results: AblationRow[]
  provenance: 'simulated' | 'live' | string
}

export interface FleetTenant {
  tenant_id: string
  name: string
  plan: string
  students: number
  memories_total: number
  calls_30d: number
  avg_memories_per_call: number
  naive_cost_30d_usd: number
  tiered_cost_30d_usd: number
  cache_hit_rate: number
  eviction_candidates: number
  wasted_spend_30d_usd: number
}

export interface FleetResponse {
  note: string
  tenants: FleetTenant[]
  provenance: 'seeded' | string
}
