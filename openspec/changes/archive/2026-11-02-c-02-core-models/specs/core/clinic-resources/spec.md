# Spec Delta

## Purpose

Define la clínica (tenant) con su configuración operativa y los recursos de
agenda que la componen —profesionales, sillones y plantilla semanal— con sus
invariantes de datos, sin todavía turnos ni bloqueos.

## ADDED Requirements

### Requirement: Slug de clínica único global

Cada clínica SHALL tener un `slug` único en todo el sistema (es URL pública de
reserva). Un segundo alta con el mismo slug SHALL ser rechazada por la base.

#### Scenario: Slug duplicado rechazado

- **WHEN** existe una clínica con slug `clinica-demo` y se inserta otra con el
  mismo slug
- **THEN** la base rechaza la inserción con violación de unicidad

#### Scenario: Slugs distintos conviven

- **WHEN** se insertan clínicas con slugs `clinica-demo` y `clinica-demo-2`
- **THEN** ambas persisten

### Requirement: Configuración por clínica con defaults

Una clínica nueva SHALL tomar por defecto timezone
`America/Argentina/Buenos_Aires`, `cancellation_window_hours=24`,
`booking_enabled=false` y pasos de recordatorio 72 h, 24 h y 3 h por WhatsApp.
Los pasos SHALL ser una lista de `{offset_h, channel}` con canal cerrado.

#### Scenario: Defaults aplicados

- **WHEN** se crea una clínica indicando solo `name` y `slug`
- **THEN** persiste con la timezone, ventana de cancelación, booking
  deshabilitado y los tres pasos de recordatorio por defecto

#### Scenario: Paso de recordatorio inválido rechazado

- **WHEN** se valida un paso de recordatorio con canal `sms`, con `offset_h`
  no positivo o con un campo extra no declarado
- **THEN** la validación lo rechaza sin persistir nada

#### Scenario: Ventana de cancelación negativa rechazada

- **WHEN** se persiste una clínica con `cancellation_window_hours` negativo
- **THEN** la base rechaza la fila con violación de CHECK

### Requirement: Profesionales y sillones activables sin borrado

Profesionales y sillones SHALL tener estado `active`; la baja SHALL ser
`active=false` conservando la fila, y las búsquedas de recursos activos de una
clínica SHALL excluir los inactivos.

#### Scenario: Profesional inactivo excluido del listado de activos

- **WHEN** una clínica tiene un profesional activo y uno inactivo y se piden
  los profesionales activos
- **THEN** solo se devuelve el activo y el inactivo sigue existiendo

#### Scenario: Duración de turno del profesional positiva

- **WHEN** se persiste un profesional con `default_duration_min` cero o
  negativo, o `buffer_min` negativo
- **THEN** la base rechaza la fila con violación de CHECK

### Requirement: Plantilla semanal con franja horaria válida

Una `schedule_rule` SHALL vincular profesional y sillón de la misma clínica con
`weekday` 0–6, `start_time < end_time`, `slot_duration_min > 0` y vigencia
`valid_from ≤ valid_to` cuando `valid_to` no es nula.

#### Scenario: Franja invertida rechazada

- **WHEN** se persiste una regla con `start_time` 18:00 y `end_time` 09:00
- **THEN** la base rechaza la fila con violación de CHECK

#### Scenario: Día de semana fuera de rango rechazado

- **WHEN** se persiste una regla con `weekday` 7
- **THEN** la base rechaza la fila con violación de CHECK

#### Scenario: Regla válida persiste

- **WHEN** se persiste una regla lunes 09:00–13:00, slots de 30 min, vigente
  desde hoy sin fecha de fin
- **THEN** la regla queda guardada y asociada a su profesional y sillón
