/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // Scala neutra "carta e inchiostro" del redesign. I nomi delle
        // chiavi sono quelli storici (ink-50 ... ink-900) apposta: le
        // centinaia di `text-ink-500` / `border-ink-200` gia' scritte
        // nelle pagine passano alla palette calda senza toccarle.
        // La scala e' completa (50..900) perche' le pagine usano gia'
        // ink-400/600/800, che nella vecchia config non esistevano e
        // venivano scartate silenziosamente da Tailwind.
        ink: {
          50: '#faf8f2',   // fondo tenue
          100: '#f1ece2',  // --line2: righe tabella, hover
          200: '#e5e0d4',  // --line: bordi di card e input
          300: '#9b9384',  // --ink3: testo terziario
          400: '#857d6e',
          500: '#6b6355',  // --ink2: testo secondario
          600: '#554e42',
          700: '#3f3a30',
          800: '#2a2620',
          900: '#1a1612'   // --ink: testo primario
        },
        // Fondi: paper e' lo sfondo dell'app, band la fascia introduttiva,
        // soft le card "da fare" (tratteggiate).
        paper: {
          DEFAULT: '#f5f2ea',
          band:    '#fbf9f3',
          soft:    '#fdfcf8',
          sunk:    '#f1ece0'   // pill di nav attiva
        },
        line: {
          DEFAULT: '#e5e0d4',
          soft:    '#f1ece2',
          dash:    '#d8d0be'
        },
        // Accento primario del redesign: l'indaco del brand. `accent-*`
        // resta il nome usato da .btn-primary e dai focus ring.
        accent: {
          50:  '#eef2f7',
          100: '#dbe4ee',
          200: '#b8c8dc',
          300: '#8fa8c5',
          500: '#1e3a5f',
          600: '#16293f',
          700: '#101f30'
        },
        pri:   '#1e3a5f',
        gold:  '#c9a23a',
        siena: '#9c4a1c',
        // piTantum brand palette (hex tokens; see also CSS variables
        // --brand-* in app.css for runtime/dark-mode overrides).
        brand: {
          primary:   '#1e3a5f',
          secondary: '#c9a23a',
          accent:    '#9c4a1c',
          bg:        '#f7f1de',
          fg:        '#1a1612',
          'primary-d':   '#88a5d8',
          'secondary-d': '#f0c869',
        },
        // Constraint level palette (HARD/SOFT/PREFERRED/ENFORCED/ALLOWED).
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
        sans:  ['IBM Plex Sans', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        serif: ['Source Serif 4', 'ui-serif', 'Georgia', 'serif'],
        mono:  ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'monospace']
      },
      borderRadius: {
        card: '11px'
      }
    }
  },
  plugins: []
};
