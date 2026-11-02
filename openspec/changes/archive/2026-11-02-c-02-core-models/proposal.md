# Proposal — c-02-core-models (C-02 `core-models` · CHANGES.md)

> Nota de nombre: el CLI de OpenSpec exige kebab-case minúsculas; el change
> `c-02-core-models` corresponde a `C-02 core-models` de CHANGES.md
> (GATE 2, governance **CRITICO**, depende de C-01 — segundo del camino crítico
> C-01→C-02→C-03→C-04→C-05→C-07→C-08→C-10→C-14).

## Why

C-01 dejó el scaffolding y una revisión Alembic vacía (`c01_base`); ningún
change de agenda (C-03 auth, C-04 configuración, C-05 turnos) puede arrancar
sin las entidades base del tenant. C-02 fija ahora —antes de que existan
turnos— el contrato de datos más difícil de cambiar después: `clinic_id`
obligatorio con aislamiento verificable (DD-07, regla 4), identidad liviana de
paciente por teléfono E.164 (SU-03), sillón como recurso independiente (SU-04)
y usuarios del personal con hash argon2id. Es CRITICO porque toca datos
personales (Ley 26.529/27.706) y credenciales.

## What Changes

- Modelos SQLAlchemy 2.x async (`app/models/`): `Clinic` (slug único global,
  `timezone`, `booking_enabled`, `cancellation_window_hours=24`,
  `reminder_steps` jsonb), `Professional`, `Chair`, `ScheduleRule` (solo
  estructura + `CHECK start_time < end_time`; la regla anti-solape RN-AG-05
  queda en C-04), `Patient` (liviano: `full_name`, `phone_e164`/`email` con al
  menos uno, `dni` opcional no único, `whatsapp_opt_in=false`), `User`
  (enum `admin/recepcion/odontologo`, `password_hash` argon2id,
  `professional_id` obligatorio si `odontologo`).
- `clinic_id NOT NULL` + FK compuestas `(clinic_id, <fk>_id)` en toda tabla
  operativa: una fila nunca puede referenciar un recurso de otra clínica.
- **Una** migración Alembic `c02_core_models` (revises `c01_base`): extensión
  `pg_trgm`, enums nativos, tablas, constraints e índices (`slug`,
  `(clinic_id, active)`, `(clinic_id, phone_e164)`, GIN trigram en
  `full_name`). Reversible (`upgrade → downgrade → upgrade`).
- Utilidades de dominio sin endpoints: normalización de teléfono a E.164
  (región default AR), búsqueda de pacientes por teléfono normalizado dentro de
  la clínica, `hash_password`/`verify_password` argon2id.
- Schemas Pydantic de borde mínimos con `extra='forbid'` (p. ej. `ReminderStep`
  para validar `reminder_steps`).
- Seed idempotente por clínica (`python -m app.seed`): 1 clinic, 1 admin con
  credencial provisoria vía env y cambio obligatorio, 1 chair "Sillón 1",
  1 professional de ejemplo inactivo. Solo datos sintéticos (`example.com`),
  sin pacientes.
- Infra de tests contra Postgres 15 real (fixtures async, sin mocks de DB) y
  corrección del `alembic/env.py` (hoy quita `+asyncpg` pero usa engine async).

Fuera de alcance: login/refresh/RBAC/endpoints de auth (C-03), CRUD de
profesionales/sillones/horarios, anti-solape de `schedule_rule`, `block` y
políticas extra de clínica (C-04), `appointment`/`EXCLUDE`/`appointment_event`
(C-05), `notification_template`/`consent`/`reminder_job` (C-09).

## Capabilities

### New Capabilities

- `core/tenancy`: partición lógica por `clinic_id` — obligatoriedad, FK
  compuestas intra-tenant, aislamiento cross-tenant probado y migración única
  reversible del modelo core.
- `core/clinic-resources`: clínica y sus recursos de agenda (profesional,
  sillón, plantilla semanal) con sus invariantes de datos y configuración por
  clínica.
- `core/patients`: registro liviano de paciente, contacto obligatorio,
  normalización E.164 y match por teléfono, resguardos mínimos de datos
  personales.
- `core/staff-users`: usuarios del personal, rol enum, vínculo
  odontólogo↔profesional y hashing argon2id de contraseñas (sin endpoints).
- `core/seed`: alta inicial idempotente de un tenant con datos sintéticos.

### Modified Capabilities

(none — `foundation/scaffolding` no cambia de requisitos; el fix de
`alembic/env.py` restituye un requisito existente, no lo modifica.)

## Impact

- Código nuevo: `backend/app/models/{enums,clinic,professional,chair,schedule_rule,patient,user}.py`,
  `backend/app/common/phone.py`, `backend/app/core/security.py` (hashing),
  `backend/app/modules/clinic/{service,schemas}.py`, `backend/app/seed.py`,
  `backend/alembic/versions/c02_core_models.py`, tests en `backend/tests/`.
- Código modificado: `backend/alembic/env.py`, `backend/tests/conftest.py`,
  `pyproject.toml`/`requirements.txt` (+`phonenumbers`, +`argon2-cffi`,
  −`passlib` si se aprueba), `.env.example` (`SEED_*`).
- Dependencias: C-03 consume `User` + hashing; C-04 consume
  `Professional`/`Chair`/`ScheduleRule`/`Clinic`; C-05/C-07 consumen `Patient`.
- Reglas duras aplicadas: 2, 3, 4, 6, 7, 8, 9, 11 (con excepción a revisar),
  13. Decisiones abiertas para revisión humana en `design.md`.
