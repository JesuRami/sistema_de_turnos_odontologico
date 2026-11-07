/** Datos de red sintéticos (regla 13) y handlers MSW reutilizables para los tests. */
import { http, HttpResponse, type HttpHandler } from "msw";
import type {
  Appointment,
  Block,
  Chair,
  ClinicPolicies,
  ClinicProfile,
  FollowUpPage,
  FollowUpRow,
  Professional,
  ReminderTimelineStep,
  ReminderTimeline,
  ScheduleRule
} from "../shared/api/types";

export const TZ = "America/Argentina/Buenos_Aires";

export const CLINIC: ClinicProfile = { id: "clinic-1", name: "Clínica Ficticia", timezone: TZ };

export function professional(overrides: Partial<Professional> = {}): Professional {
  return {
    id: "prof-1",
    display_name: "Dra. Ficticia Uno",
    color: "#2563eb",
    default_duration_min: 30,
    buffer_min: 0,
    booking_enabled: true,
    active: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides
  };
}

export function chair(overrides: Partial<Chair> = {}): Chair {
  return { id: "chair-1", name: "Sillón 1", active: true, created_at: "2026-01-01T00:00:00Z", ...overrides };
}

export function rule(overrides: Partial<ScheduleRule> = {}): ScheduleRule {
  return {
    id: "rule-1",
    professional_id: "prof-1",
    chair_id: "chair-1",
    weekday: 0,
    start_time: "09:00:00",
    end_time: "13:00:00",
    slot_duration_min: 30,
    valid_from: "2026-01-01",
    valid_to: null,
    active: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides
  };
}

export function appointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: "appt-1",
    patient: {
      id: "pat-1",
      full_name: "Ana Prueba Ejemplo",
      phone_e164: "+5491155550001",
      email: null
    },
    professional_id: "prof-1",
    chair_id: "chair-1",
    starts_at: "2030-01-07T13:00:00Z",
    ends_at: "2030-01-07T13:30:00Z",
    occupied_until: "2030-01-07T13:30:00Z",
    status: "confirmed",
    origin: "reception",
    is_overbooking: false,
    overbooking_reason: null,
    cancellation_reason: null,
    cancellation_note: null,
    cancelled_at: null,
    notes: null,
    created_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
    ...overrides
  };
}

export function block(overrides: Partial<Block> = {}): Block {
  return {
    id: "block-1",
    professional_id: null,
    chair_id: "chair-1",
    starts_at: "2030-01-07T15:00:00Z",
    ends_at: "2030-01-07T16:00:00Z",
    reason: "mantenimiento",
    notes: null,
    created_by_user_id: "user-admin",
    created_at: "2030-01-01T00:00:00Z",
    ...overrides
  };
}

export const POLICIES: ClinicPolicies = {
  cancellation_window_hours: 24,
  reminder_steps: [
    { offset_h: 72, channel: "whatsapp" },
    { offset_h: 24, channel: "whatsapp" }
  ],
  max_overbookings_per_day: 2,
  waitlist_offer_ttl_hours: 4,
  contact_phone: null
};

export interface AgendaData {
  professionals?: Professional[];
  chairs?: Chair[];
  schedules?: ScheduleRule[];
  appointments?: Appointment[];
  blocks?: Block[];
  policies?: ClinicPolicies;
  followUp?: FollowUpPage;
}

const page = <T,>(items: T[]) => HttpResponse.json({ items, next_cursor: null });

/** Handlers de lectura de la agenda; los tests suman los de escritura con `server.use`. */
export function agendaHandlers(data: AgendaData = {}): HttpHandler[] {
  return [
    http.get("/api/clinic", () => HttpResponse.json(CLINIC)),
    http.get("/api/professionals", () => page(data.professionals ?? [professional()])),
    http.get("/api/chairs", () => page(data.chairs ?? [chair()])),
    http.get("/api/schedules", () => page(data.schedules ?? [rule()])),
    http.get("/api/appointments", () => page(data.appointments ?? [])),
    http.get("/api/blocks", () => page(data.blocks ?? [])),
    http.get("/api/clinic/policies", () => HttpResponse.json(data.policies ?? POLICIES)),
    http.get("/api/reminders/follow-up", () => HttpResponse.json(data.followUp ?? followUpPage()))
  ];
}

// --- Recordatorios (C-11) ---

export function reminderStep(overrides: Partial<ReminderTimelineStep> = {}): ReminderTimelineStep {
  return {
    step: "t_24h",
    channel: "whatsapp",
    status: "delivered",
    reason: null,
    scheduled_for: "2030-01-06T13:00:00Z",
    available_at: "2030-01-06T13:00:00Z",
    sent_at: "2030-01-06T13:00:05Z",
    attempts: 1,
    last_error: null,
    manual_resends_today: 0,
    last_manual_resend_at: null,
    can_resend: true,
    resend_blocked_reason: null,
    events: [
      { type: "sent", occurred_at: "2030-01-06T13:00:05Z", previous: false, detail: { attempt: 1 } },
      { type: "delivered", occurred_at: "2030-01-06T13:01:00Z", previous: false, detail: {} }
    ],
    ...overrides
  };
}

export function timeline(steps: ReminderTimelineStep[] = [reminderStep()], overrides: Partial<ReminderTimeline> = {}): ReminderTimeline {
  return { appointment_id: "appt-1", timezone: TZ, pending_confirmation: false, steps, ...overrides };
}

export function followUpRow(overrides: Partial<FollowUpRow> = {}): FollowUpRow {
  return {
    appointment_id: "appt-1",
    starts_at: "2030-01-07T13:00:00Z",
    patient_id: "pat-1",
    patient_name: "Ana Prueba Ejemplo",
    professional_id: "prof-1",
    status: "pending",
    reasons: ["no_response"],
    last_reminder: null,
    can_confirm: true,
    ...overrides
  };
}

export function followUpPage(items: FollowUpRow[] = []): FollowUpPage {
  return {
    items,
    next_cursor: null,
    totals: {
      no_response: items.filter((i) => i.reasons.includes("no_response")).length,
      delivery_failed: items.filter((i) => i.reasons.includes("delivery_failed")).length
    }
  };
}
