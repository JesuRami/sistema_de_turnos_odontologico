/**
 * Timeline de recordatorios de un turno (C-11, US-032): por paso y canal, el estado efectivo
 * que calcula la API, sus fechas, intentos, último error y eventos. Admin y recepción pueden
 * reenviar un paso cuando la API lo permite (`can_resend`); la UI no inventa reglas: muestra el
 * motivo que devuelve la API. No hay datos de contacto ni ids del proveedor (regla 13).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { queryKeys, useReminderTimeline } from "../../shared/api/queries";
import type {
  ReminderChannel,
  ReminderEvent,
  ReminderTimelineStep,
  ReminderStepStatus,
  ResendAccepted,
  ResendBlockedReason
} from "../../shared/api/types";
import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";
import { Alert, Button } from "../../shared/ui";

const CANAL: Record<ReminderChannel, string> = { whatsapp: "WhatsApp", email: "Email" };

const ESTADO: Record<ReminderStepStatus, string> = {
  scheduled: "Programado",
  sending: "Enviando",
  sent: "Enviado",
  delivered: "Entregado",
  read: "Leído",
  failed: "Falló",
  skipped: "Omitido",
  cancelled: "Cancelado"
};

const ESTADO_ESTILO: Record<ReminderStepStatus, string> = {
  scheduled: "bg-slate-100 text-slate-800",
  sending: "bg-sky-100 text-sky-900",
  sent: "bg-sky-100 text-sky-900",
  delivered: "bg-emerald-100 text-emerald-900",
  read: "bg-emerald-200 text-emerald-950",
  failed: "bg-rose-100 text-rose-900",
  skipped: "bg-amber-100 text-amber-900",
  cancelled: "bg-slate-200 text-slate-700"
};

const EVENTO: Record<string, string> = {
  scheduled: "Programado",
  sent: "Enviado",
  delivered: "Entregado",
  read: "Leído",
  failed: "Falló",
  attempt_failed: "Intento fallido",
  skipped: "Omitido",
  cancelled: "Cancelado",
  escalated: "Derivado a email",
  lease_expired: "Reintento tras un corte",
  manual_resend: "Reenviado por recepción"
};

/** Motivos que se explican en lugar del botón; un paso futuro simplemente no lo muestra. */
const BLOQUEO: Partial<Record<ResendBlockedReason, (canal: ReminderChannel) => string>> = {
  no_consent: (c) =>
    c === "whatsapp" ? "El paciente no aceptó recibir WhatsApp" : "El paciente se dio de baja del email",
  no_recipient: (c) =>
    c === "whatsapp" ? "El paciente no tiene teléfono cargado" : "El paciente no tiene email cargado",
  appointment_started: () => "El turno ya empezó",
  appointment_inactive: () => "El turno ya no está vigente",
  reminder_in_flight: () => "Se está enviando en este momento",
  resend_cooldown: () => "Hay un reenvío en cola",
  resend_limit: () => "Se alcanzó el máximo de reenvíos de hoy"
};

export function stepLabel(step: string, channel: ReminderChannel): string {
  const horas = /^t_(\d+)h$/.exec(step);
  const paso = step === "created" ? "Alta" : horas !== null ? `${horas[1]} h antes` : step;
  return `${paso} · ${CANAL[channel]}`;
}

function cuando(iso: string, tz: string): string {
  const fecha = new Date(iso);
  return `${formatDayLabel(dateKeyOf(fecha, tz))} ${formatTime(fecha, tz)}`;
}

function Evento({ evento, tz }: { evento: ReminderEvent; tz: string }): JSX.Element {
  return (
    <li className={evento.previous ? "opacity-70" : undefined}>
      {`${EVENTO[evento.type] ?? evento.type} · ${cuando(evento.occurred_at, tz)}`}
      {evento.previous && <span className="ml-1 text-xs italic">envío anterior</span>}
    </li>
  );
}

