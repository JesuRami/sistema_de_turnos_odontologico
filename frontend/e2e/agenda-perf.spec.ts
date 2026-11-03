/**
 * US-010 CA-3: la semana con 500 turnos queda visible en menos de 2 s contra la
 * API real. Se mide desde el clic en "Siguiente" hasta que los 500 turnos están
 * en la grilla.
 */
import { expect, test } from "@playwright/test";
import { e2eEnv, readState } from "./env";

const LIMITE_MS = 2000;

test("semana con 500 turnos visible en menos de 2 s", async ({ page }) => {
  const estado = readState();
  const E2E = e2eEnv();
  await page.goto("/login");
  await page.getByLabel("Email").fill(E2E.adminEmail);
  await page.getByLabel("Contraseña", { exact: true }).fill(E2E.password);
  await page.getByRole("button", { name: "Ingresar" }).click();
  await page.getByRole("button", { name: "Semana" }).click();
  await expect(page.getByRole("columnheader")).toHaveCount(7);

  const turnos = page.getByRole("button", { name: new RegExp(estado.perfPatient) });
  const inicio = Date.now();
  await page.getByRole("button", { name: "Siguiente" }).click();
  await expect(turnos).toHaveCount(estado.perfAppointments, { timeout: 10_000 });
  const duracion = Date.now() - inicio;

  test.info().annotations.push({ type: "semana_500_ms", description: String(duracion) });
  console.log(`[perf] semana con ${estado.perfAppointments} turnos visible en ${duracion} ms`);
  expect(estado.perfAppointments).toBe(500);
  expect(duracion).toBeLessThan(LIMITE_MS);
});
