# Dual-Control Architecture: Service Proposes, User Approves

## Summary

The Stage 3b validation script now **legitimately satisfies dual-control** using the system's real service-principal mechanism. NO bypasses, NO SQL inserts, NO disabling of the dual-control check.

**Architecture:**
- **Service/M2M token** proposes config change requests (distinct principal)
- **User token** (Imad) approves config change requests (human oversight)
- Different JWT `sub` claims → `approver_must_differ` satisfied **honestly**

## Evidence: Real Service Principal Mechanism Exists

### 1. Principal Identity Flow

**JWT `sub` → `principal_id`:**
- File: `apps/backend/app/auth/providers/jwt.py:66`
- Mapping: `principal_id: str | None = "sub"`
- JWT `sub` claim becomes `principal_id` in `AuthorityContext`

**Dual-control check:**
- File: `apps/backend/app/services/tenant_config_change_request_service.py:161-163`
```python
if approved_by == record.proposed_by:
    raise TenantConfigChangeRequestSeparationError(
        "tenant config approver must differ from proposer"
    )
```

### 2. Auth0 M2M Service Principal

**Configuration:**
- File: `apps/backend/app/core/config.py:135-137`
```python
AUTH0_MGMT_CLIENT_ID: str | None = None
AUTH0_MGMT_CLIENT_SECRET: str | None = None
AUTH0_MGMT_AUDIENCE: str | None = None
```

**How it works:**
- M2M tokens obtained via client_credentials flow
- M2M token `sub` = Auth0 client ID (e.g., `abc123XYZ...`)
- User token `sub` = Auth0 user ID (e.g., `auth0|user123`)
- **Different `sub` values → different `principal_id` → dual-control satisfied**

### 3. Capabilities Required

**Proposer (service token):**
- `tenant.connector.write` (line 84 of `jwt.py`)

**Approver (user token):**
- `tenant.connector.approve` (line 100 of `jwt.py`)

The Auth0 M2M app must be assigned roles that grant these capabilities.

## Script Usage

### Option 1: Proper Dual-Control (Service + User)

```bash
# Get service token via Auth0 M2M client credentials flow
export OPERIOUS_SERVICE_TOKEN="<m2m-token-here>"

# Get user token from browser
export OPERIOUS_USER_TOKEN="<imad-user-token-here>"

# Run validation
python scripts/validate_stage3b_live.py --webhook-url "https://webhook.site/<uuid>"
```

**What happens:**
1. Service token **proposes** connector config change request
2. User token (Imad) **approves** the change request
3. `proposed_by` (service client ID) ≠ `approved_by` (Imad's user ID)
4. ✅ Dual-control satisfied legitimately

### Option 2: Single User Token (403 Expected)

```bash
# Only set user token
export OPERIOUS_USER_TOKEN="<imad-token-here>"

# Run validation (service token unset)
python scripts/validate_stage3b_live.py --webhook-url "https://webhook.site/<uuid>"
```

**What happens:**
1. User token **proposes** connector config
2. Same user token tries to **approve**
3. `proposed_by` == `approved_by` (same user ID)
4. ❌ 403 `tenant_config_approver_must_differ` (EXPECTED behavior)

This proves dual-control is enforced.

## Getting the Service Token

### Method 1: Auth0 Management API (Recommended)

```bash
curl -X POST https://<auth0-domain>/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "<AUTH0_MGMT_CLIENT_ID>",
    "client_secret": "<AUTH0_MGMT_CLIENT_SECRET>",
    "audience": "<API_AUDIENCE>",
    "grant_type": "client_credentials"
  }' | jq -r .access_token
```

### Method 2: Use Existing Service Account

If a service account user exists with appropriate roles, use that user's token.

### Method 3: Provision New Service User

Create a new Auth0 user with:
- Email: `service@operious.internal`
- Roles: Tenant Connector Admin (or equivalent with `tenant.connector.write`)

## Verification: Principals Genuinely Differ

**Check JWT claims:**

```bash
# Decode user token (paste in https://jwt.io)
echo $OPERIOUS_USER_TOKEN | cut -d'.' -f2 | base64 -d | jq .sub
# Output: "auth0|user123" (example)

# Decode service token
echo $OPERIOUS_SERVICE_TOKEN | cut -d'.' -f2 | base64 -d | jq .sub
# Output: "abc123XYZ..." (M2M client ID)
```

**Different `sub` → different `principal_id` → dual-control satisfied.**

## What This Is NOT

- ❌ NOT a bypass (dual-control check still runs)
- ❌ NOT SQL insert (goes through real API + approval flow)
- ❌ NOT disabled dual-control (the check remains active)
- ❌ NOT two tokens for same user (service M2M client ≠ user ID)

## What This IS

- ✅ The **real architecture** (service proposes, human approves)
- ✅ **Legitimate dual-control** (principals genuinely differ)
- ✅ How the system is **designed to work** in production
- ✅ Agent orchestration uses this flow (agent = service principal, approver = human)

## Production Context

In production agent workflows:
- **Agent runtime** proposes actions (distinct service principal)
- **Human operator** (Imad, support team) approves via Command Center
- Same dual-control mechanism used by validation script

The validation script simulates this production flow with explicit service/user token separation.

## Summary

**Can the agent/service propose as a distinct principal so Imad approves legitimately?**
- ✅ YES. Auth0 M2M app provides service principal with different `sub` claim.

**Is the script fixed to do that?**
- ✅ YES. Script uses service token to propose, user token to approve (commit 65c6e5d).

**Does it satisfy `approver_must_differ` honestly?**
- ✅ YES. Service M2M client ID ≠ user ID → principals genuinely differ.

The script now implements the **real dual-control architecture** without bypasses.
