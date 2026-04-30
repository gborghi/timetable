/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#f5f7fa',
          100: '#e4e9f0',
          200: '#cbd4e0',
          300: '#9aa6b8',
          500: '#5a6477',
          700: '#2f3743',
          900: '#11161e'
        },
        accent: {
          500: '#3a6df0',
          600: '#2c58cf'
        },
        // Constraint level palette (HARD/SOFT/PREFERITO/ENFORCED/ALLOWED).
        // Used everywhere a vincolo is rendered. Inline `style="background:...;
        // color:..."` blocks are being replaced by these tokens.
        c: {
          'hard-bg':       '#fecaca',
          'hard-fg':       '#991b1b',
          'hard-border':   '#dc2626',
          'soft-bg':       '#fde68a',
          'soft-fg':       '#92400e',
          'soft-border':   '#d97706',
          'pref-bg':       '#bae6fd',
          'pref-fg':       '#075985',
          'pref-border':   '#0284c7',
          'enf-bg':        '#065f46',
          'enf-fg':        '#ffffff',
          'enf-border':    '#064e3b',
          'allow-bg':      '#d1fae5',
          'allow-fg':      '#065f46',
          'allow-border':  '#10b981'
        }
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: []
};
