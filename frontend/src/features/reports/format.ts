/** Formatos de presentación de los reportes (C-13). Sin lógica de negocio. */

export function percent(value: number): string {
  return `${value.toLocaleString("es-AR", { maximumFractionDigits: 1 })} %`;
}

/** Tasa 0–1 como porcentaje con un decimal. */
export function rate(value: number): string {
  return percent(value * 100);
}

export function hours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export const EVENT_LABEL: Record<string, string> = {
  created: "Creado",
  overbooking_created: "Sobreturno creado",
  confirmed: "Confirmado",
  rescheduled: "Reprogramado",
  cancelled: "Cancelado",
  present: "Presente",
  absent: "Ausente con aviso",
  no_show: "No vino",
  updated: "Modificado"
};

export const REASON_LABEL: Record<string, string> = {
  paciente: "Paciente",
  profesional: "Profesional",
  clinica: "Clínica",
  bloqueo: "Bloqueo de agenda",
  otro: "Otro"
};

export function formatInstant(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("es-AR", {
    timeZone: tz,
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(iso));
}
