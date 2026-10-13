import { test, expect } from "@playwright/test";

/**
 * Stub E2E del circuito crítico (reserva→recordatorio→confirmación→presente).
 * Skipped hasta C-14 (diseño decisión 9): el flujo real no existe en C-01.
 */
test.describe.skip("circuito crítico de turnos (stub hasta C-14)", () => {
  test("reserva online crea turno pendiente", async ({ page }) => {
    await page.goto("/b/clinica-ejemplo");
    await expect(page.getByRole("heading")).toContainText("Reservar turno");
  });

  test("gestión por token confirma el turno", async ({ page }) => {
    await page.goto("/g/token-ejemplo");
    await expect(page.getByRole("heading")).toContainText("Gestionar mi turno");
  });
});
