import { Auth0Client } from "@auth0/nextjs-auth0/server";

let auth0Client: Auth0Client | null = null;

function getAuth0Domain() {
  const issuerBaseUrl = process.env.AUTH0_ISSUER_BASE_URL;
  if (process.env.AUTH0_DOMAIN) return process.env.AUTH0_DOMAIN;
  if (!issuerBaseUrl) return undefined;

  return issuerBaseUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

export function getAuth0Client() {
  auth0Client ??= new Auth0Client({
    appBaseUrl: process.env.APP_BASE_URL || process.env.AUTH0_BASE_URL,
    domain: getAuth0Domain(),
    authorizationParameters: {
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
  return auth0Client;
}
