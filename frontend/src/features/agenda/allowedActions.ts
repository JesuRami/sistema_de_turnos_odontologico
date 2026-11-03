/**
 * Acciones que la UI ofrece sobre un turno (D6). Replica las guardas de la API
 * (máquina de estados de C-05) SOLO para ocultar botones: la API sigue siendo
 * la autoridad y rechaza lo indebido.
 */
import type { Appointment, UserRole } from "../../shared/api/types";
import { dateKeyOf } from "../../shared/time/zoned";

export interface Actions {
  confirm: boolean;
  reschedule: boolean;
  cancel: boolean;
  present: boolean;
  absent: boolean;
  noShow: boolean;
}

export function allowedActions(
  role: UserRole,
  appointment: Pick<Appointment, "status" | "starts_at">,
  now: Date,
  tz: string
): Actions {
  const inicio = new Date(appointment.starts_at);
  const noEmpezo = now < inicio;
  const deMostrador = role === "admin" || role === "recepcion";
  const vigente = appointment.status === "pending" || appointment.status === "confirmed";
  const confirmado = appointment.status === "confirmed";
  const desdeElDia = dateKeyOf(now, tz) >= dateKeyOf(inicio, tz);
  return {
    confirm: deMostrador && appointment.status === "pending" && noEmpezo,
    reschedule: deMostrador && vigente && noEmpezo,
    cancel: deMostrador && vigente && noEmpezo,
    present: confirmado && desdeElDia,
    absent: confirmado && !noEmpezo,
    noShow: confirmado && !noEmpezo
  };
}
