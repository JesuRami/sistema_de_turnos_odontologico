import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { agendaHandlers, rule } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import SchedulesAdmin from "./SchedulesAdmin";

const AHORA = new Date("2030-01-07T11:00:00Z");

async function abrir() {
  return renderWithProviders(<SchedulesAdmin />, {
    session: await loggedSession(makeUser("admin")),
    now: () => AHORA
  });
}

describe("SchedulesAdmin", () => {
  it("muestra las franjas por profesional y sillón", async () => {
    server.use(...agendaHandlers());
    await abrir();

    const fila = await screen.findByRole("row", { name: /Lunes/ });
    expect(fila).toHaveTextContent("Dra. Ficticia Uno");
    expect(fila).toHaveTextContent("Sillón 1");
    expect(fila).toHaveTextContent("09:00–13:00");
    expect(fila).toHaveTextContent("30 min");
  });

  it("agrega una franja nueva", async () => {
    let enviado: unknown = null;
    server.use(
      http.post("/api/schedules", async ({ request }) => {
        enviado = await request.json();
        return HttpResponse.json(rule({ id: "rule-2", weekday: 1 }), { status: 201 });
      }),
      ...agendaHandlers()
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Nueva franja" }));
    await user.selectOptions(screen.getByLabelText("Día"), "1");
    await user.type(screen.getByLabelText("Desde"), "14:00");
    await user.type(screen.getByLabelText("Hasta"), "18:00");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() =>
      expect(enviado).toEqual({
        professional_id: "prof-1",
        chair_id: "chair-1",
        weekday: 1,
        start_time: "14:00",
        end_time: "18:00",
        slot_duration_min: 30,
        valid_from: "2030-01-07"
      })
    );
  });

  it("una franja solapada señala las reglas en conflicto", async () => {
    server.use(
      http.post("/api/schedules", () =>
        HttpResponse.json({ detail: "schedule_overlap", conflicts: ["rule-1"] }, { status: 409 })
      ),
      ...agendaHandlers()
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Nueva franja" }));
    await user.type(screen.getByLabelText("Desde"), "10:00");
    await user.type(screen.getByLabelText("Hasta"), "12:00");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("se superpone");
    expect(within(screen.getByRole("row", { name: /Lunes/ })).getByText("En conflicto")).toBeInTheDocument();
  });

  it("desactiva una franja", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.patch("/api/schedules/rule-1", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(rule({ active: false }));
      }),
      ...agendaHandlers()
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Desactivar franja Lunes 09:00–13:00" }));

    await waitFor(() => expect(cuerpos).toEqual([{ active: false }]));
  });
});
