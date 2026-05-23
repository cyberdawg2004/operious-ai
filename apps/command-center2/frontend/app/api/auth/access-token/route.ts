import { getAccessToken } from "@auth0/nextjs-auth0";
import { NextResponse } from "next/server";

export async function GET() {
  try {
    const { accessToken } = await getAccessToken();
    if (!accessToken) {
      return NextResponse.json(
        { error: "Auth0 access token unavailable" },
        { status: 401 }
      );
    }

    return NextResponse.json(
      { accessToken },
      { headers: { "Cache-Control": "no-store" } }
    );
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
