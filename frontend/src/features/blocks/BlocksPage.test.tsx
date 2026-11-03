import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { UserRole } from "../../shared/api/types";
import { agendaHandlers, appointment, block } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import BlocksPage from "./BlocksPage";

const AHORA = new Date("2030-01-07T11:00:00Z");

async function abrir(rol: UserRole) {
  return renderWithProviders(<BlocksPage />, {
    session: await loggedSession(makeUser(rol)),
    now: () => AHORA
  });
}

const AFECTADOS = ["appt-a", "appt-b"];

function detalleDeTurnos() {
  return [
    http.get("/api/appointments/appt-a", () =>
      HttpResponse.json(appointment({ id: "appt-a", starts_at: "2030-01-14T13:00:00Z", ends_at: "2030-01-14T13:30:00Z" }))
    ),
    http.get("/api/appointments/appt-b", () =>
      HttpResponse.json(appointment({ id: "appt-b", starts_at: "2030-01-15T14:00:00Z", ends_at: "2030-01-15T14:30:00Z" }))
    )
  ];
}

async function cargarVacaciones(user: Awaited<ReturnType<typeof abrir>>["user"], conProfesional = true) {
  await user.click(await screen.findByRole("button", { name: "Nuevo bloqueo" }));
  if (conProfesional) {
    await user.selectOptions(screen.getByLabelText("Profesional"), "prof-1");
  }
  await user.type(screen.getByLabelText("Desde (fecha)"), "2030-01-14");
  await user.type(screen.getByLabelText("Desde (hora)"), "00:00");
  await user.type(screen.getByLabelText("Hasta (fecha)"), "2030-01-19");
  await user.type(screen.getByLabelText("Hasta (hora)"), "00:00");
  await user.selectOptions(screen.getByLabelText("Motivo"), "vacaciones");
  await user.click(screen.getByRole("button", { name: "Guardar bloqueo" }));
}

describe("BlocksPage", () => {
  it("lista los bloqueos vigentes en la hora de la clínica", async () => {
    server.use(...agendaHandlers({ blocks: [block()] }));
    await abrir("recepcion");
    const fila = await screen.findByRole("row", { name: /Mantenimiento/ });
    expect(fila).toHaveTextContent("Sillón 1");
    expect(fila).toHaveTextContent("lun 07/01 12:00 → lun 07/01 13:00");
  });

  it("un bloqueo que pisa turnos los lista y permite cancelarlos en la misma operación", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.post("/api/blocks", async ({ request }) => {
        cuerpos.push(await request.json());
        return cuerpos.length === 1
          ? HttpResponse.json({ detail: "block_conflicts", appointments: AFECTADOS }, { status: 409 })
          : HttpResponse.json(block({ id: "block-9" }), { status: 201 });
      }),
      ...detalleDeTurnos(),
      ...agendaHandlers()
    );
    const { user } = await abrir("recepcion");

    await cargarVacaciones(user);

    expect(await screen.findByText("lun 14/01 10:00 · Dra. Ficticia Uno")).toBeInTheDocument();
    expect(screen.getByText("mar 15/01 11:00 · Dra. Ficticia Uno")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancelar 2 turnos y crear el bloqueo" }));

    expect(await screen.findByText("Bloqueo creado")).toBeInTheDocument();
    expect(cuerpos[0]).toEqual({
      professional_id: "prof-1",
      starts_at: "2030-01-14T03:00:00.000Z",
      ends_at: "2030-01-19T03:00:00.000Z",
      reason: "vacaciones"
    });
    expect(cuerpos[1]).toMatchObject({
      cancel_appointments: [
        { appointment_id: "appt-a", reason: "bloqueo" },
        { appointment_id: "appt-b", reason: "bloqueo" }
      ]
    });
  });

  it("el odontólogo bloquea su agenda pero no cancela turnos", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.post("/api/blocks", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json({ detail: "block_conflicts", appointments: ["appt-a"] }, { status: 409 });
      }),
      ...detalleDeTurnos(),
      ...agendaHandlers()
    );
    const { user } = await abrir("odontologo");

    await cargarVacaciones(user, false);

    expect(await screen.findByText(/recepción debe resolver los turnos/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cancelar 1 turno/ })).not.toBeInTheDocument();
    expect(cuerpos[0]).toMatchObject({ professional_id: "prof-1" });
  });

  it("solo el admin carga cierres y retira bloqueos", async () => {
    let cierre: unknown = null;
    let retirado = false;
    server.use(
      http.post("/api/blocks/closure", async ({ request }) => {
        cierre = await request.json();
        return HttpResponse.json({ items: [block()] }, { status: 201 });
      }),
      http.delete("/api/blocks/block-1", () => {
        retirado = true;
        return new HttpResponse(null, { status: 204 });
      }),
      ...agendaHandlers({ blocks: [block()] })
    );
    const { user } = await abrir("admin");

    await user.click(await screen.findByRole("button", { name: "Retirar bloqueo Mantenimiento" }));
    await waitFor(() => expect(retirado).toBe(true));

    await user.click(screen.getByRole("button", { name: "Cierre de clínica" }));
    await user.type(screen.getByLabelText("Desde (fecha)"), "2030-05-01");
    await user.type(screen.getByLabelText("Hasta (fecha)"), "2030-05-02");
    await user.click(screen.getByRole("button", { name: "Guardar cierre" }));
    await waitFor(() =>
      expect(cierre).toEqual({
        starts_at: "2030-05-01T03:00:00.000Z",
        ends_at: "2030-05-02T03:00:00.000Z",
        reason: "feriado"
      })
    );
  });

  it("recepción no ve cierres ni retiro", async () => {
    server.use(...agendaHandlers({ blocks: [block()] }));
    await abrir("recepcion");
    await screen.findByRole("row", { name: /Mantenimiento/ });
    expect(screen.queryByRole("button", { name: "Cierre de clínica" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retirar bloqueo/ })).not.toBeInTheDocument();
  });
});
