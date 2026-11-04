# Spec Delta — agenda/appointments

## ADDED Requirements

### Requirement: Instantánea del turno en cada evento

Cada `appointment_event` nuevo SHALL registrar el horario y los recursos del
turno vigentes tras la mutación (`slot_starts_at`, `slot_ends_at`,
`professional_id`, `chair_id`), escritos en la misma transacción que la
mutación. La instantánea SHALL contener solo identificadores y fechas, nunca
datos del paciente. Los eventos previos a este change SHALL permanecer sin
instantánea (la tabla sigue siendo inmutable).

#### Scenario: Evento de creación
- **WHEN** recepción crea un turno el 2026-12-01 10:00 con un profesional y un sillón
- **THEN** su evento `created` tiene `slot_starts_at` 10:00, `slot_ends_at` coherente y ambos recursos

#### Scenario: Reprogramación
- **WHEN** el turno se mueve a otro horario y sillón
- **THEN** el evento `rescheduled` lleva la instantánea del horario y sillón nuevos

#### Scenario: Transición de estado
- **WHEN** el turno se marca `present`
- **THEN** el evento `present` conserva la instantánea vigente

#### Scenario: Auditoría inmutable
- **WHEN** se intenta `UPDATE` o `DELETE` sobre un evento con instantánea
- **THEN** la base lo rechaza
