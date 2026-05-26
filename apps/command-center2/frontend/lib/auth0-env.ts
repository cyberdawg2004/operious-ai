export const requiredAuth0Env = [
  "AUTH0_SECRET",
  "AUTH0_CLIENT_ID",
  "AUTH0_CLIENT_SECRET",
] as const;

export function hasAuth0Environment() {
  const hasAppBaseUrl = Boolean(process.env.APP_BASE_URL || process.env.AUTH0_BASE_URL);
  const hasDomain = Boolean(
    process.env.AUTH0_DOMAIN || process.env.AUTH0_ISSUER_BASE_URL
  );

  return (
    requiredAuth0Env.every((key) => Boolean(process.env[key])) &&
    hasAppBaseUrl &&
    hasDomain
  );
}
