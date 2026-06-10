import type { NextConfig } from "next";
import path from "node:path";

const repoRoot = path.resolve(process.cwd(), "../../..");
const isVercelBuild = process.env.VERCEL === "1";

const nextConfig: NextConfig = {
  experimental: {
    workerThreads: false,
    cpus: 1,
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
