"use client";

import { getAuth0AccessToken, getBackendAuthorityMode } from "@/lib/api-client";

export type ApiPage<T> = {
  items: T[];
  total: number;
  offset: number;
  limit?: number;
};

export type ApiErrorPayload = {
  code?: string;
  error?: string;
  reason?: string;
  detail?: unknown;
  title?: string;
};

export class ApiError extends Error {
  status: number;
  payload: ApiErrorPayload | null;

  constructor(message: string, status: number, payload: ApiErrorPayload | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export type SessionRecord = {
  session_id: string;
  scope: string;
  external_handle: string;
  tenant_id: string | null;
  principal_id: string | null;
  opened_at: string;
  lifecycle_phase: string;
  lifecycle_recorded_at: string;
  lifecycle_reason: string | null;
  lineage_id: string;
  root_session_id: string;
  parent_session_id: string | null;
  ancestor_session_ids: string[];
  lineage_depth: number;
  sequence_head: number;
  revision: number;
  context_environment: string | null;
  context_labels: string[];
  context_attributes: Record<string, unknown>;
  context_notes: string | null;
  metadata: Record<string, unknown>;
};

export type OperationalMetrics = {
  tenant_id: string;
  window_start: string;
  window_end: string;
  ticket_throughput: number;
  governance_decision_count: number;
  governance_deny_count: number;
  governance_deny_rate: number;
  execution_count: number;
  completed_execution_count: number;
  execution_latency_ms_avg: number | null;
  execution_latency_ms_p50: number | null;
  execution_latency_ms_p95: number | null;
  qa_score_count: number;
  qa_score_average: number | null;
  escalation_count: number;
  escalation_rate: number;
  dlq_count: number;
};

export type OperationalTraceSpan = {
  span_id: string;
  tenant_id: string;
  trace_id: string;
  parent_span_id: string | null;
  span_name: string;
  substrate: string;
  operation: string;
  started_at: string;
  ended_at: string;
  latency_ms: number;
  status: string;
  error: string | null;
  attributes: Record<string, unknown>;
  created_at: string | null;
};

export type AuthPrincipal = {
  principal_id: string | null;
  tenant_id: string | null;
  organization_id: string | null;
  environment_id: string | null;
  capabilities: string[];
  authority_source: "verified" | "header" | "anonymous";
};

export type OperationalEvent = {
  event_id: string;
  operational_act: string;
  substrate: string;
  root_event_id: string;
  parent_event_id: string | null;
  causality_depth: number;
  runtime_instance_id: string;
  sequence: number;
  occurred_at: string;
  tenant_id: string | null;
  principal_id: string | null;
  organization_id: string | null;
  environment_id: string | null;
  tenant_authority_source: string | null;
  governance_decision: string | null;
  governance_decision_id: string | null;
  metadata: Record<string, unknown>;
};

export type OperationalReplayTrace = {
  root_event_id: string | null;
  status: "complete" | "partial" | "invalid";
  events: OperationalEvent[];
  lineage_edges: {
    source_event_id: string;
    target_event_id: string;
    relation: string;
    source_substrate: string;
    target_substrate: string;
    metadata: Record<string, unknown>;
  }[];
  unresolved_lineage: {
    source_event_id: string;
    relation: string;
    target_key: string;
    metadata: Record<string, unknown>;
  }[];
  findings: {
    code: string;
    severity: "warning" | "error";
    message: string;
    event_id: string | null;
    metadata: Record<string, unknown>;
  }[];
};

export type EscalationRecord = {
  escalation_id: string;
  session_id: string;
  tenant_id: string;
  reason: string;
  governance_decision_id: string;
  status: "pending" | "reviewed" | "approved" | "rejected";
  handoff_kind: "denial" | "escalation" | "crisis";
  priority: "normal" | "high";
  created_at: string;
  resolved_at: string | null;
  resolution: string | null;
  resolved_by: string | null;
  governance_override_decision_id: string | null;
  source_decision: string | null;
};

export type ApprovalRecord = {
  approval_id: string;
  tenant_id: string;
  document_id: string;
  proposed_change: string;
  evidence_sessions: string[];
  confidence: number;
  status: "pending_review" | "approved" | "rejected" | "applied";
  proposed_by: string;
  reviewed_by: string | null;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export type ActionApprovalSummary = {
  approval_id: string;
  tenant_id: string;
  session_id: string;
  execution_id: string | null;
  status: "pending" | "approved" | "denied";
  tool_name: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
  governance_decision_id: string | null;
  requested_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  metadata: Record<string, unknown>;
};

export type ActionApprovalDetail = {
  approval_id: string;
  status: "pending" | "approved" | "denied";
  tool_name: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
  requested_at: string;
  session_id: string;
  session_phase: string;
  session_opened_at: string;
  classification_category: string | null;
  classification_confidence: number | null;
  classification_summary: string | null;
  governance_decision_id: string | null;
  governance_reason: string | null;
  governance_evaluated_at: string | null;
};

export type QAScoreRecord = {
  score_id: string;
  inspection_id: string;
  execution_id: string;
  tenant_id: string;
  tenant_authority_source: string | null;
  diagnostic_accuracy: number;
  policy_compliance: number;
  timeline_integrity: number;
  resolution_quality: number;
  overall_score: number;
  supervisor_decision_kind: string;
  finding_count: number;
  evaluation_count: number;
  escalation_count: number;
  scored_at: string;
  metadata: Record<string, unknown>;
};

export type SupervisorInspectionSummary = {
  inspection_id: string;
  execution_id: string;
  tenant_id: string | null;
  session_id: string | null;
  category: string;
  decision_kind: string;
  aggregate_score: number;
  started_at: string;
  ended_at: string;
  escalation_count: number;
  is_risky: boolean;
  qa_score: QAScoreRecord | null;
  inspection: Record<string, unknown>;
};

export type SupervisorInspectionDetail = {
  inspection_id: string;
  execution_id: string;
  runtime_instance_id: string;
  correlation_id: string | null;
  request_id: string | null;
  tenant_id: string | null;
  inspection_mode: string;
  started_at: string;
  ended_at: string;
  latency_ms: number;
  error: string | null;
  tenant_authority_source: string | null;
  metadata: Record<string, unknown>;
  inspection: Record<string, unknown>;
  qa_score: QAScoreRecord | null;
  findings: {
    finding_id: string;
    evaluator_name: string;
    category: string;
    severity: string;
    code: string;
    message: string;
    metadata: Record<string, unknown>;
  }[];
  evaluations: {
    inspection_id: string;
    evaluator_name: string;
    status: string;
    score: number;
    finding_ids: string[];
    started_at: string;
    ended_at: string;
    latency_ms: number;
    error: string | null;
    metadata: Record<string, unknown>;
  }[];
  escalations: {
    escalation_id: string;
    inspection_id: string;
    decision_id: string;
    level: string;
    reason: string;
    triggering_finding_ids: string[];
    decided_at: string;
    metadata: Record<string, unknown>;
  }[];
  training_recommendations: TrainingRecommendation[];
  category: string;
  session_id: string | null;
  is_risky: boolean;
};

export type TrainingRecommendation = {
  recommendation_id: string;
  tenant_id: string;
  session_id: string;
  qa_score_id: string;
  category: string;
  finding_summary: string;
  recommendation: string;
  priority: "low" | "medium" | "high";
  status: "pending" | "acknowledged" | "applied" | "dismissed";
  created_at: string;
  metadata: Record<string, unknown>;
};

export type KnowledgeConflict = {
  doc_a_id: string;
  doc_a_title: string;
  doc_b_id: string;
  doc_b_title: string;
  excerpt_a: string;
  excerpt_b: string;
  contradiction_type: "direct_conflict" | "scope_overlap" | "temporal_conflict";
  confidence: number;
};

export type KnowledgeContradictionMetadata = {
  contradiction_flagged: boolean;
  contradiction_count: number;
  contradicting_doc_ids: string[];
  highest_confidence: number;
  contradiction_types: string[];
};

export type KnowledgeAnalysisResult = {
  tenant_id: string;
  documents_analyzed: number;
  contradictions_found: number;
  conflicts: KnowledgeConflict[];
  quarantined_with_detail: Array<{
    document_id: string;
    title: string;
    document_type: string;
    contradiction_metadata: KnowledgeContradictionMetadata | null;
  }>;
  trainer_enqueued: boolean;
  analyzed_at: string;
};

export type TenantKnowledgeDocument = {
  document_id: string;
  title: string;
  content: string;
  document_type: "sop" | "policy" | "product_guide" | "faq" | "escalation_matrix";
  status: "active" | "archived" | "pending_index" | "indexing" | "index_failed";
  review_status: "quarantined" | "approved" | "rejected";
  version: number;
  uploaded_by: string;
  vector_indexed_at: string | null;
  created_at: string;
  updated_at: string | null;
  last_index_error: string | null;
  // MVP-4: contradiction report stored when this document was quarantined
  contradiction_metadata: KnowledgeContradictionMetadata | null;
};

export type TenantKnowledgeUpload = {
  upload_id: string;
  tenant_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  uploaded_by: string;
  created_at: string;
  change_request_id: string;
  document_id: string | null;
};

export type KnowledgeDocumentVersion = {
  version_id: string;
  tenant_id: string;
  document_id: string;
  version: number;
  title: string;
  content: string;
  document_type: string;
  status: string;
  uploaded_by: string;
  source_approval_id: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type TenantGovernancePolicy = {
  policy_id: string;
  policy_type: string;
  parameters: Record<string, unknown>;
  status: "active" | "draft" | "archived";
  version: number;
  approved_by: string;
  effective_from: string;
  created_at: string;
};

export type CrisisTemplate =
  | "block_sku"
  | "halt_refunds"
  | "escalate_all"
  | "freeze_category";

export type CrisisDeployment = {
  deployment_id: string;
  tenant_id: string;
  template: CrisisTemplate;
  scope: Record<string, unknown>;
  ttl_minutes: number;
  policy_id: string | null;
  deployed_by: string;
  deployed_at: string;
  expires_at: string | null;
  status: string;
  redis_key: string;
  decision: string;
  metadata: Record<string, unknown>;
};

type CrisisDeploymentListResponse = {
  items: CrisisDeployment[];
};

export type CrisisEvent = {
  event_id: string;
  deployment_id: string;
  event_kind: "deployed" | "deactivated" | "expired";
  template: string;
  scope: Record<string, unknown>;
  actor: string;
  occurred_at: string;
  ttl_minutes: number;
};

type CrisisEventListResponse = {
  items: CrisisEvent[];
};

export type CrisisDeployRequest = {
  template: CrisisTemplate;
  scope: Record<string, unknown>;
  ttl_minutes: number;
  dry_run?: boolean;
};

export type CrisisInterceptEvent = {
  type: "intercept";
  execution_id: string;
  template: string;
  category: string | null;
  reason: string;
  intercepted_at: string;
  tenant_id: string;
};

export type TenantTopologyConfiguration = {
  config_id: string;
  topology_name: string;
  topology: Record<string, unknown>;
  status: "active" | "draft" | "archived";
  version: number;
  configured_by: string;
  created_at: string;
  updated_at: string;
};

export type TenantChannelConfiguration = {
  config_id: string;
  channel_type: string;
  routing_address: string;
  status:
    | "draft"
    | "pending_validation"
    | "validation_failed"
    | "active"
    | "disabled"
    | "paused"
    | "error"
    | "pending_verification";
  verified_at: string | null;
  credential_rotated_at: string | null;
  credential_rotation_expires_at: string | null;
  self_service_config: Record<string, unknown>;
  last_validation_error: string | null;
  validation_evidence: Record<string, unknown>;
};

export type TenantChannelCreateRequest = {
  channel_type: string;
  routing_address: string;
  credentials: Record<string, unknown>;
  webhook_secret: string;
  status?: TenantChannelConfiguration["status"];
};

export type TenantChannelUpdateRequest = {
  routing_address?: string;
  credentials?: Record<string, unknown>;
  webhook_secret?: string;
  status?: TenantChannelConfiguration["status"];
  self_service_config?: Record<string, unknown>;
};

export type TenantWhatsAppSelfServiceRequest = {
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
  status?: TenantChannelConfiguration["status"];
};

export type TenantSesSelfServiceRequest = {
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
  status?: TenantChannelConfiguration["status"];
};

// ─── Phase 2.5c/2.5d: tenant lifecycle (platform-gated) ──────────────────

/** Mirrors backend TenantStatus (app/tenant/enums.py). */
export type TenantStatus = "active" | "provisioning" | "disabled";

/**
 * A tenant lifecycle record. The backend creates a tenant with status `active`
 * (not `provisioning`). It is nonetheless INERT — fail-closed via the *absence*
 * of an action policy, not via its status — and cannot act until its
 * configuration (channel, connector, action policy) is applied through the
 * governed ledger.
 */
export type TenantLifecycleRecord = {
  tenant_id: string;
  status: TenantStatus;
  created_at: string;
};

// ─── Phase 2.5b: tenant connector reads + config-change ledger ───────────

export type TenantConnectorConfiguration = {
  connector_type: string;
  tool_name: string;
  http_method: string;
  endpoint_template: string;
  endpoint_host: string;
  field_mappings: Record<string, unknown>;
  idempotency_header_name: string;
  response_parse: Record<string, unknown>;
  success_status_codes: number[];
  status: string;
  version: number;
  configured_by: string;
  source_approval_id: string;
  content_sha256: string;
  previous_version_sha256: string | null;
  created_at: string;
  updated_at: string;
};

export type TenantConnectorTestResponse = {
  reachable: boolean;
  config_valid: boolean;
  validated_host: string | null;
  tls_verified: boolean;
  http_probe: string;
};

export type TenantOmsCredentialRequest = {
  auth_type: "bearer" | "api_key" | "basic";
  token?: string;
  api_key?: string;
  username?: string;
  password?: string;
};

/** Mirrors backend TenantConfigChangeType (app/tenant/change_requests.py). */
export type TenantConfigChangeType =
  | "knowledge"
  | "policy"
  | "execution_governance"
  | "topology"
  | "channel"
  | "connector"
  | "credential_update";

/** Mirrors backend TenantConfigChangeRequestStatus. */
export type TenantConfigChangeRequestStatus =
  | "PROPOSED"
  | "APPROVED"
  | "REJECTED"
  | "APPLIED"
  | "REVOKED";

/**
 * Governed config-change request. `proposed_payload` and `outcome_payload`
 * are credential-redacted server-side; the UI never reconstructs a secret.
 */
export type TenantConfigChangeRequest = {
  change_request_id: string;
  tenant_id: string;
  change_type: TenantConfigChangeType;
  proposed_payload: Record<string, unknown>;
  status: TenantConfigChangeRequestStatus;
  proposed_by: string;
  proposed_at: string;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  applied_at: string | null;
  applied_by: string | null;
  revoked_by: string | null;
  revoked_at: string | null;
  rejection_reason: string | null;
  outcome_payload: Record<string, unknown> | null;
};

export type TenantConfigChangeRequestCreate = {
  change_type: TenantConfigChangeType;
  payload: Record<string, unknown>;
};

export type OperationalAlert = {
  alert_id: string;
  tenant_id: string;
  slo_id: string;
  metric_name: string;
  severity: string;
  threshold_operator: string;
  threshold_value: number;
  observed_value: number;
  window_start: string;
  window_end: string;
  triggered: boolean;
  metadata: Record<string, unknown>;
};

export type DeadLetterExecution = {
  execution_id: string;
  tenant_id: string;
  kind: string;
  dispatch_id: string;
  session_id: string;
  state: string;
  attempt_count: number;
  requested_at: string;
  failed_at: string | null;
  worker_id: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
};

export type QueueDepthItem = {
  queue_name: string;
  depth: number;
  oldest_age_seconds: number | null;
  status: "ok" | "warn" | "critical" | "unknown";
  error: string | null;
};

export type QueueStatusResponse = {
  queues: Record<string, QueueDepthItem>;
  snapshot_at: string;
};

export type DeadLetterItem = {
  id: string;
  tenant_id: string;
  task_name: string;
  queue: string | null;
  error_class: string;
  error_message: string;
  attempt_count: number;
  task_payload: Record<string, unknown>;
  created_at: string;
  replayed: boolean;
  replayed_at: string | null;
  replayed_by: string | null;
};

export type DeadLetterListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: DeadLetterItem[];
};

export type DeadLetterReplayResponse = {
  id: string;
  status: "replayed";
  replayed_at: string;
};

export type SemanticCircuitState = {
  channel: string;
  state: "CLOSED" | "TRIPPED" | "RESET";
  cluster_size: number | null;
  occurred_at: string;
  similarity_threshold: number | null;
  window_seconds: number | null;
};

export type SemanticCircuitEvent = {
  event_id: string;
  tenant_id: string;
  channel: string;
  state: "CLOSED" | "TRIPPED" | "RESET";
  trigger_ticket_id: string | null;
  cluster_size: number | null;
  similarity_threshold: number | null;
  window_seconds: number | null;
  occurred_at: string;
  metadata: Record<string, unknown>;
};

export type SemanticQuarantineItem = {
  quarantine_id: string;
  tenant_id: string;
  channel: string;
  original_queue: string;
  external_id: string | null;
  ticket_payload_json: Record<string, unknown>;
  fingerprint_json: number[];
  cluster_size: number;
  similarity_threshold: number;
  status: "pending" | "fraud_confirmed" | "false_positive";
  reviewed_by: string | null;
  reviewed_at: string | null;
  resolution_note: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type SemanticQuarantineReleaseRequest = {
  verdict: "false_positive" | "fraud_confirmed";
  note?: string | null;
};

export type TenantKnowledgeCreateRequest = {
  title: string;
  content: string;
  document_type: TenantKnowledgeDocument["document_type"];
  status?: TenantKnowledgeDocument["status"];
};

export type TenantKnowledgeUpdateRequest = {
  content?: string;
  status?: TenantKnowledgeDocument["status"];
  review_status?: TenantKnowledgeDocument["review_status"];
};

export type KnowledgeIngestionResponse = {
  tenant_id: string;
  document_id: string;
  document_version: number;
  chunk_count: number;
  vector_count: number;
  vector_index_name: string;
  indexed_at: string;
};

export type TenantGovernancePolicyCreateRequest = {
  policy_type: string;
  parameters: Record<string, unknown>;
  status?: TenantGovernancePolicy["status"];
  effective_from: string;
};

export type TenantGovernancePolicyUpdateRequest = {
  parameters?: Record<string, unknown>;
  status?: TenantGovernancePolicy["status"];
  effective_from?: string;
};

type QueryValue = string | number | boolean | null | undefined;

const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";

export function getApiBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_OPERIOUS_API_BASE_URL?.replace(/\/$/, "") ||
    DEFAULT_API_BASE_URL
  );
}

export function getConfiguredTenantId(): string | null {
  return (
    process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID ||
    process.env.NEXT_PUBLIC_OPERIOUS_TENANT_ID ||
    readBrowserValue("operious_tenant_id") ||
    null
  );
}

export function getConfiguredPrincipalId(): string | null {
  return (
    process.env.NEXT_PUBLIC_OPERIOUS_PRINCIPAL_ID ||
    readBrowserValue("operious_principal_id") ||
    null
  );
}

export function getConfiguredOperatorLabel(): string {
  return (
    process.env.NEXT_PUBLIC_OPERIOUS_OPERATOR_LABEL ||
    readBrowserValue("operious_operator_label") ||
    "Unverified operator"
  );
}

function readBrowserValue(key: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}

async function readAuth0Token(): Promise<string> {
  return getAuth0AccessToken();
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(`${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function buildHeaders(extra?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extra);
  headers.set("Accept", "application/json");
  const tenantId = getConfiguredTenantId();
  const principalId = getConfiguredPrincipalId();
  const authorityMode = getBackendAuthorityMode();

  if (authorityMode === "tenant-header" && !tenantId) {
    throw new Error("Tenant context is not configured");
  }

  if (authorityMode === "verified-bearer") {
    headers.set("Authorization", `Bearer ${await readAuth0Token()}`);
  } else {
    if (tenantId) headers.set("X-Tenant-ID", tenantId);
    if (principalId) headers.set("X-Principal-ID", principalId);
  }

  return headers;
}

function errorMessage(status: number, payload: ApiErrorPayload | null): string {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    return String((detail as { code: unknown }).code);
  }
  return payload?.code || payload?.error || payload?.title || `API request failed (${status})`;
}

async function parsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit & { query?: Record<string, QueryValue> } = {}
): Promise<T> {
  const { query, headers, body, ...init } = options;
  const requestHeaders = await buildHeaders(headers);
  if (body && !(body instanceof FormData) && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      ...init,
      body,
      headers: requestHeaders,
      cache: "no-store",
    });
  } catch (error) {
    throw new Error(
      error instanceof Error
        ? error.message
        : "Unable to reach the Operious API"
    );
  }

  const payload = await parsePayload(response);
  if (!response.ok) {
    const typedPayload =
      payload && typeof payload === "object"
        ? (payload as ApiErrorPayload)
        : null;
    throw new ApiError(errorMessage(response.status, typedPayload), response.status, typedPayload);
  }
  return payload as T;
}

export function listSessions(query: { limit: number; offset: number; phase?: string }) {
  return apiRequest<{ items: SessionRecord[]; total: number }>("/session/sessions", {
    query,
  });
}

export type ConversationMessageResponse = {
  turn_id: string;
  phase_a_response: string;
  execution_id: string;
};

export function submitConversationMessage(sessionId: string, content: string) {
  return apiRequest<ConversationMessageResponse>(
    `/conversation/${sessionId}/message`,
    {
      method: "POST",
      body: JSON.stringify({ content }),
    }
  );
}

export function readCurrentPrincipal() {
  return apiRequest<AuthPrincipal>("/auth/me");
}

export function listEscalations(query: {
  status?: EscalationRecord["status"];
  session_id?: string;
  governance_decision_id?: string;
  limit: number;
  offset: number;
}) {
  return apiRequest<ApiPage<EscalationRecord>>("/escalations", { query });
}

export function approveEscalation(escalationId: string, resolution: string) {
  return apiRequest<EscalationRecord>(
    `/escalations/${encodeURIComponent(escalationId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ resolution }),
    }
  );
}

export function rejectEscalation(escalationId: string, resolution: string) {
  return apiRequest<EscalationRecord>(
    `/escalations/${encodeURIComponent(escalationId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ resolution }),
    }
  );
}

// --- SME-reviewed case approvals (Fix 1b) --------------------------------
// Distinct from the action-tool Approval Inbox: these are SME-AI-recommended
// resolutions awaiting human sign-off. Approve lets the recommendation proceed;
// guide submits a bounded re-proposal that STILL re-runs governance backend-side.

export type CaseApprovalEntryCategory =
  | "resolution_require_approval"
  | "resolution_needs_human_approval"
  | "refund_warranty"
  | "low_confidence"
  | "coordination_human_review"
  | "crisis_action";

export type CaseApprovalStatus =
  | "pending_sme_review"
  | "awaiting_approval"
  | "guidance_in_progress"
  | "approved"
  | "rejected"
  | "escalated"
  | "failed";

export type SmeRecommendation = {
  recommendation_id: string;
  recommended_reply: string;
  recommended_actions: Record<string, unknown>[];
  rationale: string;
  confidence: number;
  citations: Record<string, unknown>[];
  risk_flags: string[];
  reply_segments: Record<string, unknown>[];
  created_at: string;
  metadata: Record<string, unknown>;
};

export type CaseApprovalRecord = {
  approval_case_id: string;
  tenant_id: string;
  session_id: string | null;
  execution_id: string | null;
  dispatch_id: string | null;
  resolution_proposal_id: string | null;
  entry_category: CaseApprovalEntryCategory;
  ticket_ref: string | null;
  product: string | null;
  issue_summary: string | null;
  sme_recommendation_id: string | null;
  recommended_action: Record<string, unknown> | null;
  status: CaseApprovalStatus;
  guidance_round: number;
  governance_decision_id: string | null;
  requested_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  metadata: Record<string, unknown>;
};

export function listCaseApprovals(query: {
  status?: CaseApprovalStatus;
  entry_category?: CaseApprovalEntryCategory;
  session_id?: string;
  limit: number;
  offset: number;
}) {
  return apiRequest<ApiPage<CaseApprovalRecord>>("/approvals/cases", { query });
}

export function getCaseApproval(approvalCaseId: string) {
  return apiRequest<CaseApprovalRecord>(
    `/approvals/cases/${encodeURIComponent(approvalCaseId)}`
  );
}

export function approveCaseApproval(approvalCaseId: string, note: string | null) {
  return apiRequest<CaseApprovalRecord>(
    `/approvals/cases/${encodeURIComponent(approvalCaseId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ note }),
    }
  );
}

