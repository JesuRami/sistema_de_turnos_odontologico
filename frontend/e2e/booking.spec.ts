/**
 * Circuito crítico de C-07 contra el stack real (regla 9): reserva pública mobile en ≤ 4 pasos,
 * la agenda de recepción la muestra sin recargar y la carrera por el mismo hueco responde 409
 * con alternativos. Requiere la clínica del seed con `SEED_BOOKING_DEMO=true` (frontend/README.md).
 */
import { expect, test, type Browser, type Page } from "@playwright/test";
import { clinicSlug, e2eEnv, readState } from "./env";

const VIEWPORT = { width: 360, height: 740 };
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

/** Etiqueta `"mar 08/01"` del día local de la clínica a `dias` de hoy (Buenos Aires: UTC-3 fijo). */
function etiquetaDia(dias: number): string {
  const d = new Date(Date.now() - 3 * 3_600_000 + dias * 86_400_000);
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${DIAS[d.getUTCDay()] ?? ""} ${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}`;
}

function telefono(): string {
  return `011 15 5555-${String(Math.floor(Math.random() * 10_000)).padStart(4, "0")}`;
}

async function sinScrollHorizontal(page: Page): Promise<void> {
  const cabe = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
  );
  expect(cabe, "la página no debe desbordar horizontalmente a 360 px").toBe(true);
}

async function botonesGrandes(page: Page): Promise<void> {
  const alturas = await page
    .getByRole("main")
    .getByRole("button")
    .evaluateAll((botones) => botones.map((b) => b.getBoundingClientRect().height));
  expect(alturas.length).toBeGreaterThan(0);
  for (const altura of alturas) {
    expect(altura).toBeGreaterThanOrEqual(44);
  }
}

/** Abre el flujo hasta el paso "Tus datos" para `hora` de `dias` días adelante. */
async function hastaLosDatos(page: Page, hora: string, dias = 1): Promise<string[]> {
  const estado = readState();
  const pasos: string[] = [];
  const paso = async (): Promise<void> => {
    pasos.push((await page.getByRole("heading", { level: 2 }).textContent()) ?? "");
    await sinScrollHorizontal(page);
    await botonesGrandes(page);
  };
  await page.goto(`/b/${clinicSlug()}`);
  await expect(page.getByRole("heading", { level: 2, name: "Elegí profesional" })).toBeVisible();
  await paso();
  await page.getByRole("button", { name: estado.professional }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Elegí el día" })).toBeVisible();
  await paso();
  await page.getByRole("button", { name: etiquetaDia(dias) }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Elegí el horario" })).toBeVisible();
  await paso();
  await page.getByRole("button", { name: hora, exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Tus datos" })).toBeVisible();
  await paso();
  return pasos;
}

async function completarDatos(page: Page, nombre: string): Promise<void> {
  await page.getByLabel("Nombre y apellido").fill(nombre);
  await page.getByLabel("Teléfono").fill(telefono());
  await page.getByLabel(/recordatorios por WhatsApp/).check();
  await page.getByLabel(/Acepto la política de privacidad/).check();
  await page.getByRole("button", { name: "Confirmar turno" }).click();
}

async function contextoMobile(browser: Browser): Promise<Page> {
  const contexto = await browser.newContext({
    viewport: VIEWPORT,
    timezoneId: "UTC",
    locale: "es-AR"
  });
  return contexto.newPage();
}

test("paciente reserva en 4 pasos en mobile y recibe el link de gestión", async ({ browser }) => {
  const estado = readState();
  const page = await contextoMobile(browser);
  const nombre = `Paciente Online E2E ${estado.run} Uno`;

  const pasos = await hastaLosDatos(page, "10:00");
  await completarDatos(page, nombre);

  await expect(page.getByRole("heading", { name: "Turno reservado" })).toBeVisible();
  expect(pasos).toEqual(["Elegí profesional", "Elegí el día", "Elegí el horario", "Tus datos"]);
  const link = page.getByLabel("Link para gestionar tu turno");
  await expect(link).toHaveValue(/\/g\/[A-Za-z0-9_-]{43,}$/);
  await expect(page.getByText(`${etiquetaDia(1)} · 10:00 con ${estado.professional}`)).toBeVisible();
  await sinScrollHorizontal(page);
  await botonesGrandes(page);
  const guardado = await page.evaluate(() => localStorage.length + sessionStorage.length);
  expect(guardado).toBe(0);
});

test("la agenda de recepción muestra la reserva pendiente en ≤ 30 s sin recargar", async ({
  browser
}) => {
  const estado = readState();
  const E2E = e2eEnv();
  const recepcion = await (await browser.newContext({ timezoneId: "UTC", locale: "es-AR" })).newPage();
  await recepcion.goto("/login");
  await recepcion.getByLabel("Email").fill(E2E.adminEmail);
  await recepcion.getByLabel("Contraseña", { exact: true }).fill(E2E.password);
  await recepcion.getByRole("button", { name: "Ingresar" }).click();
  await expect(recepcion.getByRole("button", { name: "Nuevo turno" })).toBeVisible();
  await recepcion.getByRole("button", { name: "Siguiente" }).click();
  await recepcion.getByLabel("Profesional").selectOption({ label: estado.professional });
  const nombre = `Paciente Online E2E ${estado.run} Dos`;
  const reservado = recepcion.getByRole("button", {
    name: new RegExp(`11:00 ${nombre} · Pendiente`)
  });
  await expect(reservado).toHaveCount(0);

  const paciente = await contextoMobile(browser);
  await hastaLosDatos(paciente, "11:00");
  await completarDatos(paciente, nombre);
  await expect(paciente.getByRole("heading", { name: "Turno reservado" })).toBeVisible();

  // Sin recargar: el refetch de 30 s trae el turno `pending` de origen online.
  await expect(reservado).toBeVisible({ timeout: 40_000 });
});

test("dos pacientes por el mismo hueco: el segundo ve 'Ese horario se acaba de ocupar'", async ({
  browser
}) => {
  const estado = readState();
  const primero = await contextoMobile(browser);
  const segundo = await contextoMobile(browser);
  await hastaLosDatos(primero, "12:00");
  await hastaLosDatos(segundo, "12:00");

  await completarDatos(primero, `Paciente Online E2E ${estado.run} Tres`);
  await expect(primero.getByRole("heading", { name: "Turno reservado" })).toBeVisible();
  await completarDatos(segundo, `Paciente Online E2E ${estado.run} Cuatro`);

  await expect(segundo.getByText("Ese horario se acaba de ocupar")).toBeVisible();
  const alternativo = segundo.getByRole("button", { name: /^Reservar / }).first();
  await expect(alternativo).toBeVisible();
  await sinScrollHorizontal(segundo);
  await alternativo.click();
  await expect(segundo.getByRole("heading", { name: "Turno reservado" })).toBeVisible();
});
