import { defineConfig } from "@playwright/test";

/**
 * E2E contra el stack real (API + Postgres + Redis). La API debe estar levantada
 * en `E2E_API` (default http://localhost:8000); Vite se levanta solo y la usa por
 * proxy. El navegador corre en UTC: la agenda debe dibujar en la zona de la clínica.
 * Credenciales solo por entorno (regla 6): ver frontend/README.md §E2E.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    timezoneId: "UTC",
    locale: "es-AR",
    trace: "retain-on-failure"
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
    env: { API_PROXY_TARGET: process.env.E2E_API ?? "http://localhost:8000" }
  }
});
