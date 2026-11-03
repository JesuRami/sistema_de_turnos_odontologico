import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import {
  agendaHandlers,
  appointment,
  block,
  chair,
  professional
} from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import AgendaPage from "./AgendaPage";

// Lunes 2030-01-07 08:00 en Buenos Aires; el navegador de los tests está en UTC.
const AHORA = new Date("2030-01-07T11:00:00Z");

async function abrir(rol: "admin" | "recepcion" | "odontologo" = "recepcion") {
  return renderWithProviders(<AgendaPage />, {
    session: await loggedSession(makeUser(rol)),
    now: () => AHORA
  });
}

describe("AgendaPage", () => {
  it("abre el día de hoy de la clínica con una columna por sillón activo", async () => {
    server.use(
      ...agendaHandlers({
        chairs: [chair(), chair({ id: "chair-2", name: "Sillón 2" }), chair({ id: "chair-3", name: "Sillón roto", active: false })]
      })
    );
    await abrir();

    expect(await screen.findByRole("heading", { name: /lun 07\/01/ })).toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "Sillón 1" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Sillón 2" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Sillón roto" })).not.toBeInTheDocument();
  });

  it("dibuja los turnos en la hora de la clínica, no la del navegador", async () => {
    server.use(...agendaHandlers({ appointments: [appointment()] }));
    await abrir();

    expect(
      await screen.findByRole("button", { name: /10:00 Ana Prueba Ejemplo · Confirmado/ })
    ).toBeInTheDocument();
  });

  it("pide a la API el rango del día local", async () => {
    let consulta = "";
    server.use(
      http.get("/api/appointments", ({ request }) => {
        consulta = new URL(request.url).search;
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
      ...agendaHandlers()
    );
    await abrir();

    await waitFor(() => expect(consulta).not.toBe(""));
    expect(decodeURIComponent(consulta)).toContain("from=2030-01-07T03:00:00.000Z");
    expect(decodeURIComponent(consulta)).toContain("to=2030-01-08T03:00:00.000Z");
  });

  it("junta todas las páginas del rango", async () => {
    server.use(
      http.get("/api/appointments", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        return HttpResponse.json(
          cursor === null
            ? { items: [appointment()], next_cursor: "pagina-2" }
            : {
                items: [
                  appointment({
                    id: "appt-2",
                    starts_at: "2030-01-07T14:00:00Z",
                    ends_at: "2030-01-07T14:30:00Z",
                    patient: { id: "pat-2", full_name: "Bruno Ficticio" }
                  })
                ],
                next_cursor: null
              }
        );
      }),
      ...agendaHandlers()
    );
    await abrir();

    expect(await screen.findByRole("button", { name: /11:00 Bruno Ficticio/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /10:00 Ana Prueba Ejemplo/ })).toBeInTheDocument();
  });

  it("vista semana con siete días y navegación", async () => {
    server.use(
      ...agendaHandlers({
        appointments: [
          appointment(),
          appointment({
            id: "appt-mie",
            starts_at: "2030-01-09T15:00:00Z",
            ends_at: "2030-01-09T15:30:00Z",
            patient: { id: "pat-3", full_name: "Carla Ficticia" }
          })
        ]
      })
    );
    const { user } = await abrir();

    await user.click(await screen.findByRole("button", { name: "Semana" }));

    for (const dia of ["lun 07/01", "mié 09/01", "dom 13/01"]) {
      expect(await screen.findByRole("columnheader", { name: dia })).toBeInTheDocument();
    }
    expect(await screen.findByRole("button", { name: /12:00 Carla Ficticia/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByRole("columnheader", { name: "lun 14/01" })).toBeInTheDocument();
  });

  it("filtra por profesional", async () => {
    server.use(
      ...agendaHandlers({
        professionals: [professional(), professional({ id: "prof-2", display_name: "Dr. Ficticio Dos" })],
        appointments: [
          appointment(),
          appointment({
            id: "appt-2",
            professional_id: "prof-2",
            chair_id: "chair-1",
            starts_at: "2030-01-07T15:00:00Z",
            ends_at: "2030-01-07T15:30:00Z",
            patient: { id: "pat-2", full_name: "Bruno Ficticio" }
          })
        ]
      })
    );
    const { user } = await abrir();
    await screen.findByRole("button", { name: /Bruno Ficticio/ });

    await user.selectOptions(screen.getByLabelText("Profesional"), "prof-2");

    expect(screen.getByRole("button", { name: /Bruno Ficticio/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ana Prueba Ejemplo/ })).not.toBeInTheDocument();
  });

  it("distingue sobreturno, bloqueo y pendiente próximo; oculta cancelados por defecto", async () => {
    server.use(
      ...agendaHandlers({
        appointments: [
          appointment({ is_overbooking: true, overbooking_reason: "Urgencia ficticia" }),
          appointment({
            id: "appt-pend",
            status: "pending",
            starts_at: "2030-01-07T14:00:00Z",
            ends_at: "2030-01-07T14:30:00Z",
            patient: { id: "pat-2", full_name: "Bruno Ficticio" }
          }),
          appointment({
            id: "appt-canc",
            status: "cancelled",
            starts_at: "2030-01-07T15:00:00Z",
            ends_at: "2030-01-07T15:30:00Z",
            patient: { id: "pat-3", full_name: "Cancelada Ficticia" }
          })
        ],
        blocks: [block()]
      })
    );
    const { user } = await abrir();

    const sobre = await screen.findByRole("button", { name: /Ana Prueba Ejemplo/ });
    expect(within(sobre).getByText("Sobreturno")).toBeInTheDocument();
    const pendiente = screen.getByRole("button", { name: /Bruno Ficticio/ });
    expect(within(pendiente).getByText("Sin confirmar")).toBeInTheDocument();
    expect(screen.getByRole("note", { name: /Bloqueo · Mantenimiento 12:00–13:00/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cancelada Ficticia/ })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Estado"), "cancelled");
    expect(screen.getByRole("button", { name: /Cancelada Ficticia/ })).toBeInTheDocument();
  });

  it("el odontólogo no ve contacto ni botón de nuevo turno", async () => {
    server.use(
      ...agendaHandlers({
        appointments: [appointment({ patient: { id: "pat-1", full_name: "Ana Prueba Ejemplo" } })]
      })
    );
    await abrir("odontologo");

    await screen.findByRole("button", { name: /Ana Prueba Ejemplo/ });
    expect(screen.queryByRole("button", { name: "Nuevo turno" })).not.toBeInTheDocument();
    expect(screen.queryByText(/\+549/)).not.toBeInTheDocument();
  });

  it("recepción ve el botón de nuevo turno", async () => {
    server.use(...agendaHandlers());
    await abrir("recepcion");
    expect(await screen.findByRole("button", { name: "Nuevo turno" })).toBeInTheDocument();
  });
});
