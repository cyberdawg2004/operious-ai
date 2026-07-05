# Operious AI — Access Review Process

**Version:** 2026-07-05  
**Review frequency:** Quarterly (or following any personnel change)

---

## 1. Capability Model

Operious AI uses a domain-capability model. Capabilities are embedded in Auth0 JWTs and verified at every API endpoint. The full capability surface is defined in `app/dependencies/authority.py` and the role-to-capability mapping in `app/auth/providers/jwt.py`.

### 1.1 Auth0 Roles and Their Capabilities

Each Auth0 role grants a fixed, code-defined set of capabilities (source: `ROLE_CAPABILITY_MAP` in `app/auth/providers/jwt.py`):

| Auth0 Role | Capabilities Granted |
|---|---|
| `PlatformAdmin` | `platform.tenant.admin` |
| `Operator` | `operator`, `tenant.operations.read`, `tenant.supervisor.read`, `tenant.observability.read` |
| `TenantAdmin` / `TenantConfigAdmin` | `tenant.channel.admin`, `tenant.knowledge.write`, `tenant.policy.write`, `tenant.topology.write`, `tenant.execution_governance.write`, `tenant.connector.write`, `tenant.connector.read`, `tenant.config.read`, `tenant.config.write` |
| `TenantApprover` | `tenant.config.read`, `tenant.config.approve` |
| `TenantConnectorApprover` | `tenant.connector.read`, `tenant.connector.approve` |
| `TenantActionApprover` / `TenantCaseApprover` | `tenant.approvals.read`, `tenant.actions.approve` |
| `TenantPrivacyAdmin` | `tenant.privacy.admin` |
| `TenantPrivacyApprover` | `tenant.privacy.approve` |
| `TenantAuditor` | `tenant.audit.export` |
| `TenantObserver` | `tenant.observability.read` |
| `TenantConfigWriter` | `tenant.config.write`, `tenant.config.read` |
| `TenantChannelAdmin` | `tenant.channel.admin`, `tenant.config.read` |
| `TenantKnowledgeWriter` | `tenant.knowledge.write`, `tenant.config.read` |
| `TenantPolicyWriter` | `tenant.policy.write`, `tenant.config.read` |
| `TenantTopologyWriter` | `tenant.topology.write`, `tenant.config.read` |
| `TenantExecGovWriter` | `tenant.execution_governance.write`, `tenant.config.read` |
| `TenantConnectorWriter` | `tenant.connector.write`, `tenant.connector.read`, `tenant.config.read` |
| `TenantConnectorViewer` | `tenant.connector.read` |
| `TenantViewer` | `tenant_read` |
| `TenantGovernanceViewer` | `tenant.governance.read` |
| `TenantCognitionViewer` | `tenant.cognition.read` |
| `TenantSupervisor` | `tenant.supervisor.read` |
| `TenantOperationsViewer` | `tenant.operations.read` |
| `TenantResolutionGuider` | `tenant.approvals.read`, `tenant.resolution.guide` |
| `TenantApprovalsViewer` | `tenant.approvals.read` |
| `TenantTrainingWriter` | `tenant.training.write` |

### 1.2 Separation of Duties

The following pairs are intentionally separated — the same principal cannot hold both roles without explicit dual assignment:

| Propose / Write | Approve / Apply | Rationale |
|---|---|---|
| `TenantAdmin` (propose config changes) | `TenantApprover` (`tenant.config.approve`) | Dual-control config ledger (S-03) |
| `TenantConnectorWriter` (propose connector) | `TenantConnectorApprover` (`tenant.connector.approve`) | Connector credential approval |
| `TenantPrivacyAdmin` (propose erasure) | `TenantPrivacyApprover` (`tenant.privacy.approve`) | Irreversible data erasure |

Code enforcement: `require_config_apply_authorization` and `ErasureRequestSeparationError` both raise if the same principal attempts both duties.

---

## 2. Access Surfaces Subject to Review

### 2.1 Auth0 Role Assignments

**What to review:** Current list of principals with each role for each tenant and for the platform.  
**Review scope:**
- Verify no principal holds both a `*Writer`/`*Admin` role and the corresponding `*Approver` role for the same config domain.
- Verify `PlatformAdmin` is limited to Operious staff who require it.
- Verify `TenantPrivacyAdmin` and `TenantPrivacyApprover` are assigned to distinct individuals per tenant.
- Verify departed personnel have been removed.

