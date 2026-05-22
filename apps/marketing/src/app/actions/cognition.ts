'use server';

/**
 * Cognition Runtime — Server Action transport.
 *
 * Constitutional intent: the marketing site is the executive narrative
 * surface. It MUST NOT import @operious/sdk, @operious/contracts, or any
 * operational substrate package (see tests-frontend/marketing-isolation).
 * The chat experience therefore runs through a thin, server-only proxy.
 *
 * Configuration (server-side env, never NEXT_PUBLIC_):
 *
 *   OPERIOUS_COGNITION_URL  — full URL to the cognition runtime endpoint.
 *                             Example: https://cognition.operious.internal/ask
 *   OPERIOUS_COGNITION_KEY  — bearer token for the runtime, optional.
 *
 * If unset, the action returns a graceful unavailable response so the UI
 * stays composed during pre-deployment review.
 *
 * Wire format (request):
 *   POST { conversation_id, messages: [{ role, content }] }
 *
 * Wire format (response):
 *   200 { reply: string, citations?: { title: string, href?: string }[] }
 *
 * Commercial-term inquiries (rates, quotes, fees) are intentionally
 * routed to the enterprise contact track — the marketing surface never
 * surfaces commercial terms.
 */

/**
 * Boundary validation. The marketing surface intentionally avoids zod to
 * keep dependency surface minimal. The schema below is small, total, and
 * trivially auditable.
 */
const ROLES = new Set(['user', 'assistant', 'system']);

interface ValidatedRequest {
  readonly conversation_id: string;
  readonly messages: ReadonlyArray<AskMessage>;
}

const validateRequest = (
  input: unknown,
): { readonly ok: true; readonly value: ValidatedRequest } | { readonly ok: false } => {
  if (typeof input !== 'object' || input === null) return { ok: false };
  const obj = input as Record<string, unknown>;
  if (typeof obj.conversation_id !== 'string') return { ok: false };
  if (obj.conversation_id.length === 0 || obj.conversation_id.length > 80) return { ok: false };
  if (!Array.isArray(obj.messages)) return { ok: false };
  if (obj.messages.length === 0 || obj.messages.length > 40) return { ok: false };
  const messages: AskMessage[] = [];
  for (const m of obj.messages) {
    if (typeof m !== 'object' || m === null) return { ok: false };
    const msg = m as Record<string, unknown>;
    if (typeof msg.role !== 'string' || !ROLES.has(msg.role)) return { ok: false };
    if (typeof msg.content !== 'string') return { ok: false };
    if (msg.content.length === 0 || msg.content.length > 4000) return { ok: false };
    messages.push({
      role: msg.role as AskMessage['role'],
      content: msg.content,
    });
  }
  return {
    ok: true,
    value: { conversation_id: obj.conversation_id, messages },
  };
};

export interface AskMessage {
  readonly role: 'user' | 'assistant' | 'system';
  readonly content: string;
}

export interface AskOk {
  readonly status: 'ok';
  readonly reply: string;
  readonly citations: ReadonlyArray<{ readonly title: string; readonly href?: string }>;
}

export interface AskUnavailable {
  readonly status: 'unavailable';
  readonly reply: string;
}

export interface AskError {
  readonly status: 'error';
  readonly reply: string;
}

export type AskResult = AskOk | AskUnavailable | AskError;

const FALLBACK_UNAVAILABLE: AskUnavailable = {
  status: 'unavailable',
  reply:
    'The substrate cognition runtime is not reachable from this environment. Operious AI provisions per-tenant. To exercise the live runtime, request enterprise access via the contact form below — we will route you to a configured environment.',
};

const SAFETY_REDIRECT = (
  reason: string,
): AskOk => ({
  status: 'ok',
  reply: `${reason} Commercial terms are handled exclusively in private enterprise conversations. Use the contact form below or write to ops@operious.com to begin.`,
  citations: [],
});

const COMMERCIAL_TERMS_PATTERN = /(price|pricing|cost|how much|quote|fee|rate card)/i;

export async function askSubstrate(
  conversationId: string,
  history: ReadonlyArray<AskMessage>,
  userMessage: string,
): Promise<AskResult> {
  const candidate = userMessage.trim();
  if (!candidate) {
    return {
      status: 'error',
      reply: 'No question received. Please ask the substrate something specific.',
    };
  }

  if (COMMERCIAL_TERMS_PATTERN.test(candidate)) {
    return SAFETY_REDIRECT(
      'Commercial terms are determined per deployment after a structured technical engagement, never on the marketing surface.',
    );
  }

  const url = process.env.OPERIOUS_COGNITION_URL;
  const key = process.env.OPERIOUS_COGNITION_KEY;

  if (!url) {
    return FALLBACK_UNAVAILABLE;
  }

  const messages: AskMessage[] = [
    ...history.slice(-12),
    { role: 'user', content: candidate },
  ];

  const payload = {
    conversation_id: conversationId,
    messages,
  };

  const parsed = validateRequest(payload);
  if (!parsed.ok) {
    return {
      status: 'error',
      reply: 'Request did not pass substrate boundary validation. Please rephrase.',
    };
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25_000);
    // Server-side fetch only. The marketing client never touches fetch directly.
    // eslint-disable-next-line no-restricted-globals
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(key ? { Authorization: `Bearer ${key}` } : {}),
      },
      body: JSON.stringify(parsed.value satisfies ValidatedRequest),
      signal: controller.signal,
      cache: 'no-store',
    });
    clearTimeout(timeout);

    if (!response.ok) {
      return {
        status: 'error',
        reply: `Substrate runtime returned ${response.status}. Please try again momentarily.`,
      };
    }

    const data = (await response.json()) as {
      reply?: string;
      citations?: Array<{ title?: string; href?: string }>;
    };

    if (typeof data.reply !== 'string' || data.reply.length === 0) {
      return {
        status: 'error',
        reply: 'Substrate runtime returned an empty reply. Please rephrase the question.',
      };
    }

    return {
      status: 'ok',
      reply: data.reply,
      citations: (data.citations ?? [])
        .filter((c): c is { title: string; href?: string } => typeof c?.title === 'string')
        .map((c) => ({ title: c.title, href: c.href })),
    };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return {
        status: 'error',
        reply: 'Substrate runtime did not respond within the bounded interval. Please retry.',
      };
    }
    return FALLBACK_UNAVAILABLE;
  }
}
