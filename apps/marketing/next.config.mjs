/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@operious/ui', '@operious/shared'],
  experimental: {
    typedRoutes: false,
  },
};

export default nextConfig;
