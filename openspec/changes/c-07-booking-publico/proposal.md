# Proposal — C-07 `booking-publico`

## Why

Hoy un turno solo nace en recepción: el paciente tiene que llamar en horario de
atención. US-020 pide reserva online 24/7 por un link público de la clínica
(`/b/:slug`), y es la mitad del valor del MVP (la otra mitad son los
recordatorios). C-05 dejó el servicio de turnos apto para `origin=online` (nace
`pending`, nunca sobreturno, mismo lock por recurso) y el cálculo de huecos
reutilizable; falta exponerlo a un público anónimo sin abrir un agujero de
abuso, enumeración o fuga de datos. Está en el camino crítico: C-08 (gestión por
token) necesita el `manage_token` que emite este change.

## What Changes

- **API pública sin autenticación** (router `booking_public`, prefijo
  `/api/booking/{slug}`), aislada del resto y con rate-limit propio en Redis:
  - `GET /api/booking/{slug}`: nombre y zona horaria de la clínica y lista de
    profesionales reservables (solo `id` + `display_name`).
  - `GET /api/booking/{slug}/availability?professional_id&from&to`: huecos
    libres = plantilla semanal − bloqueos − turnos vigentes − buffers (RN-AG-05,
    US-020 CA-2). Solo fecha/hora/profesional, nunca sillón, ids de turnos ni
    datos de otros pacientes (RN-ON-01). Rango acotado y horizonte máximo.
  - `POST /api/booking/{slug}/appointments`: reserva con nombre + al menos un
    contacto + opt-in WhatsApp explícito si deja teléfono + aceptación del texto
    de privacidad (RN-ON-02). Normaliza E.164 y reutiliza el paciente existente
    (RN-ON-05). La duración sale de la regla, nunca del paciente (RN-AG-03), y el
    horario debe ser uno de los ofrecidos. Inserta el turno `pending` vía
    `AppointmentsService.book(origin=online)` (mismo lock y misma barrera
    EXCLUDE) y emite el `manage_token` en la misma transacción. Carrera → `409
    slot_taken` con alternativos cercanos en forma pública.
  - Teléfono inválido con email presente → se acepta con email como canal y un
    aviso explícito en la respuesta; sin contacto válido → `422`.
- **Anti-abuso sin CAPTCHA en v1** (decisión del usuario, 2026-11-04): rate-limit
  Redis por IP (10 reservas/h, RN-ON-03) y por slug, cupo de lecturas de
  disponibilidad por IP, respuestas indistinguibles para slug inexistente o
  deshabilitado, rango de consulta acotado. Un punto de extensión `BotGuard`
  (implementación no-op) permite sumar CAPTCHA después sin tocar el router.
- **`manage_token`**: 256 bits aleatorios, opaco; en la base solo su SHA-256
  (`appointment.manage_token_hash`, único). El token en claro viaja una sola vez
  en la respuesta de la reserva, nunca en logs ni eventos.
- **Frontend `/b/:slug`** mobile-first en ≤ 4 pasos (profesional → día → hora →
  datos), pantalla de confirmación con el link de gestión, manejo de `409`
  (alternativos), `422`, `429` y aviso de canal email (US-020 CA-1).
- **Agenda de recepción**: refresco periódico para que la reserva online aparezca
  sin recargar (Flujo 1 paso 6).
- **Migración `c07_booking_public`** (una sola revisión, regla 3).
- **KB**: se marca resuelta la pregunta Alta de CAPTCHA/anti-bot en
  `knowledge-base/10_preguntas_abiertas.md`.

## Out of scope (explícito)

- **`reminder_job` y mensaje de alta (`turno_creado_v1`)**: la tabla, el
  scheduler y las plantillas nacen en C-09/C-10. Contrato vigente desde C-05: C-09
  engancha la programación de jobs dentro de `AppointmentsService.book`, en la
  misma transacción; como la reserva online pasa por ese método, queda cubierta
  sin cambios en C-07. La "confirmación inmediata" de C-07 es la pantalla con el
  link de gestión.
- **Uso del token** (`GET /g/:token`, confirmar/cancelar/reprogramar, TTL 72 h,
  rotación en reprogramación): C-08.
- **Tabla `consent`** con historial de opt-in/opt-out: C-09/C-10. C-07 solo
  escribe `patient.whatsapp_opt_in` y el consentimiento de privacidad existente.
- CAPTCHA (queda la interfaz), lista de espera desde la reserva (C-12), dominio
  propio por clínica (pregunta Baja), tiempo real por push/SSE.

## Capabilities

### New Capabilities

- `booking/public-booking`: reserva online pública por slug — catálogo de
  profesionales, disponibilidad sin fuga de datos, alta del turno `pending` con
  match de paciente, emisión del token de gestión, rate-limit y anti-enumeración.
- `web/public-booking`: flujo público `/b/:slug` mobile-first de 4 pasos con
  confirmación y manejo de errores.

### Modified Capabilities

- `agenda/appointments`: todo turno online lleva un token de gestión hasheado y
  único (garantizado en la base).
- `web/agenda-board`: la agenda se refresca sola para mostrar reservas online.

## Impact

- Backend: `app/modules/booking_public` (reemplaza el stub de C-01: router,
  servicio, schemas, `BotGuard`, rate-limit), helper común de IP de cliente,
  reutiliza `AppointmentsService.book`, `suggest_slots`, `lock_resources`,
  `normalize_phone_e164` y `find_patients_by_phone`. Schemas con
  `extra='forbid'` (regla 2). Nuevos settings de rate-limit y horizonte en
  `settings.py` y `.env.example` (regla 6).
- DB: `appointment.manage_token_hash bytea` + índice único parcial `CONCURRENTLY`
  + CHECKs `NOT VALID → VALIDATE` (regla 11).
- Frontend: `features/booking` + `pages/BookingPage.tsx` (hoy placeholder),
  cliente API público sin credenciales, `refetchInterval` en la agenda.
- Tests: pytest + httpx contra Postgres 15 + Redis 7 reales (regla 9), carrera
  real, aislamiento cross-tenant (regla 4), Playwright del flujo `/b/:slug`.
  Datos sintéticos (regla 13).
- Governance: **ALTO** (endpoint anónimo expuesto a internet + emisión de
  capability token).
