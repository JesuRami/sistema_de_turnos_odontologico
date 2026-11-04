import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import BookingPage from "../../pages/BookingPage";
import {
  LUN_10,
  LUN_1030,
  PROF_1,
  SLUG,
  bookingHandlers,
  result
} from "../../test/bookingFixtures";
import { server } from "../../test/server";
import { NowProvider } from "../../shared/time/now";
import type { BookingRequest } from "./types";

const AHORA = new Date("2030-01-07T11:00:00Z");

type Usuario = ReturnType<typeof userEvent.setup>;

function abrir(): Usuario {
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

async function reservar(
  user: Usuario,
  contacto: { phone?: string; email?: string; whatsapp?: boolean } = { phone: "011 15 5555-0123", whatsapp: true }
): Promise<void> {
  await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
  await user.click(await screen.findByRole("button", { name: "lun 07/01" }));
  await user.click(await screen.findByRole("button", { name: "10:00" }));
  await user.type(await screen.findByLabelText("Nombre y apellido"), "Lucía Inventada Ficticia");
  if (contacto.phone !== undefined) {
    await user.type(screen.getByLabelText("Teléfono"), contacto.phone);
    if (contacto.whatsapp === true) {
      await user.click(screen.getByLabelText(/recordatorios por WhatsApp/));
    }
  }
  if (contacto.email !== undefined) {
    await user.type(screen.getByLabelText("Email"), contacto.email);
  }
  await user.click(screen.getByLabelText(/Acepto la política de privacidad/));
  await user.click(screen.getByRole("button", { name: "Confirmar turno" }));
}

describe("BookingPage — errores y confirmación", () => {
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("409: muestra los alternativos y elegir uno reenvía con los mismos datos", async () => {
    server.use(...bookingHandlers());
    const enviados: BookingRequest[] = [];
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, async ({ request }) => {
        const cuerpo = (await request.json()) as BookingRequest;
        enviados.push(cuerpo);
        if (enviados.length === 1) {
          return HttpResponse.json(
            { detail: "slot_taken", alternatives: [LUN_1030] },
            { status: 409 }
          );
        }
        return HttpResponse.json(
          result({ starts_at: LUN_1030.starts_at, ends_at: LUN_1030.ends_at }),
          { status: 201 }
        );
      })
    );
    const user = abrir();
    await reservar(user);

    expect(await screen.findByText("Ese horario se acaba de ocupar")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reservar lun 07/01 10:30" }));

    expect(await screen.findByRole("heading", { name: "Turno reservado" })).toBeInTheDocument();
    expect(enviados).toHaveLength(2);
    expect(enviados[1]?.starts_at).toBe(LUN_1030.starts_at);
    expect(enviados[1]?.patient).toEqual(enviados[0]?.patient);
    expect(enviados[1]?.professional_id).toBe(enviados[0]?.professional_id);
    expect(screen.getByText(/10:30/)).toBeInTheDocument();
  });

  it("409 sin alternativos ofrece volver a elegir horario", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json({ detail: "slot_taken", alternatives: [] }, { status: 409 })
      )
    );
    const user = abrir();
    await reservar(user);

    expect(await screen.findByText("Ese horario se acaba de ocupar")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Elegir otro horario" }));

    expect(await screen.findByRole("heading", { name: "Elegí el horario" })).toBeInTheDocument();
  });

  it("422 marca el campo del error", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json({ detail: "contact_required" }, { status: 422 })
      )
    );
    const user = abrir();
    await reservar(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Revisá tu teléfono o tu email");
    expect(screen.getByLabelText("Teléfono")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("422 de opt-in marca el teléfono y la casilla de WhatsApp", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json({ detail: "whatsapp_opt_in_required" }, { status: 422 })
      )
    );
    const user = abrir();
    await reservar(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("WhatsApp");
    expect(screen.getByLabelText(/recordatorios por WhatsApp/)).toHaveAttribute("aria-invalid", "true");
  });

  it("422 de privacidad marca la casilla de privacidad", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json({ detail: "privacy_consent_required" }, { status: 422 })
      )
    );
    const user = abrir();
    await reservar(user);

    await screen.findByRole("alert");
    expect(screen.getByLabelText(/Acepto la política de privacidad/)).toHaveAttribute(
      "aria-invalid",
      "true"
    );
  });

  it("429 con Retry-After: 600 dice 10 minutos", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json(
          { detail: "rate_limited" },
          { status: 429, headers: { "Retry-After": "600" } }
        )
      )
    );
    const user = abrir();
    await reservar(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Probá de nuevo en 10 minutos");
  });

  it("404 del catálogo informa que el link no está disponible", async () => {
    server.use(
      http.get(`/api/booking/${SLUG}`, () =>
        HttpResponse.json({ detail: "booking_not_found" }, { status: 404 })
      )
    );
    abrir();

    expect(await screen.findByRole("alert")).toHaveTextContent("Este link de reserva no está disponible");
  });

  it("503 informa que el servicio no está disponible sin culpar al paciente", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json({ detail: "booking_unavailable" }, { status: 503 })
      )
    );
    const user = abrir();
    await reservar(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("no está disponible en este momento");
  });

  it("aviso de teléfono inválido con email en la confirmación", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () =>
        HttpResponse.json(
          result({ channel: "email", warnings: ["phone_invalid_email_channel"] }),
          { status: 201 }
        )
      )
    );
    const user = abrir();
    await reservar(user, { phone: "12ab", email: "lucia.inventada@example.com" });

    expect(await screen.findByRole("heading", { name: "Turno reservado" })).toBeInTheDocument();
    expect(screen.getByText(/no pudimos usar tu teléfono/i)).toBeInTheDocument();
    expect(screen.getByText(/por email/i)).toBeInTheDocument();
  });

  it("la confirmación muestra el link de gestión, lo copia y no deja datos en el navegador", async () => {
    server.use(...bookingHandlers());
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, () => HttpResponse.json(result(), { status: 201 }))
    );
    const user = abrir();
    const escribir = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: escribir },
      configurable: true
    });
    await reservar(user);

    expect(await screen.findByRole("heading", { name: "Turno reservado" })).toBeInTheDocument();
    expect(screen.getByLabelText("Link para gestionar tu turno")).toHaveValue(result().manage_url);
    expect(screen.getByText(/lun 07\/01 · 10:00/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copiar link" }));

    expect(escribir).toHaveBeenCalledWith(result().manage_url);
    expect(await screen.findByRole("status")).toHaveTextContent("Link copiado");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("reservar el 10:00 pide el horario elegido", async () => {
    server.use(...bookingHandlers());
    let enviado: BookingRequest | null = null;
    server.use(
      http.post(`/api/booking/${SLUG}/appointments`, async ({ request }) => {
        enviado = (await request.json()) as BookingRequest;
        return HttpResponse.json(result(), { status: 201 });
      })
    );
    const user = abrir();
    await reservar(user);

    await screen.findByRole("heading", { name: "Turno reservado" });
    expect((enviado as BookingRequest | null)?.starts_at).toBe(LUN_10.starts_at);
  });
});
