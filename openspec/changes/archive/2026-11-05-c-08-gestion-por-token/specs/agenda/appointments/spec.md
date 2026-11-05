# Spec Delta — agenda/appointments

## ADDED Requirements

### Requirement: Transiciones del paciente con su token

Un actor de tipo `patient_token` SHALL poder ejecutar `pending→confirmed` y
`pending|confirmed→cancelled` sobre el turno de su token, sin roles de personal y
sujeto a las mismas guardas temporales y a la ventana de cancelación de la
clínica. Toda transición SHALL quedar auditada con `actor_type=patient_token`.

#### Scenario: Confirmación por token

- **WHEN** el actor es `patient_token` y el turno está `pending`
- **THEN** la transición a `confirmed` se aplica y el evento registra `from_status=pending`

#### Scenario: Cancelación por token antes del inicio

- **WHEN** el actor es `patient_token` y el turno `confirmed` empieza en 5 días con ventana de 24 h
- **THEN** la transición a `cancelled` se aplica con causa `paciente`

#### Scenario: El token no puede marcar asistencia

- **WHEN** el actor es `patient_token` y se pide `present`, `absent` o `no_show`
- **THEN** responde `409 invalid_transition` y el turno no cambia

### Requirement: Repetición de una acción del paciente es un no-op auditado

Reaplicar una transición ya alcanzada SHALL NOT duplicar el evento de estado:
SHALL registrar un evento `updated` con `idempotent_replay=true` y la acción
pedida, y devolver el estado actual. `cancelled`, `absent` y `no_show` SHALL
seguir siendo terminales.

#### Scenario: Segunda confirmación

- **WHEN** se repite la confirmación sobre un turno ya `confirmed`
- **THEN** se escribe un evento `updated` de replay y no un segundo `confirmed`

#### Scenario: Segunda cancelación

- **WHEN** se repite la cancelación sobre un turno ya `cancelled`
- **THEN** se escribe un evento `updated` de replay y el reporte no cuenta dos cancelaciones

### Requirement: Reprogramación por token reutiliza el camino atómico

La reprogramación por token SHALL usar el mismo camino de escritura que la
reprogramación de recepción, sin commit propio, conservando el `appointment_id`,
revalidando plantilla, bloqueos y recursos, y dejando la restricción de
exclusión de la base como barrera final. La colisión SHALL traducirse a `409
slot_taken` y el turno SHALL conservar su horario original.

#### Scenario: Reprogramación por token con colisión

- **WHEN** el paciente mueve su turno a un horario ocupado
- **THEN** responde `409 slot_taken` y el turno conserva horario, estado y sillón

#### Scenario: La reprogramación por token y la de recepción compiten

- **WHEN** el paciente y recepción mueven turnos al mismo hueco a la vez
- **THEN** exactamente una persiste y la otra recibe `409 slot_taken`

#### Scenario: La reprogramación no cambia el origen ni el token

- **WHEN** se reprograma un turno `origin=online`
- **THEN** conserva su origen y su hash de token de gestión
