# agenda/appointments Specification

## Purpose

Define el turno de la clínica: su invariante anti-solapamiento garantizada por
la base, su máquina de estados, los sobreturnos explícitos, la reprogramación y
cancelación controladas, la consulta de agenda y la auditoría inmutable de cada
cambio.

## Requirements

### Requirement: Invariante anti-solapamiento garantizada en la base

La base SHALL rechazar dos turnos vigentes (`pending`, `confirmed`, `present`)
no sobreturno que compartan profesional o sillón con rangos ocupados
intersectados. El rango ocupado SHALL ser `[starts_at, ends_at + buffer del
profesional)`. Los turnos `cancelled`, `absent` y `no_show` SHALL liberar el
hueco.

#### Scenario: Mismo profesional en horario intersectado

- **WHEN** existe un turno vigente 10:00–10:30 del profesional P en el sillón 1
  y se crea otro 10:15–10:45 de P en el sillón 2
- **THEN** responde `409 slot_taken` con el id del turno existente y no persiste

#### Scenario: Mismo sillón con otro profesional

- **WHEN** existe un turno vigente 10:00–10:30 en el sillón 1 y se crea otro
  10:00–10:30 en el sillón 1 con otro profesional
- **THEN** responde `409 slot_taken`

#### Scenario: Turnos contiguos conviven

- **WHEN** el profesional no tiene buffer, existe 10:00–10:30 y se crea 10:30–11:00
- **THEN** ambos persisten

#### Scenario: El buffer integra el rango ocupado

- **WHEN** el profesional tiene `buffer_min=10`, existe 10:00–10:30 y se crea
  10:35–11:00 para el mismo profesional
- **THEN** responde `409 slot_taken`

#### Scenario: Turno cancelado libera el hueco

- **WHEN** el turno 10:00–10:30 se cancela y se crea otro 10:00–10:30 para el
  mismo profesional y sillón
- **THEN** el nuevo persiste

#### Scenario: Carrera concurrente por el mismo hueco

- **WHEN** una reserva de recepción y una reserva online piden el mismo hueco
  al mismo tiempo desde conexiones distintas
- **THEN** exactamente una persiste y la otra recibe `409 slot_taken`

### Requirement: La colisión ofrece horarios alternativos

Ante `409 slot_taken`, la respuesta SHALL incluir los ids de los turnos en
conflicto y hasta 3 horarios alternativos libres del mismo profesional y
sillón, dentro de su plantilla semanal vigente y fuera de bloqueos, en los
próximos 14 días. La respuesta SHALL omitir todo dato personal de pacientes.

#### Scenario: Alternativos dentro de la plantilla

- **WHEN** el hueco pedido está ocupado y el mismo día quedan libres 11:00 y
  11:30 de la plantilla
- **THEN** la respuesta lista esos horarios entre los alternativos, en orden
  cronológico

#### Scenario: Sin alternativos

- **WHEN** no queda ningún hueco libre en los próximos 14 días
- **THEN** responde `409 slot_taken` con `alternatives` vacío

### Requirement: Turno solo dentro de horario vigente, fuera de bloqueos y con recursos activos

Crear o reprogramar un turno SHALL exigir que `[starts_at, ends_at)` caiga
completo dentro de una regla semanal activa y vigente del par profesional-sillón
(en la zona horaria de la clínica), que no intersecte un bloqueo vigente del
profesional o del sillón y que ambos recursos estén activos. El sobreturno no
exime de estas condiciones.

#### Scenario: Fuera de la plantilla semanal

- **WHEN** la regla del lunes es 09:00–13:00 y se crea un turno el lunes a las 13:30
- **THEN** responde `422 outside_schedule`

#### Scenario: Dentro de un bloqueo

- **WHEN** el profesional tiene un bloqueo de vacaciones y se crea un turno en ese rango
- **THEN** responde `409 slot_blocked` con el id del bloqueo

#### Scenario: Profesional inactivo

- **WHEN** el profesional tiene `active=false` y se crea un turno para él
- **THEN** responde `409 resource_inactive`

#### Scenario: Turno en un día pasado

- **WHEN** se crea un turno cuyo día local ya pasó
- **THEN** responde `422 appointment_in_past`

### Requirement: Alta de turno desde recepción

Admin y recepción SHALL poder crear un turno para un paciente de su clínica
indicando profesional, sillón e inicio. La duración default SHALL ser la
`slot_duration_min` de la regla que lo contiene. El turno de recepción SHALL
nacer `confirmed` con origen `reception`. El odontólogo SHALL NOT crear turnos.

#### Scenario: Recepción crea un turno

- **WHEN** recepción crea un turno válido sin indicar duración en una regla de
  30 minutos
