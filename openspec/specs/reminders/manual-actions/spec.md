# reminders/manual-actions Specification

## Purpose
Permite a recepción reencolar un recordatorio ya intentado y confirmar un turno
pendiente desde la operación diaria, con guardas de negocio, auditoría
append-only y sin duplicar mensajes por doble clic o concurrencia.

## Requirements

### Requirement: Reenvío manual disponible para recepción

`POST /api/appointments/{appointment_id}/reminders/{step}/{channel}/resend` SHALL
ser accesible solo para admin y recepción de la clínica del turno. El odontólogo
SHALL recibir `403 forbidden_role`; un turno de otra clínica, `404 not_found`; sin
sesión, `401`.

#### Scenario: Recepción reenvía un recordatorio fallido

- **WHEN** recepción reenvía el paso de 24 h por WhatsApp de un turno vigente
  cuyo job está `failed`
- **THEN** responde `202 Accepted` con el job en `scheduled`

#### Scenario: Odontólogo intenta reenviar

- **WHEN** un odontólogo llama al endpoint de reenvío de un turno propio
- **THEN** responde `403 forbidden_role` y no cambia el job

#### Scenario: Turno de otra clínica

- **WHEN** recepción de la clínica A reenvía un turno de la clínica B
- **THEN** responde `404 not_found` y no crea ninguna fila de auditoría

### Requirement: Reenvío solo sobre turnos vigentes y no iniciados

El reenvío SHALL rechazar sin efectos cuando el turno no esté `pending` o
`confirmed` (`409 appointment_inactive`) o ya haya empezado (`409
appointment_started`).

#### Scenario: Turno cancelado

- **WHEN** recepción intenta reenviar un recordatorio de un turno cancelado
- **THEN** responde `409 appointment_inactive` y el job no cambia

#### Scenario: Turno ya iniciado

- **WHEN** recepción intenta reenviar un recordatorio de un turno que empezó hace
  10 minutos
- **THEN** responde `409 appointment_started` y el job no cambia

### Requirement: Reenvío solo de pasos intentados y aplicables

El reenvío SHALL rechazar cuando el job no exista (`404 reminder_not_found`), el
paso no esté configurado o el job esté `cancelled` (`409 step_not_applicable`), el
job esté `sending` (`409 reminder_in_flight`), el job sea un paso futuro pendiente
ordinario `scheduled` con `manual_resend_at IS NULL` (`409 reminder_pending`), o el
paso pida confirmación sobre un turno online ya confirmado (`409 step_not_applicable`).

#### Scenario: Paso futuro todavía no intentado

- **WHEN** recepción intenta reenviar un paso cuyo job sigue `scheduled` para más
  adelante
- **THEN** responde `409 reminder_pending` y no adelanta el envío

#### Scenario: Paso de confirmación ya cancelado por confirmación

- **WHEN** recepción intenta reenviar el paso de 24 h de un turno online que el
  paciente ya confirmó
- **THEN** responde `409 step_not_applicable` y el job sigue cancelado

#### Scenario: Job todavía en vuelo

- **WHEN** el worker tiene el job en `sending` y recepción intenta reenviarlo
- **THEN** responde `409 reminder_in_flight` y no toca el lease

#### Scenario: Paso eliminado de la configuración

- **WHEN** el paso ya no está en `clinic.reminder_steps` y recepción intenta
  reenviarlo
- **THEN** responde `409 step_not_applicable` y no crea auditoría

### Requirement: Reenvío sujeto a consentimiento y destinatario

El reenvío por WhatsApp SHALL exigir `whatsapp_opt_in` (`409 no_consent`); el
reenvío por email SHALL exigir email y ausencia de baja de ese canal (`409
no_recipient`). Ningún rechazo SHALL crear una fila de auditoría.

#### Scenario: Paciente sin opt-in de WhatsApp

- **WHEN** recepción reenvía por WhatsApp un turno cuyo paciente tiene
  `whatsapp_opt_in=false`
- **THEN** responde `409 no_consent` y no se crea ninguna fila de auditoría

#### Scenario: Paciente sin email

- **WHEN** recepción reenvía por email un turno cuyo paciente no tiene email
- **THEN** responde `409 no_recipient` y no se crea ninguna fila de auditoría

### Requirement: Reset y auditoría del reenvío

Un reenvío aceptado SHALL, en una sola transacción, insertar una fila en
`reminder_manual_resend` con clínica, turno, job, actor, nota opcional y
`created_at`, y SHALL resetear el job a `scheduled` con `available_at=now`,
`attempts=0`, `claimed_at`, `sent_at`, `provider_message_id`, `cost_micros`,
`last_error` y `reason` en `NULL`, conservando `scheduled_for` y
`starts_at_snapshot`.

#### Scenario: Reset del job y fila de auditoría

- **WHEN** recepción reenvía un job `failed` con `provider_message_id` viejo
- **THEN** el job queda `scheduled`, sin `provider_message_id` ni `sent_at`, y
  existe una fila de auditoría con el actor y la nota

#### Scenario: Nota opcional

