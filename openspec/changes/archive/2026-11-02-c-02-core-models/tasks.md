# Tasks — c-02-core-models

> Governance **CRITICO** + TDD estricto: cada task de comportamiento sigue
> RED (test que falla, ejecutado y visto rojo) → GREEN (mínimo código) →
> TRIANGULATE (≥ 2 casos) → REFACTOR (tests verdes tras cada paso). Todos los
> tests de DB corren contra **Postgres 15 real** (compose `db` o servicio CI),
> nunca mocks (regla 9). Datos de prueba solo sintéticos, `@example.com`,
> teléfonos ficticios (regla 13). Sin commits ni builds sin pedido explícito.
> Todo DDL vive en la única revisión `c02_core_models` (revises `c01_base`).

## 0. Gate de aprobación humana

- [x] 0.1 Obtener OK explícito del humano sobre las "Decisiones abiertas para
  revisión humana" 1–5 de `design.md` y registrar la resolución (aprobada /
  alternativa elegida) al pie de `design.md` + engram; verificar que ninguna
  task siguiente se inicia sin esa nota. Si la decisión 2 se rechaza, quitar
  5.6 y el requirement "Resguardos mínimos" de `specs/core/patients`; si la 1
  se rechaza, 2.1 usa `autocommit_block` para índices.
  Nota 2026-11-02: el usuario delegó la decisión y se aprobaron TODAS las
  recomendaciones de las decisiones abiertas 1–5 (ver pie de `design.md`).

## 1. Dependencias e infraestructura de tests

- [x] 1.1 Agregar `phonenumbers` y `argon2-cffi` (versiones acotadas) y quitar
  `passlib[argon2]` en `pyproject.toml` y `requirements.txt`; verificar con
  install limpio en venv + `python -c "import phonenumbers, argon2"` y
  `grep -r passlib backend/` vacío.
- [x] 1.2 RED: escribir `backend/tests/test_migrations.py::test_ciclo_upgrade_downgrade_upgrade`
  (síncrono, crea DB temporal con `CREATE DATABASE`, corre
  `alembic.command.upgrade/downgrade/upgrade` vía `Config("alembic.ini")` y la
  dropea; skip con motivo si falta `CREATEDB`) y verlo fallar por el engine
  async con URL sin `+asyncpg`. GREEN: corregir `backend/alembic/env.py`
  (conservar/forzar `postgresql+asyncpg://`, importar `app.models`); verificar
  test verde con solo `c01_base`.
- [x] 1.3 Agregar fixtures en `backend/tests/conftest.py` (`DATABASE_URL`
  default con `+asyncpg`; fixture de sesión `upgrade head`; fixture
  `db_session` con transacción externa + `join_transaction_mode=
  "create_savepoint"` y rollback) y `backend/tests/factories.py` con fábricas
  sintéticas; verificar con dos tests que insertan y comprueban que lo
  insertado en uno no es visible en el otro (rollback real) + suite previa
  (`test_health`, `test_edges`, `test_env_example`) sigue verde.

## 2. Clinic + revisión `c02_core_models` (tracer bullet)

- [x] 2.1 RED: `tests/models/test_clinic.py` — slug duplicado → `IntegrityError`
  de unicidad; clínica con solo `name`+`slug` persiste con timezone
  `America/Argentina/Buenos_Aires`, `cancellation_window_hours=24`,
  `booking_enabled=false` y pasos 72/24/3 h whatsapp. GREEN: `naming_convention`
  en `Base.metadata`, `app/models/clinic.py`, reexport en `app/models/__init__.py`
  y crear `backend/alembic/versions/c02_core_models.py` (`CREATE EXTENSION IF
  NOT EXISTS pg_trgm`, tabla `clinic`, `UNIQUE(slug)`, comentario de la
  excepción a regla 11 según decisión 1); verificar tests verdes + 1.2 verde.
- [x] 2.2 TRIANGULATE: slugs distintos conviven; `cancellation_window_hours=-1`
  → violación `ck_clinic_cancellation_window_nonneg`; `reminder_steps` no-array
  → violación `ck_clinic_reminder_steps_array`; verificar tests verdes.
