import type { NextConfig } from "next";
import path from "node:path";

const repoRoot = path.resolve(process.cwd(), "../../..");

const nextConfig: NextConfig = {
  experimental: {
    workerThreads: false,
    cpus: 1,
  },
  outputFileTracingRoot: repoRoot,
  turbopack: {
    root: repoRoot,
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.devtool = false;
    }

    return config;
  },
};

export default nextConfig;