export function guideCaseApproval(approvalCaseId: string, guidance: string) {
  return apiRequest<CaseApprovalRecord>(
    `/approvals/cases/${encodeURIComponent(approvalCaseId)}/guide`,
    {
      method: "POST",
      body: JSON.stringify({ guidance }),
    }
  );
}

export function escalateCaseApproval(approvalCaseId: string, reason: string) {
  return apiRequest<CaseApprovalRecord>(
    `/approvals/cases/${encodeURIComponent(approvalCaseId)}/escalate`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    }
  );
}

export function rejectCaseApproval(approvalCaseId: string, reason: string | null) {
  return apiRequest<CaseApprovalRecord>(
    `/approvals/cases/${encodeURIComponent(approvalCaseId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    }
  );
}

export function readOperationalMetrics(windowStart: Date, windowEnd: Date) {
  return apiRequest<OperationalMetrics>("/observability/metrics", {
    query: {
      window_start: windowStart.toISOString(),
      window_end: windowEnd.toISOString(),
    },
  });
}

export function listTraceSpans(query: { trace_id?: string; limit: number; offset: number }) {
  return apiRequest<ApiPage<OperationalTraceSpan>>("/observability/traces", {
    query,
  });
}

export function loadOperationalReplayTrace(query: {
  event_id?: string;
  root_event_id?: string;
  governance_decision_id?: string;
  operational_act?: string;
  substrate?: string;
  limit: number;
  offset: number;
}) {
  return apiRequest<OperationalReplayTrace>("/operational-events/replay", {
    query,
  });
}

export function listApprovalRecords(query: {
  status?: ApprovalRecord["status"];
  limit: number;
  offset: number;
}) {
  return apiRequest<ApiPage<ApprovalRecord>>("/sop-intelligence/approvals", {
    query,
  });
}

export function approveApproval(approvalId: string) {
  return apiRequest<{ approval: ApprovalRecord }>(
    `/cognition/approvals/${encodeURIComponent(approvalId)}/approve`,
    { method: "POST" }
  );
}

export function applyApproval(approvalId: string) {
  return apiRequest<{ approval: ApprovalRecord }>(
    `/cognition/approvals/${encodeURIComponent(approvalId)}/apply`,
    { method: "POST" }
  );
}

export function listActionApprovals(query: {
  status?: ActionApprovalSummary["status"];
  limit: number;
  offset: number;
}) {
  return apiRequest<{ items: ActionApprovalSummary[] }>("/approvals/actions", {
    query,
  }).then((page) => page.items);
}

export function getActionApproval(approvalId: string) {
  return apiRequest<ActionApprovalDetail>(
    `/approvals/actions/${encodeURIComponent(approvalId)}`
  );
}

export function approveActionApproval(approvalId: string, note?: string) {
  return apiRequest<ActionApprovalSummary>(
    `/approvals/actions/${encodeURIComponent(approvalId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ note: note || null }),
    }
  );
}

