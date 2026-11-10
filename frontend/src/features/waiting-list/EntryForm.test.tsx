import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { entry, waitlistHandlers } from "../../test/waitlistFixtures";
import WaitingListPage from "./WaitingListPage";

const AHORA = new Date("2030-01-07T11:00:00Z");

async function abrir() {
  return renderWithProviders(<WaitingListPage />, {
    session: await loggedSession(makeUser("recepcion")),
    now: () => AHORA
  });
}

function buscador() {
  return http.get("/api/patients", () =>
    HttpResponse.json({
      items: [{ id: "pat-9", full_name: "Nueva Ficticia", phone_e164: "+5491155550109", email: null }],
      next_cursor: null
    })
  );
}

describe("EntryForm", () => {
  it("anota a un paciente buscado con período, franja y días", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      buscador(),
      http.post("/api/waiting-list", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(entry({ id: "entry-9" }), { status: 201 });
      }),
      ...waitlistHandlers()
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Anotar paciente" }));
    const dialogo = screen.getByRole("dialog");
    await user.type(within(dialogo).getByLabelText("Buscar paciente"), "Nueva");
    await user.click(await within(dialogo).findByRole("button", { name: "Elegir Nueva Ficticia" }));
    await user.selectOptions(within(dialogo).getByLabelText("Profesional"), "prof-1");
    await user.type(within(dialogo).getByLabelText("Franja desde (opcional)"), "14:00");
    await user.type(within(dialogo).getByLabelText("Franja hasta (opcional)"), "18:00");
    await user.click(within(dialogo).getByLabelText("Mar"));
    await user.click(within(dialogo).getByLabelText("Jue"));
    await user.click(within(dialogo).getByRole("button", { name: "Anotar" }));

    await waitFor(() =>
      expect(cuerpos).toEqual([
        {
          patient_id: "pat-9",
          professional_id: "prof-1",
          date_from: "2030-01-07",
          date_to: "2030-01-21",
          time_from: "14:00",
          time_to: "18:00",
          weekdays: [1, 3],
          notes: null
        }
      ])
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("ante already_waiting ofrece ir a la entrada existente", async () => {
    server.use(
      buscador(),
      http.post("/api/waiting-list", () =>
        HttpResponse.json({ detail: "already_waiting", entry_id: "entry-1" }, { status: 409 })
      ),
      ...waitlistHandlers({ entries: [entry()] })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Anotar paciente" }));
    const dialogo = screen.getByRole("dialog");
    await user.type(within(dialogo).getByLabelText("Buscar paciente"), "Nueva");
    await user.click(await within(dialogo).findByRole("button", { name: "Elegir Nueva Ficticia" }));
    await user.click(within(dialogo).getByRole("button", { name: "Anotar" }));

    expect(await within(dialogo).findByRole("alert")).toHaveTextContent("ya está en la lista");
    await user.click(within(dialogo).getByRole("button", { name: "Ver la entrada existente" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("editar manda solo las preferencias y la nota", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.patch("/api/waiting-list/entry-1", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(entry({ notes: "Prefiere la tarde" }));
      }),
      ...waitlistHandlers({ entries: [entry()] })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Editar" }));
    const dialogo = screen.getByRole("dialog");
    await user.type(within(dialogo).getByLabelText(/Nota operativa/), "Prefiere la tarde");
    await user.click(within(dialogo).getByRole("button", { name: "Guardar" }));

    await waitFor(() =>
      expect(cuerpos).toEqual([
        {
          professional_id: "prof-1",
          date_from: "2030-01-07",
          date_to: "2030-01-20",
          time_from: null,
          time_to: null,
          weekdays: null,
          notes: "Prefiere la tarde"
        }
      ])
    );
  });
});
