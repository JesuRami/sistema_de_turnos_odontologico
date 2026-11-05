/** Datos sintéticos y handlers MSW de la gestión por token (C-08, regla 13). */
import { http, HttpResponse, type HttpHandler } from "msw";
import type {
  ManageActionRequest,
  ManageAvailability,
  ManageSlot,
  ManageView
} from "../features/manage/types";

/** Formato real del token (43 caracteres url-safe); obviamente ficticio. */
export const TOKEN = "tokenFicticioDePruebaNoReal_0123456789abcdef";
export const TZ = "America/Argentina/Buenos_Aires";
export const TELEFONO = "+541155550100";
// Lunes 2030-01-07 08:00 en Buenos Aires; el navegador de los tests está en UTC.
export const AHORA = new Date("2030-01-07T11:00:00Z");
// Lunes 14/01 10:00 local = 13:00Z (faltan 7 días).
export const INICIO = "2030-01-14T10:00:00-03:00";
export const FIN = "2030-01-14T10:30:00-03:00";

export const URL_VISTA = `/api/manage/${TOKEN}`;

export function view(overrides: {
  appointment?: Partial<ManageView["appointment"]>;
  actions?: Partial<ManageView["actions"]>;
  clinic?: Partial<ManageView["clinic"]>;
} = {}): ManageView {
  return {
    clinic: {
      name: "Clínica Demo Ficticia",
      phone: TELEFONO,
      timezone: TZ,
      slug: "clinica-demo",
      ...overrides.clinic
    },
    appointment: {
      patient_first_name: "María",
      starts_at: INICIO,
      ends_at: FIN,
      professional_display_name: "Dra. Ficticia Uno",
      status: "pending",
      origin: "online",
      is_overbooking: false,
      ...overrides.appointment
    },
    policy: { cancellation_window_hours: 24, cancellation_closes_at: "2030-01-13T10:00:00-03:00" },
    actions: {
      can_confirm: true,
      can_cancel: true,
      can_reschedule: true,
      blocked_reason: null,
      ...overrides.actions
    },
    reason_options: [
      { value: "no_puedo_asistir", label: "No puedo asistir" },
      { value: "enfermedad", label: "Enfermedad" },
      { value: "viaje", label: "Viaje" },
      { value: "problema_economico", label: "Problema económico" },
      { value: "otro", label: "Otro" }
    ],
    manage_token_expires_at: "2030-01-17T10:30:00-03:00"
  };
}

export function confirmed(): ManageView {
  return view({ appointment: { status: "confirmed" }, actions: { can_confirm: false } });
}

export function cancelled(): ManageView {
  return view({
    appointment: { status: "cancelled" },
    actions: {
      can_confirm: false,
      can_cancel: false,
      can_reschedule: false,
      blocked_reason: "not_manageable"
    }
  });
}

/** Hueco de 30 min que arranca en `startsAt` (ISO con offset de la clínica). */
export function slot(startsAt: string): ManageSlot {
  const fin = new Date(new Date(startsAt).getTime() + 30 * 60_000).toISOString();
  return { starts_at: startsAt, ends_at: fin };
}

export function availability(slots: ManageSlot[]): ManageAvailability {
  return { timezone: TZ, slots };
}

export function viewHandler(body: ManageView = view()): HttpHandler {
  return http.get(URL_VISTA, () => HttpResponse.json(body));
}

/** Registra cada PATCH recibido y responde con `respond(cuerpo, n)`. */
export function actionHandler(
  sent: ManageActionRequest[],
  respond: (body: ManageActionRequest, n: number) => Response
): HttpHandler {
  return http.patch(URL_VISTA, async ({ request }) => {
    const body = (await request.json()) as ManageActionRequest;
    sent.push(body);
    return respond(body, sent.length);
  });
}
