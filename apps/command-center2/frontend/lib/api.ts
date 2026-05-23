"use client";

import { getAuth0AccessToken } from "@/lib/api-client";

export type ApiPage<T> = {
  items: T[];
  total: number;
  offset: number;
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
};

export type TenantKnowledgeDocument = {
  document_id: string;
  title: string;
  content: string;
  document_type: "sop" | "policy" | "product_guide" | "faq" | "escalation_matrix";
  status: "active" | "archived" | "pending_index" | "indexing";
  version: number;
  uploaded_by: string;
  vector_indexed_at: string | null;
  created_at: string;
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
  status: "active" | "paused" | "error" | "pending_verification";
  verified_at: string | null;
  credential_rotated_at: string | null;
  credential_rotation_expires_at: string | null;
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

export type TenantKnowledgeCreateRequest = {
  title: string;
  content: string;
  document_type: TenantKnowledgeDocument["document_type"];
  status?: TenantKnowledgeDocument["status"];
};

export type TenantKnowledgeUpdateRequest = {
  content?: string;
  status?: TenantKnowledgeDocument["status"];
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

  if (!tenantId) {
    throw new Error("Tenant context is not configured");
  }

  if (tenantId) headers.set("X-Tenant-ID", tenantId);
  if (principalId) headers.set("X-Principal-ID", principalId);
  headers.set("Authorization", `Bearer ${await readAuth0Token()}`);

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
  if (body && !requestHeaders.has("Content-Type")) {
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

export function listSessions(query: { limit: number; offset: number }) {
  return apiRequest<{ items: SessionRecord[]; total: number }>("/session/sessions", {
    query,
  });
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

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message} (${error.status})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown API failure";
}
