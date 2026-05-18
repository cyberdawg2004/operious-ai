/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: [
    '@operious/auth',
    '@operious/contracts',
    '@operious/observability',
    '@operious/sdk',
    '@operious/shared',
    '@operious/topology',
    '@operious/tracing',
    '@operious/types',
    '@operious/ui',
  ],
  experimental: {
    typedRoutes: false,
  },
};

export default nextConfig;
