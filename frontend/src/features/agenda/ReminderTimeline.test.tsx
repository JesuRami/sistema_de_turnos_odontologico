import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { ReminderTimeline as Timeline, UserRole } from "../../shared/api/types";
import { reminderStep, timeline, TZ } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import ReminderTimeline from "./ReminderTimeline";

const URL = "/api/appointments/appt-1/reminders";

function responder(datos: Timeline): void {
  server.use(http.get(URL, () => HttpResponse.json(datos)));
}

async function abrir(rol: UserRole = "recepcion") {
  return renderWithProviders(
    <ReminderTimeline appointmentId="appt-1" tz={TZ} canAct={rol !== "odontologo"} />,
    { session: await loggedSession(makeUser(rol)) }
  );
}

describe("ReminderTimeline", () => {
  it("muestra los pasos en orden con estado, fechas, intentos y último error", async () => {
    responder(
      timeline([
        reminderStep({ step: "t_72h", status: "read" }),
        reminderStep({
          step: "t_24h",
          status: "failed",
          attempts: 3,
          last_error: "meta_131026",
          events: [
            { type: "sent", occurred_at: "2030-01-06T13:00:05Z", previous: false, detail: {} },
            { type: "failed", occurred_at: "2030-01-06T13:02:00Z", previous: false, detail: {} }
          ]
        })
      ])
    );
    await abrir();

    const pasos = await screen.findAllByRole("listitem", { name: /antes|Alta/ });
    expect(pasos.map((p) => p.getAttribute("aria-label"))).toEqual([
      "72 h antes · WhatsApp",
      "24 h antes · WhatsApp"
    ]);
    expect(within(pasos[0] as HTMLElement).getByText("Leído")).toBeInTheDocument();
    const fallido = pasos[1] as HTMLElement;
    expect(within(fallido).getByText("Falló")).toBeInTheDocument();
    expect(within(fallido).getByText(/3 intentos/)).toBeInTheDocument();
    expect(within(fallido).getByText(/meta_131026/)).toBeInTheDocument();
    expect(within(fallido).getByText(/Programado: dom 06\/01 10:00/)).toBeInTheDocument();
  });

  it("un paso pendiente muestra Programado como primer hito", async () => {
    responder(
      timeline([
        reminderStep({
          step: "t_3h",
          status: "scheduled",
          sent_at: null,
          can_resend: false,
          resend_blocked_reason: "reminder_pending",
          events: [
            { type: "scheduled", occurred_at: "2030-01-07T10:00:00Z", previous: false, detail: {} }
          ]
        })
      ])
    );
    await abrir();

    const paso = await screen.findByRole("listitem", { name: "3 h antes · WhatsApp" });
    const hitos = within(paso).getAllByRole("listitem");
    expect(hitos[0]).toHaveTextContent("Programado");
    expect(within(paso).queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();
  });

  it("marca el reenvío de recepción y los eventos del envío anterior", async () => {
    responder(
      timeline([
        reminderStep({
          status: "scheduled",
          events: [
            { type: "scheduled", occurred_at: "2030-01-07T10:00:00Z", previous: false, detail: {} },
            { type: "sent", occurred_at: "2030-01-06T13:00:05Z", previous: true, detail: {} },
            {
              type: "manual_resend",
              occurred_at: "2030-01-07T10:00:00Z",
              previous: true,
              detail: { actor_role: "recepcion" }
            }
          ]
        })
      ])
    );
    await abrir();

    expect(await screen.findByText(/Reenviado por recepción/)).toBeInTheDocument();
    expect(screen.getAllByText("envío anterior")).toHaveLength(2);
  });

  it("no muestra ids del proveedor ni datos de contacto", async () => {
    responder(timeline());
    const { container } = await abrir();
    await screen.findByText("Entregado");

    expect(container.textContent).not.toMatch(/wamid|\+549|@example\.com/);
  });

  it("el odontólogo ve el timeline sin Reenviar", async () => {
    responder(timeline([reminderStep({ can_resend: false })]));
    await abrir("odontologo");

    await screen.findByText("Entregado");
    expect(screen.queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();
  });

  it("un paso sin opt-in muestra el motivo en vez del botón", async () => {
    responder(
      timeline([reminderStep({ status: "skipped", can_resend: false, resend_blocked_reason: "no_consent" })])
    );
    await abrir();

    expect(await screen.findByText(/no aceptó recibir WhatsApp/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();
  });

  it("un error de red muestra un mensaje claro", async () => {
    server.use(http.get(URL, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    await abrir();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar el historial de recordatorios")
    );
  });
});
