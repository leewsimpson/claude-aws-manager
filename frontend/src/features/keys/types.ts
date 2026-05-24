// Frozen API contract types for key management (Phase 6).

export type KeyStatus = 'active' | 'stopped' | 'revoked' | 'expired'

export interface InferenceProfileRef {
  model_id: string
  profile_arn: string
  profile_name: string
}

export interface Key {
  id: string
  developer_id: string
  developer_username: string
  developer_display_name: string
  cost_centre_id: string
  cost_centre_code: string
  cost_centre_name: string
  iam_username: string
  status: KeyStatus
  allowed_models: string[]
  rolling_limit: number | null
  rolling_period_days: number | null
  lifetime_budget: number | null
  lifetime_spend: number
  expires_at: string | null
  created_at: string
  revoked_at: string | null
  inference_profiles: InferenceProfileRef[]
}

export interface KeyFilters {
  status?: KeyStatus
  cost_centre_id?: string
  developer_id?: string
}

export interface UpdateKeyConstraintsInput {
  allowed_models?: string[]
  rolling_limit?: number | null
  rolling_period_days?: number | null
  lifetime_budget?: number | null
  expiry_days?: number | null
}
