# Authentication & SSO Options

## Overview

The platform needs authentication for both production (corporate SSO) and PoC (hardcoded users). This document covers the options and how they integrate with the overall architecture.

---

## PoC Authentication (Phase 1)

Simple hardcoded users for the proof of concept:

```
admin/admin
dev1/dev1
dev2/dev2
ccowner1/ccowner1
ccowner2/ccowner2
```

Implementation options:
- **In-memory user store** with bcrypt-hashed passwords
- **JWT tokens** for session management
- Simple middleware that checks credentials

---

## Production Authentication

### Option 1: AWS Cognito (Recommended for AWS-Native)

AWS Cognito provides:
- User pools for authentication
- OIDC/SAML federation with corporate IdPs
- Built-in token management (JWT)
- User groups for role management
- Hosted UI or custom UI integration

**Architecture:**
```
Corporate IdP (Azure AD / Okta / etc.)
        │
        ▼ (SAML/OIDC Federation)
AWS Cognito User Pool
        │
        ▼ (JWT tokens)
Our Platform (validates tokens)
```

**Key Features:**
- Federated sign-in with SAML 2.0 and OIDC
- User groups: `Admins`, `Developers`, `CostCentreOwners`
- Automatic user provisioning on first login
- User deactivation detection (for key revocation on offboarding)

**References:**
- https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html
- https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-saml-idp.html

### Option 2: Azure AD / Entra ID (If Microsoft-Centric)

If the organisation uses Microsoft:
- OIDC integration directly
- Microsoft Graph API for user/group management
- Automatic deprovisioning via SCIM

### Option 3: Okta / Auth0

Third-party identity providers:
- Rich SDK support
- SCIM for user provisioning/deprovisioning
- Custom claims for roles

---

## SSO-Based Offboarding (Requirement)

When a user is deactivated in the identity provider, all their keys must be automatically disabled.

### Implementation Approaches:

#### A. Webhook/Event-Driven (Best)
- IdP sends webhook on user deactivation
- Platform immediately disables all keys for that user
- Requires IdP webhook support (Okta, Azure AD support this)

#### B. SCIM Provisioning
- Standard protocol for user provisioning/deprovisioning
- IdP pushes changes to our SCIM endpoint
- On deactivation event, disable keys

#### C. Periodic Sync (Simplest)
- Platform periodically checks user status against IdP
- On finding deactivated user, disables their keys
- Latency between deactivation and key disable (minutes to hours)

#### D. Token Expiry + Refresh Check
- Short-lived tokens require re-authentication
- On refresh attempt, check user status
- Keys effectively stop working when token can't refresh

---

## Role-Based Access Control (RBAC)

### Roles in Our System

| Role | Permissions |
|------|-------------|
| Administrator | Full access, manage cost centres, approve any request, view all dashboards |
| Cost Centre Owner | Manage their cost centre(s), approve requests, view scoped dashboard |
| Developer | Request keys, view own keys/usage, revoke own keys |

### Implementation Options

#### JWT Claims-Based (Recommended)

```json
{
  "sub": "user-123",
  "email": "john@company.com",
  "roles": ["developer", "cost_centre_owner"],
  "cost_centres": ["CC-1234", "CC-5678"],
  "iat": 1716451200,
  "exp": 1716454800
}
```

#### Database-Backed Roles

```sql
CREATE TABLE user_roles (
  user_id UUID REFERENCES users(id),
  role VARCHAR(50) NOT NULL,
  cost_centre_id UUID REFERENCES cost_centres(id), -- NULL for global roles
  PRIMARY KEY (user_id, role, cost_centre_id)
);
```

---

## Break-Glass Super Admin

Requirement: A default super admin account configured outside the UI.

### Implementation Options:

1. **Environment Variable:**
```bash
SUPER_ADMIN_EMAIL=admin@company.com
SUPER_ADMIN_PASSWORD_HASH=$2b$12$...
```

2. **Config File:**
```json
{
  "superAdmin": {
    "username": "superadmin",
    "passwordHash": "$2b$12$..."
  }
}
```

3. **AWS Secrets Manager:**
```bash
aws secretsmanager get-secret-value --secret-id claude-manager/super-admin
```

---

## Session Management

### JWT-Based (Stateless)
- Access token (short-lived: 15-60 min)
- Refresh token (longer-lived: 7-30 days)
- No server-side session storage needed

### Cookie-Based (Stateful)
- Server-side session store (Redis/DB)
- Cookie with session ID
- Easier to revoke individual sessions

### Recommendation for PoC
- JWT with 1-hour expiry
- Refresh token with 24-hour expiry
- Switch to Cognito/SSO for production

---

## References

- https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html
- https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-saml-idp.html
- https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html
- https://learn.microsoft.com/en-us/entra/identity-platform/
- https://www.okta.com/developer/
- https://auth0.com/docs
- https://datatracker.ietf.org/doc/html/rfc7644 (SCIM)
