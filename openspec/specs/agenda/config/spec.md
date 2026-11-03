# agenda/config Specification

## Purpose
Define la configuración de agenda de cada clínica —profesionales, sillones,
plantilla semanal sin solapamientos, bloqueos, políticas operativas— con baja
lógica, RBAC por rol, aislamiento por tenant y auditoría append-only de cada
mutación. Los turnos y su disponibilidad se especifican en capacidades
posteriores (C-05, C-07).

## Requirements

### Requirement: Gestión de profesionales y sillones sin borrado

El administrador SHALL poder dar de alta, editar, desactivar y reactivar
profesionales (nombre, color `#RRGGBB`, duración default, buffer) y sillones de
su clínica. La baja SHALL ser lógica (`active=false`) y conservar el registro.
Recepción SHALL tener solo lectura; el odontólogo SHALL ver únicamente su propio
profesional.

#### Scenario: Admin desactiva un profesional

- **WHEN** un admin envía `PATCH /api/professionals/{id}` con `active=false`
- **THEN** responde 200, la fila sigue existiendo con `active=false` y se
  registra un evento `deactivated`

#### Scenario: Recepción no puede escribir

- **WHEN** recepción envía `POST /api/professionals`
- **THEN** responde `403 forbidden_role` y no persiste nada

#### Scenario: Odontólogo pide otro profesional

- **WHEN** un odontólogo pide `GET /api/professionals/{id}` de un colega
- **THEN** responde `404 not_found`

### Requirement: Plantilla semanal sin solapamientos garantizada en la base

El sistema SHALL rechazar, mediante un constraint de exclusión en PostgreSQL,
dos reglas activas del mismo (clínica, profesional, sillón, día de semana) cuyas
franjas horarias y vigencias se intersecten. La API SHALL responder `409
schedule_overlap` indicando las reglas en conflicto.

#### Scenario: Regla solapada rechazada

- **WHEN** existe lunes 09:00–13:00 vigente desde 2026-01-01 sin fin y se crea
  lunes 12:00–15:00 para el mismo profesional y sillón
- **THEN** responde `409 schedule_overlap` con el id de la regla existente

#### Scenario: Franjas contiguas conviven

- **WHEN** existe lunes 09:00–13:00 y se crea lunes 13:00–17:00
- **THEN** ambas persisten

#### Scenario: Regla inactiva no bloquea

- **WHEN** la regla existente está desactivada y se crea otra solapada
- **THEN** la nueva persiste

#### Scenario: Recurso inactivo

- **WHEN** se crea una regla para un profesional o sillón inactivo
- **THEN** responde `422 resource_inactive`

### Requirement: Bloqueo con objetivo y motivo de catálogo

Un bloqueo SHALL tener al menos un objetivo (profesional, sillón o ambos), un
rango `ends_at > starts_at` y un motivo del catálogo `vacaciones, feriado,
mantenimiento, reunion, otro`. Admin, recepción y odontólogo (solo con su
propio profesional) SHALL poder crearlos.

#### Scenario: Bloqueo sin objetivo rechazado

- **WHEN** se crea un bloqueo sin profesional ni sillón
- **THEN** responde 422 y no persiste

#### Scenario: Motivo fuera de catálogo rechazado

- **WHEN** se crea un bloqueo con motivo `siesta`
- **THEN** responde 422

#### Scenario: Odontólogo bloquea a un colega

- **WHEN** un odontólogo crea un bloqueo con el `professional_id` de otro
- **THEN** responde `403 forbidden_scope`

### Requirement: Bloqueos pasados inmutables y retiro lógico

Un bloqueo terminado SHALL ser inmutable. Uno en curso SHALL admitir solo mover
su fin a un instante no pasado. Uno futuro SHALL poder editarse o retirarse; el
retiro SHALL ser lógico y quedar auditado.

#### Scenario: Editar un bloqueo terminado

- **WHEN** un admin edita un bloqueo cuyo `ends_at` ya pasó
- **THEN** responde `409 block_immutable`

#### Scenario: Retirar un bloqueo futuro

- **WHEN** un admin envía `DELETE /api/blocks/{id}` sobre un bloqueo futuro
- **THEN** responde 204, la fila conserva `removed_at` y deja de listarse

### Requirement: Cierre de clínica como bloqueo de todos los sillones

El administrador SHALL poder cargar un feriado o cierre que cree, en una sola
transacción, un bloqueo por cada sillón activo de la clínica en el rango.

#### Scenario: Feriado sobre tres sillones

- **WHEN** la clínica tiene tres sillones activos y uno inactivo y el admin carga
  un cierre
- **THEN** se crean exactamente tres bloqueos con motivo `feriado`

### Requirement: Políticas de clínica editables con defaults sanos

Cada clínica SHALL exponer ventana de cancelación (24 h), pasos de recordatorio
(72/24/3 h), tope de sobreturnos por profesional y día (2) y expiración de
ofertas de lista de espera (4 h). El admin SHALL poder editarlos; recepción
SHALL poder leerlos.

#### Scenario: Defaults de una clínica nueva

- **WHEN** un admin pide `GET /api/clinic/policies` de una clínica recién creada
- **THEN** recibe `24`, pasos `72/24/3`, `2` y `4`

#### Scenario: Pasos de recordatorio duplicados

- **WHEN** el admin envía dos pasos con el mismo `offset_h`
- **THEN** responde 422 y la política no cambia

### Requirement: Toda mutación de configuración queda auditada

Cada alta, edición, baja, reactivación o retiro de configuración SHALL escribir
un `agenda_config_event` con actor y valores anterior/nuevo en la misma
transacción. La tabla SHALL ser append-only en la base.

#### Scenario: Evento por cambio de política

- **WHEN** el admin cambia la ventana de cancelación de 24 a 48
- **THEN** existe un evento `clinic_policy/updated` con `{"cancellation_window_hours": [24, 48]}`

#### Scenario: Auditoría inmutable

- **WHEN** se intenta `UPDATE` o `DELETE` sobre `agenda_config_event`
- **THEN** la base lo rechaza

### Requirement: Aislamiento por clínica en la configuración

Toda lectura y escritura de configuración SHALL acotarse a la clínica del
principal. Referenciar un recurso de otra clínica SHALL responder 404 (por id) o
422 (en el body), sin revelar datos.

#### Scenario: Admin de B lee un profesional de A

- **WHEN** un admin de la clínica B pide un profesional de A por id
- **THEN** responde `404 not_found`

#### Scenario: Regla con sillón de otra clínica

- **WHEN** un admin de B crea una regla con un `chair_id` de A
- **THEN** responde 422
