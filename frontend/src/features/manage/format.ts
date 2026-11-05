/** Formato del turno en la zona de la clínica (nunca la del navegador, RN-GL-03). */
import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";
import type { AppointmentStatus } from "./types";

export const STATUS_LABEL: Record<AppointmentStatus, string> = {
  pending: "Pendiente",
  confirmed: "Confirmado",
  present: "Atendido",
  absent: "Ausente con aviso",
  no_show: "No asistió",
  cancelled: "Cancelado"
};

/** `"lun 14/01 · 10:00"` en la zona de la clínica. */
export function whenLabel(iso: string, tz: string): string {
  const instante = new Date(iso);
  return `${formatDayLabel(dateKeyOf(instante, tz))} · ${formatTime(instante, tz)}`;
}