- [x] 2.3 RED→GREEN: `tests/modules/test_clinic_schemas.py` para `ReminderStep`
  (`extra='forbid'`): canal `sms`, `offset_h=0`/negativo y campo extra →
  `ValidationError`; `{offset_h: 24, channel: "whatsapp"}` válido. Implementar
  en `app/modules/clinic/schemas.py` (reemplaza `ClinicStub` si no tiene usos;
  si los tiene, conservarlo); verificar tests verdes + `test_edges` verde.

## 3. Professional y Chair (tenant + FK compuestas)

- [x] 3.1 RED: `tests/models/test_professional_chair.py` — `clinic_id` nulo →
  NOT NULL; `clinic_id` inexistente → FK; `default_duration_min=0` y
  `buffer_min=-1` → CHECK. GREEN: modelos `professional`/`chair` con
  `UNIQUE (clinic_id, id)`, índices `(clinic_id, active)` y tablas en
  `c02_core_models`; verificar tests verdes + 1.2 verde.
- [x] 3.2 RED→GREEN: `list_active_professionals`/`list_active_chairs(session,
  clinic_id)` en `app/modules/clinic/service.py` (columnas explícitas, sin
  `SELECT *`): excluyen inactivos que siguen existiendo; **test cross-tenant**
  con clínicas A y B devuelve solo filas de A para ambas tablas; verificar
  tests verdes.

## 4. ScheduleRule

- [x] 4.1 RED: `tests/models/test_schedule_rule.py` — 18:00–09:00 → CHECK;
  `weekday=7` → CHECK; `slot_duration_min=0` → CHECK; `valid_to < valid_from`
  → CHECK; `chair_id` de otra clínica → violación de FK compuesta; regla lunes
  09:00–13:00/30 min sin `valid_to` persiste. GREEN: modelo con `Time`/`Date`,
  FK compuestas `(clinic_id, professional_id)`/`(clinic_id, chair_id)`, índice
  `(professional_id, chair_id, weekday)`; verificar tests verdes + 1.2 verde.
- [x] 4.2 **Test cross-tenant** `list_schedule_rules(session, clinic_id,
  professional_id)` solo devuelve reglas de la clínica pedida; verificar verde.
  (Anti-solape RN-AG-05 NO entra: C-04.)

## 5. Patient + teléfono E.164

- [x] 5.1 RED: `tests/common/test_phone.py` — celular ficticio AMBA en formato
  nacional con `15`, internacional con espacios/guiones y E.164 normalizan al
  mismo `+549…`; fijo ficticio normaliza a `+54…`; `12ab` y número corto →
  error propio cuyo `str()` no contiene el valor. GREEN:
  `app/common/phone.py::normalize_phone_e164(raw, region="AR")` con
  `phonenumbers`; verificar tests verdes.
- [x] 5.2 RED: `tests/models/test_patient.py` — sin teléfono ni email → CHECK
  `ck_patient_contact_required`; solo email `@example.com` persiste con
  `whatsapp_opt_in=false`; dos pacientes mismo DNI ficticio persisten;
  `phone_e164` con espacios o sin `+` → CHECK de formato. GREEN: modelo +
  tabla con índice `(clinic_id, phone_e164)` no único y `GIN (full_name
  gin_trgm_ops)`; verificar tests verdes + 1.2 verde.
- [x] 5.3 RED→GREEN: `find_patients_by_phone(session, clinic_id, raw)` en
  `app/modules/clinic/service.py` — match con formato distinto al guardado;
  teléfono compartido devuelve ambos, más reciente primero; teléfono sin
  pacientes → `[]`; **test cross-tenant**: mismo teléfono en A y B solo
  devuelve A; verificar tests verdes.
- [x] 5.4 Verificar que el índice trigram se usa: test que con
  `SET enable_seqscan = off` hace `EXPLAIN` de `full_name ILIKE '%ficti%'`
  filtrado por `clinic_id` y encuentra el índice GIN; verificar verde.
- [x] 5.5 Verificar sin PII en errores: test que fuerza la violación de
  contacto y de formato de teléfono y comprueba que el mensaje de error de
  dominio expuesto no contiene nombre, teléfono ni email; verificar verde.
- [x] 5.6 (Condicional a decisión 2) RED→GREEN: columnas
  `privacy_consent_at`, `privacy_consent_version`, `archived_at`;
  versión sin fecha → CHECK `ck_patient_consent_coherent`; paciente archivado
  excluido de `find_patients_by_phone` pero la fila persiste; verificar verde.

## 6. User + hashing argon2id (sin endpoints)

