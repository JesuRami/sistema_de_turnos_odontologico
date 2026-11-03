import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { Patient } from "../../shared/api/types";
import { appointment, chair, professional, rule, TZ } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import AppointmentForm, { type FormSeed } from "./AppointmentForm";
import type { AgendaContext } from "./context";

const CONTEXTO: AgendaContext = {
  tz: TZ,
  role: "recepcion",
  professionals: [professional()],
  chairs: [chair()],
  schedules: [rule()]
};

const ANA: Patient = {
  id: "pat-1",
  full_name: "Ana Prueba Ejemplo",
  phone_e164: "+5491155550001",
  email: null,
  dni: null,
  whatsapp_opt_in: false
};

async function abrir(seed: FormSeed = { day: "2030-01-07", time: "10:00" }, contexto = CONTEXTO) {
  const onDone = vi.fn();
  const onClose = vi.fn();
  const r = renderWithProviders(
    <AppointmentForm seed={seed} context={contexto} onClose={onClose} onDone={onDone} />,
    { session: await loggedSession(makeUser(contexto.role)) }
  );
  return { ...r, onDone, onClose };
}

function buscarDevuelve(items: Patient[]) {
  return http.get("/api/patients", () => HttpResponse.json({ items }));
}

async function elegirAna(user: Awaited<ReturnType<typeof abrir>>["user"]) {
  await user.type(screen.getByLabelText("Buscar paciente"), "ana prueba");
  await user.click(await screen.findByRole("button", { name: /Elegir Ana Prueba Ejemplo/ }));
}

