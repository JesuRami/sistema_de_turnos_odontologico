# reminders/followup-board Specification

## Purpose
Convierte los jobs y eventos de recordatorio en una lista operativa para el día
de recepción: qué turnos siguen sin confirmar después del paso de 24 h y qué
turnos tienen un fallo de entrega que requiere una llamada o un reenvío.

## Requirements

### Requirement: Lista de seguimiento por rango

`GET /api/reminders/follow-up?from=&to=` SHALL devolver, para admin y recepción
de la clínica, los turnos con `starts_at` en `[from, to)` que requieren
seguimiento, ordenados por hora de inicio ascendente y paginados por cursor. El
odontólogo SHALL recibir `403 forbidden_role`; sin sesión, `401`. Un rango mayor
a 31 días SHALL responder `422 range_too_large`; `from > to`, `422
invalid_range`.

#### Scenario: Recepción abre el panel del día

- **WHEN** recepción pide el seguimiento de hoy
- **THEN** recibe los turnos que requieren llamada, ordenados por hora, con sus
  motivos y el último recordatorio

#### Scenario: Odontólogo pide el panel

- **WHEN** un odontólogo llama al endpoint de seguimiento
- **THEN** responde `403 forbidden_role`

#### Scenario: Aislamiento entre clínicas

- **WHEN** las clínicas A y B tienen turnos pendientes en el mismo rango
- **THEN** recepción de A ve solo los turnos de A

#### Scenario: Rango invertido

- **WHEN** `from` es posterior a `to`
- **THEN** responde `422 invalid_range`

### Requirement: Definición de "pendiente sin confirmar"

Un turno SHALL listarse con motivo `no_response` cuando esté `pending` y exista
un evento `sent` del paso de confirmación más cercano ya enviado. Se SHALL
preferir el paso `t_24h` si la clínica lo configura; si no, el último paso que
pide confirmación y tiene un `sent`. Un turno `confirmed` SHALL NOT listarse por
este motivo.

#### Scenario: No respondió el recordatorio de 24 h

- **WHEN** un turno online sigue `pending` y su job de 24 h tiene un evento
  `sent`
- **THEN** aparece con motivo `no_response`

#### Scenario: Turno ya confirmado

- **WHEN** el paciente confirmó el turno por WhatsApp o por el link
- **THEN** el turno no aparece como `no_response`

#### Scenario: Clínica sin paso de 24 h

- **WHEN** la clínica configura solo 72 h y 3 h y el turno sigue `pending` con el
  job de 72 h enviado
- **THEN** aparece como `no_response` por el último paso de confirmación enviado

#### Scenario: Recordatorio de 24 h fallido

- **WHEN** el job de 24 h terminó `failed` y el turno sigue `pending`
- **THEN** aparece con motivo `delivery_failed` y no como `no_response`

### Requirement: Alerta de fallos de entrega

Un turno SHALL listarse con motivo `delivery_failed` cuando tenga al menos un job
con `status=failed`, `scheduled_for` anterior al inicio del turno y sin un envío
exitoso posterior del mismo `(step, channel)`. El motivo SHALL desaparecer
cuando el job deja de estar `failed` o el turno deja de estar vigente o futuro.

#### Scenario: Fallo sin reenvío

- **WHEN** el job de 3 h de un turno confirmado queda `failed` y no se reenvió
- **THEN** el turno aparece con motivo `delivery_failed` y el último error

#### Scenario: Reenvío exitoso

- **WHEN** recepción reenvía el job fallido y el worker lo envía correctamente
- **THEN** el turno deja de aparecer por `delivery_failed`

#### Scenario: Turno cancelado

- **WHEN** un turno con un job fallido se cancela
- **THEN** deja de aparecer en el seguimiento

#### Scenario: Fallo de otra clínica

- **WHEN** el job fallido pertenece a la clínica B
- **THEN** no aparece en el seguimiento de la clínica A

### Requirement: Datos de la fila sin PII innecesaria

Cada fila SHALL incluir `appointment_id`, `starts_at`, `patient_id`,
`patient_name`, `professional_id`, `status`, `reasons`, `last_reminder` y
`can_confirm`. SHALL NOT incluir teléfono, email, DNI, links de gestión ni ids
del proveedor. Los logs del endpoint SHALL NOT contener datos personales.

#### Scenario: Fila completa

- **WHEN** recepción ve un turno con motivo `no_response`
- **THEN** la fila muestra el nombre del paciente, la hora, el motivo y el último
  paso, sin teléfono ni email

#### Scenario: Error del endpoint

- **WHEN** la consulta falla por un error interno
- **THEN** el log no incluye nombre, teléfono ni email de ningún paciente

### Requirement: Borde del día en la zona de la clínica

El rango SHALL interpretarse en la zona horaria de la clínica: un turno que
empieza a las 23:30 locales del último día del rango SHALL incluirse en ese
rango y no en el siguiente.

#### Scenario: Turno de las 23:30

- **WHEN** un turno empieza a las 23:30 locales del 31/10 y el rango termina el
  31/10
- **THEN** el turno aparece en ese rango
