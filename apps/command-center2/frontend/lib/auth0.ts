import { Auth0Client } from "@auth0/nextjs-auth0/server";

function getAuth0Domain() {
  const issuerBaseUrl = process.env.AUTH0_ISSUER_BASE_URL;
  if (process.env.AUTH0_DOMAIN) return process.env.AUTH0_DOMAIN;
  if (!issuerBaseUrl) return undefined;

  return issuerBaseUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

export const auth0 = new Auth0Client({
  appBaseUrl: process.env.APP_BASE_URL || process.env.AUTH0_BASE_URL,
  domain: getAuth0Domain(),
  routes: {
    login: "/api/auth/login",
    logout: "/api/auth/logout",
    callback: "/api/auth/callback",
    profile: "/api/auth/profile",
    backChannelLogout: "/api/auth/backchannel-logout",
  },
});
