/**
 * C-14 (SU-06): sin red, confirmar y registrar asistencia quedan en la cola de reintentos; la
 * cancelación no (dispara lista de espera y avisos, necesita la agenda viva).
 */
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Appointment } from "../../shared/api/types";
import { retryQueue } from "../../shared/offline/retryQueue";
import { appointment, chair, professional, rule, timeline, TZ } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import AppointmentDetail from "./AppointmentDetail";

const DESPUES = new Date("2030-01-07T13:10:00Z");

async function abrir(turno: Appointment) {
  const onDone = vi.fn();
  const r = renderWithProviders(
    <AppointmentDetail
      appointment={turno}
      context={{ tz: TZ, role: "recepcion", professionals: [professional()], chairs: [chair()], schedules: [rule()] }}
      onClose={() => undefined}
      onReschedule={() => undefined}
      onDone={onDone}
    />,
    { session: await loggedSession(makeUser("recepcion")), now: () => DESPUES }
  );
  return { ...r, onDone };
}

describe("AppointmentDetail sin conexión", () => {
  beforeEach(() => {
    server.use(http.get("/api/appointments/appt-1/reminders", () => HttpResponse.json(timeline([]))));
  });

  it("la asistencia sin red queda en cola y se envía al volver", async () => {
    let red = false;
    const cuerpos: unknown[] = [];
    server.use(
      http.post("/api/appointments/appt-1/transitions", async ({ request }) => {
        if (!red) {
          return HttpResponse.error();
        }
        cuerpos.push(await request.json());
        return HttpResponse.json(appointment({ status: "present" }));
      })
    );
    const { user, onDone } = await abrir(appointment());

    await user.click(screen.getByRole("button", { name: "Presente" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(expect.stringContaining("quedó en cola")));
    const [encolado] = retryQueue.getSnapshot();
    expect(encolado).toMatchObject({ id: "appt-1:present", status: "pending" });
    // La etiqueta no lleva datos de contacto del paciente (regla 13).
    expect(encolado?.label).not.toContain("+549");

    red = true;
    await retryQueue.flush(true);
    expect(cuerpos).toEqual([{ to: "present" }]);
    expect(retryQueue.getSnapshot()[0]?.status).toBe("done");
  });

  it("un error de negocio no se encola y se muestra", async () => {
    server.use(
      http.post("/api/appointments/appt-1/transitions", () =>
        HttpResponse.json({ detail: "invalid_transition" }, { status: 409 })
      )
    );
    const { user } = await abrir(appointment());

    await user.click(screen.getByRole("button", { name: "Presente" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("El turno no admite ese cambio de estado");
    expect(retryQueue.getSnapshot()).toEqual([]);
  });
});
