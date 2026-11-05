# core/reports Specification

## Purpose

Define los reportes operativos de la clínica (ocupación, ausentismo y cancelaciones) y la auditoría global de turnos para el administrador, calculados estrictamente sobre eventos inmutables.

## Requirements

### Requirement: Reportes solo para administración

Los reportes y la auditoría de la clínica SHALL ser accesibles únicamente para
el rol admin. Recepción y odontólogo SHALL recibir `403 forbidden_role`; sin
sesión, `401`. Los datos SHALL limitarse a la clínica del usuario.

#### Scenario: Recepción pide un reporte
- **WHEN** un usuario de recepción llama `GET /api/reports/occupancy`
- **THEN** responde `403 forbidden_role`

#### Scenario: Aislamiento entre clínicas
- **WHEN** existen turnos en dos clínicas y el admin de la clínica A pide un reporte
- **THEN** los números incluyen solo turnos de la clínica A

### Requirement: Rango de fechas

Cada reporte SHALL requerir `from` y `to` (fechas locales de la clínica,
inclusive) y filtrar por la fecha del turno. `from > to` SHALL responder `422
invalid_range`; más de 366 días, `422 range_too_large`. Parámetros
desconocidos SHALL rechazarse.

#### Scenario: Rango invertido
- **WHEN** `from` es posterior a `to`
- **THEN** responde `422 invalid_range`

#### Scenario: Rango excesivo
- **WHEN** el rango supera 366 días
- **THEN** responde `422 range_too_large`

### Requirement: Cálculo sobre eventos

Los reportes SHALL calcularse desde `appointment_event`, tomando el último
evento de cada turno como su estado final, y SHALL NOT leer `appointment.status`.

#### Scenario: Estado mutado no cambia el reporte
- **WHEN** se altera directamente `appointment.status` de un turno en la base de pruebas sin escribir evento
- **THEN** el reporte no cambia

#### Scenario: Turno cancelado después de reprogramarse
- **WHEN** un turno se crea, se reprograma y se cancela
- **THEN** cuenta una vez, con su horario final y estado `cancelled`

### Requirement: Reporte de ocupación

`GET /api/reports/occupancy?group_by=professional|chair` SHALL devolver, por
recurso, minutos reservados (turnos `pending`, `confirmed` o `present`, sin
sobreturnos), cantidad de turnos, cantidad de sobreturnos, minutos de capacidad
(plantilla activa menos bloqueos en el rango) y `occupancy_pct`. SHALL
incluir `capacity_basis: "current_schedule"`.

#### Scenario: Ocupación parcial
- **WHEN** un profesional tiene 8 h de plantilla en el rango y 2 turnos de 60 min activos
- **THEN** reservados 120, capacidad 480 y `occupancy_pct` 25

#### Scenario: Turno cancelado no ocupa
- **WHEN** uno de esos turnos termina `cancelled`
- **THEN** reservados 60

#### Scenario: Bloqueo reduce la capacidad
- **WHEN** un bloqueo cubre 2 h de la plantilla
- **THEN** capacidad 360

#### Scenario: Sin capacidad
- **WHEN** un recurso no tiene plantilla en el rango
- **THEN** `occupancy_pct` es 0 y no hay error

### Requirement: Reporte de ausentismo

`GET /api/reports/absenteeism` SHALL devolver, por profesional, conteos
separados de `present`, `absent`, `no_show` y cancelaciones tardías
(`payload.late = true`), y las tasas `no_show_rate`, `absent_rate` y
`late_cancellation_rate` sobre `outcomes = present + absent + no_show +
cancelaciones tardías`. Las cancelaciones dentro de la ventana SHALL NOT
contarse en el denominador.

#### Scenario: no_show distinto de cancelación tardía
- **WHEN** hay 1 `no_show` y 1 cancelación tardía
- **THEN** `no_show` = 1 y `late_cancellations` = 1, contados por separado

#### Scenario: Tasas
- **WHEN** hay 6 `present`, 1 `absent`, 2 `no_show` y 1 cancelación tardía
- **THEN** `outcomes` = 10 y `no_show_rate` = 0.2

#### Scenario: Cancelación en ventana
- **WHEN** se cancela un turno con `late = false`
- **THEN** no aparece en `outcomes`

### Requirement: Reporte de cancelaciones por motivo

`GET /api/reports/cancellations` SHALL devolver el conteo de turnos cancelados
por motivo del catálogo (`paciente`, `profesional`, `clinica`, `bloqueo`,
`otro`), separando tardías y en ventana. Todos los motivos del catálogo SHALL
aparecer, con 0 si no hay casos.

#### Scenario: Motivos y tardías
- **WHEN** hay 2 cancelaciones `paciente` (1 tardía) y 1 `clinica`
- **THEN** `paciente` = 2 (late 1, in_window 1), `clinica` = 1, el resto 0

### Requirement: Exportación CSV de cada reporte

Cada reporte SHALL admitir `format=csv` con el mismo contenido que el JSON,
encabezados fijos, UTF-8 y `Content-Disposition` de descarga. Un valor que
empiece con `=`, `+`, `-` o `@` SHALL prefijarse con `'`. `format` fuera de
`json|csv` SHALL responder `422 invalid_format`.

#### Scenario: Descarga CSV
- **WHEN** el admin pide `format=csv`
- **THEN** recibe `text/csv` con una fila por recurso y las mismas cifras que el JSON

#### Scenario: Formato inválido
- **WHEN** pide `format=xml`
- **THEN** responde `422 invalid_format`

### Requirement: Consulta de auditoría de la clínica

`GET /api/audit/appointments` SHALL listar eventos de la clínica ordenados por
`(created_at, id)`, con cursor y `limit` 1–200, filtrables por
`appointment_id`, `actor_user_id`, `event`, `from` y `to`. Cada fila SHALL
incluir actor, tipo, estados antes/después, `payload` y `created_at`, y SHALL
NOT contener nombre, teléfono ni email del paciente. Solo admin.

#### Scenario: Filtro por turno
- **WHEN** el admin filtra por `appointment_id`
- **THEN** solo recibe los eventos de ese turno, en orden cronológico

#### Scenario: Paginación estable
- **WHEN** hay más eventos que `limit`
- **THEN** recibe `next_cursor` y la página siguiente no repite ni omite filas

#### Scenario: Sin PII
- **WHEN** se audita un turno de un paciente ficticio
- **THEN** ninguna fila contiene su nombre, teléfono ni email

#### Scenario: Recepción consulta la auditoría
- **WHEN** recepción llama `GET /api/audit/appointments`
- **THEN** responde `403 forbidden_role`
