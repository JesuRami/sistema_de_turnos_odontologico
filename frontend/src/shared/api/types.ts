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
