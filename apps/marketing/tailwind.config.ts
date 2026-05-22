import type { Config } from 'tailwindcss';

/**
 * Marketing site brand system — LIGHT VARIANT.
 *
 * The marketing surface intentionally diverges from the dark operational
 * console. It is the executive narrative layer, calibrated for procurement
 * teams, CTOs, COOs, and compliance officers.
 *
 * Visual Execution Hyperprompt — pixel discipline:
 *   • Spacing: explicit, fixed scale (no arbitrary `p-[17px]`).
 *   • Border radius: exactly four values (controls, cards, panels, pill).
 *   • Shadows: exactly five tokens (hairline, card-hover, panel,
 *     dropdown, modal).
 *   • Body sans is Geist Sans (NOT Inter — Inter has been removed).
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: '#F8F5EE',
          surface: '#FFFFFF',
          raised: '#FBF9F4',
        },
        line: {
          subtle: '#EAE6DE',
          DEFAULT: '#D4CFC4',
          strong: '#B8B0A0',
        },
        ink: {
          primary: '#0A0F1C',
          body: '#2A3548',
          secondary: '#4A5468',
          tertiary: '#8A93A4',
        },
        gold: {
          DEFAULT: '#A8882C',
          highlight: '#C9A84C',
          deep: '#8A6E1F',
        },
        substrate: {
          DEFAULT: '#1A4A9A',
          deep: '#0D2860',
        },
        success: '#2E7D5C',
        warning: '#B8821C',
        critical: '#A6342D',
        dark: {
          canvas: '#05080F',
          surface: '#0B1120',
          raised: '#0F1729',
          line: '#1A2744',
          'line-strong': '#243559',
          ink: '#D8E4F4',
          'ink-muted': '#7A90B4',
          'ink-dim': '#4A5C7A',
        },
      },
      fontFamily: {
        // Cormorant SC institutional display.
        display: ['var(--font-display)', 'Cormorant SC', 'Georgia', 'serif'],
        // Geist Sans (NOT Inter) — body / UI.
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        // IBM Plex Mono — data / eyebrows / labels.
        mono: ['var(--font-mono)', 'IBM Plex Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
        '3xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
      letterSpacing: {
        editorial: '0.04em',
        wider: '0.08em',
        widest: '0.18em',
      },
      maxWidth: {
        prose: '760px',
        narrow: '680px',
        contact: '800px',
        hero: '1440px',
      },
      // Exactly four border-radius values per the pixel discipline rule.
      borderRadius: {
        // We keep `none` and `full` as Tailwind defaults; explicit tokens
        // below are the only ones components should reference.
        sm: '4px', // controls (inputs, buttons)
        DEFAULT: '4px',
        md: '8px', // cards
        lg: '12px', // panels
        full: '9999px', // status pills
      },
      // Exactly five shadow tokens.
      boxShadow: {
        hairline: '0 1px 0 var(--line-subtle)',
        'card-hover': '0 8px 24px rgba(10, 15, 28, 0.08)',
        panel: '0 4px 16px rgba(10, 15, 28, 0.04)',
        dropdown: '0 8px 32px rgba(10, 15, 28, 0.12)',
        modal: '0 24px 64px rgba(10, 15, 28, 0.16)',
        // Legacy aliases (kept temporarily — alias to the five real tokens).
        card: '0 4px 16px rgba(10, 15, 28, 0.04)',
        'dark-glow': '0 8px 24px rgba(10, 15, 28, 0.40)',
      },
      // Explicit spacing scale — every spacing must come from this list.
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
      },
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        'lattice-spin': {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        'caret-blink': {
          '0%, 49%': { opacity: '1' },
          '50%, 100%': { opacity: '0' },
        },
        'reveal-up': {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Hero scroll-indicator: vertical pulse line.
        'scroll-pulse': {
          '0%, 100%': { transform: 'scaleY(0.85)', opacity: '0.6' },
          '50%': { transform: 'scaleY(1.0)', opacity: '1' },
        },
      },
      animation: {
        'pulse-soft': 'pulse-soft 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        'lattice-spin': 'lattice-spin 240s linear infinite',
        'caret-blink': 'caret-blink 1s steps(1) infinite',
        'scroll-pulse': 'scroll-pulse 2s cubic-bezier(0.22, 1, 0.36, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;
