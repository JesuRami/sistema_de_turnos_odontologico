import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { entry, offer, waitlistHandlers } from "../../test/waitlistFixtures";
import WaitingListPage from "./WaitingListPage";

const AHORA = new Date("2030-01-07T11:00:00Z");
const HUECO = {
  professional_id: "prof-1",
  chair_id: "chair-1",
  starts_at: "2030-01-09T13:00:00Z",
  ends_at: "2030-01-09T13:30:00Z"
};

async function abrir() {
  return renderWithProviders(<WaitingListPage />, {
    session: await loggedSession(makeUser("recepcion")),
    now: () => AHORA
  });
}

describe("OfferDialog", () => {
  it("muestra los huecos de la entrada y, si hay que saltear la cola, pide motivo", async () => {
    const cuerpos: Record<string, unknown>[] = [];
    server.use(
      http.get("/api/waiting-list/entry-1/slots", () =>
        HttpResponse.json({ timezone: "America/Argentina/Buenos_Aires", items: [HUECO] })
      ),
      http.post("/api/waiting-list/entry-1/offers", async ({ request }) => {
        const cuerpo = (await request.json()) as Record<string, unknown>;
        cuerpos.push(cuerpo);
        return "fifo_skip_reason" in cuerpo
          ? HttpResponse.json(offer({ mode: "manual" }), { status: 201 })
          : HttpResponse.json({ detail: "fifo_skip_reason_required" }, { status: 422 });
      }),
      ...waitlistHandlers({ entries: [entry()] })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Ofrecer hueco" }));
    const dialogo = screen.getByRole("dialog");
    await user.click(
      await within(dialogo).findByRole("button", { name: "mié 09/01 10:00 · Dra. Ficticia Uno" })
    );
    await user.click(within(dialogo).getByRole("button", { name: "Ofrecer" }));
    await user.type(
      await within(dialogo).findByLabelText("Motivo de la excepción"),
      "Paciente con urgencia por dolor"
    );
    await user.click(within(dialogo).getByRole("button", { name: "Ofrecer igual" }));

    await waitFor(() => expect(cuerpos).toHaveLength(2));
    expect(cuerpos[1]).toEqual({ ...HUECO, ends_at: undefined, fifo_skip_reason: "Paciente con urgencia por dolor" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("sin huecos lo dice", async () => {
    server.use(
      http.get("/api/waiting-list/entry-1/slots", () =>
        HttpResponse.json({ timezone: "America/Argentina/Buenos_Aires", items: [] })
      ),
      ...waitlistHandlers({ entries: [entry()] })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Ofrecer hueco" }));

    expect(await screen.findByText(/No hay huecos libres/)).toBeInTheDocument();
  });
});