function Paso({
  paso,
  tz,
  canAct,
  enviando,
  onResend
}: {
  paso: ReminderTimelineStep;
  tz: string;
  canAct: boolean;
  enviando: boolean;
  onResend: (paso: ReminderTimelineStep) => void;
}): JSX.Element {
  const etiqueta = stepLabel(paso.step, paso.channel);
  const motivo =
    paso.resend_blocked_reason !== null ? BLOQUEO[paso.resend_blocked_reason]?.(paso.channel) : undefined;
  const intentos = paso.attempts === 1 ? "1 intento" : `${paso.attempts} intentos`;
  return (
    <li aria-label={etiqueta} className="rounded border border-dental-600/20 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{etiqueta}</span>
        <span className={`rounded px-1.5 text-xs ${ESTADO_ESTILO[paso.status]}`}>{ESTADO[paso.status]}</span>
        {canAct && paso.can_resend && (
          <Button
            variant="secondary"
            className="ml-auto"
            aria-label={`Reenviar ${etiqueta}`}
            disabled={enviando}
            onClick={() => onResend(paso)}
          >
            Reenviar
          </Button>
        )}
      </div>
      <p className="mt-1 text-xs opacity-80">
        {`Programado: ${cuando(paso.scheduled_for, tz)}`}
        {paso.sent_at !== null && ` · Enviado: ${cuando(paso.sent_at, tz)}`}
        {` · ${intentos}`}
        {paso.last_error !== null && ` · Último error: ${paso.last_error}`}
      </p>
      {canAct && !paso.can_resend && motivo !== undefined && (
        <p className="mt-1 text-xs italic">{motivo}</p>
      )}
      {paso.events.length > 0 && (
        <ol className="mt-1 space-y-0.5 text-xs">
          {paso.events.map((e, i) => (
            <Evento key={`${e.type}-${e.occurred_at}-${i}`} evento={e} tz={tz} />
          ))}
        </ol>
      )}
    </li>
  );
}

function ReminderTimeline({
  appointmentId,
  tz,
  canAct
}: {
  appointmentId: string;
  tz: string;
  canAct: boolean;
}): JSX.Element {
  const queryClient = useQueryClient();
  const datos = useReminderTimeline(appointmentId);
  const [enviando, setEnviando] = useState(false);
  // Un ref y no solo estado: dos clics seguidos llegan antes de que React vuelva a dibujar.
  const enCurso = useRef(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reenviar(paso: ReminderTimelineStep): Promise<void> {
    if (enCurso.current) {
      return;
    }
    enCurso.current = true;
    setEnviando(true);
    setAviso(null);
    setError(null);
    try {
      await apiFetch<ResendAccepted>(
        `/api/appointments/${appointmentId}/reminders/${paso.step}/${paso.channel}/resend`,
        { method: "POST" }
      );
      setAviso("Reenvío en cola");
      await queryClient.invalidateQueries({ queryKey: [...queryKeys.reminders, appointmentId] });
      await queryClient.invalidateQueries({ queryKey: queryKeys.followUp });
    } catch (e) {
      const espera = e instanceof ApiError ? e.extra.retry_after_s : undefined;
      setError(
        e instanceof ApiError && e.detail === "resend_cooldown" && typeof espera === "number"
          ? `Esperá ${espera} s antes de volver a reenviar`
          : messageFor(e)
      );
    } finally {
      enCurso.current = false;
      setEnviando(false);
    }
  }

  return (
    <section aria-label="Recordatorios" className="mt-4">
      <h3 className="mb-2 text-sm font-semibold">Recordatorios</h3>
      {datos.isError && (
        <Alert>No se pudo cargar el historial de recordatorios. Reintentá en unos segundos.</Alert>
      )}
      {datos.isPending && <p className="text-xs">Cargando recordatorios…</p>}
      {datos.data !== undefined && datos.data.steps.length === 0 && (
        <p className="text-xs opacity-80">Este turno no tiene recordatorios programados.</p>
      )}
      {datos.data !== undefined && datos.data.steps.length > 0 && (
        <ul className="space-y-2">
          {datos.data.steps.map((p) => (
            <Paso
              key={`${p.step}-${p.channel}`}
              paso={p}
              tz={tz}
              canAct={canAct}
              enviando={enviando}
              onResend={(paso) => void reenviar(paso)}
            />
          ))}
        </ul>
      )}
      {aviso !== null && (
        <div className="mt-2">
          <Alert tone="success">{aviso}</Alert>
        </div>
      )}
      {error !== null && (
        <div className="mt-2">
          <Alert>{error}</Alert>
        </div>
      )}
    </section>
  );
}

export default ReminderTimeline;
