import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/agent-api': {
        target: process.env.DBGPT_AGENT_ORIGIN || 'http://127.0.0.1:5670',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agent-api/, '/api'),
      },
    },
  },
});
