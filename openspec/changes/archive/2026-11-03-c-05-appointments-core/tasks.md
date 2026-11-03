# Tasks — C-05 `appointments-core`

> TDD rojo → verde en cada tarea: primero el test que falla (y se corre para
> verlo fallar), luego el mínimo código. Todo test de invariantes corre contra
> Postgres 15 + Redis 7 reales (regla 9). Datos solo sintéticos (regla 13).

## 1. Migración `c05_appointments_core`

- [x] 1.1 Test de base: los EXCLUDE de `appointment` rechazan solape por
  profesional y por sillón entre vigentes no sobreturno; aceptan contiguos,
  `cancelled/absent/no_show` y sobreturnos; el buffer (`occupied_until`) integra
  el rango. Verifica: `tests/models/test_appointment_db.py` en rojo y luego verde.
- [x] 1.2 Test de base: CHECKs (`ends_at > starts_at`, `occupied_until >=
  ends_at`, sobreturno ⇒ motivo, online ⇒ no sobreturno, cancelado ⇔
  `cancelled_at` + motivo, actor `user` ⇒ `actor_user_id`) y FKs compuestas
  intra-tenant. Verifica: mismo archivo, verde.
- [x] 1.3 Test de base: `appointment_event` rechaza UPDATE y DELETE. Verifica:
  `tests/models/test_appointment_event_db.py` verde.
- [x] 1.4 Test de carrera directa: dos conexiones insertan el mismo hueco sin
  pasar por el servicio; una falla con SQLSTATE `23P01`. Verifica: test verde.
- [x] 1.5 Implementar la revisión (D1, D2, D7) con encabezado de regla 3/11 y
  downgrade inverso. Verifica: `alembic upgrade head → downgrade -1 → upgrade
  head` limpio y test de drift modelo↔migración verde.

## 2. Modelos SQLAlchemy

- [x] 2.1 Enums `AppointmentStatus`, `AppointmentOrigin`, `CancellationReason`,
  `AppointmentEventType`, `ActorType`; modelos `Appointment` (con
  `ExcludeConstraint` en `__table_args__`) y `AppointmentEvent`. Verifica: tests
  de 1.x y de drift verdes.

## 3. Pacientes (US-011 CA-1)

- [x] 3.1 `GET /api/patients?q=`: teléfono → match normalizado; texto →
  similitud trigram; máximo 20; `422 query_too_short`; odontólogo `403`.
  Verifica: `tests/modules/test_patients_api.py` verde.
- [x] 3.2 `POST /api/patients`: alta rápida, E.164, `409 patient_duplicate`
  (mismo teléfono + nombre normalizado), familia aceptada, errores sin PII (se
  asserta sobre la respuesta y `caplog`). Verifica: mismo archivo verde.

## 4. Núcleo de alta de turno

- [x] 4.1 Función pura `suggest_slots` (D8): grilla por regla en zona local,
  excluye pasado, bloqueos y ocupados con buffer, devuelve los primeros 3 en 14
  días. Verifica: `tests/modules/test_availability.py` (unit, sin DB) verde,
  incluido un caso con cambio de horario de la zona simulada.
- [x] 4.2 `POST /api/appointments` de recepción: validaciones de D5 (recurso
  inactivo `409`, `outside_schedule`, `slot_blocked`, `appointment_in_past`,
  datetime sin zona `422`), duración default de la regla, nace `confirmed`, evento
  `created`; lock de D4. Verifica: `tests/modules/test_appointments_create_api.py`
  verde.
- [x] 4.3 Colisión → `409 slot_taken` con `conflicts` + `alternatives` sin PII,
  traduciendo `23P01`. Verifica: mismo archivo verde.
- [x] 4.4 Alta con `origin=online` vía servicio: nace `pending`, nunca
  sobreturno. Verifica: test de servicio verde.
- [x] 4.5 Carrera concurrente recepción vs. online por el mismo hueco (dos
  sesiones con `asyncio.gather`): exactamente un 201 y un `409`. Verifica:
  `tests/modules/test_appointments_concurrency.py` verde 20 corridas seguidas.

## 5. Sobreturnos (RN-SB-01..03)

- [x] 5.1 Sobreturno sin motivo `422`; innecesario `422 overbooking_not_needed`;
  válido `201` con evento `overbooking_created` que lista colisiones; turno
  normal sobre sobreturno vigente `409`. Verifica:
  `tests/modules/test_appointments_overbooking_api.py` verde.
- [x] 5.2 Tope diario por profesional en día local: recepción `409
  overbooking_limit`; admin pasa con `over_limit=true` en el evento. Verifica:
  mismo archivo verde.

## 6. Estados, asistencia y cancelación (RN-ST, RN-CX)

- [x] 6.1 Tabla de transiciones (D6) con test exhaustivo de pares permitidos y
  prohibidos (`409 invalid_transition`). Verifica:
  `tests/modules/test_appointment_states.py` verde.
- [x] 6.2 `POST /api/appointments/{id}/transitions`: confirmar; presente desde el
  día local; `absent/no_show` desde `starts_at` (`409 attendance_too_early`);
  odontólogo solo los suyos (`404` ajeno, `403` al confirmar o cancelar).
  Verifica: `tests/modules/test_appointments_transitions_api.py` verde.
- [x] 6.3 Cancelar: motivo de catálogo obligatorio, nota ≤ 500, `409
  appointment_started`, `late` según `cancellation_window_hours`, hueco liberado.
  Verifica: mismo archivo verde.

