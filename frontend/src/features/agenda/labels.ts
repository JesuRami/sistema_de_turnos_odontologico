/** Etiquetas en español de estados y motivos (texto además del color: accesibilidad). */
import type { AppointmentStatus, BlockReason, CancellationReason } from "../../shared/api/types";

export const STATUS_LABEL: Record<AppointmentStatus, string> = {
  pending: "Pendiente",
  confirmed: "Confirmado",
  present: "Presente",
  absent: "Ausente",
  no_show: "No vino",
  cancelled: "Cancelado"
};

export const STATUS_STYLE: Record<AppointmentStatus, string> = {
  pending: "bg-amber-100 text-amber-900",
  confirmed: "bg-sky-100 text-sky-900",
  present: "bg-emerald-100 text-emerald-900",
  absent: "bg-stone-200 text-stone-800",
  no_show: "bg-rose-100 text-rose-900",
  cancelled: "bg-stone-100 text-stone-500 line-through"
};

export const BLOCK_REASON_LABEL: Record<BlockReason, string> = {
  vacaciones: "Vacaciones",
  feriado: "Feriado",
  mantenimiento: "Mantenimiento",
  reunion: "Reunión",
  otro: "Otro"
};

export const CANCELLATION_REASON_LABEL: Record<CancellationReason, string> = {
  paciente: "Pedido del paciente",
  profesional: "Profesional",
  clinica: "Clínica",
  bloqueo: "Bloqueo de agenda",
  otro: "Otro"
};
