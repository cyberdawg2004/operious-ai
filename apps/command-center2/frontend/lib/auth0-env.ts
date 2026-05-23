export const requiredAuth0Env = [
  "AUTH0_SECRET",
  "AUTH0_BASE_URL",
  "AUTH0_ISSUER_BASE_URL",
  "AUTH0_CLIENT_ID",
  "AUTH0_CLIENT_SECRET",
] as const;

export function hasAuth0Environment() {
  return requiredAuth0Env.every((key) => Boolean(process.env[key]));
}
