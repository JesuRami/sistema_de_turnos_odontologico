# Proposal — C-08 `gestion-por-token`

## Why

C-07 dejó el turno reservado online en `pending` y emitió un `manage_token`
opaco cuyo hash vive en `appointment.manage_token_hash`. Hoy ese link
(`/g/:token`) abre un placeholder: el paciente no puede confirmar, cancelar ni
reprogramar, así que la mitad del circuito de US-021 y del Flujo 2 no existe y
C-09/C-10 no tienen el núcleo de transiciones que van a reutilizar (el webhook de
WhatsApp "SI/NO" ejecuta **las mismas** transiciones que el link).

Sin C-08 no hay reducción de ausentismo (el turno reservado nunca se confirma),
no se liberan huecos cancelados (lista de espera de C-12 se queda sin
disparador) y no hay una vía segura de mostrar datos de un turno a un paciente
sin abrir una enumeración. C-08 está en el camino crítico:
`C-05 → C-07 → C-08 → C-10 → C-14`.

## What Changes

- **Superficie pública de gestión** (router `manage`, sin `Principal`, sin
  sesión; la clínica y el turno se resuelven **solo** por el token):
  - `GET /api/manage/{token}`: resuelve `sha256(token) → appointment` y devuelve
    la vista de gestión (clínica, nombre de pila del paciente, fecha/hora en la
    zona de la clínica, profesional, estado, ventana de cancelación, qué
    acciones están habilitadas y el catálogo cerrado de motivos). Sin ids
    internos, sin sillón, sin contacto del paciente.
  - `GET /api/manage/{token}/availability?from&to`: huecos realmente
    ofrecibles para el **mismo profesional** (la misma definición de hueco que
    C-07), rango ≤ 14 días y horizonte de reserva.
  - `PATCH /api/manage/{token}`: una sola acción por request
    (`confirm` | `cancel` | `reschedule`), cuerpo discriminado con
    `extra='forbid'`. Confirmar `pending → confirmed`; cancelar con ventana
    (RN-CX-01) y motivo opcional de lista cerrada (RN-CX-04); reprogramar de
    forma atómica conservando el `appointment_id` (RN-AG-06, RN-CX-02).
  - Repetición de cualquier acción = **no-op idempotente auditado** (doble click
    o reintento del navegador no duplica eventos de estado ni cancela dos veces).
- **Errores explícitos y distintivos**: `404 manage_link_not_found` (token
  malformado o desconocido), `410 manage_link_expired` (TTL vencido → pantalla
  de contacto, RN-ON-04), `409 cancellation_window_closed` (derivación a la
  clínica, RN-CX-01), `422 appointment_in_past` (cancelar un turno pasado,
  RN-CX-05), `409 slot_taken` con alternativos para la reprogramación,
  `409 invalid_transition`/`appointment_started` para estados no operables.
- **Token**: sigue siendo de un solo turno y sin sesión. Solo se guarda el
  SHA-256; el lookup es por igualdad del hash contra el índice único parcial
  existente. TTL derivado de `ends_at + MANAGE_TOKEN_TTL_H` (72 h). Sin caché
  (`no-store`), sin `Referer`, sin token en logs ni en cuerpos de error.
- **Rate-limit estricto reutilizando el limitador Redis de C-07/C-03**: cupo por
  IP y por hash de token, lecturas y escrituras separadas; Redis caído →
  `503 manage_unavailable` (falla cerrada).
- **Invalidación de recordatorios**: punto de extensión
  `ReminderInvalidator` invocado en la misma transacción al confirmar, cancelar
  y reprogramar. En v1 es no-op (la tabla `reminder_job` nace en C-09, que
  reemplaza la implementación sin tocar el router ni el servicio de gestión).
- **Teléfono de contacto de la clínica** (habilitador mínimo de la pantalla de
  contacto de RN-ON-04): columna `clinic.contact_phone` (nullable), editable por
  admin desde la política de la clínica existente. Sin esta columna la pantalla
  de derivación no puede decir a quién llamar.
- **Frontend `/g/:token`** (hoy placeholder): pantalla mobile-first con resumen
  del turno, confirmación en un toque, cancelación con motivo, reprogramación
  con huecos válidos y pantalla de contacto para link vencido/inválido.
