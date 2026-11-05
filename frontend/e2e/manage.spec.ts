/**
 * Circuito crítico de C-08 contra el stack real (regla 9): el paciente confirma, cancela y
 * reprograma su turno desde el link de gestión en un celular de 360 px; recepción ve el cambio
 * sin recargar. Los turnos se reservan por la API pública, igual que un paciente. Requiere la
 * clínica del seed con `SEED_BOOKING_DEMO=true` (frontend/README.md §E2E). Datos sintéticos.
 */
import { expect, request, test, type Browser, type Page } from "@playwright/test";
import { clinicSlug, e2eEnv, readState } from "./env";

const VIEWPORT = { width: 360, height: 740 };
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
// Fuera de la ventana de cancelación de 24 h y de las horas que usa booking.spec.ts.
const DIAS_ADELANTE = 2;

/** Fecha local de Buenos Aires (UTC-3 fijo) a `dias` de hoy. */
function fechaLocal(dias: number): Date {
  return new Date(Date.now() - 3 * 3_600_000 + dias * 86_400_000);
}

const pad = (n: number): string => String(n).padStart(2, "0");

function etiquetaDia(dias: number): string {
  const d = fechaLocal(dias);
  return `${DIAS[d.getUTCDay()] ?? ""} ${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}`;
}

function instante(dias: number, hora: string): string {
  const d = fechaLocal(dias);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${hora}:00-03:00`;
}

/** Reserva por la API pública y devuelve la ruta `/g/<token>` del link de gestión. */
async function reservar(nombre: string, hora: string): Promise<string> {
  const estado = readState();
  const api = await request.newContext({ baseURL: e2eEnv().baseURL });
  const catalogo = (await (await api.get(`/api/booking/${clinicSlug()}`)).json()) as {
    professionals: { id: string; display_name: string }[];
  };
  const profesional = catalogo.professionals.find((p) => p.display_name === estado.professional);
  if (profesional === undefined) {
    throw new Error("el profesional del E2E no es reservable");
  }
  const respuesta = await api.post(`/api/booking/${clinicSlug()}/appointments`, {
    data: {
      professional_id: profesional.id,
      starts_at: instante(DIAS_ADELANTE, hora),
      patient: {
        full_name: nombre,
        phone: `011 15 5555-${String(Math.floor(Math.random() * 10_000)).padStart(4, "0")}`,
        whatsapp_opt_in: true,
        privacy_accepted: true
      }
    }
  });
  if (!respuesta.ok()) {
    throw new Error(`reserva → ${respuesta.status()}`);
  }
  const { manage_url: url } = (await respuesta.json()) as { manage_url: string };
  await api.dispose();
  return new URL(url).pathname;
}

async function celular(browser: Browser): Promise<Page> {
  const contexto = await browser.newContext({ viewport: VIEWPORT, timezoneId: "UTC", locale: "es-AR" });
  return contexto.newPage();
}

async function aptoParaCelular(page: Page): Promise<void> {
  const cabe = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
  );
  expect(cabe, "la página no debe desbordar horizontalmente a 360 px").toBe(true);
  const alturas = await page
    .getByRole("main")
    .getByRole("button")
    .evaluateAll((botones) => botones.map((b) => b.getBoundingClientRect().height));
  expect(alturas.length).toBeGreaterThan(0);
  for (const altura of alturas) {
    expect(altura).toBeGreaterThanOrEqual(44);
  }
}

test("el paciente confirma desde el link y recepción lo ve sin recargar", async ({ browser }) => {
  const estado = readState();
  const E2E = e2eEnv();
  const nombre = `Paciente Gestion E2E ${estado.run} Uno`;
  const ruta = await reservar(nombre, "13:00");

  const recepcion = await (await browser.newContext({ timezoneId: "UTC", locale: "es-AR" })).newPage();
  await recepcion.goto("/login");
  await recepcion.getByLabel("Email").fill(E2E.adminEmail);
  await recepcion.getByLabel("Contraseña", { exact: true }).fill(E2E.password);
  await recepcion.getByRole("button", { name: "Ingresar" }).click();
  await expect(recepcion.getByRole("button", { name: "Nuevo turno" })).toBeVisible();
  for (let dia = 0; dia < DIAS_ADELANTE; dia += 1) {
    await recepcion.getByRole("button", { name: "Siguiente" }).click();
  }
  await recepcion.getByLabel("Profesional").selectOption({ label: estado.professional });
  await expect(
    recepcion.getByRole("button", { name: new RegExp(`13:00 ${nombre} · Pendiente`) })
  ).toBeVisible({ timeout: 40_000 });

  const paciente = await celular(browser);
  await paciente.goto(ruta);
  await expect(paciente.getByRole("heading", { name: `${etiquetaDia(DIAS_ADELANTE)} · 13:00` })).toBeVisible();
  await aptoParaCelular(paciente);
  await paciente.getByRole("button", { name: "Confirmar turno" }).click();
  await expect(paciente.getByText("Confirmado", { exact: true })).toBeVisible();
  await expect(paciente.getByRole("button", { name: "Confirmar turno" })).toHaveCount(0);
  expect(await paciente.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);

  // Sin recargar: el refetch periódico de la agenda trae el turno confirmado.
  await expect(
    recepcion.getByRole("button", { name: new RegExp(`13:00 ${nombre} · Confirmado`) })
  ).toBeVisible({ timeout: 40_000 });
});

test("el paciente cancela otro turno indicando el motivo", async ({ browser }) => {
  const estado = readState();
  const ruta = await reservar(`Paciente Gestion E2E ${estado.run} Dos`, "14:00");
  const paciente = await celular(browser);

  await paciente.goto(ruta);
  await paciente.getByRole("button", { name: "Cancelar" }).click();
  const dialogo = paciente.getByRole("dialog", { name: "Cancelar turno" });
  await dialogo.getByLabel("Viaje").check();
  await aptoParaCelular(paciente);
  await dialogo.getByRole("button", { name: "Confirmar cancelación" }).click();

  await expect(paciente.getByText("Cancelado", { exact: true })).toBeVisible();
  await expect(paciente.getByRole("link", { name: "Reservar un turno nuevo" })).toBeVisible();
});

test("el paciente cambia el horario y ve el turno en el horario nuevo", async ({ browser }) => {
  const estado = readState();
  const ruta = await reservar(`Paciente Gestion E2E ${estado.run} Tres`, "15:00");
  const paciente = await celular(browser);

  await paciente.goto(ruta);
  await paciente.getByRole("button", { name: "Cambiar horario" }).click();
  await paciente.getByRole("button", { name: etiquetaDia(DIAS_ADELANTE) }).click();
  await expect(paciente.getByRole("button", { name: "15:00 (horario actual)" })).toBeDisabled();
  await paciente.getByRole("button", { name: "16:00", exact: true }).click();
  await aptoParaCelular(paciente);
  await paciente.getByRole("button", { name: "Confirmar 16:00" }).click();

  await expect(
    paciente.getByRole("heading", { name: `${etiquetaDia(DIAS_ADELANTE)} · 16:00` })
  ).toBeVisible();
});

test("un link inválido muestra la pantalla de contacto sin datos ni acciones", async ({ browser }) => {
  const paciente = await celular(browser);

  await paciente.goto(`/g/${"x".repeat(43)}`);

  await expect(paciente.getByRole("heading", { name: "Este link ya no está disponible" })).toBeVisible();
  await expect(paciente.getByRole("main").getByRole("button")).toHaveCount(0);
});
