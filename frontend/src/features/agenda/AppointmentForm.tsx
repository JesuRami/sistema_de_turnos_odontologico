/**
 * Formulario de turno (US-011/US-012, Flujo 4 paso 2): crear o reprogramar.
 * Ante `409 slot_taken` ofrece los alternativos de la API y, a admin/recepción,
 * el sobreturno explícito con motivo. No hay actualización optimista (D7).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { queryKeys } from "../../shared/api/queries";
import type {
  Alternative,
  Appointment,
  AppointmentCreate,
  AppointmentUpdate
} from "../../shared/api/types";
import {
  dateKeyOf,
  formatDayLabel,
  formatTime,
  fromZonedWallTime,
  weekdayOf,
  type DateKey
} from "../../shared/time/zoned";
import { Alert, Button, Modal, SelectField, TextArea, TextField } from "../../shared/ui";
import { PatientSearch, type PickedPatient } from "../patients/PatientPicker";
import type { AgendaContext } from "./context";

export interface FormSeed {
  day: DateKey;
  time?: string;
  chairId?: string;
  professionalId?: string;
  /** Presente = reprogramar ese turno. */
  appointment?: Appointment;
}

interface Target {
  startsAt: Date;
  professionalId: string;
  chairId: string;
}

function isAlternative(value: unknown): value is Alternative {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return typeof v.starts_at === "string" && typeof v.professional_id === "string" && typeof v.chair_id === "string";
}

function alternativesOf(error: ApiError): Alternative[] {
  const lista = error.extra.alternatives;
  return Array.isArray(lista) ? lista.filter(isAlternative) : [];
}

/** Profesional por defecto: el que atiende en ese sillón ese día, o el primero. */
function defaultProfessional(seed: FormSeed, context: AgendaContext): string {
  if (seed.appointment !== undefined) {
    return seed.appointment.professional_id;
  }
  if (seed.professionalId !== undefined) {
    return seed.professionalId;
  }
  const conRegla = context.schedules.find(
    (r) => r.active && r.weekday === weekdayOf(seed.day) && (seed.chairId === undefined || r.chair_id === seed.chairId)
  );
  return conRegla?.professional_id ?? context.professionals[0]?.id ?? "";
}

