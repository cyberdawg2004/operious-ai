import { NextResponse, type NextRequest } from "next/server";

function getAppBaseUrl(request: NextRequest): string {
  const configured = process.env.APP_BASE_URL || process.env.AUTH0_BASE_URL;
  if (configured) return configured.replace(/\/$/, "");
  return request.nextUrl.origin;
}

export function GET(request: NextRequest) {
  const appBaseUrl = getAppBaseUrl(request);
  const logoutUrl = new URL("/api/auth/logout", appBaseUrl);
  logoutUrl.searchParams.set(
    "returnTo",
    new URL("/sign-in", appBaseUrl).toString()
  );
  return NextResponse.redirect(logoutUrl);
}
