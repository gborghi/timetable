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
        }
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: []
};
