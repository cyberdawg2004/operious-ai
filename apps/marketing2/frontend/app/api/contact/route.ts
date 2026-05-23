import { NextResponse } from "next/server";

const requiredFields = [
  "name",
  "company",
  "email",
  "role",
  "domain",
  "ticketVolume",
  "useCase",
];

export async function POST(request: Request) {
  let payload: Record<string, unknown>;

  try {
    payload = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json(
      { message: "The request body must be valid JSON." },
      { status: 400 }
    );
  }

  const missing = requiredFields.filter((field) => {
    const value = payload[field];
    return typeof value !== "string" || value.trim().length === 0;
  });

  if (missing.length > 0) {
    return NextResponse.json(
      { message: `Missing required field: ${missing[0]}.` },
      { status: 400 }
    );
  }

  return NextResponse.json(
    {
      message:
        "Your request was received. Operious will follow up with architecture review next steps.",
      requestId: crypto.randomUUID(),
    },
    { status: 202 }
  );
}
