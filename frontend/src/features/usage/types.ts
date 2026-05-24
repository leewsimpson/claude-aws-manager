// Frozen API contract types for usage/cost tracking (Phase 7).

import type { KeyStatus } from '../keys/types'

export interface UsageSnapshot {
  period_start: string
  period_end: string
  model_id: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  cost: number
}

export interface KeyUsage {
  key_id: string
  status: KeyStatus
  rolling_limit: number | null
  rolling_period_days: number | null
  rolling_spend: number
  lifetime_budget: number | null
  lifetime_spend: number
  snapshots: UsageSnapshot[]
}

export interface CostCentreKeyUsage {
  key_id: string
  developer_username: string
  status: string
  lifetime_spend: number
  rolling_spend: number
  rolling_limit: number | null
  lifetime_budget: number | null
}

export interface ModelBreakdown {
  model_id: string
  cost: number
  total_tokens: number
}

export interface CostCentreUsage {
  cost_centre_id: string
  cost_centre_code: string
  budget_cap: number | null
  total_spend: number
  keys: CostCentreKeyUsage[]
  by_model: ModelBreakdown[]
}

export interface UsageSummaryCostCentre {
  cost_centre_id: string
  code: string
  name: string
  budget_cap: number | null
  total_spend: number
  active_keys: number
  stopped_keys: number
}

export interface UsageSummary {
  total_spend: number
  active_keys: number
  stopped_keys: number
  cost_centres: UsageSummaryCostCentre[]
  by_model: ModelBreakdown[]
}