- [x] 6.1 RED: `tests/core/test_password_hashing.py` — hash empieza con
  `$argon2id$` y no contiene la contraseña; verifica con la correcta; falsa con
  otra contraseña y con hash malformado (sin excepción); dos hashes de la misma
  contraseña difieren y ambos verifican. GREEN: `hash_password`,
  `verify_password`, `needs_rehash` en `app/core/security.py` con
  `argon2-cffi`; fixture de parámetros reducidos solo en tests; verificar verde.
- [x] 6.2 RED: `tests/models/test_user.py` — rol `superadmin` rechazado;
  `admin`/`recepcion` sin profesional persisten; `odontologo` sin
  `professional_id` → CHECK; `odontologo` con profesional propio persiste;
  `odontologo` con profesional de otra clínica → FK compuesta; email duplicado
  en la misma clínica → unicidad; mismo email en otra clínica persiste;
  `Admin@Example.com` → CHECK minúsculas; `must_change_password` y `active`
  por defecto según spec. GREEN: enum nativo `user_role`, modelo
  `app/models/user.py`, tabla en `c02_core_models`; verificar verde + 1.2 verde.
- [x] 6.3 RED→GREEN: helper `create_staff_user(session, clinic_id, email,
  password, role, professional_id=None, must_change_password=True)` en
  `app/modules/users/service.py` (normaliza email a minúsculas, hashea, nunca
  loguea la contraseña) + **test cross-tenant** `get_user_by_email(session,
  clinic_id, email)` no devuelve usuarios de otra clínica; verificar verde con
  `caplog` sin la contraseña.

## 7. Seed idempotente

- [x] 7.1 RED: `tests/test_seed.py` — sobre DB migrada: 1 clinic, 1 admin
  `must_change_password=true`, 1 chair "Sillón 1" activo, 1 professional
  inactivo con nombre ficticio, 0 patients; doble ejecución deja mismas
  cantidades y mismo hash; sin `SEED_ADMIN_PASSWORD` aborta nombrando la
  variable y sin filas; `capsys`/`caplog` no contienen contraseña ni hash.
  GREEN: `backend/app/seed.py` (`python -m app.seed`, `ON CONFLICT DO NOTHING`,
  una transacción); verificar tests verdes.
- [x] 7.2 Agregar `SEED_CLINIC_SLUG`, `SEED_CLINIC_NAME`, `SEED_ADMIN_EMAIL`
  (`admin@example.com`) y `SEED_ADMIN_PASSWORD` (placeholder evidente, no
  secreto) a `.env.example` y documentar el uso del seed en el README de
  backend; verificar `test_env_example` verde y que el seed con esos valores
  crea un admin `@example.com`.

## 8. Cierre de la migración

- [x] 8.1 Extender `test_migrations.py`: tras `upgrade head` existen las tablas
  e índices del change (`slug` único, `(clinic_id, active)` ×2,
  `(clinic_id, phone_e164)`, GIN trigram, `(professional_id, chair_id,
  weekday)`) y `downgrade c01_base` no deja tablas ni enums del change
  (`pg_trgm` puede quedar); verificar verde + `alembic upgrade head &&
  alembic downgrade -1 && alembic upgrade head` limpio a mano contra compose.
- [x] 8.2 REFACTOR final: revisar duplicación en modelos/fábricas, nombres de
  constraints estables y ausencia de `SELECT *`; verificar suite completa verde
  tras cada paso.

## 9. Verificación integral

- [x] 9.1 Ejecutar los gates del change (`pytest -q` completo contra Postgres
  15, `ruff check backend`, `black --check backend`, `mypy backend` strict) y
  `openspec validate c-02-core-models --strict`; registrar evidencia (salidas
  resumidas) y la tabla "TDD Cycle Evidence" en el resumen del apply.

## Workflow follow-up

- Al archivar: ajustar en `CHANGES.md` la numeración de migraciones
  (`c02_core_models` en vez de "001") y los textos de C-04 (ya no crea
  `schedule_rule`) y C-09 (siembra `notification_template`).
- Registrar en el design de C-04 que el primer `ALTER` sobre tablas de C-02
  debe cumplir la regla 11 literal (CONCURRENTLY / NOT VALID → VALIDATE).
- `/opsx:archive c-02-core-models` tras revisión humana (governance CRITICO).
