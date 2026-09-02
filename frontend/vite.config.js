import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Absolute asset paths: the SPA is served from '/', '/login' and '/app',
  // and relative paths would resolve differently at each depth.
  base: '/',
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/artifacts': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 2600,
    rollupOptions: {
      output: {
        // Plotly is the bulk of the bundle. Splitting it keeps the app shell
        // small and lets the browser cache the heavy chart engine separately.
        manualChunks: {
          plotly: ['plotly.js-dist-min'],
          leaflet: ['leaflet'],
          react: ['react', 'react-dom'],
        },
      },
    },
  },
})
