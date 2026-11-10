import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import WaitlistOfferPage from "../../pages/WaitlistOfferPage";
import { NowProvider } from "../../shared/time/now";
import { server } from "../../test/server";
import type { OfferView } from "./OfferPage";

const AHORA = new Date("2030-01-07T11:00:00Z");
const TOKEN = "w1.token-ficticio-de-oferta-0123456789abcdefghijkl";
const URL = `/api/waitlist-offer/${TOKEN}`;

function vista(overrides: Partial<OfferView> = {}): OfferView {
  return {
    clinic_name: "Clínica Ficticia",
    clinic_phone: "+5491155550100",
    timezone: "America/Argentina/Buenos_Aires",
    booking_url: "http://localhost:5174/b/clinica-ficticia",
    patient_first_name: "Valentina",
    professional_name: "Dra. Ficticia Uno",
    starts_at: "2030-01-09T13:00:00Z",
    ends_at: "2030-01-09T13:30:00Z",
    expires_at: "2030-01-07T15:30:00Z",
    status: "pending",
    appointment: null,
    ...overrides
  };
}

function abrir(): ReturnType<typeof userEvent.setup> {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NowProvider clock={() => AHORA}>
        <MemoryRouter initialEntries={[`/o/${TOKEN}`]}>
          <Routes>
            <Route path="/o/:token" element={<WaitlistOfferPage />} />
          </Routes>
        </MemoryRouter>
      </NowProvider>
    </QueryClientProvider>
  );
  return userEvent.setup();
}

describe("OfferPage", () => {
  it("muestra el hueco, el vencimiento y los tres botones", async () => {
    server.use(http.get(URL, () => HttpResponse.json(vista())));
    abrir();

    expect(await screen.findByText("mié 09/01 a las 10:00")).toBeInTheDocument();
    expect(screen.getByText("con Dra. Ficticia Uno")).toBeInTheDocument();
    expect(screen.getByText("Tenés hasta las 12:30 para tomarlo.")).toBeInTheDocument();
    for (const nombre of ["Tomar el turno", "No me sirve", "No me sirve y salir de la lista"]) {
      expect(screen.getByRole("button", { name: nombre })).toBeInTheDocument();
    }
  });

  it("vencida no ofrece acciones y muestra el teléfono", async () => {
    server.use(http.get(URL, () => HttpResponse.json(vista({ status: "expired" }))));
    abrir();

    expect(await screen.findByText(/venció/)).toBeInTheDocument();
    expect(screen.getByText(/\+5491155550100/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tomar el turno" })).not.toBeInTheDocument();
  });

  it("aceptar muestra el turno confirmado con su link de gestión", async () => {
    server.use(
      http.get(URL, () => HttpResponse.json(vista())),
      http.post(`${URL}/accept`, () =>
        HttpResponse.json(
          vista({
            status: "accepted",
            appointment: {
              starts_at: "2030-01-09T13:00:00Z",
              ends_at: "2030-01-09T13:30:00Z",
              manage_url: "http://localhost:5174/g/v1.token-ficticio"
            }
          })
        )
      )
    );
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: "Tomar el turno" }));

    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("Turno confirmado");
    expect(screen.getByRole("link", { name: "Ver o cambiar mi turno" })).toHaveAttribute(
      "href",
      "http://localhost:5174/g/v1.token-ficticio"
    );
  });

  it("doble toque manda una sola request", async () => {
    let pedidos = 0;
    server.use(
      http.get(URL, () => HttpResponse.json(vista())),
      http.post(`${URL}/accept`, async () => {
        pedidos += 1;
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(vista({ status: "accepted", appointment: null }));
      })
    );
    const user = abrir();
    const boton = await screen.findByRole("button", { name: "Tomar el turno" });

    await Promise.all([user.click(boton), user.click(boton)]);

    await waitFor(() => expect(pedidos).toBe(1));
  });

  it("rechazar y salir de la lista lo confirma", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.get(URL, () => HttpResponse.json(vista())),
      http.post(`${URL}/decline`, async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(vista({ status: "declined" }));
      })
    );
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: "No me sirve y salir de la lista" }));

    expect(await screen.findByText(/Saliste de la lista de espera/)).toBeInTheDocument();
    expect(cuerpos).toEqual([{ leave_list: true }]);
  });

  it("hueco ocupado muestra alternativos y el acceso a reservar", async () => {
    server.use(
      http.get(URL, () => HttpResponse.json(vista())),
      http.post(`${URL}/accept`, () =>
        HttpResponse.json(
          {
            detail: "slot_taken",
            alternatives: [
              { starts_at: "2030-01-09T13:30:00Z", ends_at: "2030-01-09T14:00:00Z" },
              { starts_at: "2030-01-09T14:00:00Z", ends_at: "2030-01-09T14:30:00Z" }
            ]
          },
          { status: 409 }
        )
      )
    );
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: "Tomar el turno" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Ese turno ya lo tomó otra persona");
    expect(alerta).toHaveTextContent("mié 09/01 a las 10:30");
    expect(alerta).toHaveTextContent("mié 09/01 a las 11:00");
    expect(screen.getByRole("link", { name: "Reservar otro horario online" })).toHaveAttribute(
      "href",
      "http://localhost:5174/b/clinica-ficticia"
    );
  });

  it.each([
    ["offer_expired", 409, "La oferta ya venció."],
    ["patient_busy", 409, "Ya tenés otro turno a esa hora"],
    ["rate_limited", 429, "Hiciste muchos intentos seguidos"]
  ])("error %s tiene su mensaje", async (detail, status, texto) => {
    server.use(
      http.get(URL, () => HttpResponse.json(vista())),
      http.post(`${URL}/accept`, () => HttpResponse.json({ detail }, { status }))
    );
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: "Tomar el turno" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(texto);
  });

  it("link inválido y error de red", async () => {
    server.use(http.get(URL, () => HttpResponse.json({ detail: "offer_not_found" }, { status: 404 })));
    abrir();

    expect(await screen.findByRole("alert")).toHaveTextContent("El link no es válido o ya venció");
  });

  it("no guarda nada en el navegador", async () => {
    server.use(
      http.get(URL, () => HttpResponse.json(vista())),
      http.post(`${URL}/accept`, () => HttpResponse.json(vista({ status: "accepted" })))
    );
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: "Tomar el turno" }));
    await screen.findByText("mié 09/01 a las 10:00");

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});
