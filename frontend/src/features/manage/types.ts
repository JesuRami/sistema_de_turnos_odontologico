/** Tipos de borde de la gestión por token (C-08): espejo de `manage/schemas.py`. Sin `any`. */

export type AppointmentStatus =
  | "pending"
  | "confirmed"
  | "present"
  | "absent"
  | "no_show"
  | "cancelled";

export type BlockedReason = "window_closed" | "past" | "not_manageable" | "token_expired";

export type PatientReason =
  | "no_puedo_asistir"
  | "enfermedad"
  | "viaje"
  | "problema_economico"
  | "otro";

export interface ManageClinic {
  name: string;
  phone: string | null;
  timezone: string;
  slug: string;
}

/** Datos mínimos del turno: sin ids, sin sillón y sin contacto del paciente (D5). */
export interface ManageAppointment {
  patient_first_name: string;
  starts_at: string;
  ends_at: string;
  professional_display_name: string;
  status: AppointmentStatus;
  origin: "reception" | "online";
  is_overbooking: boolean;
}

export interface ManageActions {
  can_confirm: boolean;
  can_cancel: boolean;
  can_reschedule: boolean;
  blocked_reason: BlockedReason | null;
}

export interface ReasonOption {
  value: PatientReason;
  label: string;
}

export interface ManageView {
  clinic: ManageClinic;
  appointment: ManageAppointment;
  policy: { cancellation_window_hours: number; cancellation_closes_at: string };
  actions: ManageActions;
  reason_options: ReasonOption[];
  manage_token_expires_at: string;
}

/** Hueco para reprogramar: solo inicio y fin. */
export interface ManageSlot {
  starts_at: string;
  ends_at: string;
}

export interface ManageAvailability {
  timezone: string;
  slots: ManageSlot[];
}

export type ManageActionRequest =
  | { action: "confirm" }
  | { action: "cancel"; reason?: PatientReason; note?: string }
  | { action: "reschedule"; starts_at: string };

/** Contacto que trae el `410 manage_link_expired` (nada del paciente). */
export interface ExpiredClinic {
  name: string;
  phone: string | null;
}
