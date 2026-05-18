'use client';

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { ENDPOINT } from '@operious/contracts';
import { freezeDeep, ok, err, type Result, type ResultError } from '@operious/shared';
import {
  headerForCorrelation,
  isoNow,
  newClientCorrelationId,
  newClientRequestId,
} from '@operious/tracing';
import { useAuthHeader } from '@operious/auth';

/**
 * Frontend-side request envelope. Every SDK call returns this shape so the
 * UI can render success / error envelopes without exception-driven branches.
 */
export interface RequestEnvelope<T> {
  readonly result: Result<T, ResultError>;
  readonly correlationId: string;
  readonly observedAt: string;
}

export interface OperiousClientConfig {
  readonly baseUrl: string;
  /** Custom fetch — pass for SSR / tests / mocking. */
  readonly fetch?: typeof fetch;
}

/**
 * The OperiousClient is intentionally tiny: it does NOT manage retries,
 * caching, or optimistic state. Caching is delegated to TanStack Query;
 * retries are deliberately disabled — the backend is the authority and
 * client-side retry of a denied operation would be a semantic violation.
 */
export class OperiousClient {
  readonly #config: OperiousClientConfig;
  readonly #fetch: typeof fetch;

  constructor(config: OperiousClientConfig) {
    this.#config = config;
    this.#fetch = config.fetch ?? globalThis.fetch.bind(globalThis);
  }

  get baseUrl(): string {
    return this.#config.baseUrl;
  }

  async request<T>(
    path: string,
    init: {
      method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
      body?: unknown;
      headers?: Record<string, string>;
      query?: Record<string, string | number | undefined>;
      signal?: AbortSignal;
    } = {},
  ): Promise<RequestEnvelope<T>> {
    const correlationId = newClientCorrelationId();
    const requestId = newClientRequestId();

    const url = new URL(path, this.#config.baseUrl);
    if (init.query) {
      for (const [k, v] of Object.entries(init.query)) {
        if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
      }
    }

    const headers: Record<string, string> = {
      Accept: 'application/json',
      'x-operious-client-request-id': requestId as unknown as string,
      ...headerForCorrelation(correlationId),
      ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers ?? {}),
    };

    try {
      const response = await this.#fetch(url.toString(), {
        method: init.method ?? 'GET',
        headers,
        body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
        signal: init.signal,
        credentials: 'include',
      });

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        const errorPayload: ResultError = {
          code: `http_${response.status}`,
          message: text || response.statusText || 'request failed',
          substrate: 'sdk',
          correlationId: correlationId as unknown as string,
        };
        return {
          result: err(errorPayload),
          correlationId: correlationId as unknown as string,
          observedAt: isoNow(),
        };
      }

      const value = (await response.json()) as T;
      return {
        result: ok(freezeDeep(value)),
        correlationId: correlationId as unknown as string,
        observedAt: isoNow(),
      };
    } catch (cause) {
      const errorPayload: ResultError = {
        code: 'transport_error',
        message: cause instanceof Error ? cause.message : 'network failure',
        substrate: 'sdk',
        correlationId: correlationId as unknown as string,
        cause,
      };
      return {
        result: err(errorPayload),
        correlationId: correlationId as unknown as string,
        observedAt: isoNow(),
      };
    }
  }

  get endpoints() {
    return ENDPOINT;
  }
}

const ClientContext = createContext<OperiousClient | null>(null);

interface ProviderProps {
  readonly client: OperiousClient;
  readonly children: ReactNode;
}

export const OperiousClientProvider = ({ client, children }: ProviderProps) => (
  <ClientContext.Provider value={client}>{children}</ClientContext.Provider>
);

export const useOperiousClient = (): OperiousClient => {
  const client = useContext(ClientContext);
  if (!client) {
    throw new Error(
      '[operious/sdk] useOperiousClient called outside <OperiousClientProvider>',
    );
  }
  return client;
};

/**
 * Convenience: combine the client request layer with the auth header
 * derived from `<AuthProvider>`. UI hooks that need an authed call
 * use this composed function rather than calling `client.request` directly.
 */
export const useAuthedRequest = () => {
  const client = useOperiousClient();
  const authHeader = useAuthHeader();
  return useMemo(
    () =>
      function authedRequest<T>(
        path: string,
        init: Parameters<OperiousClient['request']>[1] = {},
      ) {
        return client.request<T>(path, {
          ...init,
          headers: { ...authHeader, ...(init.headers ?? {}) },
        });
      },
    [client, authHeader],
  );
};
