import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { entry, offer, waitlistHandlers } from "../../test/waitlistFixtures";
import WaitingListPage from "./WaitingListPage";

const AHORA = new Date("2030-01-07T11:00:00Z");

async function abrir() {
  return renderWithProviders(<WaitingListPage />, {
    session: await loggedSession(makeUser("recepcion")),
    now: () => AHORA
  });
}

function panel(): HTMLElement {
  return screen.getByRole("region", { name: "Ofertas" });
}

describe("OffersPanel", () => {
  it("lista pendientes con cuenta regresiva y las cerradas de hoy", async () => {
    server.use(
      ...waitlistHandlers({
        entries: [entry({ status: "offered" })],
        offers: [
          offer(),
          offer({
            id: "offer-2",
            status: "expired",
            expires_at: "2030-01-07T10:00:00Z",
            responded_at: null
          })
        ]
      })
    );
    await abrir();

    await screen.findByText("Pendientes (1)");
    expect(panel()).toHaveTextContent("Lucía Espera Ficticia · mié 09/01 10:00 · Dra. Ficticia Uno");
    expect(panel()).toHaveTextContent("vence en 4 h 00 min");
    expect(panel()).toHaveTextContent("Cerradas hoy (1)");
    expect(panel()).toHaveTextContent("Vencida");
  });

  it("aceptar por teléfono muestra el turno creado y el acceso a la agenda", async () => {
    server.use(
      http.post("/api/waiting-list/offers/offer-1/accept", () =>
        HttpResponse.json({
          offer: offer({ status: "accepted", appointment_id: "appt-9" }),
          appointment_id: "appt-9",
          starts_at: "2030-01-09T13:00:00Z",
          ends_at: "2030-01-09T13:30:00Z"
        })
      ),
      ...waitlistHandlers({ entries: [entry({ status: "offered" })], offers: [offer()] })
    );
    const { user } = await abrir();

    await user.click(
      await screen.findByRole("button", { name: "Aceptar por teléfono la oferta de Lucía Espera Ficticia" })
    );

    const aviso = await within(panel()).findByRole("status");
    expect(aviso).toHaveTextContent("Turno creado: mié 09/01 10:00");
    expect(within(aviso).getByRole("link", { name: "Ver en la agenda" })).toHaveAttribute("href", "/");
  });

  it("hueco ocupado al aceptar explica que la entrada quedó prioritaria", async () => {
    server.use(
      http.post("/api/waiting-list/offers/offer-1/accept", () =>
        HttpResponse.json({ detail: "slot_taken", alternatives: [] }, { status: 409 })
      ),
      ...waitlistHandlers({ entries: [entry({ status: "offered" })], offers: [offer()] })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: /Aceptar por teléfono/ }));

    expect(await within(panel()).findByRole("alert")).toHaveTextContent("volvió a la cola como prioritaria");
  });

  it("un detail desconocido muestra un mensaje genérico", async () => {
    server.use(
      http.post("/api/waiting-list/offers/offer-1/decline", () =>
        HttpResponse.json({ detail: "algo_raro" }, { status: 409 })
      ),
      ...waitlistHandlers({ entries: [entry({ status: "offered" })], offers: [offer()] })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Rechazar" }));

    await waitFor(() =>
      expect(within(panel()).getByRole("alert")).toHaveTextContent("No se pudo completar la operación")
    );
  });

  it("la oferta vencida en pantalla pasa a cerradas tras el refresco", async () => {
    let vencida = false;
    server.use(
      http.get("/api/waiting-list/offers", () =>
        HttpResponse.json({
          items: [vencida ? offer({ status: "expired" }) : offer()],
          next_cursor: null
        })
      ),
      ...waitlistHandlers({ entries: [entry({ status: "offered" })] })
    );
    const { queryClient } = await abrir();
    await screen.findByText("Pendientes (1)");

    vencida = true;
    await queryClient.invalidateQueries();

    expect(await screen.findByText("Pendientes (0)")).toBeInTheDocument();
  });
});
