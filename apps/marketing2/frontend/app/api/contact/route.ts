import { NextResponse } from "next/server";

type ContactPayload = {
  name: string;
  company: string;
  email: string;
  role: string;
  domain: string;
  ticketVolume: string;
  useCase: string;
  context?: string;
  currentSystems?: string;
  automationInterest?: string;
  timeline?: string;
};

const requiredFields = [
  "name",
  "company",
  "email",
  "role",
  "domain",
  "ticketVolume",
  "useCase",
];

function isContactPayload(payload: Record<string, unknown>): payload is ContactPayload {
  return requiredFields.every((field) => {
    const value = payload[field];
    return typeof value === "string" && value.trim().length > 0;
  });
}

function normalizePayload(payload: ContactPayload, requestId: string) {
  return {
    requestId,
    source: "operious-marketing2",
    submittedAt: new Date().toISOString(),
    name: payload.name.trim(),
    company: payload.company.trim(),
    email: payload.email.trim(),
    role: payload.role.trim(),
    domain: payload.domain.trim(),
    ticketVolume: payload.ticketVolume.trim(),
    useCase: payload.useCase.trim(),
    context: payload.context?.trim() || undefined,
    currentSystems: payload.currentSystems?.trim() || undefined,
    automationInterest: payload.automationInterest?.trim() || undefined,
    timeline: payload.timeline?.trim() || undefined,
  };
}

async function forwardToConfiguredEndpoint(payload: ReturnType<typeof normalizePayload>) {
  const endpoint = process.env.CONTACT_ENDPOINT_URL;

  if (!endpoint) {
    throw new Error("Contact intake is not configured.");
  }

  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  const token = process.env.CONTACT_ENDPOINT_TOKEN;

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const providerMessage = await response.text();
    throw new Error(
      providerMessage || `Configured contact endpoint returned ${response.status}.`
    );
  }

  return { delivered: true };
}

export async function POST(request: Request) {
  let payload: Record<string, unknown>;
  const requestId = crypto.randomUUID();

  try {
    payload = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json(
      { message: "The request body must be valid JSON." },
      { status: 400 }
    );
  }

  if (!isContactPayload(payload)) {
    const missing = requiredFields.find((field) => {
      const value = payload[field];
      return typeof value !== "string" || value.trim().length === 0;
    });
    return NextResponse.json(
      { message: `Missing required field: ${missing ?? "unknown"}.` },
      { status: 400 }
    );
  }

  if (!payload.email.includes("@")) {
    return NextResponse.json(
      { message: "Enter a valid business email address." },
      { status: 400 }
    );
  }

  if (!process.env.CONTACT_ENDPOINT_URL) {
    return NextResponse.json(
      {
        error:
          "Contact intake is not configured for this deployment. Please email sales@operious.com directly.",
        message:
          "Our contact intake is currently unavailable. Please email sales@operious.com and a solutions architect will respond within one business day.",
      },
      { status: 503 }
    );
  }

  const normalizedPayload = normalizePayload(payload, requestId);

  try {
    await forwardToConfiguredEndpoint(normalizedPayload);
  } catch (error) {
    console.error("Contact endpoint forwarding failed", {
      requestId,
      error: error instanceof Error ? error.message : "Unknown error",
    });
    return NextResponse.json(
      {
        message:
          "The request reached Operious, but the configured intake endpoint rejected it. Please try again or email hello@operious.com.",
        requestId,
      },
      { status: 502 }
    );
  }

  return NextResponse.json(
    {
      message:
        "Your request was received. Operious will follow up with architecture review next steps.",
      requestId,
    },
    { status: 202 }
  );
}
