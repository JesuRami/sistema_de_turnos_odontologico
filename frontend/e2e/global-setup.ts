/**
 * Setup del E2E por API real: admin con clave definitiva, recursos y paciente
 * propios de esta corrida (sufijo único, así reejecutar no choca con lo previo),
 * una recepcionista con clave provisoria y 500 turnos en la semana siguiente para
 * medir la vista semana (US-010 CA-3). Todo sintético (regla 13).
 */
import { request, type APIRequestContext } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { e2eEnv, STATE_PATH, type E2EState } from "./env";

const TZ = "America/Argentina/Buenos_Aires";
const PERF_PARES = 3;
const PERF_TURNOS = 500;

interface Paged<T> {
  items: T[];
}

async function json<T>(r: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  if (!r.ok()) {
    throw new Error(`${r.url()} → ${r.status()} ${await r.text()}`);
  }
  return (await r.json()) as T;
}

async function adminToken(api: APIRequestContext): Promise<string> {
  const E2E = e2eEnv();
  const definitiva = await api.post("/api/auth/login", {
    data: { email: E2E.adminEmail, password: E2E.password }
  });
  if (definitiva.ok()) {
    return ((await definitiva.json()) as { access_token: string }).access_token;
  }
  const provisoria = await json<{ access_token: string }>(
    await api.post("/api/auth/login", { data: { email: E2E.adminEmail, password: E2E.adminProvisional } })
  );
  await json(
    await api.post("/api/auth/change-password", {
      headers: { Authorization: `Bearer ${provisoria.access_token}` },
      data: { current_password: E2E.adminProvisional, new_password: E2E.password }
    })
  );
  return provisoria.access_token;
}

/** Fecha local de la clínica (`YYYY-MM-DD`) a `dias` de hoy. */
function fechaLocal(dias: number): string {
  const d = new Date(Date.now() + dias * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(d);
}

/** Buenos Aires no tiene horario de verano: offset fijo -03:00. */
const instante = (fecha: string, hora: string): string => `${fecha}T${hora}:00-03:00`;

export default async function globalSetup(): Promise<void> {
  const E2E = e2eEnv();
  const api = await request.newContext({ baseURL: E2E.baseURL });
  const token = await adminToken(api);
  const auth = { Authorization: `Bearer ${token}` };
  const run = Date.now().toString(36);
  const hoy = fechaLocal(0);

  async function recurso(
    nombre: string,
    desde = "08:00",
    hasta = "20:00"
  ): Promise<{ professional: string; chair: string }> {
    const prof = await json<{ id: string }>(
      await api.post("/api/professionals", { headers: auth, data: { display_name: nombre } })
    );
    const sillon = await json<{ id: string }>(
      await api.post("/api/chairs", { headers: auth, data: { name: `Sillón ${nombre}` } })
    );
    for (let weekday = 0; weekday < 7; weekday += 1) {
      await json(
        await api.post("/api/schedules", {
          headers: auth,
          data: {
            professional_id: prof.id,
            chair_id: sillon.id,
            weekday,
            start_time: desde,
            end_time: hasta,
            slot_duration_min: 30,
            valid_from: hoy
          }
        })
      );
    }
    return { professional: prof.id, chair: sillon.id };
  }

  async function paciente(nombre: string): Promise<string> {
    const telefono = `+549115550${String(Math.floor(Math.random() * 10_000)).padStart(4, "0")}`;
    const p = await json<{ id: string }>(
      await api.post("/api/patients", { headers: auth, data: { full_name: nombre, phone: telefono } })
    );
    return p.id;
  }

  // Circuito crítico: un profesional, un sillón y un paciente de esta corrida.
  const nombreProf = `Dra. E2E ${run}`;
  // Franja de todo el día: siempre hay alternativos futuros (excluyen lo ya pasado).
  await recurso(nombreProf, "00:00", "23:59");
  const nombrePaciente = `Paciente E2E Ficticio ${run}`;
  await paciente(nombrePaciente);
  const receptionEmail = `recepcion.e2e.${run}@example.com`;
  const receptionProvisional = `${E2E.password}-provisoria`;
  await json(
    await api.post("/api/users", {
      headers: auth,
      data: { email: receptionEmail, password: receptionProvisional, role: "recepcion" }
    })
  );

  // Rendimiento: 500 turnos en la semana siguiente (lunes a domingo).
  const perfPatient = `Paciente Perf ${run}`;
  const perfPatientId = await paciente(perfPatient);
  const pares = [];
  for (let i = 0; i < PERF_PARES; i += 1) {
    pares.push(await recurso(`Dr. Perf ${run}-${i}`));
  }
  const hoyLocal = new Date(`${hoy}T12:00:00Z`);
  const diasHastaLunes = ((7 - ((hoyLocal.getUTCDay() + 6) % 7)) % 7) || 7;
  const altas: (() => Promise<unknown>)[] = [];
  for (let dia = 0; dia < 7 && altas.length < PERF_TURNOS; dia += 1) {
    const fecha = fechaLocal(diasHastaLunes + dia);
    for (let slot = 0; slot < 24 && altas.length < PERF_TURNOS; slot += 1) {
      const hora = `${String(8 + Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 === 0 ? "00" : "30"}`;
      for (const par of pares) {
        if (altas.length >= PERF_TURNOS) break;
        altas.push(() =>
          api
            .post("/api/appointments", {
              headers: auth,
              data: {
                patient_id: perfPatientId,
                professional_id: par.professional,
                chair_id: par.chair,
                starts_at: instante(fecha, hora)
              }
            })
            .then((r) => json(r))
        );
      }
    }
  }
  for (let i = 0; i < altas.length; i += 10) {
    await Promise.all(altas.slice(i, i + 10).map((alta) => alta()));
  }

  const estado: E2EState = {
    run,
    professional: nombreProf,
    chair: `Sillón ${nombreProf}`,
    patient: nombrePaciente,
    receptionEmail,
    receptionProvisional,
    perfPatient,
    perfAppointments: altas.length
  };
  writeFileSync(STATE_PATH, JSON.stringify(estado, null, 2));
  const usuarios = await json<Paged<unknown>>(await api.get("/api/users", { headers: auth }));
  if (usuarios.items.length === 0) {
    throw new Error("setup E2E incompleto");
  }
  await api.dispose();
}
