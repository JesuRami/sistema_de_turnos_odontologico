import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En Docker el backend es `http://api:8000` (API_PROXY_TARGET en compose.override.yaml);
// `localhost` dentro del contenedor es el propio frontend.
const apiTarget: string = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Sin rewrite: el backend ya expone sus rutas bajo `/api` (C-03+).
      "/api": { target: apiTarget, changeOrigin: true },
      // Salud de infraestructura, fuera de `/api`.
      "/health": { target: apiTarget, changeOrigin: true }
    }
  }
});
