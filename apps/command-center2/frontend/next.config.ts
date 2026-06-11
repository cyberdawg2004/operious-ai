import type { NextConfig } from "next";
import path from "node:path";

const repoRoot = path.resolve(process.cwd(), "../../..");
const isVercelBuild = process.env.VERCEL === "1";

// Universally-safe security response headers (#46/#49). These never break a
// standard app: clickjacking (frame-ancestors/X-Frame-Options), MIME sniffing,
// referrer leakage, transport security (HSTS), and a least-privilege
// Permissions-Policy. A full script-src Content-Security-Policy is intentionally
// NOT enforced here yet: it must be validated against the live Auth0 redirect
// flow on staging first to avoid breaking authentication.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
  // Clickjacking defense-in-depth for modern browsers; frame embedding denied.
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
];

const nextConfig: NextConfig = {
  experimental: {
    workerThreads: false,
    cpus: 1,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
  ...(isVercelBuild
    ? {}
    : {
        outputFileTracingRoot: repoRoot,
        turbopack: {
          root: repoRoot,
        },
      }),
  webpack: (config, { dev }) => {
    if (dev) {
      config.devtool = false;
    }

    config.ignoreWarnings = [
      ...(config.ignoreWarnings ?? []),
      {
        module: /@auth0\/nextjs-auth0\/dist\/utils\/dpopUtils\.js/,
        message: /Critical dependency: the request of a dependency is an expression/,
      },
    ];

    return config;
  },
};

export default nextConfig;
