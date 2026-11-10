import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import BookingPage from "../../pages/BookingPage";
import { NowProvider } from "../../shared/time/now";
import { PROF_1, SLUG, bookingHandlers } from "../../test/bookingFixtures";
import { server } from "../../test/server";
import type { WaitlistJoined } from "./types";

const AHORA = new Date("2030-01-07T11:00:00Z");
const URL = `/api/booking/${SLUG}/waiting-list`;

function abrir(): ReturnType<typeof userEvent.setup> {
  render(
    <QueryClientProvider client={new QueryClient()}>
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

function anotado(overrides: Partial<WaitlistJoined> = {}): WaitlistJoined {
  return {
    professional_id: PROF_1.id,
    date_from: "2030-01-07",
    date_to: "2030-01-21",
    time_from: null,
    time_to: null,
    weekdays: null,
    channel: "whatsapp",
    warnings: [],
    ...overrides
  };
}

async function hastaLaAnotacion(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
  await user.click(await screen.findByRole("button", { name: "Anotarme en la lista de espera" }));
  await screen.findByRole("heading", { name: "Lista de espera" });
}

async function completarDatos(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(screen.getByLabelText("Nombre y apellido"), "Lucía Inventada Ficticia");
  await user.type(screen.getByLabelText("Teléfono"), "011 15 5555-0123");
  await user.click(screen.getByLabelText("Quiero recibir recordatorios por WhatsApp"));
  await user.click(screen.getByLabelText(/Acepto la política de privacidad/));
}

describe("WaitlistStep", () => {
  it("sin horarios ofrece anotarse con el profesional preseleccionado", async () => {
    server.use(...bookingHandlers({ slots: [] }));
    const user = abrir();

    await user.click(await screen.findByRole("button", { name: PROF_1.display_name }));
    expect(await screen.findByText("No hay horarios libres en estos días")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anotarme en la lista de espera" }));

    expect(screen.getByLabelText("Profesional")).toHaveValue(PROF_1.id);
  });

  it("anotación exitosa con resumen y el cuerpo esperado", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      ...bookingHandlers(),
      http.post(URL, async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(anotado(), { status: 201 });
      })
    );
    const user = abrir();
    await hastaLaAnotacion(user);
    await user.click(screen.getByLabelText("Mar"));
    await completarDatos(user);

    await user.click(screen.getByRole("button", { name: "Anotarme en la lista de espera" }));

    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("Te anotamos en la lista de espera");
    expect(aviso).toHaveTextContent("Con Dra. Ficticia Uno, del 07/01 al 21/01");
    expect(aviso).toHaveTextContent("por WhatsApp");
    expect(cuerpos).toEqual([
      {
        professional_id: PROF_1.id,
        date_from: "2030-01-07",
        date_to: "2030-01-21",
        time_from: null,
        time_to: null,
        weekdays: [1],
        patient: {
          full_name: "Lucía Inventada Ficticia",
          phone: "011 15 5555-0123",
          whatsapp_opt_in: true,
          privacy_accepted: true
        }
      }
    ]);
  });

  it("ya anotado muestra el teléfono de la clínica", async () => {
    server.use(
      ...bookingHandlers(),
      http.post(URL, () =>
        HttpResponse.json(
          { detail: "already_waiting", clinic_phone: "+5491155550100" },
          { status: 409 }
        )
      )
    );
    const user = abrir();
    await hastaLaAnotacion(user);
    await completarDatos(user);

    await user.click(screen.getByRole("button", { name: "Anotarme en la lista de espera" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ya estás en la lista de espera para ese profesional. Si querés cambiar algo, comunicate con la clínica al +5491155550100."
    );
  });

  it("429 conserva lo cargado", async () => {
    server.use(
      ...bookingHandlers(),
      http.post(URL, () =>
        HttpResponse.json({ detail: "rate_limited" }, { status: 429, headers: { "Retry-After": "60" } })
      )
    );
    const user = abrir();
    await hastaLaAnotacion(user);
    await completarDatos(user);

    await user.click(screen.getByRole("button", { name: "Anotarme en la lista de espera" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("no perdiste lo que cargaste");
    expect(screen.getByLabelText("Nombre y apellido")).toHaveValue("Lucía Inventada Ficticia");
  });

  it("no guarda datos del paciente en el navegador", async () => {
    server.use(
      ...bookingHandlers(),
      http.post(URL, () => HttpResponse.json(anotado(), { status: 201 }))
    );
    const user = abrir();
    await hastaLaAnotacion(user);
    await completarDatos(user);
    await user.click(screen.getByRole("button", { name: "Anotarme en la lista de espera" }));
    await screen.findByRole("status");

    await waitFor(() => {
      expect(window.localStorage.length).toBe(0);
      expect(window.sessionStorage.length).toBe(0);
    });
  });
});
