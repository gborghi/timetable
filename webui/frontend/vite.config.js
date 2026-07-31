import { sveltekit } from '@sveltejs/kit/vite';

export default {
  plugins: [sveltekit()],
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    allowedHosts: ['.ts.net'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false
      }
    }
  },
  // `npm run preview` serve il build statico. Non eredita nulla da
  // `server`, e il backend non monta StaticFiles: senza questo blocco
  // le chiamate a /api (api.ts usa BASE = "", stessa origin) finiscono
  // sul server statico e rispondono 404.
  // host: l'IP Tailscale e non 0.0.0.0, cosi' il sito non viene
  // esposto anche sulla LAN.
  preview: {
    port: 4173,
    strictPort: true,
    host: process.env.PITANTUM_PREVIEW_HOST || '127.0.0.1',
    allowedHosts: ['.ts.net'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false
      }
    }
  }
};
