/**
 * Detalle de un turno con sus acciones (US-012/US-013): confirmar, reprogramar,
 * cancelar con motivo y asistencia. Los botones salen de `allowedActions`; si la
 * API igual rechaza, se muestra su motivo y el turno queda como estaba.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { queryKeys } from "../../shared/api/queries";
import type {
  Appointment,
  CancellationReason,
  TransitionRequest,
  TransitionTarget
} from "../../shared/api/types";
import { useClock } from "../../shared/time/now";
import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";
import { Alert, Button, Modal, SelectField, TextArea } from "../../shared/ui";
import { allowedActions } from "./allowedActions";
import type { AgendaContext } from "./context";
import { CANCELLATION_REASON_LABEL, STATUS_LABEL, STATUS_STYLE } from "./labels";

const MOTIVOS = Object.keys(CANCELLATION_REASON_LABEL) as CancellationReason[];

const EXITO: Record<TransitionTarget, string> = {
  confirmed: "Turno confirmado",
  cancelled: "Turno cancelado",
  present: `Asistencia registrada: ${STATUS_LABEL.present}`,
  absent: `Asistencia registrada: ${STATUS_LABEL.absent}`,
  no_show: `Asistencia registrada: ${STATUS_LABEL.no_show}`
};

function AppointmentDetail({
  appointment,
  context,
  onClose,
  onReschedule,
  onDone
}: {
  appointment: Appointment;
  context: AgendaContext;
  onClose: () => void;
  onReschedule: (appointment: Appointment) => void;
  onDone: (message: string) => void;
}): JSX.Element {
  const queryClient = useQueryClient();
  const clock = useClock();
  const { tz } = context;
  const acciones = allowedActions(context.role, appointment, clock(), tz);
  const [cancelando, setCancelando] = useState(false);
  const [motivo, setMotivo] = useState<CancellationReason | "">("");
  const [nota, setNota] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const inicio = new Date(appointment.starts_at);
  const fin = new Date(appointment.ends_at);
  const profesional = context.professionals.find((p) => p.id === appointment.professional_id);
  const sillon = context.chairs.find((c) => c.id === appointment.chair_id);
  const contacto = [appointment.patient.phone_e164, appointment.patient.email].filter(
    (c): c is string => typeof c === "string" && c !== ""
  );

  async function transicion(body: TransitionRequest): Promise<void> {
    setError(null);
    setEnviando(true);
    try {
      await apiFetch<Appointment>(`/api/appointments/${appointment.id}/transitions`, {
        method: "POST",
        body
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.appointments });
      onDone(EXITO[body.to]);
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setEnviando(false);
    }
  }

  function confirmarCancelacion(): void {
    if (motivo === "") {
      setError("Elegí el motivo de la cancelación");
      return;
    }
    const body: TransitionRequest = { to: "cancelled", reason: motivo };
    if (nota.trim() !== "") {
      body.note = nota.trim();
    }
    void transicion(body);
  }

  const asistencia = acciones.present || acciones.absent || acciones.noShow;

  return (
    <Modal title={`Turno de ${appointment.patient.full_name}`} onClose={onClose}>
      <dl className="mb-4 space-y-1 text-sm">
        <div>
          <dt className="sr-only">Horario</dt>
          <dd className="font-medium">
            {`${formatDayLabel(dateKeyOf(inicio, tz))} ${formatTime(inicio, tz)}–${formatTime(fin, tz)}`}
          </dd>
        </div>
        <div>
          <dt className="sr-only">Profesional y sillón</dt>
          <dd>{`${profesional?.display_name ?? "Profesional"} · ${sillon?.name ?? "Sillón"}`}</dd>
        </div>
        <div className="flex flex-wrap gap-1">
          <dt className="sr-only">Estado</dt>
          <dd className={`rounded px-1.5 text-xs ${STATUS_STYLE[appointment.status]}`}>
            {STATUS_LABEL[appointment.status]}
          </dd>
          {appointment.is_overbooking && (
            <dd className="rounded bg-violet-100 px-1.5 text-xs text-violet-900">
              Sobreturno{appointment.overbooking_reason !== null ? `: ${appointment.overbooking_reason}` : ""}
            </dd>
          )}
        </div>
        {contacto.map((c) => (
          <div key={c}>
            <dt className="sr-only">Contacto</dt>
            <dd>{c}</dd>
          </div>
        ))}
        {appointment.notes !== null && (
          <div>
            <dt className="sr-only">Notas</dt>
            <dd className="italic">{appointment.notes}</dd>
          </div>
        )}
        {appointment.cancellation_reason !== null && (
          <div>
            <dt className="sr-only">Cancelación</dt>
            <dd>
              Cancelado: {CANCELLATION_REASON_LABEL[appointment.cancellation_reason]}
              {appointment.cancellation_note !== null ? ` — ${appointment.cancellation_note}` : ""}
            </dd>
          </div>
        )}
      </dl>

      <div className="flex flex-wrap gap-2">
        {acciones.confirm && (
          <Button onClick={() => void transicion({ to: "confirmed" })} disabled={enviando}>
            Confirmar
          </Button>
        )}
        {acciones.reschedule && (
          <Button variant="secondary" onClick={() => onReschedule(appointment)}>
            Reprogramar
          </Button>
        )}
        {acciones.cancel && !cancelando && (
          <Button variant="danger" onClick={() => setCancelando(true)}>
            Cancelar turno
          </Button>
        )}
      </div>

      {asistencia && (
        <div className="mt-3 space-y-2">
          <p className="text-xs opacity-80">Ausente: avisó. No-show: no avisó.</p>
          <div className="flex flex-wrap gap-2">
            {acciones.present && (
              <Button onClick={() => void transicion({ to: "present" })} disabled={enviando}>
                Presente
              </Button>
            )}
            {acciones.absent && (
              <Button variant="secondary" onClick={() => void transicion({ to: "absent" })} disabled={enviando}>
                Ausente (avisó)
              </Button>
            )}
            {acciones.noShow && (
              <Button variant="secondary" onClick={() => void transicion({ to: "no_show" })} disabled={enviando}>
                No-show (no avisó)
              </Button>
            )}
          </div>
        </div>
      )}

      {cancelando && (
        <fieldset className="mt-4 space-y-2 rounded border border-rose-200 p-3">
          <legend className="px-1 text-sm font-medium">Cancelar turno</legend>
          <SelectField
            label="Motivo"
            value={motivo}
            onChange={(e) => setMotivo(e.target.value as CancellationReason | "")}
          >
            <option value="">Elegí un motivo</option>
            {MOTIVOS.map((m) => (
              <option key={m} value={m}>
                {CANCELLATION_REASON_LABEL[m]}
              </option>
            ))}
          </SelectField>
          <TextArea label="Nota" value={nota} maxLength={500} onChange={(e) => setNota(e.target.value)} />
          <div className="flex gap-2">
            <Button variant="danger" onClick={confirmarCancelacion} disabled={enviando}>
              Confirmar cancelación
            </Button>
            <Button variant="ghost" onClick={() => setCancelando(false)}>
              Volver
            </Button>
          </div>
        </fieldset>
      )}

      {error !== null && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
    </Modal>
  );
}

export default AppointmentDetail;
