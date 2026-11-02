# Design — c-02-core-models

## Context

Ver `proposal.md` (Why). Estado observado del código tras C-01:

- `backend/app/models/base.py`: `Base(AsyncAttrs, DeclarativeBase)` vacío;
  `app/models/__init__.py` vacío (Alembic no ve modelos todavía).
- `backend/alembic/versions/c01_base.py`: revisión `c01_base` vacía,
  `down_revision=None`. `alembic.ini` en la raíz (`script_location =
  backend/alembic`).
- `backend/alembic/env.py`: `_database_url()` hace
  `url.replace("+asyncpg", "")` y luego usa `async_engine_from_config`. Con
  `postgresql://` el engine async carga `psycopg2` (no instalado y no async):
  **el modo online no puede funcionar tal cual**. Hay que corregirlo para que
  el `upgrade` de C-02 corra de verdad (ver Decisión 9).
- `backend/tests/conftest.py`: sin fixtures de DB; `DATABASE_URL` por defecto
  sin `+asyncpg`. CI (`ci-backend.yml`) ya levanta `postgres:15.8-bookworm` y
  corre `upgrade → downgrade -1 → upgrade` + pytest + ruff/black + mypy strict.
- Dependencias: `passlib[argon2]` presente (sin uso aún); no hay
  `phonenumbers` ni `argon2-cffi`.
- `app/modules/clinic/schemas.py` solo tiene un stub `extra='forbid'`; no hay
  módulo `patients/` (C-01 fijó 9 dominios; no se agregan directorios nuevos).

Restricciones: reglas duras 2, 3, 4, 6, 7, 8, 9, 11, 13; DD-07 (una DB por
clínica, `clinic_id` igualmente obligatorio); SU-03; SU-04; RN-GL-03/04;
governance CRITICO (sin código hasta aprobar este diseño).

## Goals / Non-Goals

**Goals:**

- Que la integridad multi-tenant sea **estructural** (FK compuestas), no solo
  disciplina de servicio, y que esté probada contra Postgres real.
- Dejar `User`/hashing listos para que C-03 solo agregue tokens y endpoints.
- Dejar `Patient` con identidad por teléfono E.164 reutilizable por recepción
  (C-06) y booking público (C-07).
- Una sola revisión Alembic reversible, verificada en CI.

**Non-Goals:**

- Endpoints HTTP nuevos (ni CRUD ni auth). Solo modelos, servicios internos,
  schemas mínimos y seed.
- Anti-solape de `schedule_rule` (RN-AG-05, C-04), RLS (DD-07 la descarta en
  v1), historial de consentimiento por canal (`consent`, C-09).

## Decisions

1. **FK compuestas intra-tenant.** Cada padre referenciable (`professional`,
   `chair`) expone `UNIQUE (clinic_id, id)`; los hijos (`schedule_rule`,
   `user`) referencian `(clinic_id, professional_id)` / `(clinic_id, chair_id)`.
   Por qué: la base impide por sí misma que un `user` de A apunte a un
   profesional de B (regla 4 sin depender del servicio). Alternativa: FK simple
   + validación en servicio (descartada: el bug cross-tenant sería silencioso).
   Costo: un índice único extra por padre; aceptable.

2. **Enums nativos de Postgres** (`user_role`; el canal de recordatorio vive
   dentro del jsonb, sin tipo DB en C-02) vía `sqlalchemy.Enum(..., name=..., native_enum=True)`,
   creados/dropeados explícitamente en la migración. `reminder_steps` es
   `JSONB` con `CHECK (jsonb_typeof(reminder_steps) = 'array')`; la forma de
   cada paso (`offset_h > 0`, `channel ∈ {whatsapp, email}`) se valida con el
   schema Pydantic `ReminderStep` (`extra='forbid'`) en la escritura.
   Alternativa: tabla `reminder_step` normalizada (descartada: el KB fija jsonb
   y C-04 la edita como política completa).

3. **Constraints de datos en la DB, no solo en Pydantic.** CHECKs:
   `cancellation_window_hours >= 0`; `default_duration_min > 0`,
   `buffer_min >= 0`; `weekday BETWEEN 0 AND 6`, `start_time < end_time`,
   `slot_duration_min > 0`, `valid_to IS NULL OR valid_from <= valid_to`;
   `phone_e164 IS NOT NULL OR email IS NOT NULL`;
   `phone_e164 ~ '^\+[1-9][0-9]{7,14}$'`; `email = lower(email)` en `user`;
   `role <> 'odontologo' OR professional_id IS NOT NULL`. Todos con nombre
   explícito (`ck_<tabla>_<regla>`) vía `naming_convention` en `Base.metadata`
   para que Alembic genere/dropee nombres estables.

