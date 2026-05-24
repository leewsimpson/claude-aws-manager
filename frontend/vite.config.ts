/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API proxy target is environment-driven so the same config works locally
// and inside Docker. In Docker Compose, another agent sets
// VITE_API_PROXY_TARGET=http://backend:8000. Locally it defaults to localhost.
const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // host: true binds to 0.0.0.0 so the dev server is reachable from outside
    // the container (required for Docker).
    host: true,
    port: 5173,
    proxy: {
      // All /api requests proxy to the backend. Do NOT rewrite the path —
      // the backend serves its routes under /api.
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})
