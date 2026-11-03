# web/agenda-admin Specification

## Purpose

Define las pantallas con las que el admin configura la clínica en la SPA
—profesionales, sillones, plantilla semanal, bloqueos y políticas— y cómo
resuelve los turnos que un bloqueo pisa.

## Requirements

### Requirement: Gestión de profesionales y sillones

El admin SHALL listar, crear y editar profesionales (nombre, color, duración por
defecto, buffer, reserva online) y sillones, y desactivarlos o reactivarlos.
La SPA SHALL NOT ofrecer borrar ninguno.

#### Scenario: Alta de profesional

- **WHEN** el admin crea un profesional ficticio con color y buffer de 10 minutos
- **THEN** aparece en el listado y en el filtro de la agenda con ese color

#### Scenario: Desactivar un sillón

- **WHEN** el admin desactiva un sillón
- **THEN** el sillón queda marcado inactivo y deja de mostrarse como columna de la agenda

### Requirement: Plantilla semanal

El admin SHALL ver la plantilla semanal por profesional y sillón, y crear,
editar o desactivar franjas. Ante `409 schedule_overlap`, la SPA SHALL señalar
las franjas con las que se solapa.

#### Scenario: Franja nueva

- **WHEN** el admin agrega los martes de 14:00 a 18:00 con slots de 30 minutos
- **THEN** la franja aparece en la plantilla

#### Scenario: Franja solapada

- **WHEN** la API responde `409 schedule_overlap`
- **THEN** la SPA marca las franjas en conflicto y no guarda la nueva

### Requirement: Bloqueos con resolución de turnos afectados

El personal SHALL crear bloqueos de profesional, de sillón o de ambos con
motivo del catálogo; el admin SHALL editarlos, retirarlos y cargar cierres de
clínica. Ante `409 block_conflicts`, la SPA SHALL listar los turnos afectados
(fecha, hora y profesional) y permitir cancelarlos con motivo en la misma
operación; solo admin y recepción SHALL ver esa opción.

#### Scenario: Bloqueo que pisa turnos

- **WHEN** recepción bloquea las vacaciones de una profesional que tiene 2 turnos en ese rango
- **THEN** la SPA lista los 2 turnos y ofrece cancelarlos con motivo `bloqueo`

#### Scenario: Resolución confirmada

- **WHEN** recepción confirma cancelar ambos turnos
- **THEN** el bloqueo se crea y los turnos aparecen cancelados en la agenda

#### Scenario: Odontólogo con turnos afectados

- **WHEN** un odontólogo bloquea su propia agenda sobre un turno suyo
- **THEN** la SPA informa que recepción debe resolver los turnos y no ofrece cancelarlos

### Requirement: Políticas de la clínica

El admin SHALL editar la ventana de cancelación, los pasos de recordatorio, el
tope de sobreturnos y la vigencia de ofertas, viendo los valores actuales.
Recepción SHALL verlas en solo lectura.

#### Scenario: Cambio de tope

- **WHEN** el admin cambia el tope de sobreturnos a 3
- **THEN** la pantalla muestra 3 al volver a cargarla

#### Scenario: Recepción consulta

- **WHEN** recepción abre las políticas
- **THEN** ve los valores sin controles de edición
