import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Appointment, UserRole } from "../../shared/api/types";
import { appointment, chair, professional, reminderStep, rule, timeline, TZ } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import AppointmentDetail from "./AppointmentDetail";

const ANTES = new Date("2030-01-07T11:00:00Z"); // 08:00 local, turno a las 10:00
const DESPUES = new Date("2030-01-07T13:10:00Z");

async function abrir(turno: Appointment, { rol = "recepcion" as UserRole, ahora = ANTES } = {}) {
  const onDone = vi.fn();
  const onReschedule = vi.fn();
  const r = renderWithProviders(
    <AppointmentDetail
      appointment={turno}
      context={{ tz: TZ, role: rol, professionals: [professional()], chairs: [chair()], schedules: [rule()] }}
      onClose={() => undefined}
      onReschedule={onReschedule}
      onDone={onDone}
    />,
    { session: await loggedSession(makeUser(rol)), now: () => ahora }
  );
  return { ...r, onDone, onReschedule };
}

function capturarTransicion() {
  const cuerpos: unknown[] = [];
  server.use(
    http.post("/api/appointments/appt-1/transitions", async ({ request }) => {
      cuerpos.push(await request.json());
      return HttpResponse.json(appointment());
    })
  );
  return cuerpos;
}

const TIMELINE = "/api/appointments/appt-1/reminders";
const REENVIO = "/api/appointments/appt-1/reminders/t_24h/whatsapp/resend";

