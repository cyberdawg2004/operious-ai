import type { Config } from 'tailwindcss';

/**
 * Operious Command Center — light operational palette.
 *
 * Token names mirror the Marketing surface so shared @operious/ui
 * primitives render correctly here; only the values shift to fit the
 * operator workstation register. Body sans is Geist Sans (Inter has
 * been removed across the platform per the Visual Execution Hyperprompt).
 *
 * Pixel discipline (from the spec):
 *   • Spacing scale is explicit; arbitrary values are a design smell.
 *   • Exactly four border-radius tokens (sm, md, lg, full).
 *   • Exactly five shadow tokens (hairline, card-hover, panel,
 *     dropdown, modal).
 */
const config: Config = {
  content: [
    './src/**/*.{ts,tsx}',
    '../../packages/ui/src/**/*.{ts,tsx}',
    '../../packages/observability/src/**/*.{ts,tsx}',
    '../../packages/topology/src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: '#F8F5EE',
          subtle: '#F8F5EE',
          raised: '#FBF9F4',
          inset: '#FFFFFF',
        },
        line: {
          DEFAULT: '#EAE6DE',
          subtle: '#EAE6DE',
          strong: '#D4CFC4',
        },
        fg: {
          DEFAULT: '#0A0F1C',
          muted: '#2A3548',
          subtle: '#4A5468',
          dim: '#8A93A4',
        },
        accent: {
          DEFAULT: '#A8882C',
          subtle: '#B8982C',
          glow: '#C9A84C',
          deep: '#8A6E1F',
        },
        signal: {
          allow: '#2E7D5C',
          escalate: '#B8821C',
          deny: '#A6342D',
          deadlock: '#6B5418',
          neutral: '#4A5468',
          info: '#1A4A9A',
          governed: '#A8882C',
        },
        substrate: {
          boundary: '#1A4A9A',
          governance: '#A8882C',
          coordination: '#4A5468',
          session: '#2E7D5C',
          execution: '#0D2860',
          supervisor: '#6B5418',
          arbitration: '#A6342D',
          hardening: '#8A93A4',
        },
      },
      fontFamily: {
        // Geist Sans (NOT Inter).
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        display: [
          'var(--font-cormorant)',
          '"Cormorant SC"',
          'Georgia',
          'serif',
        ],
        mono: [
          'var(--font-plex-mono)',
          '"IBM Plex Mono"',
          'ui-monospace',
          'monospace',
        ],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      // Four border-radius tokens — per the pixel discipline rule.
      borderRadius: {
        sm: '4px',
        DEFAULT: '4px',
        md: '8px',
        lg: '12px',
        full: '9999px',
      },
      spacing: {
        '0.5': '2px',
        '1': '4px',
        '1.5': '6px',
        '2': '8px',
        '3': '12px',
        '4': '16px',
        '5': '20px',
        '6': '24px',
        '8': '32px',
        '10': '40px',
        '12': '48px',
        '16': '64px',
        '20': '80px',
        '24': '96px',
        '32': '128px',
        '40': '160px',
        '48': '192px',
        '64': '256px',
        sidebar: '240px',
        panel: '480px',
      },
      // Five shadow tokens (legacy aliases retained but resolve to the same
      // base set so existing components keep rendering).
      boxShadow: {
        hairline: '0 1px 0 #EAE6DE',
        'card-hover': '0 8px 24px rgba(10, 15, 28, 0.08)',
        panel: '0 4px 16px rgba(10, 15, 28, 0.04)',
        dropdown: '0 8px 32px rgba(10, 15, 28, 0.12)',
        modal: '0 24px 64px rgba(10, 15, 28, 0.16)',
        // Legacy aliases — collapse to the canonical five.
        card: '0 1px 0 rgba(10, 15, 28, 0.04), 0 1px 2px rgba(10, 15, 28, 0.04)',
        raised: '0 4px 16px rgba(10, 15, 28, 0.04)',
      },
      letterSpacing: {
        wider: '0.04em',
        widest: '0.12em',
      },
      keyframes: {
        pulseAmber: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideOutRight: {
          '0%': { transform: 'translateX(0)', opacity: '1' },
          '100%': { transform: 'translateX(100%)', opacity: '0' },
        },
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        scaleIn: {
          '0%': { transform: 'scale(0.96)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        sealSpin: {
          '0%':   { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        'pulse-amber': 'pulseAmber 2s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        // Spec: panel open is 320ms / close 240ms — defined in motion.ts and
        // applied via framer-motion. CSS animations below are fallbacks only.
        'slide-in-right':
          'slideInRight 320ms cubic-bezier(0.4, 0, 0.2, 1) forwards',
        'slide-out-right':
          'slideOutRight 240ms cubic-bezier(0.4, 0, 0.2, 1) forwards',
        'fade-in': 'fadeIn 200ms cubic-bezier(0.4, 0, 0.2, 1)',
        'scale-in': 'scaleIn 200ms cubic-bezier(0.4, 0, 0.2, 1)',
        'seal-spin': 'sealSpin 800ms cubic-bezier(0.87, 0, 0.13, 1)',
      },
    },
  },
  plugins: [],
};

export default config;