- **THEN** responde 201 con `status=confirmed`, `origin=reception`,
  `ends_at = starts_at + 30 min` y se registra un evento `created`

#### Scenario: Odontólogo intenta crear

- **WHEN** un odontólogo envía `POST /api/appointments`
- **THEN** responde `403 forbidden_role`

#### Scenario: Paciente de otra clínica

- **WHEN** el body referencia un paciente, profesional o sillón de otra clínica
- **THEN** responde 422 sin revelar si existe

### Requirement: El turno online nace pendiente y nunca es sobreturno

Un turno con origen `online` SHALL nacer `pending` y la base SHALL rechazar
cualquier turno online marcado como sobreturno.

#### Scenario: Turno online persistido

- **WHEN** el servicio crea un turno con origen `online` en un hueco libre
- **THEN** persiste con `status=pending` e `is_overbooking=false`

#### Scenario: Sobreturno online rechazado por la base

- **WHEN** se intenta persistir un turno `origin=online` con `is_overbooking=true`
- **THEN** la base lo rechaza con violación de CHECK

### Requirement: Sobreturno explícito, con motivo y rol autorizado

Un sobreturno SHALL requerir `is_overbooking=true` explícito, motivo no vacío y
rol admin o recepción, y SHALL persistir solo si el horario colisiona con un
turno vigente. Al crearlo SHALL registrarse un evento `overbooking_created`
con actor, motivo y turnos con los que colisiona.

#### Scenario: Sobreturno sin motivo

- **WHEN** recepción envía `is_overbooking=true` sin motivo
- **THEN** responde 422 y no persiste

#### Scenario: Sobreturno válido

- **WHEN** recepción envía `is_overbooking=true` con motivo sobre un hueco ocupado
- **THEN** responde 201 con `is_overbooking=true` y el evento `overbooking_created`
  lista el turno con el que colisiona

#### Scenario: Sobreturno innecesario

- **WHEN** se envía `is_overbooking=true` sobre un hueco libre
- **THEN** responde `422 overbooking_not_needed`

#### Scenario: Un turno normal no se superpone a un sobreturno vigente

- **WHEN** existe un sobreturno vigente 10:00–10:30, se cancela el turno con el
  que colisionaba y se crea un turno normal 10:00–10:30 para el mismo profesional
- **THEN** responde `409 slot_taken` con el id del sobreturno

### Requirement: Tope diario de sobreturnos por profesional

La clínica SHALL limitar los sobreturnos vigentes por profesional y día local a
`max_overbookings_per_day`. Recepción SHALL recibir `409 overbooking_limit` al
superarlo; el admin SHALL poder excederlo y el evento SHALL registrar el exceso.

#### Scenario: Recepción supera el tope

- **WHEN** el tope es 2, el profesional ya tiene 2 sobreturnos vigentes ese día
  y recepción crea un tercero
- **THEN** responde `409 overbooking_limit`

#### Scenario: Admin supera el tope

- **WHEN** en la misma situación lo crea un admin
- **THEN** responde 201 y el evento indica `over_limit=true`

### Requirement: Máquina de estados del turno

Las transiciones SHALL limitarse a: `pending→confirmed`, `confirmed→present`,
`pending|confirmed→cancelled`, `confirmed→absent` y `confirmed→no_show`.
`cancelled`, `absent` y `no_show` SHALL ser terminales. Toda transición no
listada SHALL responder `409 invalid_transition` sin cambios.

#### Scenario: Confirmación manual

- **WHEN** recepción confirma un turno `pending`
- **THEN** pasa a `confirmed` y se registra un evento `confirmed` con
  `from_status=pending`

#### Scenario: Transición desde estado terminal

- **WHEN** se intenta confirmar un turno `cancelled`
- **THEN** responde `409 invalid_transition` y el turno no cambia

#### Scenario: Pendiente no pasa directo a presente

- **WHEN** se marca presente un turno `pending`
- **THEN** responde `409 invalid_transition`

### Requirement: Asistencia solo por personal y desde el día del turno

`present` SHALL marcarse solo desde el día local del turno; `absent` y
`no_show` solo desde su hora de inicio. Admin y recepción SHALL poder marcar
cualquier turno de su clínica y el odontólogo solo los suyos. `no_show` SHALL
ser sin aviso y `absent` con aviso tardío o justificado.

#### Scenario: Presente en un turno futuro

- **WHEN** se marca presente un turno de mañana
- **THEN** responde `409 attendance_too_early`

#### Scenario: No-show antes de la hora

- **WHEN** se marca `no_show` un turno de hoy que todavía no empezó
- **THEN** responde `409 attendance_too_early`

#### Scenario: Odontólogo marca su turno

