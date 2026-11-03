# Tasks — C-04 `agenda-config`

> TDD rojo → verde en cada tarea: primero el test que falla, luego el mínimo
> código. Todo test de invariantes corre contra Postgres 15 + Redis 7 reales.

## 1. Migración `c04_agenda_config`

- [x] 1.1 Test de migración: `schedule_rule` rechaza solape de franja+vigencia
  para el mismo (clínica, profesional, sillón, día) entre reglas activas; acepta
  franjas contiguas, otro día, otro sillón, vigencias disjuntas y reglas
  inactivas.
- [x] 1.2 Test: `clinic` tiene `max_overbookings_per_day=2` y
  `waitlist_offer_ttl_hours=4` por defecto y rechaza negativos / TTL 0.
- [x] 1.3 Test: `block` exige profesional o sillón, `ends_at > starts_at`, motivo
  del catálogo y FKs intra-tenant.
- [x] 1.4 Test: `agenda_config_event` rechaza UPDATE y DELETE.
- [x] 1.5 Implementar la revisión (D1–D5) con encabezado que documente la
  excepción a la regla 11; `upgrade → downgrade -1 → upgrade` limpio.

## 2. Modelos SQLAlchemy

- [x] 2.1 `ScheduleRule.__table_args__` declara el EXCLUDE (paridad modelo↔migración).
- [x] 2.2 `Clinic`: columnas de política nuevas.
- [x] 2.3 Modelos `Block`, `AgendaConfigEvent` y enums `BlockReason`,
  `ConfigEntity`, `ConfigAction`.

## 3. Profesionales y sillones (US-001)

- [x] 3.1 API: alta, edición, baja/reactivación lógica; listado por cursor con
  filtro `active`; color `#RRGGBB`.
- [x] 3.2 RBAC: recepción solo lectura (`403` en escritura); odontólogo ve solo
  su profesional y `404` para otros; sillones legibles por todo el personal.
- [x] 3.3 Auditoría de cada mutación (created/updated/deactivated/reactivated).

## 4. Plantilla semanal (US-002)

- [x] 4.1 API: alta/edición/desactivación; solape → `409 schedule_overlap` con ids
  en conflicto; recurso inactivo o de otra clínica → `422`.
- [x] 4.2 RBAC: admin escribe; recepción lee todo; odontólogo lee las propias.
- [x] 4.3 Auditoría de cada mutación.

## 5. Bloqueos (US-003)

- [x] 5.1 API: alta con profesional y/o sillón + motivo (RN-BL-01); listado por
  rango con cursor; edición/retiro lógico de futuros; inmutabilidad de pasados y
  regla de bloqueo en curso (RN-BL-03).
- [x] 5.2 `POST /api/blocks/closure`: un bloqueo por sillón activo, atómico, solo
  admin (RN-BL-04).
- [x] 5.3 RBAC: recepción CR; odontólogo CR solo con su `professional_id`; edición
  y retiro solo admin.
- [x] 5.4 Auditoría de cada mutación.

## 6. Políticas de clínica (US-004)

- [x] 6.1 `GET/PATCH /api/clinic/policies` con defaults sanos, validación de
  `reminder_steps` (1..5, offsets únicos) y auditoría anterior/nuevo.
- [x] 6.2 RBAC: admin RU; recepción R; odontólogo `403`.

## 7. Transversal

- [x] 7.1 Aislamiento cross-tenant: un principal de la clínica B no lee ni
  modifica recursos, reglas, bloqueos ni políticas de A (404/422, nunca datos).
- [x] 7.2 Bordes con `extra='forbid'`: `clinic_id` u otros campos extra → `422`.
- [x] 7.3 Mover `encode/decode_cursor` a `app/common/pagination.py` sin romper
  `/api/users`.

## 8. Cierre

- [x] 8.1 Gate: `alembic upgrade/downgrade -1/upgrade`, `pytest -q` (Postgres 15
  + Redis 7), `ruff check backend`, `black --check backend`, `mypy backend`,
  `openspec validate c-04-agenda-config --strict`.
- [x] 8.2 `backend/README.md`: endpoints, excepción regla 11, advertencia de
  downgrade, feriados vs. sillones nuevos.
- [x] 8.3 CHANGES.md: registrar RN-BL-02 → C-05, rechazo de reserva por recurso
  inactivo → C-05/C-07, snapshot de pasos → C-09.

## Evidencia del apply (2026-11-03)

Entorno equivalente a CI: contenedor `python:3.12.7` (imagen `api`) con
`postgres:15.8-bookworm` + `redis:7.4-bookworm` en `localhost`, sin `.env`.

| Tarea | Rojo | Verde |
|---|---|---|
| 1 Migración | `tests/models/test_agenda_config_db.py` y `test_migrations.py` fallan (faltan modelos/objetos) | `c04_agenda_config`; 121 tests de modelos+migraciones, sin drift modelo↔migración |
| 3 Recursos | `test_agenda_resources_api.py`: 18/19 fallan (rutas inexistentes) | 19 passed; `/api/users` intacto tras mover el cursor (7.3) |
| 4 Plantilla | `test_agenda_schedules_api.py` escrito antes del código (rojo no corrido aparte); la primera corrida dio 2 fallos reales (orden de auditoría en una misma transacción, flush fuera del savepoint) | `clock_timestamp()` en la auditoría + cambios dentro del savepoint; 17 passed |
| 5 Bloqueos | `test_agenda_blocks_api.py` escrito antes del código (rojo no corrido aparte) | 28 passed |
| 6 Políticas | `test_clinic_policies_api.py`: 16 fallan | 16 passed |
| Regresión | 10 tests de C-03 creaban dos reglas idénticas (ahora prohibido por el EXCLUDE) | días distintos, misma intención |

Gate 8.1: `alembic upgrade head → downgrade -1 → upgrade head` OK; `pytest -q`
**407 passed**; `ruff check`, `black --check`, `mypy` (136 archivos) limpios;
`openspec validate c-04-agenda-config --strict` válido. Humo sobre el stack de
Docker: migración aplicada, endpoints publicados en OpenAPI, `401` sin token.