4. **`schedule_rule.valid_from/valid_to` como `Date`** (no `timestamptz`).
   Por qué: la vigencia es por día calendario de la clínica (RN-GL-03); un
   `timestamptz` obliga a aritmética de zona para algo que es una fecha.
   El KB dice ambas cosas (`Time/Date nativos` y `DateTime(timezone=True)`);
   se elige `Date` — ver decisión abierta 5.e.

5. **Columnas comunes**: `id uuid` (default `gen_random_uuid()` server-side,
   nativo en PG13+), `created_at timestamptz default now()` en todas,
   `updated_at` en las mutables. Sin `DELETE` en servicios: bajas por
   `active=false` (`professional`, `chair`, `user`, `schedule_rule`) y
   `archived_at` en `patient` (regla 7, RN-GL-04).

6. **Teléfono**: función pura `normalize_phone_e164(raw, region="AR") -> str`
   en `app/common/phone.py` (lib `phonenumbers`, formato E.164, rechaza
   `is_valid_number == False`) que lanza un error propio con mensaje genérico
   (sin el valor: regla 13). Búsqueda `find_patients_by_phone(session,
   clinic_id, raw)` en `app/modules/clinic/service.py`: normaliza, filtra
   `clinic_id` + `archived_at IS NULL`, lista columnas explícitas (regla 8),
   `ORDER BY created_at DESC`. Índice `(clinic_id, phone_e164)` **no único**
   (familias comparten teléfono; el KB lo define no único).

7. **Hashing**: `hash_password`/`verify_password` en `app/core/security.py`
   con `argon2-cffi` (`PasswordHasher`, tipo argon2id por defecto, parámetros
   RFC 9106 low-memory). `verify_password` devuelve `False` ante
   `VerifyMismatchError`/`InvalidHashError`, nunca propaga. Se expone
   `needs_rehash` para que C-03 rehashee en login. Ver decisión abierta 5.c.

8. **Seed como script idempotente** `python -m app.seed` (no migración de
   datos): lee `SEED_CLINIC_SLUG`, `SEED_CLINIC_NAME`, `SEED_ADMIN_EMAIL`,
   `SEED_ADMIN_PASSWORD` del entorno (falla rápida nombrando la variable),
   hace upsert por `slug` / `(clinic_id, email)` con `ON CONFLICT DO NOTHING`
   en una sola transacción y nunca imprime secretos. Por qué no migración:
   una migración con credenciales es un secreto versionado (regla 6) y el seed
   es por tenant, no por esquema.

9. **Fix de `alembic/env.py`**: conservar `+asyncpg` (normalizar
   `postgresql://` → `postgresql+asyncpg://` si viene sin driver) en modo
   online; offline sigue generando SQL. Importar `app.models` en `env.py` para
   poblar `target_metadata`. Se cubre con el test de ciclo de migración
   (task 1.2) que hoy fallaría.

10. **Infra de tests (regla 9)**: fixture de sesión que aplica `upgrade head`
    sobre la DB de `DATABASE_URL`; fixture por test con conexión +
    transacción externa y `AsyncSession(join_transaction_mode=
    "create_savepoint")` con rollback al final. El test de ciclo de migración
    usa una **DB temporal propia** (`CREATE DATABASE` / `DROP DATABASE`) para
    no destruir el esquema de los demás tests, y es síncrono (Alembic
    `command.upgrade` corre su propio `asyncio.run`). Helpers de fábrica
    sintéticos en `tests/factories.py` (nombres tipo "Paciente Ficticio Uno",
    `@example.com`, teléfonos ficticios).

11. **Ubicación del código**: modelos en `app/models/<entidad>.py` + reexport
    en `app/models/__init__.py`; servicios de clínica/pacientes en
    `app/modules/clinic/`; usuarios en `app/modules/users/` (solo modelo y
    helper de creación, sin router). No se crean directorios nuevos (spec
    `foundation/scaffolding`).

## Decisiones abiertas para revisión humana

> Governance CRITICO: ninguna se implementa sin OK explícito. Cada una trae
> recomendación; las tasks asumen la recomendación y marcan qué cambia si se
> rechaza.

