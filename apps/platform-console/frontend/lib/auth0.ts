import { Auth0Client } from "@auth0/nextjs-auth0/server";

/**
 * The Platform Console's OWN Auth0 client — a SEPARATE Auth0 application from
 * the Command Center (true platform/tenant separation, B-full). Mirrors the
 * Command Center pattern but is independently configured.
 */

function getAuth0Domain() {
  const issuerBaseUrl = process.env.AUTH0_ISSUER_BASE_URL;
  if (process.env.AUTH0_DOMAIN) return process.env.AUTH0_DOMAIN;
  if (!issuerBaseUrl) return undefined;

  return issuerBaseUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

export const auth0 = new Auth0Client({
  appBaseUrl: process.env.APP_BASE_URL || process.env.AUTH0_BASE_URL,
  domain: getAuth0Domain(),
  authorizationParameters: {
    // Audience baked in from the start: the access token must be minted for the
    // backend API, not the Auth0 userinfo audience. Omitting this is what cost a
    // full debugging cycle on the Command Center — done right here on day one.
    audience: process.env.AUTH0_AUDIENCE || "https://api.operious.ai",
    scope: process.env.AUTH0_SCOPE || "openid profile email",
  },
  routes: {
    login: "/api/auth/login",
    logout: "/api/auth/logout",
    callback: "/api/auth/callback",
    profile: "/api/auth/profile",
    backChannelLogout: "/api/auth/backchannel-logout",
  },
});
