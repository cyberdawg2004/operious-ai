/**
 * Pure builders for the tenant config-change ledger payloads (Phase 2.5b-ui).
 *
 * This module is intentionally React-free so the security-critical payload
 * shaping can be unit-tested in isolation (tests-frontend imports it directly).
 *
 * HARD CONSTRAINT A (Step 0): credentials are a SEPARATE path. The connector
 * config payload MUST NOT carry credentials/credentials_enc/webhook_secret —
 * the 2.5a ledger rejects those with "connector config credentials must use
 * the channel credential path". A connector credential is set via a CHANNEL
 * change request instead. `buildConnectorChangePayload` therefore strips any
 * forbidden key defensively, and exposes that guarantee for tests.
 */

import type { TenantConfigChangeType } from "@/lib/api";

/** The payload _schema_version the 2.5a validator pins. */
export const CONFIG_CHANGE_SCHEMA_VERSION = "1";

/** action_tools policy discriminator (mirrors ACTION_TOOLS_POLICY_TYPE). */
export const ACTION_TOOLS_POLICY_TYPE = "action_tools";

/**
 * Credential keys the connector ledger validator forbids. Mirrors
 * `_validate_connector_payload` forbidden set in
 * tenant_config_change_request_service.py. Kept here so the editor can never
 * leak a credential into the connector config payload.
 */
export const CONNECTOR_FORBIDDEN_CREDENTIAL_KEYS = [
  "access_token",
  "api_key",
  "auth_header",
  "bearer_token",
  "credential",
  "credentials",
  "credentials_enc",
  "webhook_secret",
] as const;

/** connector_type must map to a tenant channel type (2.5a validator). */
export const CONNECTOR_TYPE_OPTIONS = [
  "email",
  "whatsapp",
  "shopify",
  "shulex",
  "lark",
  "zendesk",
  "voice",
  "jira",
  "linear",
] as const;

export const HTTP_METHOD_OPTIONS = [
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
] as const;

export const CONNECTOR_STATUS_OPTIONS = ["active", "disabled"] as const;

/** Wire values of governance Decision (app/governance/enums.py). */
export const POLICY_DECISION_VALUES = [
  "allow",
  "deny",
  "require_approval",
] as const;
export type PolicyDecision = (typeof POLICY_DECISION_VALUES)[number];

export type ConnectorChangeInput = {
  connector_type: string;
  tool_name: string;
  http_method: string;
  endpoint_template: string;
  endpoint_host: string;
  field_mappings: Record<string, unknown>;
  idempotency_header_name: string;
  response_parse: Record<string, unknown>;
  success_status_codes: number[];
  status?: string;
};

export type ConfigChangeRequestBody = {
  change_type: TenantConfigChangeType;
  payload: Record<string, unknown>;
};

/**
 * Build a `connector` change request body. Credentials are NEVER included —
 * any forbidden credential key present on the input is stripped defensively,
 * so a UI mistake cannot send a credential down the connector path.
 */
export function buildConnectorChangePayload(
  input: ConnectorChangeInput
): ConfigChangeRequestBody {
  const payload: Record<string, unknown> = {
    _schema_version: CONFIG_CHANGE_SCHEMA_VERSION,
    operation: "configure",
    connector_type: input.connector_type,
    tool_name: input.tool_name,
    http_method: input.http_method.toUpperCase(),
    endpoint_template: input.endpoint_template,
    endpoint_host: input.endpoint_host,
    field_mappings: input.field_mappings,
    idempotency_header_name: input.idempotency_header_name,
    response_parse: input.response_parse,
    success_status_codes: input.success_status_codes,
    status: input.status ?? "active",
  };
  return { change_type: "connector", payload: stripCredentialKeys(payload) };
}

/**
 * Defensive: drop any forbidden credential key at any depth. The connector
 * config path must remain credential-free.
 */
export function stripCredentialKeys<T>(value: T): T {
  const forbidden = new Set<string>(CONNECTOR_FORBIDDEN_CREDENTIAL_KEYS);
  const visit = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(visit);
    if (node && typeof node === "object") {
      const out: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(node as Record<string, unknown>)) {
        if (forbidden.has(key.toLowerCase())) continue;
        out[key] = visit(item);
      }
      return out;
    }
    return node;
  };
  return visit(value) as T;
}

/** Returns true if any forbidden credential key appears anywhere in payload. */
export function payloadContainsCredentialKeys(value: unknown): boolean {
  const forbidden = new Set<string>(CONNECTOR_FORBIDDEN_CREDENTIAL_KEYS);
  const visit = (node: unknown): boolean => {
    if (Array.isArray(node)) return node.some(visit);
    if (node && typeof node === "object") {
      for (const [key, item] of Object.entries(node as Record<string, unknown>)) {
        if (forbidden.has(key.toLowerCase())) return true;
        if (visit(item)) return true;
      }
    }
    return false;
  };
  return visit(value);
}

