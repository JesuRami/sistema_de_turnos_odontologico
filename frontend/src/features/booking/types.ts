/** Tipos de borde de la reserva pública (C-07): espejo de `booking_public/schemas.py`. */

export interface BookingProfessional {
  id: string;
  display_name: string;
}

export interface BookingCatalog {
  name: string;
  timezone: string;
  professionals: BookingProfessional[];
}

/** Hueco ofrecible: solo inicio, fin y profesional (RN-ON-01: sin sillón ni ocupación). */
export interface BookingSlot {
  starts_at: string;
  ends_at: string;
  professional_id: string;
}

export interface BookingAvailability {
  timezone: string;
  slots: BookingSlot[];
}

export interface BookingPatient {
  full_name: string;
  phone?: string;
  email?: string;
  /** Solo se envía con teléfono: la elección explícita del paciente (RN-ON-02). */
  whatsapp_opt_in?: boolean;
  privacy_accepted: boolean;
}

export interface BookingRequest {
  professional_id: string;
  starts_at: string;
  patient: BookingPatient;
}

export type BookingWarning = "phone_invalid_email_channel" | "whatsapp_declined_email_channel";

/** Anotación pública en la lista de espera (C-12): profesional o "Cualquiera" (`null`). */
export interface WaitlistJoinRequest {
  professional_id: string | null;
  date_from: string;
  date_to: string;
  time_from: string | null;
  time_to: string | null;
  weekdays: number[] | null;
  patient: BookingPatient;
}

export interface WaitlistJoined {
  professional_id: string | null;
  date_from: string;
  date_to: string;
  time_from: string | null;
  time_to: string | null;
  weekdays: number[] | null;
  channel: "whatsapp" | "email";
  warnings: BookingWarning[];
}

export interface BookingResult {
  starts_at: string;
  ends_at: string;
  professional_id: string;
  channel: "whatsapp" | "email";
  warnings: BookingWarning[];
  manage_url: string;
}