describe("AppointmentForm — alta", () => {
  it("crea el turno para un paciente existente en el horario elegido", async () => {
    let enviado: unknown = null;
    server.use(
      buscarDevuelve([ANA]),
      http.post("/api/appointments", async ({ request }) => {
        enviado = await request.json();
        return HttpResponse.json(appointment(), { status: 201 });
      })
    );
    const { user, onDone } = await abrir();

    await elegirAna(user);
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Turno creado: lun 07/01 10:00"));
    expect(enviado).toEqual({
      patient_id: "pat-1",
      professional_id: "prof-1",
      chair_id: "chair-1",
      starts_at: "2030-01-07T13:00:00.000Z"
    });
  });

  it("alta rápida de paciente dentro del formulario", async () => {
    let alta: unknown = null;
    server.use(
      buscarDevuelve([]),
      http.post("/api/patients", async ({ request }) => {
        alta = await request.json();
        return HttpResponse.json({ ...ANA, id: "pat-9", full_name: "Bruno Ficticio" }, { status: 201 });
      })
    );
    const { user } = await abrir();

    await user.type(screen.getByLabelText("Buscar paciente"), "bruno ficticio");
    expect(await screen.findByText("Sin resultados")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Paciente nuevo" }));
    await user.type(screen.getByLabelText("Nombre y apellido"), "Bruno Ficticio");
    await user.type(screen.getByLabelText("Teléfono"), "011 15 5550-0009");
    await user.click(screen.getByRole("button", { name: "Crear paciente" }));

    expect(await screen.findByText("Paciente: Bruno Ficticio")).toBeInTheDocument();
    expect(alta).toEqual({ full_name: "Bruno Ficticio", phone: "011 15 5550-0009" });
  });

  it("si el alta es duplicada ofrece usar el existente", async () => {
    server.use(
      buscarDevuelve([]),
      http.post("/api/patients", () =>
        HttpResponse.json({ detail: "patient_duplicate", patient_id: "pat-1" }, { status: 409 })
      ),
      http.get("/api/patients/pat-1", () =>
        HttpResponse.json({ ...ANA, archived_at: null, merged_into_patient_id: null, appointments_count: 3 })
      )
    );
    const { user } = await abrir();

    await user.type(screen.getByLabelText("Buscar paciente"), "ana prueba");
    await user.click(await screen.findByRole("button", { name: "Paciente nuevo" }));
    await user.type(screen.getByLabelText("Nombre y apellido"), "Ana Prueba Ejemplo");
    await user.type(screen.getByLabelText("Teléfono"), "011 15 5550-0001");
    await user.click(screen.getByRole("button", { name: "Crear paciente" }));
    await user.click(await screen.findByRole("button", { name: "Usar el paciente existente" }));

    expect(await screen.findByText("Paciente: Ana Prueba Ejemplo")).toBeInTheDocument();
  });

  it("sin paciente no envía", async () => {
    const { user } = await abrir();
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Elegí o cargá un paciente");
  });
});

describe("AppointmentForm — colisión", () => {
  const ocupado = () =>
    HttpResponse.json(
      {
        detail: "slot_taken",
        conflicts: ["appt-otro"],
        alternatives: [
          {
            starts_at: "2030-01-07T14:00:00+00:00",
            ends_at: "2030-01-07T14:30:00+00:00",
            professional_id: "prof-1",
            chair_id: "chair-1"
          },
          {
            starts_at: "2030-01-07T14:30:00+00:00",
            ends_at: "2030-01-07T15:00:00+00:00",
            professional_id: "prof-1",
            chair_id: "chair-1"
          }
        ]
      },
      { status: 409 }
    );

  it("ofrece los alternativos y crea en el elegido", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      buscarDevuelve([ANA]),
      http.post("/api/appointments", async ({ request }) => {
        cuerpos.push(await request.json());
        return cuerpos.length === 1 ? ocupado() : HttpResponse.json(appointment(), { status: 201 });
      })
    );
    const { user, onDone } = await abrir();

    await elegirAna(user);
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));
    expect(await screen.findByText("El horario ya está ocupado")).toBeInTheDocument();
    expect(screen.queryByText("appt-otro")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Usar lun 07/01 11:00" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(cuerpos[1]).toMatchObject({ starts_at: "2030-01-07T14:00:00.000Z", chair_id: "chair-1" });
  });

  it("crea un sobreturno con motivo", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      buscarDevuelve([ANA]),
      http.post("/api/appointments", async ({ request }) => {
        cuerpos.push(await request.json());
        return cuerpos.length === 1 ? ocupado() : HttpResponse.json(appointment(), { status: 201 });
      })
    );
    const { user, onDone } = await abrir();

    await elegirAna(user);
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));
    await user.click(await screen.findByRole("button", { name: "Confirmar sobreturno" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Indicá el motivo del sobreturno");
    await user.type(screen.getByLabelText("Motivo del sobreturno"), "Urgencia ficticia");
    await user.click(screen.getByRole("button", { name: "Confirmar sobreturno" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(cuerpos[1]).toMatchObject({
      is_overbooking: true,
      overbooking_reason: "Urgencia ficticia",
      starts_at: "2030-01-07T13:00:00.000Z"
    });
  });

  it("informa el tope de sobreturnos", async () => {
    let n = 0;
    server.use(
      buscarDevuelve([ANA]),
      http.post("/api/appointments", () => {
        n += 1;
        return n === 1
          ? ocupado()
          : HttpResponse.json({ detail: "overbooking_limit" }, { status: 409 });
      })
    );
    const { user } = await abrir();

    await elegirAna(user);
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));
    await user.type(await screen.findByLabelText("Motivo del sobreturno"), "Urgencia ficticia");
    await user.click(screen.getByRole("button", { name: "Confirmar sobreturno" }));

    expect(await screen.findByText(/tope diario de sobreturnos/)).toBeInTheDocument();
  });

  it("una hora inexistente por cambio de horario no se envía", async () => {
    const { user } = await abrir(
      { day: "2030-03-31", time: "02:30" },
      { ...CONTEXTO, tz: "Europe/Madrid" }
    );
    server.use(buscarDevuelve([ANA]));
    await elegirAna(user);
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Esa hora no existe en la zona de la clínica");
  });
});

describe("AppointmentForm — reprogramar", () => {
  it("envía solo los cambios y ante rechazo no cierra", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.patch("/api/appointments/appt-1", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json({ detail: "slot_taken", conflicts: [], alternatives: [] }, { status: 409 });
      })
    );
    const { user, onDone } = await abrir({ day: "2030-01-07", appointment: appointment() });

    expect(screen.getByText("Paciente: Ana Prueba Ejemplo")).toBeInTheDocument();
    const hora = screen.getByLabelText("Hora");
    await user.clear(hora);
    await user.type(hora, "11:00");
    await user.click(screen.getByRole("button", { name: "Guardar turno" }));

    expect(await screen.findByText("El horario ya está ocupado")).toBeInTheDocument();
    expect(screen.getByText("No hay horarios libres en los próximos 14 días")).toBeInTheDocument();
    expect(cuerpos).toEqual([{ starts_at: "2030-01-07T14:00:00.000Z" }]);
    expect(onDone).not.toHaveBeenCalled();
  });
});
