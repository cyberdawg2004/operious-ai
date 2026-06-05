/**
 * Tenant status framing (Phase 2.5d-platform-onboarding).
 *
 * The backend creates a tenant with status `active` (see
 * tenant_lifecycle_service.create_tenant). A freshly created tenant is
 * nonetheless INERT — it cannot act until an action_tools policy is applied.
 * "Inert" is therefore a property of *missing configuration*, NOT of status:
 * the status is `active`, the tenant is fail-closed via the absent policy.
 *
 * This corrects the earlier (wrong) copy that called new tenants
 * "provisioning". React-free so the framing is unit-testable.
 */

import type { TenantStatus } from "@/lib/api";

export type TenantStatusFraming = {
  /** Short badge label. */
  label: string;
  /** One-line explanation suitable for operator copy. */
  detail: string;
};

export function describeTenantStatus(status: TenantStatus): TenantStatusFraming {
  switch (status) {
    case "active":
      return {
        label: "Active · inert",
        detail:
          "Status: active — inert (no action policy yet), fail-closed until configured.",
      };
    case "disabled":
      return {
        label: "Disabled",
        detail: "Status: disabled — the tenant is administratively turned off.",
      };
    case "provisioning":
      return {
        label: "Provisioning",
        detail: "Status: provisioning — the tenant is being set up.",
      };
    default:
      return { label: String(status), detail: `Status: ${String(status)}.` };
  }
}