1. **Regla 11 (CONCURRENTLY + NOT VALID→VALIDATE) sobre tablas nuevas.**
   Todas las tablas de C-02 se crean en la misma migración y están vacías e
   invisibles para otras transacciones hasta el commit. `CREATE INDEX
   CONCURRENTLY` no puede correr dentro de una transacción: cumplirlo literal
   exige `op.get_context().autocommit_block()`, lo que hace la migración
   **no atómica** (un fallo a mitad deja tablas sin índices y un downgrade
   parcial). `NOT VALID` sobre una tabla vacía no evita ningún escaneo.
   **Recomendación: excepción acotada y documentada** — la regla 11 aplica a
   índices/FK/CHECK sobre tablas **preexistentes con datos**; para objetos
   creados sobre tablas creadas en la misma revisión se usa DDL transaccional
   normal. Se deja comentario en la migración y una línea en `design` de C-04+
   para que el primer `ALTER` sobre tablas de C-02 (p. ej. columnas de
   política en `clinic`, C-04) sí use CONCURRENTLY/NOT VALID. Alternativa:
   cumplimiento literal con `autocommit_block` para los índices (rechazada por
   atomicidad). *Si se rechaza*: la task 2.1 separa índices en bloque
   autocommit y el test de ciclo de migración cubre el fallo parcial.

2. **Ley 26.529 / 27.706 en `patient` (v1).** El MVP no guarda datos
   clínicos, pero nombre+teléfono+turnos en un consultorio son dato sensible
   de salud en contexto. **Recomendación (mínimo que evita re-arquitecturar):**
   `privacy_consent_at timestamptz NULL`, `privacy_consent_version text NULL`
   (CHECK: versión ⇒ fecha) y `archived_at timestamptz NULL` (baja lógica,
   excluida de búsquedas; regla 7). Fuera de v1 (requiere asesor legal):
   plazo de retención y anonimización, export/portabilidad FHIR, consentimiento
   por canal con historial (`consent`, C-09). Las columnas son nullable para no
   bloquear la carga por recepción; C-07 decidirá si el booking las exige.
   *Si se rechaza*: se quita el requirement "Resguardos mínimos" de
   `specs/core/patients` y la task 5.6; `archived_at` conviene mantenerlo
   igual por regla 7.

3. **Normalización E.164.** **Recomendación: `phonenumbers`** (port de
   libphonenumber de Google; ya citado en `08` §Seguridad; maneja el `9` de
   celulares y el `15` nacional argentino, que una regex propia resuelve mal).
   Región default `AR`, tomada de una constante (no del timezone de la
   clínica) y parametrizable. Costo: dependencia de ~10 MB de metadata.
   Alternativa: regex/normalizador propio (rechazada: casos AR de prefijo
   `0`/`15`/`9` son la fuente principal de duplicados).

4. **ID de la revisión.** CHANGES.md la llama "Migración 001" (y C-03 "002",
   C-04 "003"), pero C-01 ya ocupó la primera con `c01_base`.
   **Recomendación: `revision = "c02_core_models"`, `down_revision =
   "c01_base"`**, archivo `backend/alembic/versions/c02_core_models.py`
   (convención `cNN_<slug>` ligada al change, legible en `alembic history`).
   Alternativa: hash autogenerado de Alembic (rechazada: rompe la trazabilidad
   change→migración). Proponer actualizar la numeración de CHANGES.md al
   archivar.

5. **Otras ambigüedades KB ↔ CHANGES detectadas:**
   - a. **`schedule_rule` en C-02 vs. C-04.** C-02 la lista en modelos, pero
     C-04 dice "Migración 003: `schedule_rule`, `block`…". **Recomendación:**
     crear la tabla en C-02 (está en el scope y en "Leer antes") con sus CHECKs
     estructurales; C-04 agrega el anti-solape RN-AG-05 y `block`. Corregir el
     texto de C-04 en CHANGES.md al archivar.
   - b. **Seed de `notification_template` y "catálogo de motivos de bloqueo".**
     El seed de C-02 los pide, pero `notification_template` nace en C-09
     (migración 005) y `block.reason` es un enum de `block` (C-04).
     **Recomendación:** excluirlos del seed de C-02; C-04 agrega el enum de
     motivos y C-09 siembra las 3 plantillas placeholder extendiendo el mismo
     `app.seed`. Crear tablas vacías ahora sería scope de otros changes.
   - c. **`passlib[argon2]` vs `argon2-cffi`.** `passlib` está sin
     mantenimiento desde 2020 y depende del módulo `crypt` removido en
     Python 3.13. **Recomendación:** `argon2-cffi` directo y quitar `passlib`
     de `pyproject.toml`/`requirements.txt` (no hay usos).
   - d. **Índice trigram "`(clinic_id, full_name)`".** Un GIN compuesto con
     `clinic_id` requiere `btree_gin`. Con una DB por clínica (DD-07) el
     prefijo `clinic_id` no filtra nada. **Recomendación:** `GIN (full_name
     gin_trgm_ops)` solo, con `clinic_id` como predicado adicional; revisar
     al pasar a multi-tenant real.
   - e. **Tipo de `valid_from/valid_to`**: `Date` (Decisión 4) vs
     `DateTime(timezone=True)` del KB. Recomendación `Date`.
   - f. **`booking_enabled` sin default en el KB.** Recomendación `false` en
     clínica y `true` en profesional (la clínica habilita la reserva pública
     explícitamente cuando terminó de configurar horarios).
   - g. **Credencial del admin del seed.** El KB pide "credenciales
     provisorias con cambio obligatorio". Recomendación: `SEED_ADMIN_PASSWORD`
     obligatoria por env (sin default; `.env.example` con placeholder
     evidente) + columna `user.must_change_password` (C-03 la hace cumplir).
     Alternativa: generar aleatoria e imprimirla (rechazada: secreto en logs).
   - h. **Email de usuario**: "único por clínica" sin regla de mayúsculas.
     Recomendación: normalizar a minúsculas en el borde + `CHECK (email =
     lower(email))` + `UNIQUE (clinic_id, email)`; evita índice funcional y
     `citext`.
   - i. **`pg_trgm` en downgrade.** Recomendación: `CREATE EXTENSION IF NOT
     EXISTS pg_trgm` en upgrade y **no** dropearla en downgrade (puede usarla
     otro objeto; es inocua). El test de "sin residuos" se limita a tablas y
     tipos del change.