export type ActionPolicyInput = {
  /** Present when proposing an UPDATE to an existing policy. */
  policyId?: string;
  effectiveFrom?: string;
  warrantyConfidenceGte: number;
  warrantyIssueCategories: string[];
  warrantyElse: PolicyDecision;
  replacementAlways: PolicyDecision;
  refundAmountCentsLte: number;
  refundConfidenceGte?: number | null;
  refundElse: PolicyDecision;
  warehouseAllowSeverities: string[];
  warehouseRequireApprovalSeverities: string[];
};

/**
 * Assemble the `tools` parameters block that
 * `validate_action_tools_policy_parameters` expects. Malformed combinations
 * are still rejected server-side at propose; the form surfaces that error.
 */
export function buildActionPolicyParameters(
  input: ActionPolicyInput
): Record<string, unknown> {
  const refundAllow: Record<string, unknown> = {
    refund_amount_cents_lte: input.refundAmountCentsLte,
  };
  if (input.refundConfidenceGte !== null && input.refundConfidenceGte !== undefined) {
    refundAllow.confidence_gte = input.refundConfidenceGte;
  }
  return {
    tools: {
      "warranty.claim": {
        allow: {
          confidence_gte: input.warrantyConfidenceGte,
          issue_category_in: input.warrantyIssueCategories,
        },
        else: input.warrantyElse,
      },
      "replacement.order": {
        always: input.replacementAlways,
      },
      "refund.request": {
        allow: refundAllow,
        else: input.refundElse,
      },
      "warehouse.repair.report": {
        allow: { severity_in: input.warehouseAllowSeverities },
        require_approval: {
          severity_in: input.warehouseRequireApprovalSeverities,
        },
      },
    },
  };
}

/**
 * Build a `policy` change request body for the action_tools policy. When
 * `policyId` is present the ledger treats it as an update; otherwise a new
 * policy is proposed (requires effective_from).
 */
export function buildActionPolicyChangePayload(
  input: ActionPolicyInput
): ConfigChangeRequestBody {
  const payload: Record<string, unknown> = {
    _schema_version: CONFIG_CHANGE_SCHEMA_VERSION,
    policy_type: ACTION_TOOLS_POLICY_TYPE,
    parameters: buildActionPolicyParameters(input),
  };
  if (input.policyId) {
    payload.operation = "update";
    payload.policy_id = input.policyId;
  }
  if (input.effectiveFrom) {
    payload.effective_from = input.effectiveFrom;
  }
  return { change_type: "policy", payload };
}

export type ChannelCredentialInput = {
  configId: string;
  routingAddress?: string;
  /** Blank values are dropped — blank means "keep current". Write-only. */
  credentials?: Record<string, string>;
  webhookSecret?: string;
  status?: string;
};

/**
 * Build a `channel` change request body that rotates a connector's credential
 * via the dedicated channel credential path (HARD CONSTRAINT A, step ii).
 *
 * Write-only semantics: only credential fields the operator actually typed are
 * included. A blank field is omitted entirely, so it keeps the current value —
 * the existing value is never read back into the form, never displayed, never
 * re-sent.
 */
export function buildChannelCredentialChangePayload(
  input: ChannelCredentialInput
): ConfigChangeRequestBody {
  const payload: Record<string, unknown> = {
    _schema_version: CONFIG_CHANGE_SCHEMA_VERSION,
    operation: "update",
    config_id: input.configId,
  };
  const credentials = dropBlankValues(input.credentials ?? {});
  if (Object.keys(credentials).length > 0) {
    payload.credentials = credentials;
  }
  if (input.webhookSecret && input.webhookSecret.trim()) {
    payload.webhook_secret = input.webhookSecret.trim();
  }
  if (input.routingAddress && input.routingAddress.trim()) {
    payload.routing_address = input.routingAddress.trim();
  }
  if (input.status) {
    payload.status = input.status;
  }
  return { change_type: "channel", payload };
}

export type ChannelCreateInput = {
  channelType: string;
  routingAddress: string;
  credentials: Record<string, string>;
  webhookSecret: string;
  status?: string;
};

/**
 * Build a `channel` change request body that CREATES a channel through the
 * governed ledger (Phase 2.5d). In production, direct channel create is
 * disabled — onboarding must propose a channel change request that goes
 * proposed → approved → applied like every other control.
 *
 * This is the channel credential path, so credentials/webhook_secret are
 * expected here (unlike the connector path, where they are forbidden). The
 * 2.5a validator requires channel_type, routing_address, credentials, and
 * webhook_secret for a `configure` operation.
 */
export function buildChannelChangePayload(
  input: ChannelCreateInput
): ConfigChangeRequestBody {
  const payload: Record<string, unknown> = {
    _schema_version: CONFIG_CHANGE_SCHEMA_VERSION,
    operation: "configure",
    channel_type: input.channelType,
    routing_address: input.routingAddress,
    credentials: dropBlankValues(input.credentials),
    webhook_secret: input.webhookSecret,
    status: input.status ?? "pending_validation",
  };
  return { change_type: "channel", payload };
}