function AppointmentForm({
  seed,
  context,
  onClose,
  onDone
}: {
  seed: FormSeed;
  context: AgendaContext;
  onClose: () => void;
  onDone: (message: string) => void;
}): JSX.Element {
  const queryClient = useQueryClient();
  const original = seed.appointment;
  const { tz } = context;
  const [patient, setPatient] = useState<PickedPatient | null>(
    original !== undefined ? original.patient : null
  );
  const [professionalId, setProfessionalId] = useState(defaultProfessional(seed, context));
  const [chairId, setChairId] = useState(
    original?.chair_id ?? seed.chairId ?? context.chairs[0]?.id ?? ""
  );
  const [day, setDay] = useState<DateKey>(seed.day);
  const [time, setTime] = useState(
    seed.time ?? (original !== undefined ? formatTime(new Date(original.starts_at), tz) : "09:00")
  );
  const [duration, setDuration] = useState("");
  const [notes, setNotes] = useState(original?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<{ target: Target; alternatives: Alternative[] } | null>(null);
  const [motivo, setMotivo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const deMostrador = context.role === "admin" || context.role === "recepcion";

  function etiqueta(instante: Date): string {
    return `${formatDayLabel(dateKeyOf(instante, tz))} ${formatTime(instante, tz)}`;
  }

  async function enviar(target: Target, overbookingReason?: string): Promise<void> {
    setError(null);
    setEnviando(true);
    try {
      const duracion = duration.trim() === "" ? undefined : Number(duration);
      if (original === undefined) {
        if (patient === null) {
          setError("Elegí o cargá un paciente");
          return;
        }
        const body: AppointmentCreate = {
          patient_id: patient.id,
          professional_id: target.professionalId,
          chair_id: target.chairId,
          starts_at: target.startsAt.toISOString()
        };
        if (duracion !== undefined) {
          body.duration_min = duracion;
        }
        if (notes.trim() !== "") {
          body.notes = notes.trim();
        }
        if (overbookingReason !== undefined) {
          body.is_overbooking = true;
          body.overbooking_reason = overbookingReason;
        }
        await apiFetch<Appointment>("/api/appointments", { method: "POST", body });
      } else {
        const body: AppointmentUpdate = {};
        if (target.startsAt.getTime() !== new Date(original.starts_at).getTime()) {
          body.starts_at = target.startsAt.toISOString();
        }
        if (target.professionalId !== original.professional_id) {
          body.professional_id = target.professionalId;
        }
        if (target.chairId !== original.chair_id) {
          body.chair_id = target.chairId;
        }
        if (duracion !== undefined) {
          body.duration_min = duracion;
        }
        if (notes.trim() !== (original.notes ?? "")) {
          body.notes = notes.trim() === "" ? null : notes.trim();
        }
        if (overbookingReason !== undefined) {
          body.is_overbooking = true;
          body.overbooking_reason = overbookingReason;
        }
        await apiFetch<Appointment>(`/api/appointments/${original.id}`, { method: "PATCH", body });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.appointments }),
        queryClient.invalidateQueries({ queryKey: queryKeys.blocks })
      ]);
      onDone(`${original === undefined ? "Turno creado" : "Turno reprogramado"}: ${etiqueta(target.startsAt)}`);
    } catch (e) {
      if (e instanceof ApiError && e.detail === "slot_taken") {
        setOcupado({ target, alternatives: alternativesOf(e) });
      } else {
        setError(messageFor(e));
      }
    } finally {
      setEnviando(false);
    }
  }

  function onSubmit(event: FormEvent): void {
    event.preventDefault();
    setOcupado(null);
    if (original === undefined && patient === null) {
      setError("Elegí o cargá un paciente");
      return;
    }
    const startsAt = fromZonedWallTime(day, time, tz);
    if (startsAt === null) {
      setError("Esa hora no existe en la zona de la clínica (cambio de horario)");
      return;
    }
    void enviar({ startsAt, professionalId, chairId });
  }

  function confirmarSobreturno(): void {
    if (ocupado === null) {
      return;
    }
    if (motivo.trim() === "") {
      setError("Indicá el motivo del sobreturno");
      return;
    }
    void enviar(ocupado.target, motivo.trim());
  }

  return (
    <Modal title={original === undefined ? "Nuevo turno" : "Reprogramar turno"} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-3" noValidate>
        {patient !== null ? (
          <div className="flex items-center justify-between rounded bg-dental-50 px-3 py-2 text-sm">
            <span>Paciente: {patient.full_name}</span>
            {original === undefined && (
              <Button variant="ghost" onClick={() => setPatient(null)}>
                Cambiar
              </Button>
            )}
          </div>
        ) : (
          <PatientSearch onPick={setPatient} />
        )}

        <div className="grid grid-cols-2 gap-2">
          <SelectField label="Profesional" value={professionalId} onChange={(e) => setProfessionalId(e.target.value)}>
            {context.professionals.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Sillón" value={chairId} onChange={(e) => setChairId(e.target.value)}>
            {context.chairs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
          <TextField label="Fecha" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          <TextField label="Hora" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          <TextField
            label="Duración (min)"
            type="number"
            min={5}
            max={480}
            placeholder="Según la plantilla"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
          />
        </div>
        <TextArea label="Notas" value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} />

        {ocupado !== null && (
          <section aria-label="Horario ocupado" className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
            <p className="font-medium">El horario ya está ocupado</p>
            {ocupado.alternatives.length === 0 ? (
              <p>No hay horarios libres en los próximos 14 días</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {ocupado.alternatives.map((alt) => {
                  const inicio = new Date(alt.starts_at);
                  return (
                    <Button
                      key={alt.starts_at}
                      variant="secondary"
                      onClick={() =>
                        void enviar({ startsAt: inicio, professionalId: alt.professional_id, chairId: alt.chair_id })
                      }
                    >
                      Usar {etiqueta(inicio)}
                    </Button>
                  );
                })}
              </div>
            )}
            {deMostrador && (
              <div className="space-y-2 border-t border-amber-300 pt-2">
                <TextArea
                  label="Motivo del sobreturno"
                  value={motivo}
                  maxLength={500}
                  onChange={(e) => setMotivo(e.target.value)}
                />
                <Button variant="secondary" onClick={confirmarSobreturno} disabled={enviando}>
                  Confirmar sobreturno
                </Button>
              </div>
            )}
          </section>
        )}

        {error !== null && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={enviando}>
            Guardar turno
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default AppointmentForm;
