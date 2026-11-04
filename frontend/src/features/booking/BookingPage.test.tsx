import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import BookingPage from "../../pages/BookingPage";
import {
  LUN_10,
  PROF_1,
  PROF_2,
  SLUG,
  bookingHandlers,
  catalog,
  result
} from "../../test/bookingFixtures";
import { server } from "../../test/server";
import { NowProvider } from "../../shared/time/now";
import type { BookingRequest } from "./types";

// Lunes 2030-01-07 08:00 en Buenos Aires; el navegador de los tests está en UTC.
const AHORA = new Date("2030-01-07T11:00:00Z");

function abrir(): ReturnType<typeof userEvent.setup> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } }
  });
  render(
    <QueryClientProvider client={queryClient}>
      <NowProvider clock={() => AHORA}>
        <MemoryRouter initialEntries={[`/b/${SLUG}`]}>
          <Routes>
            <Route path="/b/:slug" element={<BookingPage />} />
          </Routes>
        </MemoryRouter>
      </NowProvider>
    </QueryClientProvider>
  );
  return userEvent.setup();
}

type Usuario = ReturnType<typeof userEvent.setup>;

async function hastaElContacto(user: Usuario): Promise<void> {
  await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
  await user.click(await screen.findByRole("button", { name: "lun 07/01" }));
  await user.click(await screen.findByRole("button", { name: "10:00" }));
  await screen.findByRole("heading", { name: "Tus datos" });
}

async function completar(user: Usuario, extra: { phone?: string; email?: string } = {}): Promise<void> {
  await user.type(screen.getByLabelText("Nombre y apellido"), "Lucía Inventada Ficticia");
  if (extra.phone !== undefined) {
    await user.type(screen.getByLabelText("Teléfono"), extra.phone);
  }
  if (extra.email !== undefined) {
    await user.type(screen.getByLabelText("Email"), extra.email);
  }
  await user.click(screen.getByLabelText(/Acepto la política de privacidad/));
}

