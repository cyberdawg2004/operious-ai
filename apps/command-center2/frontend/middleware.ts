import { withMiddlewareAuthRequired } from "@auth0/nextjs-auth0/edge";

export default withMiddlewareAuthRequired();

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/operations/:path*",
    "/((?!sign-in|api/auth|_next|favicon).*)",
  ],
};
