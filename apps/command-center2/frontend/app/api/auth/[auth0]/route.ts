import { handleAuth } from "@auth0/nextjs-auth0";
import { hasAuth0Environment } from "@/lib/auth0-env";
import { NextResponse } from "next/server";

type Auth0RouteParams = { auth0: string | string[] };
type Auth0RouteContext = { params: Auth0RouteParams | Promise<Auth0RouteParams> };

const authHandler = handleAuth();

export async function GET(request: Request, context: Auth0RouteContext) {
  if (!hasAuth0Environment()) {
    const signInUrl = new URL("/sign-in", request.url);
    signInUrl.searchParams.set("auth", "unconfigured");
    return NextResponse.redirect(signInUrl);
  }

  const params = await context.params;
  return authHandler(request, { ...context, params });
}
