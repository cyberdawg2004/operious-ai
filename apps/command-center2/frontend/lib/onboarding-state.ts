/**
 * Onboarding state machine (Phase 2.5d).
 *
 * Step state is DERIVED FROM REAL BACKEND DATA, never from local click
 * tracking. A step is `complete` only when its backend state confirms it —
 * e.g. a connector is complete only once its change request is APPLIED (it
 * shows up in the connectors read), not merely proposed. This makes it
 * impossible to falsely show "done".
 *
 * This module is React-free so the transitions are unit-testable in isolation.
 */

import type {
  AuthPrincipal,
  TenantChannelConfiguration,
  TenantConfigChangeRequest,
  TenantConnectorConfiguration,
  TenantGovernancePolicy,
  TenantLifecycleRecord,
} from "@/lib/api";

export const PLATFORM_TENANT_ADMIN_CAPABILITY = "platform.tenant.admin";

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
  | "create-tenant"
  | "grant-access"
  | "channel"
  | "connector"
  | "connector-credential"
  | "action-policy";

export type OnboardingPhase = "platform" | "tenant";

export type PendingChange = {
  change_request_id: string;
  status: TenantConfigChangeRequest["status"];
};

export type OnboardingStep = {
  id: OnboardingStepId;
  phase: OnboardingPhase;
  title: string;
  state: OnboardingStepState;
  /** A governed change awaiting approval/apply for this step, if any. */
  pendingChange: PendingChange | null;
};

export type OnboardingSnapshot = {
  targetTenantId: string | null;
  principal: AuthPrincipal | null;
  tenants: TenantLifecycleRecord[];
  channels: TenantChannelConfiguration[];
  connectors: TenantConnectorConfiguration[];
  policies: TenantGovernancePolicy[];
  changeRequests: TenantConfigChangeRequest[];
};

export function hasPlatformAdmin(principal: AuthPrincipal | null): boolean {
  return Boolean(
    principal?.capabilities?.includes(PLATFORM_TENANT_ADMIN_CAPABILITY)
  );
}

export function tenantExists(snapshot: OnboardingSnapshot): boolean {
  if (!snapshot.targetTenantId) return false;
  return snapshot.tenants.some(
    (tenant) => tenant.tenant_id === snapshot.targetTenantId
  );
}

/**
 * The Auth0 re-auth boundary. Phase B (tenant-scoped config) is unlocked only
 * when the ACTING token is scoped to the target tenant. There is no
 * cross-tenant configuration path — this is a tenant-isolation strength, not
 * an inconvenience. Attempting tenant-scoped reads before this holds 400s with
 * tenant_axis_missing, so the wizard must gate on it.
 */
export function tokenScopedToTarget(snapshot: OnboardingSnapshot): boolean {
  if (!snapshot.targetTenantId) return false;
  return snapshot.principal?.tenant_id === snapshot.targetTenantId;
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
 * policy is active — that is what lets it act. Before that it cannot.
 */
export function tenantIsOperational(snapshot: OnboardingSnapshot): boolean {
  return findActiveActionPolicy(snapshot.policies) !== null;
}

export function computeOnboardingSteps(
  snapshot: OnboardingSnapshot
): OnboardingStep[] {
  const isAdmin = hasPlatformAdmin(snapshot.principal);
  const created = tenantExists(snapshot);
  const scoped = tokenScopedToTarget(snapshot);
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

  // Step 1 — create tenant (platform gate, direct inert create).
  const createTenant: OnboardingStep = {
    id: "create-tenant",
    phase: "platform",
    title: "Create tenant",
    state: created ? "complete" : isAdmin ? "available" : "blocked",
    pendingChange: null,
  };

  // Step 2 — security gate: re-auth boundary into the new tenant.
  const grantAccess: OnboardingStep = {
    id: "grant-access",
    phase: "platform",
    title: "Grant tenant access (re-auth boundary)",
    state: !created ? "blocked" : scoped ? "complete" : "available",
    pendingChange: null,
  };

  const phaseBBlocked = !scoped;

  // Step 3 — governed channel create.
  const channel: OnboardingStep = {
    id: "channel",
    phase: "tenant",
    title: "Configure channel (governed)",
    state: phaseBBlocked
      ? "blocked"
      : hasChannel
        ? "complete"
        : pendingChannelCreate
          ? "in-progress"
          : "available",
    pendingChange: pendingChange(pendingChannelCreate),
  };

  // Step 4 — connector, gated on a matching channel existing.
  const connectorBlocked = phaseBBlocked || !hasChannel;
  const connector: OnboardingStep = {
    id: "connector",
    phase: "tenant",
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

  // Step 5 — connector credential via the channel credential path.
  const credential: OnboardingStep = {
    id: "connector-credential",
    phase: "tenant",
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

  // Step 6 — action policy; applying it is what makes the tenant operational.
  const actionPolicy: OnboardingStep = {
    id: "action-policy",
    phase: "tenant",
    title: "Configure action policy",
    state: phaseBBlocked
      ? "blocked"
      : activePolicy
        ? "complete"
        : pendingPolicy
          ? "in-progress"
          : "available",
    pendingChange: pendingChange(pendingPolicy),
  };

  return [
    createTenant,
    grantAccess,
    channel,
    connector,
    credential,
    actionPolicy,
  ];
}
