import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // bind on all interfaces so phones on the same LAN can reach the dev server
    host: true,
  },
})
