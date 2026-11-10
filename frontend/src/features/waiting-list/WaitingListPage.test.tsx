import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { UserRole } from "../../shared/api/types";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { entry, offer, waitlistHandlers } from "../../test/waitlistFixtures";
import WaitingListPage from "./WaitingListPage";

const AHORA = new Date("2030-01-07T11:00:00Z");

async function abrir(rol: UserRole) {
  return renderWithProviders(<WaitingListPage />, {
    session: await loggedSession(makeUser(rol)),
    now: () => AHORA
  });
}

describe("WaitingListPage", () => {
  it("muestra la cola en el orden de la API con prioridad, período, franja y oferta", async () => {
    server.use(
      ...waitlistHandlers({
        entries: [
          entry({
            id: "entry-p",
            patient: { id: "pat-p", full_name: "Prioritaria Ficticia", phone_e164: null, email: null },
            prioritized_at: "2030-01-07T10:00:00Z",
            priority_reason: "Urgencia por dolor",
            time_from: "14:00:00",
            time_to: "18:00:00",
            weekdays: [1, 3]
          }),
          entry({
            status: "offered",
            pending_offer: {
              id: "offer-1",
              professional_id: "prof-1",
              chair_id: "chair-1",
              starts_at: "2030-01-09T13:00:00Z",
              ends_at: "2030-01-09T13:30:00Z",
              expires_at: "2030-01-07T13:05:00Z",
              mode: "auto"
            }
          })
        ]
      })
    );
    await abrir("recepcion");

    const cola = await screen.findByRole("list", { name: "Cola" });
    const items = await within(cola).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Prioritaria Ficticia");
    expect(items[0]).toHaveTextContent("Prioritaria: Urgencia por dolor");
    expect(items[0]).toHaveTextContent("14:00–18:00 · Mar, Jue");
    expect(items[1]).toHaveTextContent("Lucía Espera Ficticia");
    expect(items[1]).toHaveTextContent("07/01 al 20/01");
    expect(items[1]).toHaveTextContent("Oferta pendiente: mié 09/01 10:00 · vence en 2 h 05 min");
    expect(items[1]).toHaveTextContent("+5491155550101");
  });

  it("los filtros se mandan a la API", async () => {
    const pedidos: URL[] = [];
    server.use(
      http.get("/api/waiting-list", ({ request }) => {
        pedidos.push(new URL(request.url));
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
      ...waitlistHandlers()
    );
    const { user } = await abrir("recepcion");
    await screen.findByText(/No hay pacientes en la lista/);

    await user.selectOptions(screen.getByLabelText("Profesional"), "prof-1");
    await user.selectOptions(screen.getByLabelText("Estado"), "withdrawn");

    await waitFor(() => {
      const ultimo = pedidos[pedidos.length - 1];
      expect(ultimo?.searchParams.get("professional_id")).toBe("prof-1");
      expect(ultimo?.searchParams.getAll("status")).toEqual(["withdrawn"]);
    });
  });

  it("Cargar más pide la página siguiente con el cursor", async () => {
    server.use(
      http.get("/api/waiting-list", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        return HttpResponse.json(
          cursor === null
            ? { items: [entry()], next_cursor: "c1" }
            : { items: [entry({ id: "entry-2", patient: { id: "pat-2", full_name: "Segunda Ficticia" } })], next_cursor: null }
        );
      }),
      ...waitlistHandlers()
    );
    const { user } = await abrir("recepcion");
    await screen.findByText("Lucía Espera Ficticia");

    await user.click(screen.getByRole("button", { name: "Cargar más" }));

    expect(await screen.findByText("Segunda Ficticia")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
  });

  it("vacío explica cómo anotar y el error permite reintentar", async () => {
    let falla = true;
    server.use(
      http.get("/api/waiting-list", () =>
        falla
          ? HttpResponse.json({ detail: "auth_unavailable" }, { status: 503 })
          : HttpResponse.json({ items: [], next_cursor: null })
      ),
      ...waitlistHandlers()
    );
    const { user } = await abrir("recepcion");

    expect(await screen.findByRole("alert")).toHaveTextContent("no responde");
    falla = false;
    await user.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText(/Usá “Anotar paciente”/)).toBeInTheDocument();
  });

  it("el odontólogo ve la cola sin contacto ni acciones", async () => {
    server.use(
      ...waitlistHandlers({
        entries: [entry({ patient: { id: "pat-1", full_name: "Lucía Espera Ficticia" } })],
        offers: [offer()]
      })
    );
    await abrir("odontologo");

    expect(await screen.findByText("Lucía Espera Ficticia")).toBeInTheDocument();
    expect(screen.queryByText("+5491155550101")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anotar paciente" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ofrecer hueco" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Priorizar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ofertas" })).not.toBeInTheDocument();
  });

  it("priorizar pide motivo y lo manda", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      ...waitlistHandlers({ entries: [entry()] }),
      http.post("/api/waiting-list/entry-1/priority", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(entry({ prioritized_at: AHORA.toISOString(), priority_reason: "Urgencia por dolor" }));
      })
    );
    const { user } = await abrir("recepcion");

    await user.click(await screen.findByRole("button", { name: "Priorizar" }));
    await user.type(screen.getByLabelText("Motivo"), "Urgencia por dolor");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Priorizar" }));

    await waitFor(() => expect(cuerpos).toEqual([{ reason: "Urgencia por dolor" }]));
  });

  it("retirar pide confirmación", async () => {
    let retirada = false;
    server.use(
      ...waitlistHandlers({ entries: [entry()] }),
      http.post("/api/waiting-list/entry-1/withdraw", () => {
        retirada = true;
        return HttpResponse.json(entry({ status: "withdrawn", closed_reason: "withdrawn_by_staff" }));
      })
    );
    const { user } = await abrir("recepcion");

    await user.click(await screen.findByRole("button", { name: "Retirar" }));
    const dialogo = screen.getByRole("dialog");
    expect(dialogo).toHaveTextContent("¿Retirar a Lucía Espera Ficticia");
    expect(retirada).toBe(false);
    await user.click(within(dialogo).getByRole("button", { name: "Retirar" }));

    await waitFor(() => expect(retirada).toBe(true));
  });
});
