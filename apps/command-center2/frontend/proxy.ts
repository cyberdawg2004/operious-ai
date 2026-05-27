import { auth0 } from "@/lib/auth0";
import { hasAuth0Environment } from "@/lib/auth0-env";
import { NextResponse, type NextRequest } from "next/server";

function isProtectedPath(pathname: string) {
  return (
    pathname === "/" ||
    pathname === "/dashboard" ||
    pathname.startsWith("/dashboard/") ||
    pathname === "/operations" ||
    pathname.startsWith("/operations/")
  );
}

export async function proxy(request: NextRequest) {
  if (!hasAuth0Environment()) {
    const signInUrl = new URL("/sign-in", request.url);
    signInUrl.searchParams.set("auth", "unconfigured");
    return NextResponse.redirect(signInUrl);
  }

  if (isProtectedPath(request.nextUrl.pathname)) {
    const session = await auth0.getSession(request);
    if (!session) {
      const signInUrl = new URL("/sign-in", request.url);
      signInUrl.searchParams.set(
        "returnTo",
        `${request.nextUrl.pathname}${request.nextUrl.search}`,
      );
      return NextResponse.redirect(signInUrl);
    }
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
