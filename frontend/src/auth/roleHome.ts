// Single source of truth for where a signed-in user lands. A user may hold
// several roles; precedence is admin → cco → developer. Used by HomeRedirect
// (post-login routing) and ProtectedRoute (bouncing users off pages their role
// can't use) so both stay consistent with the role-aware nav in AppLayout.
export function roleHome(roles: string[]): string {
  if (roles.includes('admin')) return '/usage'
  if (roles.includes('cco')) return '/key-requests'
  return '/keys'
}
