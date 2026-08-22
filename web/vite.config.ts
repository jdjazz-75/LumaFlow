// LumaFlow v1.0 (2026-08-07)
// Configuration Vite minimale : plugin React pour le build/dev server du frontend.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
})
