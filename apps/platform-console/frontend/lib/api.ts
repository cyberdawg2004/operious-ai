"use client";

import {
  getApiBaseUrl,
  getAuth0AccessToken,
  getBackendAuthorityMode,
} from "@/lib/api-client";

/**
 * Lean platform API client. Intentionally minimal — the Platform Console only
 * needs the current principal (for gating) and the tenant lifecycle reads
 * (for the landing page). It does NOT mirror the whole Command Center api.ts.
 *
 * Authority is verified-bearer: every request attaches Authorization: Bearer
 * <Auth0 token>, never X-Tenant-ID.
 */

type QueryValue = string | number | boolean | null | undefined;

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

export type AuthPrincipal = {
  principal_id: string | null;
  tenant_id: string | null;
  organization_id: string | null;
  environment_id: string | null;
  capabilities: string[];
  authority_source: "verified" | "header" | "anonymous";
};

/** Mirrors backend TenantStatus (app/tenant/enums.py). */
export type TenantStatus = "active" | "provisioning" | "disabled";

export type TenantLifecycleRecord = {
  tenant_id: string;
  status: TenantStatus;
  created_at: string;
};

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
  if (getBackendAuthorityMode() === "verified-bearer") {
    headers.set("Authorization", `Bearer ${await getAuth0AccessToken()}`);
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
      error instanceof Error ? error.message : "Unable to reach the Operious API"
    );
  }

  const payload = await parsePayload(response);
  if (!response.ok) {
    const typedPayload =
      payload && typeof payload === "object" ? (payload as ApiErrorPayload) : null;
    throw new ApiError(errorMessage(response.status, typedPayload), response.status, typedPayload);
  }
  return payload as T;
}

export function readCurrentPrincipal() {
  return apiRequest<AuthPrincipal>("/auth/me");
}

// ── Tenant lifecycle (platform.tenant.admin) ────────────────────────────────

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

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message} (${error.status})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown API failure";
}
