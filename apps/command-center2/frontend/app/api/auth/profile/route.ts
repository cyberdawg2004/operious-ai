import { getAuth0Client } from "@/lib/auth0";
import { hasAuth0Environment } from "@/lib/auth0-env";
import { NextResponse } from "next/server";

export async function GET() {
  if (!hasAuth0Environment()) {
    return NextResponse.json(
      { error: "Auth0 environment is not configured" },
      { status: 401 }
    );
  }

  const auth0 = getAuth0Client();

  try {
    const session = await auth0.getSession();
    if (!session) {
      return NextResponse.json(
        { error: "Not authenticated" },
        { status: 401 }
      );
    }
    return NextResponse.json(session.user, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Profile unavailable",
      },
      { status: 401 }
    );
  }
}
