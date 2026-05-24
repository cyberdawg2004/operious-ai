"use client";

type QueryValue = string | number | boolean | null | undefined;
export type BackendAuthorityMode = "tenant-header" | "verified-bearer";

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
    "Authenticated operator"
  );
}

export function getBackendAuthorityMode(): BackendAuthorityMode {
  const raw =
    process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE ||
    process.env.NEXT_PUBLIC_OPERIOUS_BACKEND_AUTHORITY_MODE ||
    "";
  const normalized = raw.trim().toLowerCase();
  if (
    normalized === "verified-bearer" ||
    normalized === "bearer" ||
    normalized === "auth0"
  ) {
    return "verified-bearer";
  }
  return "tenant-header";
}

export async function getAuth0AccessToken(): Promise<string> {
  const response = await fetch("/api/auth/access-token", {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => null);

  if (!response.ok || !payload?.accessToken) {
    const message =
      payload && typeof payload.error === "string"
        ? payload.error
        : `Auth0 access token request failed (${response.status})`;
    throw new Error(message);
  }

  return String(payload.accessToken);
}

export async function apiRequest(
  path: string,
  options: RequestInit & { query?: Record<string, QueryValue> } = {}
): Promise<Response> {
  const { query, headers, body, ...init } = options;
  const tenantId = getConfiguredTenantId();
  const authorityMode = getBackendAuthorityMode();
  if (authorityMode === "tenant-header" && !tenantId) {
    throw new Error("Tenant context is not configured");
  }

  const url = new URL(`${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", "application/json");
  if (authorityMode === "verified-bearer") {
    requestHeaders.set("Authorization", `Bearer ${await getAuth0AccessToken()}`);
  } else if (tenantId) {
    requestHeaders.set("X-Tenant-ID", tenantId);
  }
  if (body && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const principalId = getConfiguredPrincipalId();
  if (authorityMode === "tenant-header" && principalId) {
    requestHeaders.set("X-Principal-ID", principalId);
  }

  return fetch(url.toString(), {
    ...init,
    body,
    headers: requestHeaders,
    cache: "no-store",
  });
}

function readBrowserValue(key: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}
