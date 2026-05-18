import type { Config } from 'tailwindcss';
import preset from '@operious/ui/tailwind-preset';

const config: Config = {
  presets: [preset],
  content: [
    './src/**/*.{ts,tsx}',
    '../../packages/ui/src/**/*.{ts,tsx}',
    '../../packages/observability/src/**/*.{ts,tsx}',
    '../../packages/topology/src/**/*.{ts,tsx}',
  ],
};

export default config;
