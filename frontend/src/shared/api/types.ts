/**
 * Tipos de borde de la API (D2), escritos a mano desde los schemas Pydantic de
 * C-03 a C-06. Instantes como string ISO-8601 con zona; ids como string UUID.
 */

export type Uuid = string;
export type IsoDateTime = string;

export type UserRole = "admin" | "recepcion" | "odontologo";

export interface UserProfile {
  id: Uuid;
  email: string;
  role: UserRole;
  clinic_id: Uuid;
  professional_id: Uuid | null;
  must_change_password: boolean;
  last_login_at: IsoDateTime | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserProfile;
}

export interface RefreshResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface ClinicProfile {
  id: Uuid;
  name: string;
  timezone: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

// ------------------------------------------------------------- recursos (C-04)

export interface Professional {
  id: Uuid;
  display_name: string;
  color: string | null;
  default_duration_min: number;
  buffer_min: number;
  booking_enabled: boolean;
  active: boolean;
  created_at: IsoDateTime;
}

export interface Chair {
  id: Uuid;
  name: string;
  active: boolean;
  created_at: IsoDateTime;
}

export interface ScheduleRule {
  id: Uuid;
  professional_id: Uuid;
  chair_id: Uuid;
  weekday: number;
  start_time: string;
  end_time: string;
  slot_duration_min: number;
  valid_from: string;
  valid_to: string | null;
  active: boolean;
  created_at: IsoDateTime;
}

export type BlockReason = "vacaciones" | "feriado" | "mantenimiento" | "reunion" | "otro";

export interface Block {
  id: Uuid;
  professional_id: Uuid | null;
  chair_id: Uuid | null;
  starts_at: IsoDateTime;
  ends_at: IsoDateTime;
  reason: BlockReason;
  notes: string | null;
  created_by_user_id: Uuid;
  created_at: IsoDateTime;
}

export interface ReminderStep {
  offset_h: number;
  channel: "whatsapp" | "email";
}

export interface ClinicPolicies {
  cancellation_window_hours: number;
  reminder_steps: ReminderStep[];
  max_overbookings_per_day: number;
  waitlist_offer_ttl_hours: number;
  /** Teléfono de derivación pública en E.164 (C-08); `null` = sin cargar. */
  contact_phone: string | null;
}

// ---------------------------------------------------------------- turnos (C-05)

export type AppointmentStatus =
  | "pending"
  | "confirmed"
  | "present"
  | "absent"
  | "no_show"
  | "cancelled";

export type AppointmentOrigin = "reception" | "online";

export type CancellationReason = "paciente" | "profesional" | "clinica" | "bloqueo" | "otro";

export type TransitionTarget = "confirmed" | "present" | "absent" | "no_show" | "cancelled";

/** Admin y recepción reciben contacto; el odontólogo solo id y nombre (D12 de C-05). */
export interface AppointmentPatient {
  id: Uuid;
  full_name: string;
  phone_e164?: string | null;
  email?: string | null;
}

export interface Appointment {
  id: Uuid;
  patient: AppointmentPatient;
  professional_id: Uuid;
  chair_id: Uuid;
  starts_at: IsoDateTime;
  ends_at: IsoDateTime;
  occupied_until: IsoDateTime;
  status: AppointmentStatus;
  origin: AppointmentOrigin;
  is_overbooking: boolean;
  overbooking_reason: string | null;
  cancellation_reason: CancellationReason | null;
  cancellation_note: string | null;
  cancelled_at: IsoDateTime | null;
  notes: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface AppointmentCreate {
  patient_id: Uuid;
  professional_id: Uuid;
  chair_id: Uuid;
  starts_at: IsoDateTime;
  duration_min?: number;
  is_overbooking?: boolean;
  overbooking_reason?: string;
  notes?: string;
}

export interface AppointmentUpdate {
  starts_at?: IsoDateTime;
  duration_min?: number;
  professional_id?: Uuid;
  chair_id?: Uuid;
  is_overbooking?: boolean;
  overbooking_reason?: string | null;
  notes?: string | null;
}

export interface TransitionRequest {
  to: TransitionTarget;
  reason?: CancellationReason;
  note?: string;
}

export interface Alternative {
  starts_at: IsoDateTime;
  ends_at: IsoDateTime;
  professional_id: Uuid;
  chair_id: Uuid;
}

export interface CancelInstruction {
  appointment_id: Uuid;
  reason: CancellationReason;
  note?: string;
}

// ------------------------------------------------------------- pacientes (C-05/06)

export interface Patient {
  id: Uuid;
  full_name: string;
  phone_e164: string | null;
  email: string | null;
  dni: string | null;
  whatsapp_opt_in: boolean;
}

export interface PatientDetail extends Patient {
  archived_at: IsoDateTime | null;
  merged_into_patient_id: Uuid | null;
  appointments_count: number;
}

export interface PatientCreate {
  full_name: string;
  phone?: string;
  email?: string;
  dni?: string;
  whatsapp_opt_in?: boolean;
}

export interface PatientMergeResult {
  merge_id: Uuid;
  source_patient_id: Uuid;
  target_patient_id: Uuid;
  moved_appointments: number;
  appointment_ids: Uuid[];
  filled_fields: string[];
}

// ---------------------------------------------------------------- C-13 reportes

export type ReportGroupBy = "professional" | "chair";

export interface OccupancyRow {
  resource_id: Uuid;
  resource_name: string;
  appointments: number;
  overbookings: number;
  booked_min: number;
  capacity_min: number;
  occupancy_pct: number;
}

export interface OccupancyReport {
  group_by: ReportGroupBy;
  from_date: string;
  to_date: string;
  capacity_basis: "current_schedule";
  rows: OccupancyRow[];
  totals: Omit<OccupancyRow, "resource_id" | "resource_name">;
}

export interface AbsenteeismRow {
  professional_id: Uuid;
  professional_name: string;
  present: number;
  absent: number;
  no_show: number;
  late_cancellations: number;
  outcomes: number;
  no_show_rate: number;
  absent_rate: number;
  late_cancellation_rate: number;
}

export interface AbsenteeismReport {
  from_date: string;
  to_date: string;
  rows: AbsenteeismRow[];
  totals: Omit<AbsenteeismRow, "professional_id" | "professional_name">;
}

export interface CancellationRow {
  reason: string;
  total: number;
  late: number;
  in_window: number;
}

export interface CancellationsReport {
  from_date: string;
  to_date: string;
  rows: CancellationRow[];
  total: number;
}

/** Reporte de mensajes de recordatorio por paso y canal (C-10). Costos en USD como texto decimal. */
export type ReminderChannel = "whatsapp" | "email";

export interface WhatsAppReportRow {
  step: string;
  channel: ReminderChannel;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  cost_usd: string;
}

export interface WhatsAppReport {
  from_date: string;
  to_date: string;
  currency: "USD";
  rows: WhatsAppReportRow[];
  totals: Omit<WhatsAppReportRow, "step" | "channel">;
}

export type AppointmentEventKind =
  | "created"
  | "overbooking_created"
  | "confirmed"
  | "rescheduled"
  | "cancelled"
  | "present"
  | "absent"
  | "no_show"
  | "updated";

export interface AuditEvent {
  id: Uuid;
  appointment_id: Uuid;
  event: AppointmentEventKind;
  actor_type: "user" | "system" | "patient_token";
  actor_user_id: Uuid | null;
  from_status: AppointmentStatus | null;
  to_status: AppointmentStatus | null;
  payload: Record<string, unknown>;
  created_at: IsoDateTime;
}

// --- Recordatorios: timeline, reenvío y seguimiento (C-11) ---

/** Estado efectivo de un paso (D2): el del job o el derivado de sus eventos. */
export type ReminderStepStatus =
  | "scheduled"
  | "sending"
  | "sent"
  | "delivered"
  | "read"
  | "failed"
  | "skipped"
  | "cancelled";

export type ResendBlockedReason =
  | "no_consent"
  | "no_recipient"
  | "appointment_started"
  | "appointment_inactive"
  | "step_not_applicable"
  | "reminder_in_flight"
  | "reminder_pending"
  | "resend_cooldown"
  | "resend_limit";

export interface ReminderEvent {
  type: string;
  occurred_at: IsoDateTime;
  /** Evento de un intento anterior a un reenvío manual ("envío anterior"). */
  previous: boolean;
  detail: Record<string, string | number | boolean | null>;
}

export interface ReminderTimelineStep {
  step: string;
  channel: ReminderChannel;
  status: ReminderStepStatus;
  reason: string | null;
  scheduled_for: IsoDateTime;
  available_at: IsoDateTime;
  sent_at: IsoDateTime | null;
  attempts: number;
  last_error: string | null;
  manual_resends_today: number;
  last_manual_resend_at: IsoDateTime | null;
  can_resend: boolean;
  resend_blocked_reason: ResendBlockedReason | null;
  events: ReminderEvent[];
}

export interface ReminderTimeline {
  appointment_id: Uuid;
  timezone: string;
  pending_confirmation: boolean;
  steps: ReminderTimelineStep[];
}

export interface ResendAccepted {
  job_id: Uuid;
  status: "scheduled";
  available_at: IsoDateTime;
  manual_resends_today: number;
  cooldown_until: IsoDateTime;
}

export type FollowUpReason = "no_response" | "delivery_failed";

export interface FollowUpRow {
  appointment_id: Uuid;
  starts_at: IsoDateTime;
  patient_id: Uuid;
  patient_name: string;
  professional_id: Uuid;
  status: AppointmentStatus;
  reasons: FollowUpReason[];
  last_reminder: {
    step: string;
    channel: ReminderChannel;
    status: string;
    sent_at: IsoDateTime | null;
    last_error: string | null;
  } | null;
  can_confirm: boolean;
}

export interface FollowUpPage extends Page<FollowUpRow> {
  totals: Record<FollowUpReason, number>;
}
