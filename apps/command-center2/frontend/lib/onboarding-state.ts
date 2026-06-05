/**
 * Onboarding state machine (Phase 2.5d) — Command Center, PHASE B ONLY.
 *
 * Creating a tenant (Phase A) is a PLATFORM operation and lives in the Platform
 * Console. A tenant operator must never see "create tenant" in the tenant
 * surface. The Command Center onboarding guide therefore starts at Phase B:
 * "you are scoped to a tenant — here is how to configure it" (channel →
 * connector → credential → action policy).
 *
 * Step state is DERIVED FROM REAL BACKEND DATA — a step is `complete` only when
 * its change request is APPLIED (reflected in a read), never from click
 * tracking. The tenant being configured is the one the acting token is scoped
 * to (principal.tenant_id); there is no cross-tenant target. React-free so the
 * transitions are unit-testable.
 */

import type {
  AuthPrincipal,
  TenantChannelConfiguration,
  TenantConfigChangeRequest,
  TenantConnectorConfiguration,
  TenantGovernancePolicy,
} from "@/lib/api";

// Mirrors ACTION_TOOLS_POLICY_TYPE in config-change-payloads.ts. Inlined so
// this state module carries no runtime cross-module import (keeps it directly
// unit-testable in isolation).
const ACTION_TOOLS_POLICY_TYPE = "action_tools";

export type OnboardingStepState =
  | "blocked"
  | "available"
  | "in-progress"
  | "complete";

export type OnboardingStepId =
  | "channel"
  | "connector"
  | "connector-credential"
  | "action-policy";

export type PendingChange = {
  change_request_id: string;
  status: TenantConfigChangeRequest["status"];
};

export type OnboardingStep = {
  id: OnboardingStepId;
  title: string;
  state: OnboardingStepState;
  /** A governed change awaiting approval/apply for this step, if any. */
  pendingChange: PendingChange | null;
};

export type OnboardingSnapshot = {
  principal: AuthPrincipal | null;
  channels: TenantChannelConfiguration[];
  connectors: TenantConnectorConfiguration[];
  policies: TenantGovernancePolicy[];
  changeRequests: TenantConfigChangeRequest[];
};

/**
 * Phase B requires a tenant-scoped session. The acting token's tenant defines
 * what is being configured — there is no cross-tenant target. If the session is
 * not tenant-scoped, every step is blocked (tenant-scoped reads would 400 with
 * tenant_axis_missing). This is the residual re-auth guard on the tenant side.
 */
export function isTenantScoped(principal: AuthPrincipal | null): boolean {
  return Boolean(principal?.tenant_id);
}

export function findActiveActionPolicy(
  policies: TenantGovernancePolicy[]
): TenantGovernancePolicy | null {
  return (
    policies.find(
      (policy) =>
        policy.policy_type === ACTION_TOOLS_POLICY_TYPE &&
        policy.status === "active"
    ) ?? null
  );
}

function isPending(request: TenantConfigChangeRequest): boolean {
  return request.status === "PROPOSED" || request.status === "APPROVED";
}

function changeOperation(request: TenantConfigChangeRequest): string {
  const operation = request.proposed_payload.operation;
  return typeof operation === "string" ? operation : "configure";
}

function pendingChange(
  request: TenantConfigChangeRequest | undefined
): PendingChange | null {
  return request
    ? { change_request_id: request.change_request_id, status: request.status }
    : null;
}

/**
 * The tenant is operational (no longer inert/fail-closed) once an action_tools
 * policy is active — that is what lets it act. The backend creates a tenant with
 * status `active`; "inert" means it has no action policy yet, not that its
 * status is provisioning.
 */
export function tenantIsOperational(snapshot: OnboardingSnapshot): boolean {
  return findActiveActionPolicy(snapshot.policies) !== null;
}

export function computeOnboardingSteps(
  snapshot: OnboardingSnapshot
): OnboardingStep[] {
  const scoped = isTenantScoped(snapshot.principal);
  const hasChannel = snapshot.channels.length > 0;
  const hasConnector = snapshot.connectors.length > 0;
  const credentialRotated = snapshot.channels.some(
    (channel) => channel.credential_rotated_at !== null
  );
  const activePolicy = findActiveActionPolicy(snapshot.policies);

  const pending = snapshot.changeRequests.filter(isPending);
  const pendingChannelCreate = pending.find(
    (cr) => cr.change_type === "channel" && changeOperation(cr) === "configure"
  );
  const pendingChannelCredential = pending.find(
    (cr) => cr.change_type === "channel" && changeOperation(cr) === "update"
  );
  const pendingConnector = pending.find((cr) => cr.change_type === "connector");
  const pendingPolicy = pending.find(
    (cr) =>
      cr.change_type === "policy" &&
      cr.proposed_payload.policy_type === ACTION_TOOLS_POLICY_TYPE
  );

  // Step 1 — governed channel create.
  const channel: OnboardingStep = {
    id: "channel",
    title: "Configure channel (governed)",
    state: !scoped
      ? "blocked"
      : hasChannel
        ? "complete"
        : pendingChannelCreate
          ? "in-progress"
          : "available",
    pendingChange: pendingChange(pendingChannelCreate),
  };

  // Step 2 — connector, gated on a matching channel existing.
  const connectorBlocked = !scoped || !hasChannel;
  const connector: OnboardingStep = {
    id: "connector",
    title: "Configure connector",
    state: connectorBlocked
      ? "blocked"
      : hasConnector
        ? "complete"
        : pendingConnector
          ? "in-progress"
          : "available",
    pendingChange: pendingChange(pendingConnector),
  };

  // Step 3 — connector credential via the channel credential path.
  const credential: OnboardingStep = {
    id: "connector-credential",
    title: "Set connector credential",
    state: connectorBlocked
      ? "blocked"
      : credentialRotated
        ? "complete"
        : pendingChannelCredential
          ? "in-progress"
          : "available",
    pendingChange: pendingChange(pendingChannelCredential),
  };

  // Step 4 — action policy; applying it is what makes the tenant operational.
  const actionPolicy: OnboardingStep = {
    id: "action-policy",
    title: "Configure action policy",
    state: !scoped
      ? "blocked"
      : activePolicy
        ? "complete"
        : pendingPolicy
          ? "in-progress"
          : "available",
    pendingChange: pendingChange(pendingPolicy),
  };

  return [channel, connector, credential, actionPolicy];
}
