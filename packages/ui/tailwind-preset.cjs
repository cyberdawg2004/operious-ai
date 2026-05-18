/** @type {import('tailwindcss').Config} */
module.exports = {
  theme: {
    extend: {
      colors: {
        // Operious enterprise palette — deterministic, restrained, monochrome-leaning.
        // Surfaces are layered to read as inspectable infrastructure, not consumer SaaS.
        bg: {
          DEFAULT: '#0a0c10',
          subtle: '#0f1218',
          raised: '#141821',
          inset: '#080a0e',
        },
        line: {
          DEFAULT: '#1f2530',
          subtle: '#171c25',
          strong: '#2a3140',
        },
        fg: {
          DEFAULT: '#e6e8ec',
          muted: '#9ba3b1',
          subtle: '#6c7585',
          dim: '#4a5260',
        },
        accent: {
          DEFAULT: '#8aa6ff',
          subtle: '#5d7cd6',
          glow: '#a9bfff',
        },
        signal: {
          allow: '#3aa67c',
          escalate: '#d6a14a',
          deny: '#cc6464',
          deadlock: '#a35cc4',
          neutral: '#7c8595',
        },
      },
      fontFamily: {
        sans: ['"Inter"', '"InterVariable"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"IBM Plex Mono"', 'ui-monospace', 'monospace'],
        display: ['"Inter"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        sm: '4px',
        md: '6px',
        lg: '10px',
      },
      boxShadow: {
        inset: 'inset 0 1px 0 rgba(255,255,255,0.04)',
        raised: '0 1px 0 rgba(255,255,255,0.04), 0 8px 24px -12px rgba(0,0,0,0.6)',
      },
      letterSpacing: {
        wider: '0.04em',
        widest: '0.12em',
      },
    },
  },
  plugins: [],
};
