/**
 * Circuito crítico de C-06 contra el stack real (regla 9): login con cambio de
 * clave → crear turno → colisión con alternativo → marcar presente.
 */
import { expect, test } from "@playwright/test";
import { e2eEnv, readState } from "./env";

test("recepción: primer ingreso, turno, alternativo y presente", async ({ page }) => {
  const estado = readState();
  const E2E = e2eEnv();

  // 1. Login con clave provisoria → cambio obligatorio → agenda.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Ingresar" })).toBeVisible();
  await page.getByLabel("Email").fill(estado.receptionEmail);
  await page.getByLabel("Contraseña", { exact: true }).fill(estado.receptionProvisional);
  await page.getByRole("button", { name: "Ingresar" }).click();
  await expect(page.getByRole("heading", { name: "Cambiar contraseña" })).toBeVisible();
  await page.getByLabel("Contraseña actual").fill(estado.receptionProvisional);
  await page.getByLabel("Contraseña nueva", { exact: true }).fill(E2E.password);
  await page.getByLabel("Repetir contraseña nueva").fill(E2E.password);
  await page.getByRole("button", { name: "Cambiar contraseña" }).click();
  await expect(page.getByRole("button", { name: "Nuevo turno" })).toBeVisible();

  async function nuevoTurno(): Promise<void> {
    await page.getByRole("button", { name: "Nuevo turno" }).click();
    const dialogo = page.getByRole("dialog");
    await dialogo.getByLabel("Buscar paciente").fill(estado.patient);
    await dialogo.getByRole("button", { name: `Elegir ${estado.patient}` }).click();
    await dialogo.getByLabel("Profesional").selectOption({ label: estado.professional });
    await dialogo.getByLabel("Sillón").selectOption({ label: estado.chair });
    await dialogo.getByLabel("Hora").fill("08:00");
    await dialogo.getByRole("button", { name: "Guardar turno" }).click();
  }

  // 2. Turno a las 08:00 de hoy (hora de la clínica; el navegador está en UTC).
  await nuevoTurno();
  await expect(page.getByRole("status")).toContainText("Turno creado");
  await page.getByLabel("Profesional").selectOption({ label: estado.professional });
  await expect(page.getByRole("button", { name: `08:00 ${estado.patient} · Confirmado` })).toBeVisible();

  // 3. El mismo hueco otra vez → 409 → alternativo.
  await nuevoTurno();
  const dialogo = page.getByRole("dialog");
  await expect(dialogo.getByText("El horario ya está ocupado")).toBeVisible();
  // Los alternativos son futuros: su hora depende del momento real de la corrida.
  const alternativo = dialogo.getByRole("button", { name: /^Usar / }).first();
  const hora = ((await alternativo.textContent()) ?? "").match(/\d{2}:\d{2}$/)?.[0] ?? "";
  expect(hora).not.toBe("");
  await alternativo.click();
  await expect(page.getByRole("status")).toContainText(`Turno creado`);
  await expect(page.getByRole("status")).toContainText(hora);
  await expect(page.getByRole("button", { name: `${hora} ${estado.patient} · Confirmado` })).toBeVisible();

  // 4. Presente en el turno de las 08:00.
  await page.getByRole("button", { name: `08:00 ${estado.patient} · Confirmado` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Presente" }).click();
  await expect(page.getByRole("button", { name: `08:00 ${estado.patient} · Presente` })).toBeVisible();
});
