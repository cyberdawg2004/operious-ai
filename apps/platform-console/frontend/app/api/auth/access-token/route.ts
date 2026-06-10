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
    const { token } = await auth0.getAccessToken();
    if (!token) {
      return NextResponse.json(
        { error: "Auth0 access token unavailable" },
        { status: 401 }
      );
    }

    const response = NextResponse.json(
      { accessToken: token },
      {
        headers: {
          "Cache-Control": "no-store",
        },
      }
    );
    return response;
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Auth0 access token unavailable",
      },
      { status: 401 }
    );
  }
}
