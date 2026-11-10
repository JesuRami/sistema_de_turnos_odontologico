/**
 * Catálogo de errores de dominio (D8): `detail` de la API → mensaje en español.
 * Nunca se interpolan datos del paciente (regla 13); lo desconocido es genérico.
 */
import { ApiError } from "./client";

export const GENERIC_ERROR = "No se pudo completar la operación";

const MENSAJES: Record<string, string> = {
  // red / sesión (C-03)
  network_error: "No hay conexión con el servidor. Probá de nuevo en unos segundos",
  invalid_credentials: "Email o contraseña incorrectos",
  rate_limited: "Demasiados intentos. Esperá un momento antes de reintentar",
  token_invalid: "Tu sesión no es válida. Volvé a ingresar",
  token_expired: "Tu sesión venció. Volvé a ingresar",
  invalid_session: "Tu sesión se cerró. Volvé a ingresar",
  invalid_refresh: "Tu sesión venció. Volvé a ingresar",
  refresh_reuse: "Tu sesión se cerró por seguridad. Volvé a ingresar",
  forbidden_role: "No tenés permiso para esta acción",
  forbidden_scope: "Solo podés operar sobre tu propia agenda",
  password_change_required: "Tenés que cambiar la contraseña antes de seguir",
  auth_unavailable: "El servicio de sesiones no responde. Probá de nuevo en unos minutos",
  not_found: "No se encontró el registro (puede haber sido modificado)",
  validation_error: "Revisá los datos ingresados",
  // configuración (C-04)
  schedule_overlap: "La franja se superpone con otra del mismo profesional y sillón",
  block_immutable: "Ese bloqueo ya empezó o terminó y no se puede modificar así",
  block_in_past: "El bloqueo no puede terminar en el pasado",
  invalid_block_range: "El fin del bloqueo debe ser posterior al inicio",
  invalid_resource: "El profesional o sillón elegido no es válido",
  no_active_chairs: "No hay sillones activos para cerrar",
  invalid_range: "El rango de fechas no es válido",
  // turnos (C-05)
  slot_taken: "El horario ya está ocupado",
  slot_blocked: "El horario está bloqueado",
  resource_inactive: "El profesional o el sillón están dados de baja",
  outside_schedule: "El horario está fuera de la atención del profesional",
  appointment_in_past: "No se pueden agendar turnos en días pasados",
  overbooking_not_needed: "El horario está libre: no hace falta un sobreturno",
  overbooking_limit:
    "Se alcanzó el tope diario de sobreturnos: solo un admin puede excederlo",
  invalid_transition: "El turno no admite ese cambio de estado",
  appointment_started: "El turno ya empezó",
  attendance_too_early: "Todavía no se puede registrar la asistencia de este turno",
  appointment_changed: "Alguien modificó el turno al mismo tiempo. Volvé a intentarlo",
  invalid_patient: "El paciente no es válido o fue dado de baja",
  block_conflicts: "El bloqueo pisa turnos que hay que resolver",
  invalid_cancellation: "La lista de turnos a cancelar no coincide con los afectados",
  // pacientes (C-05/C-06)
  query_too_short: "Escribí al menos 3 caracteres",
  query_too_long: "La búsqueda es demasiado larga",
  invalid_phone: "El teléfono no es válido",
  invalid_email: "El email no es válido",
  contact_required: "Cargá al menos un teléfono o un email",
  patient_duplicate: "Ya existe un paciente con ese nombre y teléfono",
  invalid_merge: "No se pueden fusionar esas fichas",
  // recordatorios (C-11)
  appointment_inactive: "El turno ya no está vigente",
  reminder_not_found: "Ese recordatorio no existe para este turno",
  step_not_applicable: "Ese recordatorio ya no aplica a este turno",
  reminder_in_flight: "El recordatorio se está enviando en este momento",
  reminder_pending: "El recordatorio todavía no se envió: sale a su hora",
  no_consent: "El paciente no aceptó recibir mensajes por ese canal",
  no_recipient: "Falta el teléfono o el email del paciente para ese canal",
  resend_cooldown: "Hay un reenvío en cola. Esperá un momento",
  resend_limit: "Se alcanzó el máximo de reenvíos de hoy para este recordatorio",
  invalid_note: "La nota no puede tener teléfonos, emails ni DNI (máx. 200 caracteres)",
  range_too_large: "El rango elegido es demasiado largo",
  // lista de espera (C-12)
  already_waiting: "El paciente ya está en la lista de espera para ese profesional",
  entry_offered: "La entrada tiene una oferta pendiente: esperá la respuesta o retirala primero",
  entry_closed: "La entrada ya está cerrada (convertida, vencida o retirada)",
  priority_reason_required:
    "Indicá un motivo de prioridad de 10 a 200 caracteres, sin teléfonos, emails ni DNI",
  fifo_skip_reason_required:
    "Hay pacientes antes en la cola: indicá el motivo para saltear el orden de llegada",
  invalid_time_window: "La franja horaria no es válida: completá desde y hasta, en ese orden",
  invalid_weekdays: "Elegí al menos un día de la semana, sin repetir",
  offer_expired: "La oferta ya venció",
  offer_closed: "La oferta ya fue respondida o retirada",
  patient_busy: "El paciente ya tiene otro turno a esa hora",
  offer_not_found: "La oferta no existe o el link venció",
  // borde endurecido (C-14)
  concurrent_update: "Otra persona estaba modificando lo mismo. Volvé a intentarlo",
  conflict: "El cambio choca con datos que ya existen",
  db_timeout: "El servidor tardó demasiado en responder. Probá de nuevo en unos segundos",
  db_unavailable: "El servidor no está disponible en este momento. Probá de nuevo en unos minutos",
  internal_error: GENERIC_ERROR,
  invalid_host: GENERIC_ERROR,
  method_not_allowed: GENERIC_ERROR
};

/** Código corto del error para que soporte lo cruce con los logs (`request_id`, sin PII). */
export function supportCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status < 500) {
    return null;
  }
  const id = error.extra.request_id;
  return typeof id === "string" && id !== "" ? id.slice(0, 8) : null;
}

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const mensaje = MENSAJES[error.detail] ?? GENERIC_ERROR;
    const codigo = supportCode(error);
    return codigo === null ? mensaje : `${mensaje} (código ${codigo})`;
  }
  return GENERIC_ERROR;
}