export type WhatsAppSelfServiceChannelInput = {
  waba_id?: string;
  phone_number_id: string;
  business_account_id?: string;
  graph_api_version?: string;
  app_id?: string;
  config_id?: string;
  access_token?: string;
  system_user_token?: string;
  webhook_verify_token?: string;
  app_secret?: string;
  status?: string;
};

export function buildWhatsAppSelfServiceChannelChangePayload(
  input: WhatsAppSelfServiceChannelInput
): ConfigChangeRequestBody {
  const credentials = dropBlankValues({
    access_token: input.access_token ?? "",
    system_user_token: input.system_user_token ?? "",
    webhook_verify_token: input.webhook_verify_token ?? "",
    app_secret: input.app_secret ?? "",
  });
  const payload: Record<string, unknown> = {
    _schema_version: CONFIG_CHANGE_SCHEMA_VERSION,
    operation: "configure",
    channel_type: "whatsapp",
    routing_address: input.phone_number_id,
    credentials: {
      ...credentials,
      provider: "meta_whatsapp_manual",
      phone_number_id: input.phone_number_id,
      graph_api_version: input.graph_api_version ?? "v25.0",
    },
    webhook_secret: "pending-provider-validation",
    status: input.status ?? "pending_validation",
    self_service_config: compactValues({
      setup: "manual_token",
      waba_id: input.waba_id,
      phone_number_id: input.phone_number_id,
      business_account_id: input.business_account_id,
      graph_api_version: input.graph_api_version ?? "v25.0",
      app_id: input.app_id,
      config_id: input.config_id,
    }),
  };
  return { change_type: "channel", payload };
}

export type SesSelfServiceChannelInput = {
  mode: "managed" | "byo_role" | "byo_access_key";
  region: string;
  source_email?: string;
  source_domain?: string;
  inbound_address?: string;
  inbound_domain?: string;
  topic_arn?: string;
  receipt_rule_set?: string;
  receipt_rule_name?: string;
  role_arn?: string;
  external_id?: string;
  access_key_id?: string;
  secret_access_key?: string;
  session_token?: string;
  status?: string;
};

export function buildSesSelfServiceChannelChangePayload(
  input: SesSelfServiceChannelInput
): ConfigChangeRequestBody {
  const routingAddress =
    input.inbound_address
    ?? input.source_email
    ?? input.inbound_domain
    ?? input.source_domain
    ?? "";
  const credentials = dropBlankValues({
    access_key_id: input.access_key_id ?? "",
    secret_access_key: input.secret_access_key ?? "",
    session_token: input.session_token ?? "",
  });
  const payload: Record<string, unknown> = {
    _schema_version: CONFIG_CHANGE_SCHEMA_VERSION,
    operation: "configure",
    channel_type: "email",
    routing_address: routingAddress,
    credentials: compactValues({
      ...credentials,
      mode: input.mode,
      region: input.region,
      source_email_address: input.source_email,
      domain: input.source_domain,
      role_arn: input.role_arn,
      external_id: input.external_id,
      topic_arn: input.topic_arn,
    }),
    webhook_secret: input.topic_arn ?? "pending-provider-validation",
    status: input.status ?? "pending_validation",
    self_service_config: compactValues({
      mode: input.mode,
      region: input.region,
      source_email: input.source_email,
      source_domain: input.source_domain,
      inbound_address: input.inbound_address,
      inbound_domain: input.inbound_domain,
      topic_arn: input.topic_arn,
      receipt_rule_set: input.receipt_rule_set,
      receipt_rule_name: input.receipt_rule_name,
      role_arn: input.role_arn,
      external_id: input.external_id,
    }),
  };
  return { change_type: "channel", payload };
}

function compactValues(value: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (item !== undefined && item !== null && item !== "") {
      out[key] = item;
    }
  }
  return out;
}

function dropBlankValues(values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(values)) {
    if (value && value.trim()) out[key] = value.trim();
  }
  return out;
}

/**
 * Client-side change_type filter (HARD CONSTRAINT C). The ledger list endpoint
 * only supports `status`, not `change_type`, so config-change surfaces fetch
 * PROPOSED requests and filter here. A server-side change_type filter is a
 * future backend optimization if the ledger grows.
 */
export type ConfigChangeKind = "connector" | "action_policy" | "knowledge";

export function classifyConfigChange(item: {
  change_type: TenantConfigChangeType;
  proposed_payload: Record<string, unknown>;
}): ConfigChangeKind | null {
  if (item.change_type === "connector") return "connector";
  if (
    item.change_type === "policy" &&
    item.proposed_payload.policy_type === ACTION_TOOLS_POLICY_TYPE
  ) {
    return "action_policy";
  }
  if (item.change_type === "knowledge") return "knowledge";
  return null;
}

export function filterConfigChangeRequests<
  T extends {
    change_type: TenantConfigChangeType;
    proposed_payload: Record<string, unknown>;
  }
>(items: T[]): T[] {
  return items.filter((item) => classifyConfigChange(item) !== null);
}
