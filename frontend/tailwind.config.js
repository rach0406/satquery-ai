/** @type {import('tailwindcss').Config} */

/*
 * SatQuery AI design system — "Orbital"
 * ------------------------------------
 * A light, institutional palette: paper-white surfaces, deep space-navy ink,
 * and a single confident satellite blue for action. Reads as a scientific
 * instrument rather than a generic dark AI dashboard.
 *
 * Dark navy is retained for deliberate accents — the hero, the map canvas,
 * section dividers — where a night-sky field is thematically right.
 */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // --- light surfaces ------------------------------------------
        paper: {
          DEFAULT: '#ffffff',
          50: '#fbfcfe',
          100: '#f5f8fc',
          200: '#eef3f9',
          300: '#e3eaf3',
          400: '#d3dde9',
        },
        // --- ink: deep space navy ------------------------------------
        ink: {
          950: '#060c18',
          900: '#0a1424',
          800: '#0f1e33',
          700: '#16294380',
          600: '#334764',
          500: '#4a5f80',
          400: '#697d9c',
          300: '#8e9fb8',
          200: '#b4c1d3',
          100: '#d7dfe9',
        },
        // deep opaque navies for hero / map chrome
        night: {
          950: '#050a14',
          900: '#08111f',
          850: '#0b1728',
          800: '#101f34',
          700: '#182c47',
          600: '#22395a',
        },
        // --- action ---------------------------------------------------
        orbit: {
          50: '#eff5ff',
          100: '#dbe8fe',
          200: '#bfd6fe',
          300: '#93bbfd',
          400: '#6096fa',
          500: '#3b78f6',
          600: '#2a78d6',
          700: '#1d5bb8',
          800: '#1e4a94',
          900: '#1e4074',
        },
        // --- signal / status -----------------------------------------
        signal: {
          green: '#12855c',
          amber: '#b26b00',
          red: '#c8322f',
          teal: '#0d7d8a',
          violet: '#5b46b8',
          magenta: '#b8317a',
        },
        // --- validated chart series (light surface) -------------------
        series: {
          1: '#2a78d6',
          2: '#eb6834',
          3: '#1baf7a',
          4: '#eda100',
          5: '#e87ba4',
          6: '#4a3aa7',
        },
      },

      fontFamily: {
        display: ['"Space Grotesk"', 'Sora', 'Inter', 'system-ui', 'sans-serif'],
        sans: ['Inter', '"Segoe UI"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'Consolas', 'monospace'],
      },

      /* A deliberate type scale. Sizes step by a clear ratio and each has a
         line-height chosen for its role, so hierarchy comes from the scale
         rather than from ad-hoc sizes sprinkled through the markup. */
      fontSize: {
        micro: ['0.75rem', { lineHeight: '1.15rem', letterSpacing: '0.02em' }],
        tiny: ['0.8125rem', { lineHeight: '1.25rem' }],
        small: ['0.875rem', { lineHeight: '1.4rem' }],
        base: ['0.9375rem', { lineHeight: '1.65rem' }],
        body: ['1rem', { lineHeight: '1.75rem' }],
        lead: ['1.125rem', { lineHeight: '1.85rem' }],
        h5: ['1.0625rem', { lineHeight: '1.5rem', letterSpacing: '-0.005em' }],
        h4: ['1.25rem', { lineHeight: '1.7rem', letterSpacing: '-0.01em' }],
        h3: ['1.5rem', { lineHeight: '2rem', letterSpacing: '-0.015em' }],
        h2: ['2rem', { lineHeight: '2.5rem', letterSpacing: '-0.02em' }],
        h1: ['2.75rem', { lineHeight: '3.15rem', letterSpacing: '-0.025em' }],
        display: ['3.5rem', { lineHeight: '3.85rem', letterSpacing: '-0.03em' }],
        hero: ['4.25rem', { lineHeight: '4.5rem', letterSpacing: '-0.035em' }],
      },

      spacing: {
        18: '4.5rem',
        22: '5.5rem',
        section: '7rem',
        'section-sm': '4.5rem',
      },

      maxWidth: {
        prose: '68ch',
        content: '1200px',
        wide: '1440px',
      },

      borderRadius: {
        card: '14px',
        panel: '18px',
        pill: '999px',
      },

      boxShadow: {
        card: '0 1px 2px rgba(10,20,36,.05), 0 4px 16px -6px rgba(10,20,36,.10)',
        raised: '0 2px 4px rgba(10,20,36,.05), 0 12px 32px -12px rgba(10,20,36,.18)',
        float: '0 8px 20px -6px rgba(10,20,36,.14), 0 24px 56px -20px rgba(10,20,36,.24)',
        focus: '0 0 0 3px rgba(42,120,214,.22)',
        'inner-line': 'inset 0 -1px 0 rgba(10,20,36,.06)',
        glow: '0 0 0 1px rgba(96,150,250,.35), 0 0 40px -8px rgba(59,120,246,.55)',
      },

      backgroundImage: {
        'orbit-grid':
          'linear-gradient(rgba(42,120,214,.055) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(42,120,214,.055) 1px, transparent 1px)',
        'night-sky':
          'radial-gradient(1200px 700px at 15% -10%, rgba(42,120,214,.28), transparent 60%),' +
          'radial-gradient(900px 600px at 88% 8%, rgba(13,125,138,.22), transparent 58%),' +
          'linear-gradient(168deg, #08111f 0%, #0b1728 48%, #060c18 100%)',
        'paper-wash':
          'radial-gradient(900px 500px at 8% -12%, rgba(42,120,214,.07), transparent 62%),' +
          'radial-gradient(700px 420px at 96% 0%, rgba(13,125,138,.055), transparent 58%)',
      },

      backgroundSize: {
        grid: '38px 38px',
      },

      keyframes: {
        floatUp: {
          from: { opacity: '0', transform: 'translateY(14px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        orbitSpin: { to: { transform: 'rotate(360deg)' } },
        pulseSoft: {
          '0%,100%': { opacity: '1' },
          '50%': { opacity: '.45' },
        },
        sweep: {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        twinkle: {
          '0%,100%': { opacity: '.25' },
          '50%': { opacity: '.9' },
        },
      },
      animation: {
        floatUp: 'floatUp .5s cubic-bezier(.22,1,.36,1) both',
        fadeIn: 'fadeIn .4s ease both',
        shimmer: 'shimmer 1.6s infinite',
        orbitSpin: 'orbitSpin 26s linear infinite',
        pulseSoft: 'pulseSoft 2s ease-in-out infinite',
        sweep: 'sweep 4s linear infinite',
        twinkle: 'twinkle 3.5s ease-in-out infinite',
      },

      transitionTimingFunction: {
        out: 'cubic-bezier(.22,1,.36,1)',
      },
    },
  },
  plugins: [],
}
