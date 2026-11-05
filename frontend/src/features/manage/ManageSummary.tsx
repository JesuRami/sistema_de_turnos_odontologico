/**
 * Resumen del turno y acciones habilitadas. Las reglas (ventana, estado, pasado) las decide el
 * servidor en `actions`; acá solo se muestran (D14). Sin sillón ni ids (D5).
 */
import { STATUS_LABEL, whenLabel } from "./format";
import ManageContact, { GHOST_DANGER, PRIMARY, SECONDARY } from "./ManageContact";
import type { ManageView } from "./types";

const PILL: Record<string, string> = {
  pending: "bg-amber-100 text-amber-900",
  confirmed: "bg-emerald-100 text-emerald-900",
  cancelled: "bg-rose-100 text-rose-900"
};

interface ManageSummaryProps {
  view: ManageView;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onReschedule: () => void;
}

function ManageSummary({
  view,
  busy,
  onConfirm,
  onCancel,
  onReschedule
}: ManageSummaryProps): JSX.Element {
  const { appointment, actions, clinic, policy } = view;
  const tz = clinic.timezone;
  const vigente = appointment.status === "pending" || appointment.status === "confirmed";
  const bloqueo = actions.blocked_reason;

  return (
    <>
      <section className="mt-4 rounded-lg border border-dental-600/20 bg-white p-4" aria-labelledby="turno">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="turno" className="text-lg font-semibold">
              {whenLabel(appointment.starts_at, tz)}
            </h2>
            <p className="text-sm opacity-80">{appointment.professional_display_name}</p>
          </div>
          <span
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium ${PILL[appointment.status] ?? "bg-dental-50"}`}
          >
            {STATUS_LABEL[appointment.status]}
          </span>
        </div>
        <p className="mt-3 text-sm">
          Hola, {appointment.patient_first_name}.{" "}
          {appointment.status === "pending" && "Confirmá tu asistencia o cambiala si no podés venir."}
        </p>

        {vigente && (
          <div className="mt-4 flex flex-col gap-2">
            {appointment.status === "pending" && actions.can_confirm && (
              <button type="button" className={PRIMARY} disabled={busy} onClick={onConfirm}>
                Confirmar turno
              </button>
            )}
            <button
              type="button"
              className={SECONDARY}
              disabled={busy || !actions.can_reschedule}
              onClick={onReschedule}
            >
              Cambiar horario
            </button>
            <button
              type="button"
              className={GHOST_DANGER}
              disabled={busy || !actions.can_cancel}
              onClick={onCancel}
            >
              Cancelar
            </button>
          </div>
        )}
      </section>

      {bloqueo === "window_closed" && (
        <section role="status" className="mt-4 rounded-lg border border-amber-700/40 bg-amber-50 p-4 text-sm">
          <p>
            Faltan menos de {policy.cancellation_window_hours} h para tu turno. Para cancelarlo o
            cambiarlo, hablá con la clínica.
          </p>
          <ManageContact clinicName={clinic.name} phone={clinic.phone} />
        </section>
      )}
      {bloqueo === "past" && vigente && (
        <section role="status" className="mt-4 rounded-lg border border-dental-600/20 bg-white p-4 text-sm">
          <p>Este turno ya empezó. Si necesitás algo, hablá con la clínica.</p>
          <ManageContact clinicName={clinic.name} phone={clinic.phone} />
        </section>
      )}
      {appointment.status === "cancelled" && (
        <a className={`${SECONDARY} mt-4 w-full`} href={`/b/${encodeURIComponent(clinic.slug)}`}>
          Reservar un turno nuevo
        </a>
      )}
      {bloqueo === null && (
        <p className="mt-4 text-sm opacity-80">
          Podés cancelar o cambiar el horario sin costo hasta {policy.cancellation_window_hours} h
          antes ({whenLabel(policy.cancellation_closes_at, tz)}). Después de ese plazo, llamanos.
        </p>
      )}
      <p className="mt-6 text-xs opacity-70">
        Este link es personal y vence el {whenLabel(view.manage_token_expires_at, tz)}. No lo
        compartas.
      </p>
    </>
  );
}

export default ManageSummary;
