// Frozen API contract types for cost-centre management (Phase 3).

export interface Owner {
  user_id: string
  username: string
  display_name: string
  assigned_at: string
}

export interface RequestDefaults {
  allowed_models?: string[]
  rolling_limit?: number | null
  rolling_period_days?: number | null
  lifetime_budget?: number | null
  expires_at?: string | null
}

export interface CostCentre {
  id: string
  code: string
  name: string
  description: string | null
  status: 'active' | 'archived'
  budget_cap: number | null
  request_defaults: RequestDefaults | null
  created_by: string
  created_at: string
  updated_at: string
  owners: Owner[]
}

export interface UserListItem {
  id: string
  username: string
  display_name: string
  email: string
  roles: string[]
  is_active: boolean
}

export interface CreateCostCentreInput {
  code: string
  name: string
  description?: string
  budget_cap?: number | null
  request_defaults?: RequestDefaults | null
}

export interface UpdateCostCentreInput {
  name?: string
  description?: string | null
  budget_cap?: number | null
  request_defaults?: RequestDefaults | null
}
