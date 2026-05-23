import { withMiddlewareAuthRequired } from "@auth0/nextjs-auth0/edge";
import { hasAuth0Environment } from "@/lib/auth0-env";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

const auth0Middleware = withMiddlewareAuthRequired();

export default function middleware(request: NextRequest, event: NextFetchEvent) {
  if (!hasAuth0Environment()) {
    const signInUrl = new URL("/sign-in", request.url);
    signInUrl.searchParams.set("auth", "unconfigured");
    return NextResponse.redirect(signInUrl);
  }

  return auth0Middleware(request, event);
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/operations/:path*",
    "/((?!sign-in|api/auth|_next|favicon).*)",
  ],
};