describe("BookingPage — flujo", () => {
  it("catálogo → día → hora → datos → confirmación en 4 pasos", async () => {
    server.use(...bookingHandlers());
    let enviado: BookingRequest | null = null;
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, async ({ request }) => {
        enviado = (await request.json()) as BookingRequest;
        return HttpResponse.json(result(), { status: 201 });
      })
    );
    const user = abrir();
    const pasos: string[] = [];

    await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
    pasos.push((await screen.findByRole("heading", { level: 2 })).textContent ?? "");
    await user.click(await screen.findByRole("button", { name: "lun 07/01" }));
    pasos.push((await screen.findByRole("heading", { level: 2 })).textContent ?? "");
    await user.click(await screen.findByRole("button", { name: "10:00" }));
    pasos.push((await screen.findByRole("heading", { level: 2 })).textContent ?? "");
    await completar(user, { phone: "011 15 5555-0123" });
    await user.click(screen.getByLabelText(/recordatorios por WhatsApp/));
    await user.click(screen.getByRole("button", { name: "Confirmar turno" }));

    expect(await screen.findByRole("heading", { name: "Turno reservado" })).toBeInTheDocument();
    expect(pasos).toEqual(["Elegí el día", "Elegí el horario", "Tus datos"]);
    expect(enviado).toEqual({
      professional_id: PROF_1.id,
      starts_at: LUN_10.starts_at,
      patient: {
        full_name: "Lucía Inventada Ficticia",
        phone: "011 15 5555-0123",
        whatsapp_opt_in: true,
        privacy_accepted: true
      }
    });
  });

  it("con un solo profesional se saltea el primer paso", async () => {
    server.use(...bookingHandlers({ catalog: catalog({ professionals: [PROF_2] }) }));
    abrir();

    expect(await screen.findByRole("heading", { name: "Elegí el día" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Elegí profesional" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Volver" })).not.toBeInTheDocument();
  });

  it("muestra los horarios en la zona de la clínica aunque el navegador esté en UTC", async () => {
    server.use(...bookingHandlers());
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
    await user.click(await screen.findByRole("button", { name: "lun 07/01" }));

    expect(await screen.findByRole("button", { name: "10:00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "10:30" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "13:00" })).not.toBeInTheDocument();
  });

  it("volver atrás conserva la selección", async () => {
    server.use(...bookingHandlers());
    const user = abrir();
    await hastaElContacto(user);

    await user.click(screen.getByRole("button", { name: "Volver" }));
    expect(await screen.findByRole("button", { name: "10:00", pressed: true })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Volver" }));
    expect(await screen.findByRole("button", { name: "lun 07/01", pressed: true })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Volver" }));
    expect(
      await screen.findByRole("button", { name: PROF_1.display_name, pressed: true })
    ).toBeInTheDocument();
  });

  it("la casilla de WhatsApp aparece sin marcar solo al escribir un teléfono", async () => {
    server.use(...bookingHandlers());
    const user = abrir();
    await hastaElContacto(user);

    expect(screen.queryByLabelText(/recordatorios por WhatsApp/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Teléfono"), "011 15 5555-0123");

    const casilla = screen.getByLabelText(/recordatorios por WhatsApp/);
    expect(casilla).toBeInTheDocument();
    expect(casilla).not.toBeChecked();
  });

  it("no envía sin contacto ni privacidad y lo explica", async () => {
    server.use(...bookingHandlers());
    let pedidos = 0;
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () => {
        pedidos += 1;
        return HttpResponse.json(result(), { status: 201 });
      })
    );
    const user = abrir();
    await hastaElContacto(user);
    await user.type(screen.getByLabelText("Nombre y apellido"), "Lucía Inventada Ficticia");

    await user.click(screen.getByRole("button", { name: "Confirmar turno" }));

    expect(screen.getByText("Dejanos un teléfono o un email para avisarte")).toBeInTheDocument();
    expect(screen.getByText("Tenés que aceptar la política de privacidad")).toBeInTheDocument();
    expect(screen.getByLabelText("Teléfono")).toHaveAttribute("aria-invalid", "true");
    expect(pedidos).toBe(0);
  });

  it("teléfono sin WhatsApp y sin email: pide elegir, sin enviar", async () => {
    server.use(...bookingHandlers());
    let pedidos = 0;
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () => {
        pedidos += 1;
        return HttpResponse.json(result(), { status: 201 });
      })
    );
    const user = abrir();
    await hastaElContacto(user);
    await completar(user, { phone: "011 15 5555-0123" });

    await user.click(screen.getByRole("button", { name: "Confirmar turno" }));

    expect(
      screen.getByText("Para usar tu teléfono aceptá los avisos por WhatsApp o dejanos un email")
    ).toBeInTheDocument();
    expect(pedidos).toBe(0);
  });

  it("solo email: envía sin teléfono ni opt-in", async () => {
    server.use(...bookingHandlers());
    let enviado: BookingRequest | null = null;
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, async ({ request }) => {
        enviado = (await request.json()) as BookingRequest;
        return HttpResponse.json(result({ channel: "email" }), { status: 201 });
      })
    );
    const user = abrir();
    await hastaElContacto(user);
    await completar(user, { email: "lucia.inventada@example.com" });

    await user.click(screen.getByRole("button", { name: "Confirmar turno" }));

    await screen.findByRole("heading", { name: "Turno reservado" });
    expect(enviado).toEqual({
      professional_id: PROF_1.id,
      starts_at: LUN_10.starts_at,
      patient: {
        full_name: "Lucía Inventada Ficticia",
        email: "lucia.inventada@example.com",
        privacy_accepted: true
      }
    });
  });

  it("navega entre ventanas de 14 días", async () => {
    server.use(...bookingHandlers());
    const user = abrir();
    await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
    await screen.findByRole("button", { name: "lun 07/01" });

    await user.click(screen.getByRole("button", { name: "Ver más días" }));

    expect(await screen.findByText("No hay horarios libres en estos días")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ver días anteriores" }));
    expect(await screen.findByRole("button", { name: "lun 07/01" })).toBeInTheDocument();
  });

  it("pide la disponibilidad anónima: sin cookies y por rango de 14 días de la clínica", async () => {
    let credenciales = "";
    let consulta = "";
    server.use(
      http.get(`/api/booking/${SLUG}/availability`, ({ request }) => {
        // La primera es la ventana visible; las siguientes son prefetch.
        if (consulta === "") {
          credenciales = request.credentials;
          consulta = decodeURIComponent(new URL(request.url).search);
        }
        return HttpResponse.json({ timezone: "America/Argentina/Buenos_Aires", slots: [] });
      }),
      ...bookingHandlers()
    );
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));

    await waitFor(() => expect(consulta).not.toBe(""));
    expect(credenciales).toBe("omit");
    expect(consulta).toContain("professional_id=prof-1");
    expect(consulta).toContain("from=2030-01-07T03:00:00.000Z");
    expect(consulta).toContain("to=2030-01-21T03:00:00.000Z");
  });

  it("muestra los pasos de forma accesible y el nombre de la clínica", async () => {
    server.use(...bookingHandlers());
    abrir();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Clínica Demo Ficticia" })
    ).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByText("Paso 1 de 4")).toBeInTheDocument();
  });
});
