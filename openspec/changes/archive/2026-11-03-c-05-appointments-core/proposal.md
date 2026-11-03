# Proposal — C-05 `appointments-core`

## Why

Sin turnos no hay agenda: C-04 dejó recursos, plantilla semanal, bloqueos y
políticas, pero todavía no se puede agendar a nadie. C-05 crea el turno con la
invariante central del sistema (nunca dos turnos vigentes sobre el mismo
profesional o sillón al mismo tiempo, RN-AG-01) garantizada por PostgreSQL, su
máquina de estados y una auditoría inmutable. Es el change que destraba el MVP:
C-06, C-07, C-09 y C-13 dependen de él.

## What Changes

- **Tabla `appointment`** con `starts_at/ends_at` `timestamptz`, `occupied_until`
  (fin + buffer del profesional, RN-AG-04), `status`, `origin`, sobreturno,
  cancelación y notas operativas (nunca clínicas). Dos constraints `EXCLUDE USING
  gist` sobre `tstzrange(starts_at, occupied_until)`, uno por profesional y otro
  por sillón, entre turnos vigentes (`pending`, `confirmed`, `present`) que no
  son sobreturno. CHECKs de coherencia: rango, cancelación con motivo, sobreturno
  con motivo y **un turno online nunca es sobreturno** (RN-SB-01 en la base).
- **Máquina de estados RN-ST-01** en un solo punto del servicio: recepción nace
  `confirmed`, online nace `pending` (RN-ST-02); `present/absent/no_show` solo
  por personal y solo desde el día del turno (RN-ST-03); `absent` = no vino pero
  avisó (tarde o con justificación), `no_show` = no vino y no avisó (RN-ST-04).
  `cancelled`, `absent` y `no_show` son terminales y liberan el hueco.
- **API de turnos** (prefijo `/api`, RBAC de `03_actores_y_roles.md`):
  - `POST /api/appointments`: crear desde recepción, validando horario vigente,
    bloqueos y recursos activos. Si colisiona, responde `409 slot_taken` con los
    turnos en conflicto y hasta 3 **horarios alternativos** (regla dura 1),
    salvo sobreturno explícito con motivo (RN-SB-01/02) y dentro del tope diario
    (RN-SB-03; superarlo exige admin).
  - `PATCH /api/appointments/{id}`: reprogramación atómica (RN-AG-06): si el
    nuevo horario colisiona, el turno queda intacto.
  - `POST /api/appointments/{id}/transitions`: confirmar, presente, ausente,
    no-show y cancelar (motivo de catálogo obligatorio para el personal,
    RN-CX-04; prohibido sobre turnos `present` o ya empezados, RN-CX-05).
  - `GET /api/appointments` (rango + filtros + cursor) y `GET
    /api/appointments/{id}`; el odontólogo ve solo los suyos y sin contacto del
    paciente.
  - `GET /api/appointments/{id}/events`: historial del turno (solo admin).
- **Auditoría `appointment_event`** append-only (trigger que rechaza UPDATE y
  DELETE) escrita en la misma transacción que cada mutación (RN-GL-01), con
  actor, estado anterior/nuevo y antes/después.
- **API mínima de pacientes** para US-011 CA-1: `GET /api/patients?q=` (nombre
  por trigram o teléfono normalizado) y `POST /api/patients` (alta rápida con
  nombre + contacto). Solo admin y recepción.
- **RN-BL-02 (pendiente de C-04)**: crear o editar un bloqueo que pisa turnos
  vigentes responde `409 block_conflicts` con los turnos afectados, salvo que la
  misma request los cancele explícitamente (misma transacción).
- **Recurso inactivo** (contrato de C-04): reservar sobre un profesional o
  sillón con `active=false` responde `409 resource_inactive`.
- **Migración `c05_appointments_core`** (una sola revisión, regla 3).

## Out of scope (explícito)

- **Jobs de recordatorio** (US-011 CA-3, RN-CX-03 "cancela jobs"): `reminder_job`
  nace en C-09. Contrato: C-09 programa los jobs al crear o reprogramar y los
  cancela al cancelar, en la misma transacción que el servicio de turnos.
- **Evaluación de lista de espera al cancelar** (RN-CX-03, RN-LE-02): C-12.
- **Reserva online y disponibilidad pública** (C-07): C-05 deja el servicio
  apto para `origin=online` (nace `pending`, nunca sobreturno) y el cálculo de
  alternativos reutilizable, pero no publica endpoints.
- **`manage_token`** y gestión por token (C-08).
- **Rol de base `app_writer`** separado del owner: hoy la app se conecta como
  owner, así que un `REVOKE` no protegería nada. La inmutabilidad la garantiza el
  trigger; separar el usuario de migraciones del de la app pasa a C-14 y se
  registra en CHANGES.
- Reportes sobre eventos (C-13), UI de agenda (C-06), fusión de pacientes
  duplicados (C-06).

## Capabilities

### New Capabilities

- `agenda/appointments`: turnos con invariante anti-solapamiento en la base,
  máquina de estados, sobreturnos, reprogramación, cancelación, consulta de
  agenda y auditoría inmutable por turno.

### Modified Capabilities

- `agenda/config`: los bloqueos ya no pueden pisar turnos vigentes sin resolución
  explícita en la misma operación (RN-BL-02).
- `core/patients`: se agregan la búsqueda y el alta rápida de pacientes por el
  personal.

## Impact

- Backend: nuevo `app/modules/appointments` (router, servicio, máquina de
  estados, alternativos), `app/modules/patients` (búsqueda y alta),
  `BlocksService.create/update` suma el chequeo RN-BL-02. Schemas Pydantic v2
  con `extra='forbid'` (regla 2).
- DB: enums `appointment_status`, `appointment_origin`, `cancellation_reason`,
  `appointment_event_type`, `actor_type`; tablas `appointment` (2 EXCLUDE + CHECKs
  + índices) y `appointment_event` (+ trigger). Tablas nuevas: sin excepción a la
  regla 11.
- Concurrencia: lock de fila sobre profesional y sillón al crear, reprogramar o
  bloquear; C-07 debe usar el mismo lock.
- Tests: Postgres 15 + Redis 7 reales (regla 9), carrera concurrente real entre
  dos conexiones, aislamiento cross-tenant (regla 4), datos sintéticos (regla 13).
- Governance: **CRITICO**.
