import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  agendaHandlers,
  appointment,
  block,
  chair,
  followUpPage,
  followUpRow,
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

  describe("tiempo real por polling (C-07, D13)", () => {
    afterEach(() => {
      vi.useRealTimers();
      Reflect.deleteProperty(document, "visibilityState");
    });

    function pendientesEnLaRed(): { pedidos: () => number } {
      let pedidos = 0;
      server.use(
        http.get("/api/appointments", () => {
          pedidos += 1;
          const items =
            pedidos === 1
              ? []
              : [
                  appointment({
                    id: "appt-online",
                    status: "pending",
                    origin: "online",
                    patient: { id: "pat-9", full_name: "Online Ficticia", phone_e164: null, email: null }
                  })
                ];
          return HttpResponse.json({ items, next_cursor: null });
        }),
        ...agendaHandlers()
      );
      return { pedidos: () => pedidos };
    }

    it("con la pestaña visible vuelve a pedir el rango a los 30 s y muestra el turno pendiente nuevo", async () => {
      const red = pendientesEnLaRed();
      const sesion = await loggedSession(makeUser("recepcion"));
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(<AgendaPage />, { session: sesion, now: () => AHORA });
      await waitFor(() => expect(red.pedidos()).toBe(1));
      expect(screen.queryByRole("button", { name: /Online Ficticia/ })).not.toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(29_000);
      expect(red.pedidos()).toBe(1);
      await vi.advanceTimersByTimeAsync(2_000);

      expect(await screen.findByRole("button", { name: /Online Ficticia/ })).toBeInTheDocument();
      expect(red.pedidos()).toBe(2);
    });

    it("con la pestaña oculta no vuelve a pedir", async () => {
      const red = pendientesEnLaRed();
      const sesion = await loggedSession(makeUser("recepcion"));
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(<AgendaPage />, { session: sesion, now: () => AHORA });
      await waitFor(() => expect(red.pedidos()).toBe(1));
      Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });

      await vi.advanceTimersByTimeAsync(65_000);

      expect(red.pedidos()).toBe(1);
    });
  });

  describe("panel de seguimiento (C-11)", () => {
    const pendiente = appointment({ id: "appt-pend", status: "pending" });
    const otro = appointment({
      id: "appt-ok",
      starts_at: "2030-01-07T14:00:00Z",
      ends_at: "2030-01-07T14:30:00Z",
      patient: { id: "pat-2", full_name: "Bruno Ficticio" }
    });

    it("recepción ve los contadores y el filtro deja solo esos turnos", async () => {
      server.use(
        ...agendaHandlers({
          appointments: [pendiente, otro],
          followUp: followUpPage([
            followUpRow({ appointment_id: "appt-pend" }),
            followUpRow({ appointment_id: "appt-x2" }),
            followUpRow({ appointment_id: "appt-x3" }),
            followUpRow({ appointment_id: "appt-x4", reasons: ["delivery_failed"] })
          ])
        })
      );
      const { user } = await abrir();

      const panel = await screen.findByRole("region", { name: "Seguimiento de recordatorios" });
      expect(await within(panel).findByText("3 sin confirmar")).toBeInTheDocument();
      expect(within(panel).getByText("1 con fallo de envío")).toBeInTheDocument();
      await screen.findByRole("button", { name: /Bruno Ficticio/ });

      await user.click(within(panel).getByRole("button", { name: "Solo para llamar" }));

      expect(screen.getByRole("button", { name: /Ana Prueba Ejemplo/ })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Bruno Ficticio/ })).not.toBeInTheDocument();
    });

    it("sin turnos para llamar muestra 0 y el filtro no cambia la grilla", async () => {
      server.use(...agendaHandlers({ appointments: [otro] }));
      const { user } = await abrir();

      const panel = await screen.findByRole("region", { name: "Seguimiento de recordatorios" });
      expect(await within(panel).findByText("0 sin confirmar")).toBeInTheDocument();
      await user.click(within(panel).getByRole("button", { name: "Solo para llamar" }));

      expect(await screen.findByRole("button", { name: /Bruno Ficticio/ })).toBeInTheDocument();
    });

    it("pide el seguimiento del rango visible", async () => {
      let consulta = "";
      server.use(
        http.get("/api/reminders/follow-up", ({ request }) => {
          consulta = decodeURIComponent(new URL(request.url).search);
          return HttpResponse.json(followUpPage());
        }),
        ...agendaHandlers()
      );
      await abrir();

      await waitFor(() => expect(consulta).toContain("from=2030-01-07T03:00:00.000Z"));
      expect(consulta).toContain("to=2030-01-08T03:00:00.000Z");
    });

    it("el odontólogo no ve el panel ni pide el seguimiento", async () => {
      let pedidos = 0;
      server.use(
        http.get("/api/reminders/follow-up", () => {
          pedidos += 1;
          return HttpResponse.json(followUpPage());
        }),
        ...agendaHandlers({ appointments: [otro] })
      );
      await abrir("odontologo");

      await screen.findByRole("button", { name: /Bruno Ficticio/ });
      expect(
        screen.queryByRole("region", { name: "Seguimiento de recordatorios" })
      ).not.toBeInTheDocument();
      expect(pedidos).toBe(0);
    });

    it("el refresco periódico actualiza el panel", async () => {
      let pedidos = 0;
      server.use(
        http.get("/api/reminders/follow-up", () => {
          pedidos += 1;
          return HttpResponse.json(
            followUpPage(pedidos === 1 ? [] : [followUpRow({ appointment_id: "appt-pend" })])
          );
        }),
        ...agendaHandlers({ appointments: [pendiente] })
      );
      const sesion = await loggedSession(makeUser("recepcion"));
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderWithProviders(<AgendaPage />, { session: sesion, now: () => AHORA });
        expect(await screen.findByText("0 sin confirmar")).toBeInTheDocument();

        await vi.advanceTimersByTimeAsync(31_000);

        expect(await screen.findByText("1 sin confirmar")).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
