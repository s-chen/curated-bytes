/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // Served from a sub-path on GitHub Pages until the custom domain is set (e.g. /curated-bytes/).
  // The deploy workflow passes the path Pages reports; locally it's the root.
  base: `${process.env.BASE_PATH ?? ''}/`,
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    restoreMocks: true,
  },
})
