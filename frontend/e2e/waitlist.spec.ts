/**
 * Circuito crítico de C-12 contra el stack real (regla 9): recepción anota a un paciente en la
 * lista de espera, un turno compatible se cancela, la oferta aparece en el panel y el paciente la
 * toma desde su link en un celular de 360 px; el turno `waitlist` queda confirmado en la agenda.
 *
 * El link de la oferta viaja por WhatsApp/email: el E2E lo arma con la misma firma que el servidor
 * (`w1.` + HMAC-SHA256 con `MANAGE_LINK_SECRET`), por eso necesita `E2E_MANAGE_LINK_SECRET` igual al
 * secreto del stack. Datos sintéticos (regla 13).
 */
import { createHmac } from "node:crypto";
import { expect, request, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { clinicSlug, e2eEnv, readState } from "./env";

const VIEWPORT = { width: 360, height: 740 };
const DIAS_ADELANTE = 3; // fuera de la ventana de cancelación y de los otros E2E

const pad = (n: number): string => String(n).padStart(2, "0");

function instante(dias: number, hora: string): string {
  const d = new Date(Date.now() - 3 * 3_600_000 + dias * 86_400_000);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${hora}:00-03:00`;
}

/** Misma credencial que `app/modules/waiting_list/links.py`. */
function offerToken(secret: string, offerId: string): string {
  const id = Buffer.from(offerId.replace(/-/g, ""), "hex");
  const mac = createHmac("sha256", secret)
    .update(Buffer.concat([Buffer.from("waitlist-offer/v1"), id]))
    .digest()
    .subarray(0, 16);
  return `w1.${Buffer.concat([id, mac]).toString("base64url")}`;
}

function secretoDeLinks(): string {
  const valor = process.env.E2E_MANAGE_LINK_SECRET;
  if (valor === undefined || valor === "") {
    throw new Error("Falta E2E_MANAGE_LINK_SECRET (igual a MANAGE_LINK_SECRET del stack)");
  }
  return valor;
}

async function apiStaff(): Promise<{ api: APIRequestContext; headers: Record<string, string> }> {
  const E2E = e2eEnv();
  const api = await request.newContext({ baseURL: E2E.baseURL });
  const login = await api.post("/api/auth/login", {
    data: { email: E2E.adminEmail, password: E2E.password }
  });
  expect(login.ok()).toBe(true);
  const { access_token: token } = (await login.json()) as { access_token: string };
  return { api, headers: { Authorization: `Bearer ${token}` } };
}

async function celular(browser: Browser): Promise<Page> {
  const contexto = await browser.newContext({ viewport: VIEWPORT, timezoneId: "UTC", locale: "es-AR" });
  return contexto.newPage();
}

test("la lista de espera llena un hueco cancelado de punta a punta", async ({ browser }) => {
  const estado = readState();
  const E2E = e2eEnv();
  const { api, headers } = await apiStaff();
  const espera = `Paciente Espera E2E ${estado.run}`;

  // Paciente que va a esperar (alta rápida del personal, con opt-in de WhatsApp).
  const alta = await api.post("/api/patients", {
    headers,
    data: {
      full_name: espera,
      phone: `011 15 5555-${String(Math.floor(Math.random() * 10_000)).padStart(4, "0")}`,
      whatsapp_opt_in: true
    }
  });
  expect(alta.ok()).toBe(true);

  // Turno de otra persona que se va a cancelar (reserva pública).
  const catalogo = (await (await api.get(`/api/booking/${clinicSlug()}`)).json()) as {
    professionals: { id: string; display_name: string }[];
  };
  const profesional = catalogo.professionals.find((p) => p.display_name === estado.professional);
  if (profesional === undefined) {
    throw new Error("el profesional del E2E no es reservable");
  }
  const reserva = await api.post(`/api/booking/${clinicSlug()}/appointments`, {
    data: {
      professional_id: profesional.id,
      starts_at: instante(DIAS_ADELANTE, "11:00"),
      patient: {
        full_name: `Titular Espera E2E ${estado.run}`,
        phone: `011 15 5555-${String(Math.floor(Math.random() * 10_000)).padStart(4, "0")}`,
        whatsapp_opt_in: true,
        privacy_accepted: true
      }
    }
  });
  expect(reserva.ok()).toBe(true);
  const { manage_url: gestion } = (await reserva.json()) as { manage_url: string };

  // 1. Recepción anota al paciente desde el panel.
  const recepcion = await (await browser.newContext({ timezoneId: "UTC", locale: "es-AR" })).newPage();
  await recepcion.goto("/login");
  await recepcion.getByLabel("Email").fill(E2E.adminEmail);
  await recepcion.getByLabel("Contraseña", { exact: true }).fill(E2E.password);
  await recepcion.getByRole("button", { name: "Ingresar" }).click();
  await recepcion.getByRole("link", { name: "Lista de espera" }).click();
  await recepcion.getByRole("button", { name: "Anotar paciente" }).click();
  const dialogo = recepcion.getByRole("dialog");
  await dialogo.getByLabel("Buscar paciente").fill(espera);
  await dialogo.getByRole("button", { name: `Elegir ${espera}` }).click();
  await dialogo.getByLabel("Profesional").selectOption({ label: estado.professional });
  await dialogo.getByRole("button", { name: "Anotar" }).click();
  await expect(recepcion.getByRole("list", { name: "Cola" }).getByText(espera)).toBeVisible();

  // 2. El titular cancela con su link: la oferta nace en esa misma transacción.
  const token = new URL(gestion).pathname.split("/").pop() ?? "";
  const cancelacion = await api.patch(`/api/manage/${token}`, { data: { action: "cancel" } });
  expect(cancelacion.ok()).toBe(true);

  // 3. La oferta aparece en el panel sin recargar.
  await expect(
    recepcion.getByRole("region", { name: "Ofertas" }).getByText(new RegExp(espera))
  ).toBeVisible({ timeout: 40_000 });

  // 4. El paciente abre su link en el celular y toma el turno.
  const ofertas = (await (
    await api.get("/api/waiting-list/offers", { headers, params: { status: "pending" } })
  ).json()) as { items: { id: string; entry_id: string }[] };
  const oferta = ofertas.items[0];
  expect(oferta).toBeDefined();
  const paciente = await celular(browser);
  await paciente.goto(`/o/${offerToken(secretoDeLinks(), oferta?.id ?? "")}`);
  await expect(paciente.getByText(/Tenés hasta las/)).toBeVisible();
  const cabe = await paciente.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
  );
  expect(cabe, "la página no debe desbordar a 360 px").toBe(true);
  for (const altura of await paciente
    .getByRole("main")
    .getByRole("button")
    .evaluateAll((botones) => botones.map((b) => b.getBoundingClientRect().height))) {
    expect(altura).toBeGreaterThanOrEqual(44);
  }
  await paciente.getByRole("button", { name: "Tomar el turno" }).click();
  await expect(paciente.getByText("Turno confirmado")).toBeVisible();
  expect(await paciente.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);

  // 5. El turno `waitlist` queda confirmado en la agenda de recepción.
  await recepcion.getByRole("link", { name: "Agenda" }).click();
  for (let dia = 0; dia < DIAS_ADELANTE; dia += 1) {
    await recepcion.getByRole("button", { name: "Siguiente" }).click();
  }
  await recepcion.getByLabel("Profesional").selectOption({ label: estado.professional });
  await expect(
    recepcion.getByRole("button", { name: new RegExp(`11:00 ${espera} · Confirmado`) })
  ).toBeVisible({ timeout: 40_000 });
  await api.dispose();
});
