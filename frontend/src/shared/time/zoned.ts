/**
 * Fechas en la zona horaria de la clínica (D4), sin librería: `Intl.DateTimeFormat`.
 *
 * La agenda nunca usa la zona del navegador. Un día de calendario se representa
 * como `DateKey` (`"YYYY-MM-DD"`); la aritmética de días es de calendario (UTC
 * puro), y la conversión a instantes pasa siempre por la zona de la clínica.
 */

export type DateKey = string;

interface WallParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(tz: string): Intl.DateTimeFormat {
  let formatter = formatters.get(tz);
  if (formatter === undefined) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
    formatters.set(tz, formatter);
  }
  return formatter;
}

function wallParts(instant: Date, tz: string): WallParts {
  const valores: Record<string, number> = {};
  for (const parte of formatterFor(tz).formatToParts(instant)) {
    if (parte.type !== "literal") {
      valores[parte.type] = Number(parte.value);
    }
  }
  return {
    year: valores.year ?? 0,
    month: valores.month ?? 0,
    day: valores.day ?? 0,
    hour: valores.hour ?? 0,
    minute: valores.minute ?? 0
  };
}

const pad = (n: number): string => String(n).padStart(2, "0");

function keyOf(parts: Pick<WallParts, "year" | "month" | "day">): DateKey {
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
}

function parseKey(key: DateKey): { year: number; month: number; day: number } {
  const [year, month, day] = key.split("-").map(Number);
  return { year: year ?? 0, month: month ?? 0, day: day ?? 0 };
}

/** Minutos que la zona está adelantada a UTC en ese instante. */
function offsetMinutes(instant: Date, tz: string): number {
  const p = wallParts(instant, tz);
  const comoUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  return Math.round((comoUtc - Math.floor(instant.getTime() / 60000) * 60000) / 60000);
}

/** Día de calendario de la clínica en ese instante. */
export function dateKeyOf(instant: Date, tz: string): DateKey {
  return keyOf(wallParts(instant, tz));
}

/** `"HH:MM"` en la zona de la clínica. */
export function formatTime(instant: Date, tz: string): string {
  const p = wallParts(instant, tz);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

/** Minutos desde la medianoche local de la clínica. */
export function minutesOfDay(instant: Date, tz: string): number {
  const p = wallParts(instant, tz);
  return p.hour * 60 + p.minute;
}

/**
 * Instante de una hora de pared (`"HH:MM"`) de un día en la zona de la clínica.
 * `null` si esa hora no existe (salto por cambio de horario).
 */
export function fromZonedWallTime(key: DateKey, time: string, tz: string): Date | null {
  const { year, month, day } = parseKey(key);
  const [hour, minute] = time.split(":").map(Number);
  const pared = Date.UTC(year, month - 1, day, hour ?? 0, minute ?? 0);
  let candidato = pared - offsetMinutes(new Date(pared), tz) * 60000;
  candidato = pared - offsetMinutes(new Date(candidato), tz) * 60000;
  const resultado = new Date(candidato);
  const p = wallParts(resultado, tz);
  const coincide =
    keyOf(p) === key && p.hour === (hour ?? 0) && p.minute === (minute ?? 0);
  return coincide ? resultado : null;
}

/** Primer instante del día local (la medianoche puede no existir en algunas zonas). */
function startOfZonedDay(key: DateKey, tz: string): Date {
  for (let hora = 0; hora < 24; hora += 1) {
    const inicio = fromZonedWallTime(key, `${pad(hora)}:00`, tz);
    if (inicio !== null) {
      return inicio;
    }
  }
  throw new Error("día sin horas válidas");
}

/** `[from, to)` del día local: rango a pedir a la API. */
export function zonedDayRange(key: DateKey, tz: string): { from: Date; to: Date } {
  return { from: startOfZonedDay(key, tz), to: startOfZonedDay(addDays(key, 1), tz) };
}

/** `[from, to)` de `days` días locales desde `key`. */
export function zonedRange(key: DateKey, days: number, tz: string): { from: Date; to: Date } {
  return { from: startOfZonedDay(key, tz), to: startOfZonedDay(addDays(key, days), tz) };
}

/** Suma días de calendario. */
export function addDays(key: DateKey, days: number): DateKey {
  const { year, month, day } = parseKey(key);
  const d = new Date(Date.UTC(year, month - 1, day + days));
  return keyOf({ year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() });
}

/** Día de semana con lunes = 0 (misma convención que `schedule_rule.weekday`). */
export function weekdayOf(key: DateKey): number {
  const { year, month, day } = parseKey(key);
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
}

/** Lunes de la semana de `key`. */
export function startOfWeekKey(key: DateKey): DateKey {
  return addDays(key, -weekdayOf(key));
}

/** Etiqueta corta del día (`"lun 07/01"`), independiente del navegador. */
export function formatDayLabel(key: DateKey): string {
  const nombres = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
  const { month, day } = parseKey(key);
  return `${nombres[weekdayOf(key)] ?? ""} ${pad(day)}/${pad(month)}`;
}
