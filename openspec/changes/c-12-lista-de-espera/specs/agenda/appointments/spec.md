# Spec Delta — agenda/appointments

## ADDED Requirements

### Requirement: Turno con origen lista de espera

Un turno creado por la aceptación de una oferta SHALL tener origen `waitlist`,
SHALL nacer `confirmed`, SHALL NOT ser sobreturno ni tener hash de token
aleatorio, y su inicio SHALL ser futuro. La base SHALL rechazar un turno
`waitlist` marcado como sobreturno. El evento `created` SHALL registrar el id de
la oferta, sin datos del paciente.

#### Scenario: Turno de lista de espera persistido

- **WHEN** se acepta una oferta en un hueco libre
- **THEN** el turno persiste con `origin=waitlist`, `status=confirmed`,
  `is_overbooking=false` y `manage_token_hash` nulo

#### Scenario: Sobreturno de lista de espera rechazado por la base

- **WHEN** se intenta persistir un turno `origin=waitlist` con `is_overbooking=true`
- **THEN** la base lo rechaza con violación de CHECK

#### Scenario: Evento de creación con la oferta

- **WHEN** se crea un turno por una aceptación
- **THEN** su evento `created` registra `origin=waitlist` y el id de la oferta

#### Scenario: Hueco en el pasado

- **WHEN** se intenta crear un turno con origen `waitlist` cuyo inicio ya pasó
- **THEN** responde `422 appointment_in_past` y no se crea turno (una oferta de ese hueco ya
  estaría vencida: su `expires_at` nunca supera el inicio)

#### Scenario: Gestión del turno por link firmado

- **WHEN** el paciente abre el link de gestión que recibe con el turno nuevo
- **THEN** puede verlo, cancelarlo o reprogramarlo como cualquier turno

### Requirement: La cancelación evalúa la lista de espera

Toda transición a `cancelled` SHALL invocar la evaluación de la lista de espera
dentro de su misma transacción, después de cancelar los recordatorios
pendientes. Si la evaluación falla, la cancelación SHALL revertir y el turno
SHALL conservar su estado.

#### Scenario: Cancelación con oferta

- **WHEN** recepción cancela un turno futuro con una entrada compatible en la cola
- **THEN** el turno queda `cancelled`, sus jobs pendientes `cancelled` y existe una
  oferta para ese hueco, todo en un solo commit

#### Scenario: Evaluación que falla

- **WHEN** la evaluación lanza un error inesperado durante una cancelación
- **THEN** el turno sigue en su estado anterior y no hay evento `cancelled`

#### Scenario: Asistencia no evalúa

- **WHEN** recepción marca `no_show` un turno
- **THEN** no se evalúa la lista de espera
