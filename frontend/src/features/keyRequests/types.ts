// Frozen API contract types for the key request & approval flow (Phase 5).

export type KeyRequestStatus = 'pending' | 'approved' | 'rejected'

export interface ApprovedConstraints {
  allowed_models: string[]
  rolling_limit: number | null
  rolling_period_days: number | null
  lifetime_budget: number | null
  expiry_days: number | null
  expires_at: string | null
}

export interface KeyRequest {
  id: string
  developer_id: string
  developer_username: string
  developer_display_name: string
  cost_centre_id: string
  cost_centre_code: string
  cost_centre_name: string
  status: KeyRequestStatus
  justification: string | null
  rejection_reason: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  approved_constraints: ApprovedConstraints | null
  created_at: string
  updated_at: string
}

export interface InferenceProfileRef {
  model_id: string
  profile_arn: string
  profile_name: string
}

export interface ProvisionedKey {
  id: string
  cost_centre_id: string
  cost_centre_code: string
  iam_username: string
  status: string
  allowed_models: string[]
  rolling_limit: number | null
  rolling_period_days: number | null
  lifetime_budget: number | null
  expires_at: string | null
  bearer_token: string
  inference_profiles: InferenceProfileRef[]
}

export interface KeyRequestResult {
  request: KeyRequest
  key: ProvisionedKey | null
}

export interface CreateKeyRequestInput {
  cost_centre_id: string
  justification?: string
}

export interface ApproveKeyRequestInput {
  allowed_models?: string[]
  rolling_limit?: number
  rolling_period_days?: number
  lifetime_budget?: number
  expiry_days?: number
  expires_at?: string
}

export interface RejectKeyRequestInput {
  rejection_reason: string
}