- **WHEN** un odontólogo marca presente un turno propio de hoy
- **THEN** pasa a `present`

#### Scenario: Odontólogo marca turno ajeno

- **WHEN** un odontólogo marca presente un turno de otro profesional
- **THEN** responde `404 not_found`

### Requirement: Cancelación con motivo, solo antes del inicio

Admin y recepción SHALL cancelar indicando un motivo del catálogo (`paciente`,
`profesional`, `clinica`, `bloqueo`, `otro`) y una nota opcional. Un turno
`present` o ya empezado SHALL NOT cancelarse. El evento SHALL indicar si la
cancelación fue tardía (dentro de la ventana de cancelación de la clínica).

#### Scenario: Cancelación sin motivo

- **WHEN** recepción cancela sin motivo
- **THEN** responde 422 y el turno no cambia

#### Scenario: Cancelación tardía registrada

- **WHEN** la ventana es 24 h y recepción cancela un turno que empieza en 3 h
- **THEN** pasa a `cancelled` y el evento registra `late=true`

#### Scenario: Turno ya empezado

- **WHEN** se cancela un turno cuyo inicio ya pasó
- **THEN** responde `409 appointment_started`

### Requirement: Reprogramación atómica que conserva el turno

Admin y recepción SHALL poder mover un turno `pending` o `confirmed` no empezado
a otro horario, sillón o profesional. La operación SHALL revalidar todas las
condiciones de alta; si alguna falla, el turno SHALL conservar su horario
original. SHALL conservar el id y auditar el horario anterior y el nuevo.

#### Scenario: Reprogramación exitosa

- **WHEN** recepción mueve un turno de 10:00 a 11:00 en un hueco libre
- **THEN** responde 200 con el mismo id y se registra un evento `rescheduled`
  con el horario anterior y el nuevo

#### Scenario: Reprogramación que colisiona

- **WHEN** recepción mueve un turno a un horario ocupado
- **THEN** responde `409 slot_taken` y el turno conserva su horario original

#### Scenario: Reprogramar sobre sí mismo

- **WHEN** un turno 10:00–10:30 se mueve a 10:15–10:45 y no hay otros turnos
- **THEN** responde 200 (el turno no colisiona consigo mismo)

### Requirement: Los turnos nunca se borran

El sistema SHALL NOT exponer ninguna operación de borrado físico de turnos; la
única baja SHALL ser la cancelación con motivo.

#### Scenario: DELETE no existe

- **WHEN** se envía `DELETE /api/appointments/{id}`
- **THEN** responde 405 y el turno sigue existiendo

### Requirement: Auditoría inmutable de cada mutación del turno

Cada alta, transición, reprogramación o edición SHALL escribir en la misma
transacción un evento con actor, tipo, estado anterior y nuevo, y los valores
anteriores y nuevos. Si el evento no se escribe, la mutación SHALL fallar. La
base SHALL rechazar UPDATE y DELETE sobre los eventos.

#### Scenario: Evento rechaza UPDATE

- **WHEN** se ejecuta un UPDATE o DELETE sobre un evento de turno
- **THEN** la base lo rechaza con error

#### Scenario: Falla de auditoría revierte la mutación

- **WHEN** la escritura del evento falla durante una cancelación
- **THEN** el turno conserva su estado anterior

#### Scenario: Historial visible solo para admin

- **WHEN** un admin pide `GET /api/appointments/{id}/events`
- **THEN** recibe los eventos en orden cronológico; recepción y odontólogo reciben
  `403 forbidden_role`

### Requirement: Consulta de agenda por rango con alcance por rol

El personal SHALL listar turnos que intersectan un rango (máximo 31 días) con
filtros por profesional, sillón y estado, ordenados por inicio y paginados por
cursor. El odontólogo SHALL ver solo sus turnos y sin teléfono ni email del
paciente.

#### Scenario: Recepción lista la semana

- **WHEN** recepción pide una semana sin filtros
- **THEN** recibe los turnos de todos los profesionales de su clínica, por inicio

#### Scenario: Odontólogo ve solo los suyos

- **WHEN** un odontólogo lista la semana
- **THEN** recibe solo turnos de su profesional y sin contacto del paciente

#### Scenario: Rango demasiado largo

- **WHEN** se pide un rango de 60 días
- **THEN** responde `422 invalid_range`

### Requirement: Aislamiento por clínica de los turnos

Un principal SHALL NOT leer, crear, modificar ni ver eventos de turnos de otra
clínica; pedir un turno ajeno por id SHALL responder `404 not_found`.

#### Scenario: Turno de otra clínica

- **WHEN** un admin de la clínica B pide o modifica un turno de la clínica A
- **THEN** responde `404 not_found` y el turno no cambia