## Risks / Trade-offs

- [Riesgo] `CREATE EXTENSION pg_trgm` requiere privilegio → Mitigación:
  `pg_trgm` es *trusted* desde PG13 (basta ser owner de la DB); documentar en
  README de despliegue; CI usa superusuario del servicio.
- [Riesgo] Test de ciclo con `CREATE DATABASE` requiere permiso `CREATEDB` →
  Mitigación: el usuario de CI/compose dev es owner; si no, el test se salta
  con motivo explícito y el paso de CI `upgrade/downgrade/upgrade` sigue
  cubriendo el ciclo.
- [Riesgo] FK compuestas complican el ORM (`relationship` con
  `foreign_keys`/`primaryjoin`) → Mitigación: declarar
  `ForeignKeyConstraint` en `__table_args__` y relaciones solo donde se usan;
  mypy strict las cubre.
- [Riesgo] `phonenumbers` acepta números "posibles" pero no asignados →
  Mitigación: usar `is_valid_number`; aceptar que un número válido pero
  inexistente pase (no hay forma offline de saberlo).
- [Riesgo] Hash argon2id lento en tests → Mitigación: parámetros de test
  reducidos vía fixture, no vía código de producción.
- [Trade-off] Excepción a la regla 11 (si se aprueba) → aceptada solo para
  objetos de tablas creadas en la misma revisión; queda escrita.
- [Trade-off] Teléfono no único → el match devuelve N pacientes; la UI de
  C-06/C-07 decide. Aceptado (SU-03, familias).

## Migration Plan

1. `alembic upgrade head` aplica `c02_core_models` sobre `c01_base`
   (extensión, enums, tablas, constraints, índices) en una transacción.
2. `python -m app.seed` con `SEED_*` del entorno crea el tenant inicial.
3. Rollback: `alembic downgrade c01_base` dropea tablas y enums en orden
   inverso de dependencias (deja `pg_trgm`). No hay datos previos que migrar.
4. CI: `upgrade → downgrade -1 → upgrade` + pytest contra Postgres 15.

## Open Questions

- Parámetros exactos de argon2id para producción (memoria/tiempo) según el
  tamaño de instancia del deploy — se ajustan en C-14 sin cambiar specs.
- Lista definitiva de regiones aceptadas para teléfonos extranjeros
  (pacientes de países limítrofes): hoy se acepta cualquier E.164 válido.

## Resolución de decisiones abiertas

**2026-11-02 — APROBADAS** (el usuario delegó la decisión): se adoptan TODAS las
recomendaciones de "Decisiones abiertas para revisión humana" 1–5:
excepción acotada a la regla 11 para objetos de tablas creadas en la misma
revisión (1); consentimiento mínimo + `archived_at` en `patient`, task 5.6
incluida (2); `phonenumbers` con región default AR (3); revisión
`c02_core_models` sobre `c01_base` (4); y 5.a–5.i (`schedule_rule` en C-02,
sin seed de plantillas/motivos, `argon2-cffi` en lugar de `passlib`, GIN
trigram solo sobre `full_name`, `Date` para vigencias, `booking_enabled`
false en clínica / true en profesional, `SEED_ADMIN_PASSWORD` obligatoria por
env + `must_change_password`, email en minúsculas con CHECK, `pg_trgm` no se
dropea en downgrade).
