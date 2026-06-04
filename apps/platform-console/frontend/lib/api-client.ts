"use client";

export type BackendAuthorityMode = "tenant-header" | "verified-bearer";

const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";

export function getApiBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_OPERIOUS_API_BASE_URL?.replace(/\/$/, "") ||
    DEFAULT_API_BASE_URL
  );
}

export function getBackendAuthorityMode(): BackendAuthorityMode {
  const raw =
    process.env.NEXT_PUBLIC_BACKEND_AUTHORITY_MODE ||
    process.env.NEXT_PUBLIC_OPERIOUS_BACKEND_AUTHORITY_MODE ||
    "";
  const normalized = raw.trim().toLowerCase();
  // Fail-closed default: verified bearer (Auth0) is the only authority mode a
  // production backend honours (S-01). The Platform Console is a
  // verified-bearer surface; spoofable ``tenant-header`` must be opted into
  // EXPLICITLY and is intended only for local dev against a non-prod backend.
  if (
    normalized === "tenant-header" ||
    normalized === "header" ||
    normalized === "legacy"
  ) {
    return "tenant-header";
  }
  return "verified-bearer";
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
