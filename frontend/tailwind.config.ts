// RoutePass — Tailwind CSS configuration
// Dark-first design system. All values mirror globals.css custom properties.
// Never add one-off colors inline — extend this config instead.

import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: ['class'], // .light class opt-in for light overrides
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    // ── Override (not extend) the default container so it centers automatically
    container: {
      center: true,
      padding: '2rem',
      screens: { '2xl': '1400px' },
    },

    extend: {
      // ── Brand Colors ────────────────────────────────────────────────────────
      colors: {
        // Primary — mint green (on dark backgrounds this is the CTA color)
        primary: {
          DEFAULT: '#3ECFAF',
          hover:   '#2EB89A',
          light:   'rgba(62,207,175,0.1)',
        },
        // Accent — same as primary on dark
        accent: {
          DEFAULT: '#3ECFAF',
          hover:   '#2EB89A',
        },
        // Backgrounds — dark defaults
        bg:      '#0a0a0a',
        surface: {
          DEFAULT: '#111111',
          raised:  '#171717',
        },
        // Borders — dark defaults
        border: {
          DEFAULT: '#242424',
          strong:  '#303030',
        },
        // Text — dark defaults
        text: {
          primary:   '#ededed',
          secondary: '#737373',
          disabled:  '#525252',
          inverse:   '#0a0a0a',
        },
        // Semantic — adjusted for dark bg
        success: {
          DEFAULT: '#34d399',
          light:   'rgba(52,211,153,0.12)',
        },
        warning: {
          DEFAULT: '#fbbf24',
          light:   'rgba(251,191,36,0.12)',
        },
        error: {
          DEFAULT: '#f87171',
          light:   'rgba(248,113,113,0.12)',
        },
        info: {
          DEFAULT: '#60a5fa',
          light:   'rgba(96,165,250,0.12)',
        },
      },

      // ── Border Radius ────────────────────────────────────────────────────────
      // Matches DESIGN.md exactly. Never use raw px values in components.
      borderRadius: {
        sm:   '4px',
        md:   '8px',
        lg:   '12px',
        xl:   '16px',
        full: '9999px',
      },

      // ── Box Shadows ──────────────────────────────────────────────────────────
      boxShadow: {
        sm:    '0 1px 2px rgba(0,0,0,0.06)',
        md:    '0 4px 12px rgba(0,0,0,0.08)',
        lg:    '0 8px 24px rgba(0,0,0,0.10)',
        inner: 'inset 0 2px 4px rgba(0,0,0,0.04)',
      },

      // ── Typography ───────────────────────────────────────────────────────────
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-jetbrains-mono)', 'monospace'],
        display: ['var(--font-outfit)', 'var(--font-inter)', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        // DESIGN.md type scale
        'display':    ['36px', { lineHeight: '1.2',  fontWeight: '700' }],
        'heading-xl': ['30px', { lineHeight: '1.25', fontWeight: '700' }],
        'heading-lg': ['24px', { lineHeight: '1.3',  fontWeight: '600' }],
        'heading-md': ['20px', { lineHeight: '1.35', fontWeight: '600' }],
        'heading-sm': ['16px', { lineHeight: '1.4',  fontWeight: '600' }],
        'body-lg':    ['16px', { lineHeight: '1.6',  fontWeight: '400' }],
        'body':       ['14px', { lineHeight: '1.6',  fontWeight: '400' }],
        'body-sm':    ['13px', { lineHeight: '1.5',  fontWeight: '400' }],
        'caption':    ['12px', { lineHeight: '1.4',  fontWeight: '400' }],
        'label':      ['12px', { lineHeight: '1.0',  fontWeight: '500' }],
        'mono':       ['13px', { lineHeight: '1.5',  fontWeight: '400' }],
      },

      // ── Spacing ──────────────────────────────────────────────────────────────
      // 4px base unit. All values from DESIGN.md.
      spacing: {
        'space-1':  '4px',
        'space-2':  '8px',
        'space-3':  '12px',
        'space-4':  '16px',
        'space-5':  '20px',
        'space-6':  '24px',
        'space-8':  '32px',
        'space-10': '40px',
        'space-12': '48px',
        'space-16': '64px',
      },

      // ── Animations ───────────────────────────────────────────────────────────
      keyframes: {
        shimmer: {
          '0%':   { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
        'slide-in-right': {
          '0%':   { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)',    opacity: '1' },
        },
        'scale-in': {
          '0%':   { transform: 'scale(0.97)', opacity: '0' },
          '100%': { transform: 'scale(1)',    opacity: '1' },
        },
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.4' },
        },
      },
      animation: {
        shimmer:          'shimmer 1.5s ease-in-out infinite',
        'slide-in-right': 'slide-in-right 200ms ease-out',
        'scale-in':       'scale-in 200ms ease-out',
        'pulse-slow':     'pulse 2s infinite',
      },
    },
  },
  plugins: [],
}

export default config
