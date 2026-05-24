import { getAccessToken } from "@auth0/nextjs-auth0";
import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  try {
    const tokenResponse = new NextResponse();
    const { accessToken } = await getAccessToken(request, tokenResponse);
    if (!accessToken) {
      return NextResponse.json(
        { error: "Auth0 access token unavailable" },
        { status: 401 }
      );
    }

    const response = NextResponse.json(
      { accessToken },
      {
        headers: {
          "Cache-Control": "no-store",
          ...Object.fromEntries(tokenResponse.headers),
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
