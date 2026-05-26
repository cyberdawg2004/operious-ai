import { auth0 } from "@/lib/auth0";
import { hasAuth0Environment } from "@/lib/auth0-env";
import { NextResponse } from "next/server";

export async function proxy(request: Request) {
  if (!hasAuth0Environment()) {
    const signInUrl = new URL("/sign-in", request.url);
    signInUrl.searchParams.set("auth", "unconfigured");
    return NextResponse.redirect(signInUrl);
  }

  return auth0.middleware(request);
}

export const config = {
  matcher: [
    "/api/auth/:path*",
    "/dashboard/:path*",
    "/operations/:path*",
    "/((?!sign-in|api/auth|_next|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