**How:** Auth0 Management Dashboard → Users & Roles. The backend's `AUTH0_MGMT_CLIENT_ID` / `AUTH0_MGMT_CLIENT_SECRET` are used for programmatic provisioning via `build_auth0_management_client`.

### 2.2 Fly.io Access

**What to review:** Fly.io organization members with deploy or secret access to the `operious-ai-imad` app.  
**Review scope:**
- List current members via Fly.io dashboard → Organization → Members.
- Verify only current employees with operational necessity retain access.
- Verify secrets (`fly secrets list --app operious-ai-imad`) do not expose stale credentials.

### 2.3 Neon Database Access

**What to review:** Neon project members and database roles.  
**Review scope:**
- Verify `neondb_owner` access is limited to database administrators.
- Verify `operious_app` role retains `BYPASSRLS=False` (run: `SELECT rolbypassrls FROM pg_roles WHERE rolname = 'operious_app'`).
- Verify no other role has `BYPASSRLS=True`.
- Verify connection credentials (`DATABASE_URL`) are rotated after any access change.

### 2.4 AWS IAM (Bedrock, SES, S3)

**What to review:** IAM users and roles for Bedrock inference, SES delivery, and S3 attachment storage.  
**Review scope:**
- Verify Bedrock access is limited to the inference calls needed by the platform.
- Verify SES credentials (`LIVE_SES_ACCESS_KEY_ID`) are scoped to the sending domain only.
- Verify S3 access (`ATTACHMENTS_S3_ACCESS_KEY_ID`) is scoped to the attachments bucket only.
- Verify no unused IAM users or access keys remain.

### 2.5 GCP Cloud KMS

**What to review:** Service account with access to the KMS key (`OPERIOUS_KMS_KEY_RESOURCE`).  
**Review scope:**
- Verify the service account (`GOOGLE_APPLICATION_CREDENTIALS`) has `cloudkms.cryptoKeyVersions.useToDecrypt` and `useToEncrypt` only — no broader KMS admin rights.
- Verify no other service account has access to the key.

---

## 3. Quarterly Review Checklist

The following checklist is completed by the platform security owner each quarter:

- [ ] Auth0 role assignments audited for all tenants and platform roles
- [ ] Dual-control role pairs verified (no principal holds both sides)
- [ ] `PlatformAdmin` list reviewed and confirmed to current Operious staff
- [ ] `TenantPrivacyAdmin` and `TenantPrivacyApprover` are distinct per tenant
- [ ] Fly.io organization membership reviewed; departed employees removed
- [ ] `operious_app` `BYPASSRLS=False` verified in Neon production
- [ ] AWS IAM users and keys for Bedrock/SES/S3 reviewed
- [ ] GCP service account access to KMS key reviewed
- [ ] Fly secrets reviewed for stale or unused entries
- [ ] Review findings documented and action items tracked

---

## 4. Offboarding Procedure

When a team member or contractor leaves or changes roles:

1. **Auth0:** Remove or adjust role assignments in the Auth0 Management Dashboard. If the individual held `TenantApprover` or `TenantPrivacyApprover`, assign a replacement before removal to preserve dual-control coverage.
2. **Fly.io:** Remove from Fly.io organization membership via the dashboard.
3. **Neon:** Revoke direct database access if any was granted; rotate `ALEMBIC_DATABASE_URL` if the individual had DDL access.
4. **AWS IAM:** Deactivate or delete personal IAM keys.
5. **GCP:** Remove personal GCP identities from KMS key IAM bindings.
6. **Webhook secrets:** If the individual had access to connector or webhook secrets, rotate those secrets via `fly secrets set`.
7. **Audit trail:** The governance event log (`governance_decisions` table, `tenant_config_change_requests` table) is preserved and is not modified during offboarding.

---

## 5. Access Grants

New access is granted on the principle of least privilege:

- Grant the most specific capability role that satisfies the work requirement.
- Never grant `PlatformAdmin` without a documented operational reason.
- Always assign `TenantApprover` / `TenantPrivacyApprover` to a different individual than the corresponding write/admin role.
- Document the grant reason and reviewer in the access management system.

---

## Contact

Access review questions: `security@operious.com`