## 7. Reprogramación (RN-AG-06, RN-CX-02)

- [x] 7.1 `PATCH /api/appointments/{id}`: mueve horario, sillón o profesional
  revalidando D5 + colisión; conserva id; evento `rescheduled` con
  antes/después; no colisiona consigo mismo; recalcula `occupied_until` con el
  buffer del profesional destino. Verifica:
  `tests/modules/test_appointments_reschedule_api.py` verde.
- [x] 7.2 Reprogramación que colisiona deja el turno intacto (se relee de la base
  tras el `409`); edición de `notes` emite `updated`; `DELETE` responde `405`.
  Verifica: mismo archivo verde.

## 8. Consulta y auditoría

- [x] 8.1 `GET /api/appointments` (rango ≤ 31 días, filtros, cursor, `limit` ≤
  500) y `GET /api/appointments/{id}`; odontólogo solo los suyos y sin contacto.
  Verifica: `tests/modules/test_appointments_list_api.py` verde.
- [x] 8.2 `GET /api/appointments/{id}/events` solo admin; orden cronológico;
  payload sin PII. Falla de auditoría inyectada revierte la mutación. Verifica:
  `tests/modules/test_appointment_audit.py` verde.

## 9. Bloqueos sobre turnos (RN-BL-02)

- [x] 9.1 `BlocksService.create/update` con lock (D4): `409 block_conflicts`;
  `cancel_appointments` que cubre exactamente los afectados cancela y bloquea en
  una transacción; incompleto `409`; sobrante `422`; odontólogo `403`; turnos
  terminados no cuentan. Verifica: tests nuevos en
  `tests/modules/test_agenda_blocks_api.py` verdes y los 28 existentes siguen
  verdes.

## 10. Transversal

- [x] 10.1 Aislamiento cross-tenant: un principal de la clínica B no lee, crea,
  modifica, transiciona ni ve eventos de turnos ni pacientes de A (`404`/`422`,
  nunca datos). Verifica: `tests/modules/test_appointments_tenancy.py` verde.
- [x] 10.2 Bordes con `extra='forbid'`: `clinic_id`, `status`, `origin` o campos
  desconocidos en los bodies → `422`. Verifica: tests de schema verdes.

## 11. Cierre

- [x] 11.1 Gate: `alembic upgrade/downgrade -1/upgrade`, `pytest -q` (Postgres 15
  + Redis 7), `ruff check backend`, `black --check backend`, `mypy backend`,
  `openspec validate c-05-appointments-core --strict`. Verifica: todo verde,
  con evidencia en una tabla al final de este archivo.
- [x] 11.2 `backend/README.md`: endpoints de turnos y pacientes, códigos de
  error, lock por recurso, semántica `absent` vs. `no_show`, advertencia de
  downgrade. Verifica: sección presente.
- [x] 11.3 `CHANGES.md`: notas de cierre de C-05 y contratos diferidos (jobs →
  C-09, lista de espera al cancelar → C-12, lock compartido → C-07, rol
  `app_writer` → C-14). Verifica: diff de CHANGES.md.

## Workflow follow-up

- `/opsx:archive c-05-appointments-core` y marcar `[x]` en CHANGES.md.

## Evidencia del apply (2026-11-03)

Entorno equivalente a CI: imagen `api` (`python:3.12.7`) con el repo montado,
contra `postgres:15.8-bookworm` + `redis:7.4-bookworm` en una red Docker propia.

| Tarea | Rojo | Verde |
|---|---|---|
| 1 Migración | `test_appointment_db.py`, `test_appointment_event_db.py`, `test_appointment_race_db.py` no colectan (faltan modelos) | `c05_appointments_core`; 162 tests de modelos + migraciones, drift modelo↔migración vacío, carrera directa falla con `23P01` |
| 1 Regresión | `test_patient_indexes` (C-02): el nuevo UNIQUE de `patient` compite con el GIN trigram | UNIQUE en orden `(id, clinic_id)` y el test lo retira dentro de su transacción (mismo criterio que con el btree) |
| 3 Pacientes | `test_patients_api.py`: 23 fallan (rutas inexistentes) | 23 passed |
| 4.1 Alternativos | test escrito antes del módulo (rojo no corrido aparte) | 10 passed, incluye salto de horario en Europe/Madrid |
| 4.2/4.3 Alta | `test_appointments_create_api.py` escrito antes del servicio (rojo no corrido aparte); primera corrida: 1 fallo del propio test | 40 passed |
| 4.4/4.5 Online y carrera | servicio ya implementado en 4.2: verdes a la primera | 4 passed; la carrera recepción vs. online corre 20 rondas seguidas en un test (1 éxito + 1 `409 slot_taken` por ronda) |
| 5–8, 10 | servicio ya implementado: verdes a la primera (72 + 35) | prueba de mutación: quitar el filtro de alcance del odontólogo y el `exclude_id` de la reprogramación rompe 4 tests; restaurado |
| 9 Bloqueos | 8 de 9 tests nuevos fallan; los 28 previos siguen verdes | 37 passed |

Gate 11.1: `alembic upgrade head → downgrade -1 → upgrade head` OK; `pytest -q`
**640 passed + 1 fallo de entorno** (`test_auth_redis_url_usa_la_base_logica_configurada`
asserta `localhost:6379` y en esta red Redis se llama `c05-redis`; corrido aparte
compartiendo la red del contenedor Redis: verde). `ruff check backend`,
`black --check backend` y `mypy backend` (166 archivos) limpios;
`openspec validate c-05-appointments-core --strict` válido.
