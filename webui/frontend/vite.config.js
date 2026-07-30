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
  }
};
