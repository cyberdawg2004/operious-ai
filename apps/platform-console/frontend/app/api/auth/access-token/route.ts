import { auth0 } from "@/lib/auth0";
import { NextResponse } from "next/server";

export async function GET() {
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