- **Migración `c08_manage_token`** (una sola revisión): `clinic.contact_phone`
  nullable + `CHECK NOT VALID → VALIDATE`. Sin reescritura de tablas, sin
  índices nuevos, sin bloqueo.

## Out of scope (explícito)

- **`reminder_job`, scheduler y plantillas**: C-09/C-10. C-08 solo define el
  punto de invalidación y el evento que los hace idempotentes.
- **Webhook de WhatsApp (`POST /webhooks/whatsapp`) y respuestas "SI/NO"**:
  C-10. Reutilizará el mismo núcleo de transiciones que expone C-08.
- **Reportes**: C-13 queda **intencionalmente intacto**. El detalle del motivo
  del paciente se guarda en el evento (`patient_reason`), pero el reporte de
  cancelaciones por causa (5 valores del enum) no se toca ni se re-agrega.
- **Cambio de profesional al reprogramar** ("o cualquiera si la clínica lo
  permite", US-021 CA-3): v1 reprograma con el mismo profesional. El flag de
  política no existe en el modelo y agregarlo es otro change.
- **Rotación del `manage_token` como comportamiento por defecto**: decisión
  abierta con default propuesto en `design.md` (no rotar en v1); implementarla
  después no requiere migración porque la columna ya existe.
- Login del paciente, CAPTCHA en gestión, notificación al paciente del cambio
  (el aviso por WhatsApp/email es C-09/C-10), lista de espera desde la
  cancelación (el disparador lo implementa C-12 sobre el evento `cancelled`).

## Capabilities

### New Capabilities

- `booking/manage-token`: gestión de un turno por link con token capability —
  resolución por hash, vigencia, vista acotada, confirmar/cancelar/reprogramar,
  idempotencia, ventana de cancelación, motivo del paciente, rate-limit, TTL y
  auditoría sin datos personales.
- `web/manage-token`: página pública `/g/:token` sin sesión ni almacenamiento
  del token, con resumen, confirmación en un toque, cancelación con motivo,
  reprogramación y pantalla de contacto.

### Modified Capabilities

- `agenda/appointments`: se agregan las transiciones iniciadas por el paciente
  con su token (`pending → confirmed`, `pending|confirmed → cancelled`), el
  no-op auditado de una acción repetida y la reprogramación reutilizable por
  token, atómica y con la restricción de exclusión de la base como barrera
  final. Los requisitos existentes no se reescriben.
- `agenda/config`: la política de la clínica suma el teléfono de contacto que
  usan las pantallas de derivación de la gestión por token.

## Impact

- Backend: nuevo `app/modules/manage` (router, servicio, schemas, vista y
  catálogo de motivos); `AppointmentsService` expone la reprogramación sin
  commit (`reschedule(...)`) y `apply_transition` se reutiliza con
  `Actor(type=PATIENT_TOKEN)`; nuevo puerto `ReminderInvalidator` en
  `app/modules/reminders`; `app/core/rate_limit.py` y `settings.py` suman claves
  y cupos de gestión; `app/common/exceptions.py` extiende la redacción del 422 a
  `/api/manage/`; `clinic` suma `contact_phone` en modelo, schemas de políticas
  y PATCH.
- DB: una revisión Alembic (`c08_manage_token`): `clinic.contact_phone`
  nullable + `CHECK` `NOT VALID → VALIDATE`. **No** hay columna nueva en
  `appointment`: el TTL se deriva de `ends_at` y la idempotencia es por estado.
- Frontend: `features/manage` (api, queries, tipos de borde sin `any`,
  componentes PascalCase) y `pages/ManagePage.tsx`; input de teléfono de
  contacto en `PoliciesPage`.
- Tests: pytest + httpx contra Postgres 15 + Redis 7 reales (regla 9) — incluida
  la carrera real por el mismo hueco durante una reprogramación, el test de
  invariante en la base y el aislamiento cross-tenant (regla 4); Vitest de la
  página y Playwright del circuito crítico. Datos sintéticos (regla 13).
- Governance: **ALTO** (endpoint anónimo de internet que muta turnos y expone
  datos de un paciente).
