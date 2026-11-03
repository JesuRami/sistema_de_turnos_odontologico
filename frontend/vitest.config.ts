import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// El navegador simulado corre en UTC: la agenda debe dibujar en la zona de la clínica,
// nunca en la del navegador (D4). Se fija antes de que arranquen los workers.
process.env.TZ = "UTC";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
    clearMocks: true
  }
});