export function denyActionApproval(approvalId: string, reason: string) {
  return apiRequest<ActionApprovalSummary>(
    `/approvals/actions/${encodeURIComponent(approvalId)}/deny`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    }
  );
}

export function listSupervisorInspections(query: {
  status?: "all" | "risky";
  session_id?: string;
  limit: number;
  offset: number;
}) {
  return apiRequest<ApiPage<SupervisorInspectionSummary>>("/supervisor/inspections", {
    query,
  });
}

export function getSupervisorInspection(inspectionId: string) {
  return apiRequest<SupervisorInspectionDetail>(
    `/supervisor/inspections/${encodeURIComponent(inspectionId)}`
  );
}

export function listTrainingRecommendations(query: {
  status?: TrainingRecommendation["status"] | "all";
  limit: number;
  offset: number;
}) {
  return apiRequest<ApiPage<TrainingRecommendation>>("/trainer/recommendations", {
    query,
  });
}

export function updateTrainingRecommendationStatus(
  recommendationId: string,
  status: "acknowledged" | "dismissed"
) {
  return apiRequest<TrainingRecommendation>(
    `/trainer/recommendations/${encodeURIComponent(recommendationId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }
  );
}

export function listKnowledgeDocuments(query: {
  document_type?: TenantKnowledgeDocument["document_type"];
  status?: TenantKnowledgeDocument["status"];
  limit: number;
  offset: number;
}) {
  return apiRequest<ApiPage<TenantKnowledgeDocument>>("/tenant/knowledge", {
    query,
  });
}

export function createKnowledgeDocument(request: TenantKnowledgeCreateRequest) {
  return apiRequest<TenantKnowledgeDocument>("/tenant/knowledge", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateKnowledgeDocument(
  documentId: string,
  request: TenantKnowledgeUpdateRequest
) {
  return apiRequest<TenantKnowledgeDocument>(
    `/tenant/knowledge/${encodeURIComponent(documentId)}`,
    {
      method: "PUT",
      body: JSON.stringify(request),
    }
  );
}

export function uploadKnowledgeDocument(
  file: File,
  title: string,
  documentType: string
) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  form.append("document_type", documentType);
  return apiRequest<TenantKnowledgeUpload>("/tenant/knowledge/uploads", {
    method: "POST",
    body: form,
  });
}

export function ingestKnowledgeDocument(documentId: string) {
  return apiRequest<KnowledgeIngestionResponse>(
    `/knowledge/documents/${encodeURIComponent(documentId)}/ingest`,
    { method: "POST" }
  );
}

export function analyzeKnowledgeBase(documentTypes?: string[]) {
  return apiRequest<KnowledgeAnalysisResult>("/knowledge/analyze", {
    method: "POST",
    body: JSON.stringify({ document_types: documentTypes ?? [] }),
    headers: { "Content-Type": "application/json" },
  });
}

export function listKnowledgeVersions(documentId: string) {
  return apiRequest<ApiPage<KnowledgeDocumentVersion>>("/cognition/knowledge/versions", {
    query: {
      document_id: documentId,
      limit: 25,
      offset: 0,
    },
  });
}

export function listGovernancePolicies() {
  return apiRequest<ApiPage<TenantGovernancePolicy>>("/tenant/policies", {
    query: { limit: 100, offset: 0 },
  });
}

export function listGovernancePoliciesByType(
  policyType: string,
  status: "active" | "draft" | "archived" = "active"
) {
  return apiRequest<ApiPage<TenantGovernancePolicy>>("/tenant/policies", {
    query: { policy_type: policyType, status, limit: 1, offset: 0 },
  });
}

export function createGovernancePolicy(request: TenantGovernancePolicyCreateRequest) {
  return apiRequest<TenantGovernancePolicy>("/tenant/policies", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateGovernancePolicy(
  policyId: string,
  request: TenantGovernancePolicyUpdateRequest
) {
  return apiRequest<TenantGovernancePolicy>(
    `/tenant/policies/${encodeURIComponent(policyId)}`,
    {
      method: "PUT",
      body: JSON.stringify(request),
    }
  );
}

export function listActiveCrisisDeployments() {
  return apiRequest<CrisisDeploymentListResponse>("/governance/crisis/active").then(
    (response) => response.items
  );
}

export function deployCrisisRule(request: CrisisDeployRequest) {
  return apiRequest<CrisisDeployment>("/governance/crisis/deploy", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function deactivateCrisisDeployment(deploymentId: string) {
  return apiRequest<CrisisDeployment>(
    `/governance/crisis/${encodeURIComponent(deploymentId)}`,
    { method: "DELETE" }
  );
}

export function listCrisisEvents(query: { limit?: number; since?: string } = {}) {
  return apiRequest<CrisisEventListResponse>("/governance/crisis/events", {
    query: {
      limit: query.limit ?? 100,
      since: query.since,
    },
  }).then((response) => response.items);
}

export function getCrisisTickerUrl() {
  return `${getApiBaseUrl()}/governance/crisis/ticker`;
}

export function listTopologyConfigurations() {
  return apiRequest<ApiPage<TenantTopologyConfiguration>>("/tenant/topologies", {
    query: { limit: 100, offset: 0 },
  });
}

export function listChannelConfigurations() {
  return apiRequest<ApiPage<TenantChannelConfiguration>>("/tenant/channels", {
    query: { limit: 100, offset: 0 },
  });
}

export function createChannelConfiguration(request: TenantChannelCreateRequest) {
  return apiRequest<TenantChannelConfiguration>("/tenant/channels", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateChannelConfiguration(
  configId: string,
  request: TenantChannelUpdateRequest
) {
  return apiRequest<TenantChannelConfiguration>(
    `/tenant/channels/${encodeURIComponent(configId)}`,
    {
      method: "PUT",
      body: JSON.stringify(request),
    }
  );
}

export function createWhatsAppSelfServiceChannel(
  request: TenantWhatsAppSelfServiceRequest
) {
  return apiRequest<TenantChannelConfiguration>(
    "/tenant/channels/whatsapp/self-service",
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

export function updateWhatsAppSelfServiceChannel(
  request: TenantWhatsAppSelfServiceRequest
) {
  return apiRequest<TenantChannelConfiguration>(
    "/tenant/channels/whatsapp/self-service",
    {
      method: "PUT",
      body: JSON.stringify(request),
    }
  );
}

export function createSesSelfServiceChannel(request: TenantSesSelfServiceRequest) {
  return apiRequest<TenantChannelConfiguration>(
    "/tenant/channels/email/self-service",
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

export function updateSesSelfServiceChannel(request: TenantSesSelfServiceRequest) {
  return apiRequest<TenantChannelConfiguration>(
    "/tenant/channels/email/self-service",
    {
      method: "PUT",
      body: JSON.stringify(request),
    }
  );
}

// ─── Phase 2.5c/2.5d: tenant lifecycle (platform.tenant.admin) ───────────

export function createTenantLifecycle(tenantId: string) {
  return apiRequest<TenantLifecycleRecord>("/tenant/lifecycle/tenants", {
    method: "POST",
    body: JSON.stringify({ tenant_id: tenantId }),
  });
}

export function listTenantLifecycle(query: { limit?: number; offset?: number } = {}) {
  return apiRequest<ApiPage<TenantLifecycleRecord>>("/tenant/lifecycle/tenants", {
    query: {
      limit: query.limit ?? 100,
      offset: query.offset ?? 0,
    },
  });
}

// ─── Phase 2.5b: connector reads (credential-free) ───────────────────────

export function listConnectorConfigurations(query: {
  connector_type?: string;
  tool_name?: string;
  status?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return apiRequest<ApiPage<TenantConnectorConfiguration>>("/tenant/connectors", {
    query: {
      connector_type: query.connector_type,
      tool_name: query.tool_name,
      status: query.status ?? "active",
      limit: query.limit ?? 100,
      offset: query.offset ?? 0,
    },
  });
}

export function listConnectorConfigurationHistory(
  toolName: string,
  query: { connector_type?: string; status?: string; limit?: number; offset?: number } = {}
) {
  return apiRequest<ApiPage<TenantConnectorConfiguration>>(
    `/tenant/connectors/${encodeURIComponent(toolName)}`,
    {
      query: {
        connector_type: query.connector_type,
        status: query.status,
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
      },
    }
  );
}

export function testConnectorConfiguration(tenantId: string, toolName: string) {
  return apiRequest<TenantConnectorTestResponse>(
    `/tenant/${encodeURIComponent(tenantId)}/connectors/${encodeURIComponent(toolName)}/test`,
    {
      method: "POST",
    }
  );
}

export function proposeConnectorCredentials(
  tenantId: string,
  toolName: string,
  request: TenantOmsCredentialRequest
) {
  return apiRequest<void>(
    `/tenant/${encodeURIComponent(tenantId)}/connectors/${encodeURIComponent(toolName)}/credentials`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

// ─── Phase 2.5b: governed config-change ledger ───────────────────────────

export function proposeConfigChangeRequest(request: TenantConfigChangeRequestCreate) {
  return apiRequest<TenantConfigChangeRequest>("/tenant/config/change-requests", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function listConfigChangeRequests(query: {
  status?: TenantConfigChangeRequestStatus;
  limit?: number;
  offset?: number;
}) {
  // The ledger list endpoint supports `status` only, not `change_type`.
  // Callers filter by change_type client-side (see config-change-payloads.ts).
  return apiRequest<ApiPage<TenantConfigChangeRequest>>(
    "/tenant/config/change-requests",
    {
      query: {
        status: query.status,
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
      },
    }
  );
}

export function approveConfigChangeRequest(changeRequestId: string) {
  return apiRequest<TenantConfigChangeRequest>(
    `/tenant/config/change-requests/${encodeURIComponent(changeRequestId)}/approve`,
    { method: "POST" }
  );
}

export function rejectConfigChangeRequest(changeRequestId: string, reason: string) {
  return apiRequest<TenantConfigChangeRequest>(
    `/tenant/config/change-requests/${encodeURIComponent(changeRequestId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    }
  );
}

export function applyConfigChangeRequest(changeRequestId: string) {
  return apiRequest<TenantConfigChangeRequest>(
    `/tenant/config/change-requests/${encodeURIComponent(changeRequestId)}/apply`,
    { method: "POST" }
  );
}

export function revokeConfigChangeRequest(changeRequestId: string) {
  return apiRequest<TenantConfigChangeRequest>(
    `/tenant/config/change-requests/${encodeURIComponent(changeRequestId)}/revoke`,
    { method: "POST" }
  );
}

export function listOperationalAlerts(windowStart: Date, windowEnd: Date) {
  return apiRequest<ApiPage<OperationalAlert>>("/observability/alerts", {
    query: {
      window_start: windowStart.toISOString(),
      window_end: windowEnd.toISOString(),
    },
  });
}

export function listDeadLetterExecutions() {
  return apiRequest<ApiPage<DeadLetterExecution>>("/observability/dlq", {
    query: { limit: 100, offset: 0 },
  });
}

export function getQueueStatus() {
  return apiRequest<QueueStatusResponse>("/operations/queue-status");
}

export function listDeadLetters(query: {
  queue?: string | null;
  error_class?: string | null;
  limit: number;
  offset: number;
}) {
  return apiRequest<DeadLetterListResponse>("/operations/dead-letters", { query });
}

export function replayDeadLetter(id: string) {
  return apiRequest<DeadLetterReplayResponse>(
    `/operations/dead-letters/${encodeURIComponent(id)}/replay`,
    { method: "POST" }
  );
}

export function listSemanticCircuitStates() {
  return apiRequest<SemanticCircuitState[]>("/semantic/circuit-states");
}

export function listSemanticCircuitEvents(query: {
  channel?: string | null;
  limit?: number;
} = {}) {
  return apiRequest<SemanticCircuitEvent[]>("/semantic/circuit-events", {
    query: {
      channel: query.channel,
      limit: query.limit ?? 50,
    },
  });
}

export function listSemanticQuarantine(query: {
  status?: SemanticQuarantineItem["status"];
  limit?: number;
} = {}) {
  return apiRequest<SemanticQuarantineItem[]>("/semantic/quarantine", {
    query: {
      status: query.status ?? "pending",
      limit: query.limit ?? 50,
    },
  });
}

export function releaseSemanticQuarantine(
  id: string,
  request: SemanticQuarantineReleaseRequest
) {
  return apiRequest<SemanticQuarantineItem>(
    `/semantic/quarantine/${encodeURIComponent(id)}/release`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message} (${error.status})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown API failure";
}