describe("AppointmentDetail", () => {
  beforeEach(() => {
    server.use(http.get(TIMELINE, () => HttpResponse.json(timeline([]))));
  });

  it("muestra el turno en la hora de la clínica con su contacto", async () => {
    await abrir(appointment({ notes: "Trae estudios ficticios" }));
    expect(screen.getByText("lun 07/01 10:00–10:30")).toBeInTheDocument();
    expect(screen.getByText("Dra. Ficticia Uno · Sillón 1")).toBeInTheDocument();
    expect(screen.getByText("+5491155550001")).toBeInTheDocument();
    expect(screen.getByText("Trae estudios ficticios")).toBeInTheDocument();
  });

  it("recepción confirma un pendiente", async () => {
    const cuerpos = capturarTransicion();
    const { user, onDone } = await abrir(appointment({ status: "pending" }));

    await user.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Turno confirmado"));
    expect(cuerpos).toEqual([{ to: "confirmed" }]);
  });

  it("cancelar exige motivo y manda la nota", async () => {
    const cuerpos = capturarTransicion();
    const { user, onDone } = await abrir(appointment());

    await user.click(screen.getByRole("button", { name: "Cancelar turno" }));
    await user.click(screen.getByRole("button", { name: "Confirmar cancelación" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Elegí el motivo de la cancelación");
    expect(cuerpos).toEqual([]);

    await user.selectOptions(screen.getByLabelText("Motivo"), "paciente");
    await user.type(screen.getByLabelText("Nota"), "Avisó por teléfono");
    await user.click(screen.getByRole("button", { name: "Confirmar cancelación" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Turno cancelado"));
    expect(cuerpos).toEqual([{ to: "cancelled", reason: "paciente", note: "Avisó por teléfono" }]);
  });

  it("asistencia desde la hora del turno, con la diferencia explicada", async () => {
    const cuerpos = capturarTransicion();
    const { user, onDone } = await abrir(appointment(), { ahora: DESPUES });

    expect(screen.getByText(/Ausente: avisó\. No-show: no avisó\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar turno" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "No-show (no avisó)" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Asistencia registrada: No vino"));
    expect(cuerpos).toEqual([{ to: "no_show" }]);
  });

  it("un turno de mañana no ofrece asistencia", async () => {
    await abrir(
      appointment({ starts_at: "2030-01-08T13:00:00Z", ends_at: "2030-01-08T13:30:00Z" })
    );
    for (const nombre of ["Presente", "Ausente (avisó)", "No-show (no avisó)"]) {
      expect(screen.queryByRole("button", { name: nombre })).not.toBeInTheDocument();
    }
  });

  it("el odontólogo solo marca asistencia y no ve contacto", async () => {
    const turno = appointment({ patient: { id: "pat-1", full_name: "Ana Prueba Ejemplo" } });
    await abrir(turno, { rol: "odontologo", ahora: DESPUES });

    expect(screen.getByRole("button", { name: "Presente" })).toBeInTheDocument();
    for (const nombre of ["Confirmar", "Reprogramar", "Cancelar turno"]) {
      expect(screen.queryByRole("button", { name: nombre })).not.toBeInTheDocument();
    }
    expect(screen.queryByText(/\+549/)).not.toBeInTheDocument();
  });

  it("si la API rechaza, muestra el motivo y no cierra", async () => {
    server.use(
      http.post("/api/appointments/appt-1/transitions", () =>
        HttpResponse.json({ detail: "appointment_started" }, { status: 409 })
      )
    );
    const { user, onDone } = await abrir(appointment({ status: "pending" }));

    await user.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("El turno ya empezó");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("reprogramar abre el formulario con el turno", async () => {
    const turno = appointment();
    const { user, onReschedule } = await abrir(turno);
    await user.click(screen.getByRole("button", { name: "Reprogramar" }));
    expect(onReschedule).toHaveBeenCalledWith(turno);
  });

  describe("recordatorios (C-11)", () => {
    function fallido() {
      let lecturas = 0;
      server.use(
        http.get(TIMELINE, () => {
          lecturas += 1;
          return HttpResponse.json(
            timeline([
              lecturas === 1
                ? reminderStep({ status: "failed", last_error: "meta_131026" })
                : reminderStep({
                    status: "scheduled",
                    can_resend: false,
                    resend_blocked_reason: "resend_cooldown"
                  })
            ])
          );
        })
      );
      return { lecturas: () => lecturas };
    }

    it("el detalle incluye el timeline", async () => {
      server.use(http.get(TIMELINE, () => HttpResponse.json(timeline())));
      await abrir(appointment());

      expect(await screen.findByRole("region", { name: "Recordatorios" })).toBeInTheDocument();
      expect(await screen.findByText("Entregado")).toBeInTheDocument();
    });

    it("recepción reenvía: 202 muestra Reenvío en cola y refresca", async () => {
      const red = fallido();
      server.use(
        http.post(REENVIO, () =>
          HttpResponse.json(
            {
              job_id: "job-1",
              status: "scheduled",
              available_at: "2030-01-07T11:00:00Z",
              manual_resends_today: 1,
              cooldown_until: "2030-01-07T11:01:00Z"
            },
            { status: 202 }
          )
        )
      );
      const { user } = await abrir(appointment());

      await user.click(await screen.findByRole("button", { name: "Reenviar 24 h antes · WhatsApp" }));

      expect(await screen.findByText("Reenvío en cola")).toBeInTheDocument();
      await waitFor(() => expect(red.lecturas()).toBe(2));
      expect(await screen.findByText("Programado", { selector: "span" })).toBeInTheDocument();
    });

    it("409 resend_cooldown muestra los segundos que faltan", async () => {
      fallido();
      server.use(
        http.post(REENVIO, () =>
          HttpResponse.json({ detail: "resend_cooldown", retry_after_s: 42 }, { status: 409 })
        )
      );
      const { user } = await abrir(appointment());

      await user.click(await screen.findByRole("button", { name: "Reenviar 24 h antes · WhatsApp" }));

      expect(await screen.findByText(/Esperá 42 s antes de volver a reenviar/)).toBeInTheDocument();
    });

    it("doble clic manda un solo pedido", async () => {
      fallido();
      let pedidos = 0;
      server.use(
        http.post(REENVIO, async () => {
          pedidos += 1;
          await new Promise((r) => setTimeout(r, 50));
          return HttpResponse.json({ detail: "resend_cooldown", retry_after_s: 60 }, { status: 409 });
        })
      );
      const { user } = await abrir(appointment());
      const boton = await screen.findByRole("button", { name: "Reenviar 24 h antes · WhatsApp" });

      await user.dblClick(boton);

      await screen.findByText(/Esperá 60 s/);
      expect(pedidos).toBe(1);
    });

    it("el odontólogo ve el timeline sin Reenviar ni Confirmar", async () => {
      server.use(
        http.get(TIMELINE, () => HttpResponse.json(timeline([reminderStep({ can_resend: false })])))
      );
      await abrir(appointment({ status: "pending" }), { rol: "odontologo" });

      await screen.findByText("Entregado");
      expect(screen.queryByRole("button", { name: /Reenviar/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Confirmar" })).not.toBeInTheDocument();
    });

    it("si el timeline falla, el resto del turno sigue visible", async () => {
      server.use(http.get(TIMELINE, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
      await abrir(appointment());

      expect(
        await screen.findByText(/No se pudo cargar el historial de recordatorios/)
      ).toBeInTheDocument();
      expect(screen.getByText("lun 07/01 10:00–10:30")).toBeInTheDocument();
    });
  });
});
