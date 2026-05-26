import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    workerThreads: false,
    cpus: 1,
  },
  turbopack: {},
  webpack: (config, { dev }) => {
    if (dev) {
      config.devtool = false;
    }

    return config;
  },
};

export default nextConfig;