- **WHEN** recepción reenvía sin nota
- **THEN** la fila de auditoría se crea con `note` en `NULL`

### Requirement: El reenvío no envía en la request

La request de reenvío SHALL NOT llamar al proveedor ni al SMTP: SHALL dejar el
job `scheduled` para que el worker lo despache en el próximo tick. Si el
proveedor está deshabilitado, el job SHALL quedar `scheduled` sin evento `sent`
nuevo.

#### Scenario: El envío no ocurre en la request

- **WHEN** el proveedor de WhatsApp está deshabilitado y recepción reenvía
- **THEN** responde `202` y el job queda `scheduled` sin evento `sent` nuevo

### Requirement: Estados tardíos del mensaje anterior

Después de un reenvío, un evento `delivered`, `read` o `failed` del
`provider_message_id` anterior SHALL ignorarse y SHALL NOT cambiar el job
reenviado. El evento `sent` anterior SHALL conservarse en el timeline.

#### Scenario: Estado tardío del mensaje anterior

- **WHEN** después del reenvío llega un `delivered` del
  `provider_message_id` anterior
- **THEN** no cambia el job reenviado y el timeline conserva el `sent` anterior
  sin ese `delivered`

### Requirement: Nota del reenvío sin datos personales

La nota del reenvío SHALL ser opcional, de hasta 200 caracteres, y SHALL
rechazarse con `422 invalid_note` si contiene un teléfono, email o DNI. El error
y los logs SHALL NOT repetir el valor rechazado.

#### Scenario: Nota con datos personales

- **WHEN** recepción envía una nota con un DNI o un teléfono
- **THEN** responde `422 invalid_note`, no crea la fila y no repite el valor en
  el error ni en los logs

### Requirement: Límites anti-duplicado y concurrencia

El reenvío SHALL respetar el cooldown por job (`409 resend_cooldown` con
`retry_after_s > 0`) y el tope diario por job en el día local de la clínica
(`409 resend_limit`). Dos pedidos concurrentes bajo `FOR UPDATE` SHALL producir
un solo `202` y un `409 resend_cooldown`, con una sola fila de auditoría.

#### Scenario: Doble clic inmediato

- **WHEN** recepción hace dos veces clic en "Reenviar" dentro del cooldown
- **THEN** el primer pedido responde `202` y el segundo `409 resend_cooldown`

#### Scenario: Tope diario

- **WHEN** un job ya alcanzó el máximo diario de reenvíos manuales
- **THEN** el siguiente pedido responde `409 resend_limit` y no crea auditoría

#### Scenario: Dos recepcionistas a la vez

- **WHEN** dos requests concurrentes reenvían el mismo job
- **THEN** una responde `202`, la otra `409 resend_cooldown` con `retry_after_s > 0`
  (no `reminder_pending`) y existe una sola fila en `reminder_manual_resend`

### Requirement: Orden de las guardas del reenvío

El reenvío SHALL evaluar consentimiento, destinatario, cooldown y tope **antes**
de verificar el estado del job. Un job `scheduled` con `manual_resend_at IS NOT
NULL` es un reenvío en curso y SHALL responder `409 resend_cooldown`; `409
reminder_pending` queda para un job `scheduled` ordinario (`manual_resend_at IS
NULL`).

#### Scenario: Reenvío en cola pasado el cooldown

- **WHEN** recepción reenvió un paso, el worker todavía no lo envió y pasó el
  cooldown
- **THEN** un nuevo pedido responde `409 resend_cooldown` con `retry_after_s > 0`
  y no `reminder_pending`

### Requirement: Reenvío tras recuperar el consentimiento

Un job `skipped` por `no_consent` SHALL poder reenviarse después de que recepción
registre el opt-in del canal, siempre que las demás guardas se cumplan.

#### Scenario: Opt-in antes del reenvío

- **WHEN** un job de WhatsApp quedó `skipped (no_consent)`, recepción registra el
  opt-in y luego reenvía
- **THEN** responde `202` y el job queda `scheduled`

### Requirement: Confirmación manual auditada

La confirmación manual de un turno `pending` SHALL ejecutarse con
`POST /api/appointments/{id}/transitions` y `to=confirmed`, que SHALL escribir
`appointment_event` con el actor de usuario en la misma transacción (RN-GL-01).
La operación SHALL ser exclusiva de admin y recepción; el odontólogo SHALL
recibir `403 forbidden_role`. Un turno que ya no está `pending` SHALL NOT generar
un segundo evento de confirmación.

#### Scenario: Recepción confirma un turno pendiente

- **WHEN** recepción confirma un turno `pending` desde la agenda
- **THEN** el turno queda `confirmed` y existe un evento `confirmed` con
  `actor_type=user` y el id del usuario

#### Scenario: Odontólogo intenta confirmar

- **WHEN** un odontólogo intenta confirmar un turno `pending`
- **THEN** responde `403 forbidden_role` y no se escribe ningún evento

#### Scenario: Confirmación repetida

- **WHEN** recepción confirma un turno que ya está `confirmed`
- **THEN** la API rechaza la transición y no se agrega un segundo evento
  `confirmed`
