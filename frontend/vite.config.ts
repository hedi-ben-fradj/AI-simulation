import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server proxies the backend so the browser only talks to one origin.
// The backend (and only the backend) holds the Anthropic API key.
const backend = process.env.AISIM_BACKEND ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: { pixi: ['pixi.js'], charts: ['recharts'], mantine: ['@mantine/core', '@mantine/hooks'] },
      },
    },
  },
  test: { environment: 'node' },
} as any);
