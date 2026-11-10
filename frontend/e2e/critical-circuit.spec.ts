/**
 * Circuito crítico del piloto (C-14, D12) contra el stack real (regla 9):
 *
 *   reserva online → recordatorio enviado → confirmación del paciente → recepción marca Presente
 *
 * 1. El paciente reserva por `/b/:slug` en un celular de 360 px un horario de HOY (la asistencia
 *    solo se registra desde el día del turno). Si en el día local de la clínica ya no quedan
 *    horarios con margen, el test se salta con el motivo.
 * 2. El worker (con `REMINDER_WHATSAPP_PROVIDER=fake`) envía el paso `created`; se verifica en el
 *    timeline del turno por la API y en el detalle de la agenda.
 * 3. El paciente confirma desde su link `/g/:token`.
 * 4. Recepción ve el turno "Confirmado" y registra "Presente".
 *
 * Datos sintéticos (regla 13). Variables: frontend/README.md §E2E.
 */
import { expect, request, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { clinicSlug, e2eEnv, readState } from "./env";

const VIEWPORT = { width: 360, height: 740 };
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MARGEN_MIN = 120; // lejos de los alternativos "próximos" que usa agenda.spec.ts
const ENVIADO = /^(sent|delivered|read)$/;

const pad = (n: number): string => String(n).padStart(2, "0");

/** Buenos Aires no tiene horario de verano: UTC-3 fijo (igual que los otros E2E). */
function ahoraLocal(): Date {
  return new Date(Date.now() - 3 * 3_600_000);
}

function etiquetaHoy(): string {
  const d = ahoraLocal();
  return `${DIAS[d.getUTCDay()] ?? ""} ${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}`;
}

function minutos(hhmm: string): number {
  const [h = "0", m = "0"] = hhmm.split(":");
  return Number(h) * 60 + Number(m);
}

async function staffApi(): Promise<{ api: APIRequestContext; headers: Record<string, string> }> {
  const E2E = e2eEnv();
  const api = await request.newContext({ baseURL: E2E.baseURL });
  const login = await api.post("/api/auth/login", { data: { email: E2E.adminEmail, password: E2E.password } });
  expect(login.ok()).toBe(true);
  const { access_token: token } = (await login.json()) as { access_token: string };
  return { api, headers: { Authorization: `Bearer ${token}` } };
}

async function celular(browser: Browser): Promise<Page> {
  const contexto = await browser.newContext({ viewport: VIEWPORT, timezoneId: "UTC", locale: "es-AR" });
  return contexto.newPage();
}

interface TurnoApi {
  id: string;
  status: string;
  starts_at: string;
  origin: string;
  patient: { full_name: string };
}

async function turnoDe(api: APIRequestContext, headers: Record<string, string>, nombre: string): Promise<TurnoApi> {
  const desde = new Date(Date.now() - 12 * 3_600_000).toISOString();
  const hasta = new Date(Date.now() + 36 * 3_600_000).toISOString();
  const respuesta = await api.get("/api/appointments", { headers, params: { from: desde, to: hasta, limit: 500 } });
  expect(respuesta.ok()).toBe(true);
  const { items } = (await respuesta.json()) as { items: TurnoApi[] };
  const turno = items.find((t) => t.patient.full_name === nombre);
  if (turno === undefined) {
    throw new Error("el turno reservado no aparece en la agenda");
  }
  return turno;
}

test("reserva online → recordatorio → confirmación → presente", async ({ browser }) => {
  const estado = readState();
  const E2E = e2eEnv();
  const { api, headers } = await staffApi();
  const nombre = `Paciente Circuito E2E ${estado.run}`;

  // --- 1. Reserva pública en mobile, hoy, con margen.
  const paciente = await celular(browser);
  await paciente.goto(`/b/${clinicSlug()}`);
  await paciente.getByRole("button", { name: estado.professional }).click();
  const hoy = paciente.getByRole("button", { name: etiquetaHoy() });
  test.skip((await hoy.count()) === 0, "sin horarios hoy en el día local de la clínica");
  await hoy.click();
  await expect(paciente.getByRole("heading", { level: 2, name: "Elegí el horario" })).toBeVisible();
  const objetivo = minutos(`${pad(ahoraLocal().getUTCHours())}:${pad(ahoraLocal().getUTCMinutes())}`) + MARGEN_MIN;
  const horas = (await paciente.getByRole("button", { name: /^\d{2}:\d{2}$/ }).allTextContents()).map((h) => h.trim());
  const hora = horas.find((h) => minutos(h) >= objetivo);
  test.skip(hora === undefined, `no quedan horarios hoy después de ${MARGEN_MIN} min`);
  await paciente.getByRole("button", { name: hora ?? "", exact: true }).click();
  await paciente.getByLabel("Nombre y apellido").fill(nombre);
  await paciente.getByLabel("Teléfono").fill(`011 15 5555-${String(Math.floor(Math.random() * 10_000)).padStart(4, "0")}`);
  await paciente.getByLabel(/recordatorios por WhatsApp/).check();
  await paciente.getByLabel(/Acepto la política de privacidad/).check();
  await paciente.getByRole("button", { name: "Confirmar turno" }).click();
  await expect(paciente.getByRole("heading", { name: "Turno reservado" })).toBeVisible();
  const link = await paciente.getByLabel("Link para gestionar tu turno").inputValue();
  const ruta = new URL(link).pathname;
  expect(ruta).toMatch(/^\/g\/[A-Za-z0-9_-]{43,}$/);

  const turno = await turnoDe(api, headers, nombre);
  expect(turno).toMatchObject({ status: "pending", origin: "online" });

  // --- 2. El worker envía el recordatorio de alta (proveedor `fake` en el stack del E2E).
  await expect
    .poll(
      async () => {
        const r = await api.get(`/api/appointments/${turno.id}/reminders`, { headers });
        if (!r.ok()) {
          return `http_${r.status()}`;
        }
        const timeline = (await r.json()) as { steps: { step: string; status: string }[] };
        return timeline.steps.find((s) => s.step === "created")?.status ?? "sin_paso";
      },
      { timeout: 90_000, intervals: [2_000, 5_000] }
    )
    .toMatch(ENVIADO);

  // --- 3. El paciente confirma desde su link.
  await paciente.goto(ruta);
  await paciente.getByRole("button", { name: "Confirmar turno" }).click();
  await expect(paciente.getByText("Confirmado", { exact: true })).toBeVisible();
  expect((await turnoDe(api, headers, nombre)).status).toBe("confirmed");

  // --- 4. Recepción lo ve confirmado (sin recargar: refresco de la agenda) y marca Presente.
  const recepcion = await (await browser.newContext({ timezoneId: "UTC", locale: "es-AR" })).newPage();
  await recepcion.goto("/login");
  await recepcion.getByLabel("Email").fill(E2E.adminEmail);
  await recepcion.getByLabel("Contraseña", { exact: true }).fill(E2E.password);
  await recepcion.getByRole("button", { name: "Ingresar" }).click();
  await expect(recepcion.getByRole("button", { name: "Nuevo turno" })).toBeVisible();
  await recepcion.getByLabel("Profesional").selectOption({ label: estado.professional });
  const confirmado = recepcion.getByRole("button", { name: `${hora} ${nombre} · Confirmado` });
  await expect(confirmado).toBeVisible({ timeout: 45_000 });
  await confirmado.click();
  const detalle = recepcion.getByRole("dialog");
  await expect(detalle.getByText("Reserva online")).toBeVisible();
  // El timeline del detalle muestra el recordatorio de alta enviado (C-11).
  await expect(detalle.getByRole("region", { name: /recordatorios/i })).toBeVisible();
  await detalle.getByRole("button", { name: "Presente" }).click();
  await expect(recepcion.getByRole("button", { name: `${hora} ${nombre} · Presente` })).toBeVisible();
  expect((await turnoDe(api, headers, nombre)).status).toBe("present");

  // Sin datos del paciente guardados en el navegador de recepción (regla 13, SU-06).
  const guardado = await recepcion.evaluate(() =>
    Object.keys(localStorage).filter((k) => /turno|paciente|agenda/i.test(k)).length
  );
  expect(guardado).toBe(0);
  await api.dispose();
});

test("la agenda del día imprimible lista el circuito y no guarda datos", async ({ browser }) => {
  const E2E = e2eEnv();
  const page = await (await browser.newContext({ timezoneId: "UTC", locale: "es-AR" })).newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(E2E.adminEmail);
  await page.getByLabel("Contraseña", { exact: true }).fill(E2E.password);
  await page.getByRole("button", { name: "Ingresar" }).click();
  await page.getByRole("link", { name: "Imprimir agenda del día" }).click();

  await expect(page.getByRole("heading", { name: /^Agenda del / })).toBeVisible();
  await expect(page.getByRole("button", { name: "Imprimir" })).toBeVisible();
  // El marco de la app no sale en papel.
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("navigation", { name: "Secciones" })).toBeHidden();
});
