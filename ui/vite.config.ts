import { fileURLToPath } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // import.meta.url plutôt que __dirname : le chargeur de config natif de Vite 8 ne fournit pas __dirname.
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5190,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:7900",
    },
  },
})
