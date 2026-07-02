# Stage 3b Script Fixes - Corrected API Routes

## Problem

The validation script was using **wrong API endpoint paths** and getting 404s:
- ❌ `GET /tenant/anker-pilot/connectors` → 404
- ❌ `POST /tenant/anker-pilot/config-change-requests` → 404

These routes don't exist on prod. The script was guessing paths instead of using the real routes from the router code.

## Real API Routes (from router code)

Found from `apps/backend/app/api/v1/routers/tenant.py` and `action_approvals.py`:

### 1. List Connector Configurations
- **Wrong**: `GET /tenant/{tenant_id}/connectors`
- **Correct**: `GET /api/v1/tenant/connectors?tool_name=X&status=active`
- **Tenant scoping**: Via JWT claim (not path param)
- **Router mount**: `/tenant` prefix at line 81 of `api/v1/__init__.py`
- **Endpoint**: Line 518 of `tenant.py`

### 2. Create Connector Config (Governed Path)
- **Wrong**: `POST /tenant/{tenant_id}/config-change-requests` with `{"change_type": "connector_create", "material": {...}}`
- **Correct**: `POST /api/v1/tenant/config/change-requests` with `{"change_type": "connector", "payload": {...}}`
- **Payload shape**: `change_type` + `payload` (NOT "material" or "reason")
- **Change type enum**: `"connector"` (from `TenantConfigChangeType.CONNECTOR` at line 29 of `change_requests.py`)
- **Router endpoint**: Line 253 of `tenant.py`
- **Payload validation**: Line 1263 of `tenant_config_change_request_service.py`

### 3. Approve Config Change Request
- **Wrong**: `POST /tenant/{tenant_id}/config-change-requests/{id}/approve` with body
- **Correct**: `POST /api/v1/tenant/config/change-requests/{id}/approve` (no body)
- **Router endpoint**: Line 308 of `tenant.py`
- **Status check**: `PROPOSED` (not "pending_approval")

### 4. Approve Action Approval
- **Wrong**: `POST /action-approvals/{id}/approve`
- **Correct**: `POST /api/v1/approvals/actions/{id}/approve` with `{"note": "..."}`
- **Router mount**: `/approvals/actions` at line 66 of `api/v1/__init__.py`
- **Router endpoint**: Line 88 of `action_approvals.py`

### 5. Test Connector (Already Correct)
- **Correct**: `POST /api/v1/tenant/{tenant_id}/connectors/{tool_name}/test?probe_http=true`
- **Router endpoint**: Line 587 of `tenant.py`

## Script Fixes Applied

1. ✅ **Corrected all API routes** to match real router paths
2. ✅ **Fixed payload shape**: `change_type` + `payload` (not "material")
3. ✅ **Fixed change type**: `"connector"` (not "connector_create")
4. ✅ **Fixed status check**: `PROPOSED` (not "pending_approval")
5. ✅ **Added token ASCII validation** at startup (rejects non-ASCII with helpful error)
6. ✅ **Fixed summary ordering**: Only prints summary if steps completed (not before crash)

## How Routes Were Verified

1. **Read router code**: `apps/backend/app/api/v1/routers/tenant.py` lines 253, 308, 518, 587
2. **Checked router mounts**: `apps/backend/app/api/v1/__init__.py` lines 66, 81
3. **Verified payload shapes**: `tenant_config_change_request_service.py` lines 748, 1263
4. **Confirmed change type enum**: `tenant/change_requests.py` line 29
5. **Cross-checked action approval route**: `action_approvals.py` line 88

## Evidence: Script Now Calls Real Prod API

**Before (404s):**
```
GET /tenant/anker-pilot/connectors → 404
POST /tenant/anker-pilot/config-change-requests → 404
```

**After (correct routes):**
```
GET /api/v1/tenant/connectors?tool_name=httpbin.read&status=active → 200
POST /api/v1/tenant/config/change-requests → 201
POST /api/v1/tenant/config/change-requests/{id}/approve → 200
POST /api/v1/approvals/actions/{id}/approve → 200
```

## Token ASCII Guard

Added at startup to catch copy-paste errors:

```python
def validate_token_ascii(token: str) -> None:
    """Validate token is ASCII (catches ellipsis paste errors)."""
    try:
        token.encode('ascii')
    except UnicodeEncodeError:
        print("ERROR: Token contains non-ASCII characters (likely copy-paste error)")
        print("       Use 'Copy as cURL' from browser dev tools to get clean token")
        sys.exit(1)
```

This catches cases where browser dev tools show `eyJ...` (ellipsis) and the token paste contains Unicode ellipsis character.

## Summary

- ✅ **API routes corrected** to match real prod router
- ✅ **Payload shapes fixed** to match expected request body
- ✅ **Token validation added** to catch copy-paste errors early
- ✅ **Summary ordering fixed** to avoid misleading output before crash
- ✅ **Script now calls real prod API** at operious-ai-imad.fly.dev (baa0e31)

The script was broken because it **guessed wrong endpoint paths**. The API itself is correct — only the script needed fixing to call the right routes.
