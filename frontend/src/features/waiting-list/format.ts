/** Textos de la lista de espera (C-12): período, franja, días y vencimiento, en la zona de la clínica. */
import type { WaitingListEntry } from "../../shared/api/types";
import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";

export const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"] as const;

/** `2030-01-08` → `08/01` (sin aritmética de zonas: es una fecha local de la clínica). */
export function shortDate(isoDate: string): string {
  const [, mes = "", dia = ""] = isoDate.split("-");
  return `${dia}/${mes}`;
}

export function periodLabel(entry: Pick<WaitingListEntry, "date_from" | "date_to">): string {
  return `${shortDate(entry.date_from)} al ${shortDate(entry.date_to)}`;
}

export function windowLabel(
  entry: Pick<WaitingListEntry, "time_from" | "time_to" | "weekdays">
): string {
  const partes: string[] = [];
  if (entry.time_from !== null && entry.time_to !== null) {
    partes.push(`${entry.time_from.slice(0, 5)}–${entry.time_to.slice(0, 5)}`);
  }
  if (entry.weekdays !== null) {
    partes.push(entry.weekdays.map((d) => WEEKDAYS[d] ?? "?").join(", "));
  }
  return partes.length > 0 ? partes.join(" · ") : "Cualquier horario";
}

export function slotLabel(startsAt: string, tz: string): string {
  const inicio = new Date(startsAt);
  return `${formatDayLabel(dateKeyOf(inicio, tz))} ${formatTime(inicio, tz)}`;
}

/** "vence en 2 h 05 min" / "venció": cuenta regresiva gruesa, al minuto. */
export function remaining(expiresAt: string, now: Date): string {
  const minutos = Math.floor((new Date(expiresAt).getTime() - now.getTime()) / 60_000);
  if (minutos <= 0) {
    return "venció";
  }
  const horas = Math.floor(minutos / 60);
  const resto = minutos % 60;
  return horas > 0 ? `vence en ${horas} h ${String(resto).padStart(2, "0")} min` : `vence en ${resto} min`;
}
