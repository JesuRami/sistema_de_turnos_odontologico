# Backend — Sistema de Turnos Odontológico

FastAPI + SQLAlchemy 2.x async + Alembic sobre PostgreSQL 15. Los comandos se
corren desde la raíz del repo salvo que se indique otra cosa.

## Base de datos y migraciones

```bash
# DATABASE_URL acepta postgresql:// o postgresql+asyncpg:// (se fuerza asyncpg)
alembic upgrade head      # c01_base -> c02_core_models -> c03_auth_rbac
alembic downgrade c02_core_models
```

- `pg_trgm` se crea con `CREATE EXTENSION IF NOT EXISTS`. Es una extensión
  *trusted* desde PostgreSQL 13: alcanza con ser owner de la base (no hace falta
  superusuario). El downgrade no la elimina.
- Todas las tablas operativas llevan `clinic_id NOT NULL`; las referencias entre
  tablas son claves foráneas compuestas `(clinic_id, id)`.

### Revisión `c03_auth_rbac` (C-03)

Agrega `user.password_changed_at`, la tabla append-only `auth_event`, el enum
`auth_event_type`, los índices `(clinic_id, created_at)` / `(user_id, created_at)`
y el trigger `trg_auth_event_no_mutate` (BEFORE UPDATE/DELETE). Es una única
revisión versionada (`down_revision="c02_core_models"`); no hay cambios de
schema fuera de Alembic (regla 3). El DDL nuevo se crea completo en la misma
revisión porque son objetos nuevos más un `ADD COLUMN` nullable (metadata-only),
excepción acotada documentada en el encabezado de la migración (regla 11).

⚠️ **El downgrade pierde eventos de seguridad**: `alembic downgrade c02_core_models`
hace `DROP TABLE auth_event` y borra el historial de login, refresh, cambios de
rol y bajas. Exportarlo antes con:

```bash
psql "$DATABASE_URL" -c "COPY auth_event TO STDOUT CSV HEADER" > auth_event_$(date +%F).csv
```

Los eventos son auditoría, no una fuente de verdad recuperable: si el CSV no se
guardó, esos registros no se pueden reconstruir.

## Seed del tenant inicial

Crea una clínica, un admin con cambio de contraseña obligatorio, el sillón
"Sillón 1" y un profesional de ejemplo inactivo. Es idempotente por slug y no
imprime secretos. Se ejecuta desde `backend/`:

```bash
cd backend
SEED_CLINIC_SLUG=clinica-demo \
SEED_CLINIC_NAME="Clínica Demo Ficticia" \
SEED_ADMIN_EMAIL=admin@example.com \
SEED_ADMIN_PASSWORD='<clave provisoria>' \
python -m app.seed
```

Las cuatro variables `SEED_*` son obligatorias (ver `.env.example`); si falta
alguna el seed aborta nombrándola y no escribe nada. Usar solo datos sintéticos
(dominio `example.com`).

## Autenticación y sesiones (C-03)

Solo personal de clínica (admin, recepción, odontólogo). El paciente no tiene
cuenta: opera por token de un solo uso en la reserva pública.

| Método y ruta | Auth | Respuesta |
|---|---|---|
| `POST /api/auth/login` | pública (rate-limit) | `200` `{access_token, token_type, expires_in, user}` + cookie de refresh |
| `POST /api/auth/refresh` | cookie de refresh + `Origin` permitido | `200` `{access_token, token_type, expires_in}` + cookie rotada |
| `POST /api/auth/logout` | access **o** cookie | `204`, cookie borrada (idempotente) |
| `GET /api/auth/me` | Bearer | `200` `UserProfile` (sin hash ni tokens) |
| `POST /api/auth/change-password` | Bearer | `200` `{"status":"ok"}`, revoca las demás sesiones |
| `GET /api/users?cursor=&limit=` | Bearer `admin` | página por cursor, solo de su clínica |
| `POST /api/users` | Bearer `admin` | `201` sin hash ni contraseña, `must_change_password=true` |
| `PATCH /api/users/{id}` | Bearer `admin` | `200`; `active=false` es baja lógica y revoca sesiones |
| `POST /api/users/{id}/password-reset` | Bearer `admin` | `204`, clave provisoria + sesiones revocadas |

No existe `DELETE /api/users/{id}` → `405` (regla 7: nunca borrado físico).

### Cookie de refresh por entorno

| `ENV` | Nombre | Flags |
|---|---|---|
| `dev` (default) | `refresh_token` | `HttpOnly`, `SameSite=Lax`, **sin** `Secure` |
| `prod` | `__Host-refresh_token` | `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, sin `Domain` |

`Max-Age = JWT_REFRESH_DAYS × 86400` (default 7 días). En prod `COOKIE_DOMAIN`
debe quedar vacío: `__Host-` lo exige. El access vive ≤ 15 min y va en memoria
del cliente, nunca en `localStorage` (regla 10).

### Contrato de rotación para la SPA (single-flight)

Cada `POST /api/auth/refresh` rota el refresh **estrictamente**: no hay ventana
de gracia. Presentar un refresh ya rotado se interpreta como reuso, responde
`401 refresh_reuse` y **revoca toda la familia**, incluido el refresh vigente.

Por eso la SPA (C-06) debe:

1. Mantener **una sola** promesa de refresh en vuelo y compartirla entre todos
   los requests que reciban `401` (single-flight).
2. Reintentar cada request una sola vez con el access nuevo.
3. Si el refresh devuelve `401`, cerrar la sesión local y mandar a login.

Dos pestañas que refrescan a la vez con el mismo token provocan reuso y cierran
la sesión; el single-flight debe ser por origen (p. ej. `BroadcastChannel` o
`localStorage` + `navigator.locks`), no por pestaña.

### Códigos de error

| HTTP | `detail` | Cuándo |
|---|---|---|
| `401` | `invalid_credentials` | email inexistente, clave incorrecta o usuario inactivo (mensaje único) |
| `401` | `token_invalid` / `token_expired` | access ausente, mal firmado, `alg`/`iss`/`aud` inválidos o vencido |
| `401` | `invalid_session` | sesión revocada o usuario desactivado después de emitido el access |
| `401` | `invalid_refresh` / `refresh_reuse` | cookie ausente/inválida/vencida o refresh ya rotado |
| `403` | `forbidden_role` | rol sin permiso (no consulta la DB) |
| `403` | `password_change_required` | `must_change_password=true` fuera de `/auth/me`, `/auth/change-password`, `/auth/logout` |
| `403` | `origin_not_allowed` | `Origin` fuera de `CORS_ORIGINS` en refresh/logout |
| `409` | `last_admin` | desactivar o degradar al único admin activo |
| `422` | varios | body inválido (`extra='forbid'`), contraseña < 12 o igual a la actual, profesional de otra clínica |
| `429` | `rate_limited` | cupo agotado; incluye `Retry-After` |
| `503` | `auth_unavailable` | Redis caído: auth **falla cerrado** (nunca valida sin sesión) |

Rate-limits por defecto: login `5/60s` por IP+email y `30/60s` por IP, refresh
`60/60s` por IP, cambio de contraseña `5/60s` por usuario (configurables en
`.env`, formato `<intentos>/<segundos>s`).

## Seguridad — checklist de C-03

Verificado con `jwt-security-review` + `auth-implementation-patterns`:

| Control | Dónde se prueba |
|---|---|
| `alg` pineado a HS256; `alg=none`, HS512 y firma ajena rechazados | `tests/core/test_jwt.py` |
| `iss`, `aud`, `exp` y campos requeridos (`sid`, `type="access"`) validados | `tests/core/test_jwt.py` |
| Secreto JWT ≥ 32 bytes y algoritmo/`exp` validados al arrancar sin imprimir el valor | `tests/core/test_settings_auth.py` |
| `sub` = UUID estable del usuario (nunca email) y `email` solo como claim informativo | `tests/core/test_jwt.py`, `tests/modules/test_auth_login.py` |
| Rotación con detección de reuso y revocación de familia, sin ventana de gracia | `tests/core/test_sessions.py`, `tests/modules/test_auth_refresh.py` |
| Revocación inmediata: sesión/rol/baja invalidan el access en el siguiente request (Redis + fila viva) | `tests/common/test_principal.py`, `tests/modules/test_users_api.py` |
| Cookie `HttpOnly` (y `Secure` + `__Host-` en prod), `SameSite=Lax`, sin refresh en el body | `tests/modules/test_auth_login.py`, `app/modules/auth/cookies.py` |
| CSRF: `Origin` en allowlist para refresh/logout | `tests/modules/test_auth_refresh.py` |
| Sin tokens, hashes, emails ni PII en logs o mensajes de error | `tests/modules/test_auth_audit.py`, `tests/modules/test_errors.py` |
| Autorización server-side por rol + `must_change_password`; el tenant sale del principal | `tests/common/test_require_roles.py`, `tests/modules/test_users_api.py` |
| Aislamiento cross-tenant probado en cada tabla operativa | `tests/modules/test_users_api.py`, `tests/models/test_tenancy.py` |
| Rate-limit antes de evaluar credenciales; Redis caído ⇒ `503` (fail-closed) | `tests/modules/test_auth_login.py`, `tests/core/test_redis_client.py` |
| Contraseñas 12–128 sin reglas de composición, hash vigente con rehash perezoso | `tests/modules/test_auth_change_password.py`, `tests/modules/test_auth_login.py` |

## Tests

Los tests corren contra **PostgreSQL real y Redis real** (nunca mocks de base de
datos ni de Redis — regla 9). Los que necesitan alguno de los dos se saltan con
motivo explícito si el servicio no responde, para que `pytest` siga siendo útil
sin infraestructura; CI siempre los ejecuta.

```bash
# DB de tests: TEST_DATABASE_URL > DATABASE_URL > default local
export TEST_DATABASE_URL=postgresql+asyncpg://turnos:ci-secret@localhost:5432/turnos_test
export REDIS_URL=redis://localhost:6379/0
pytest -q
ruff check backend && black --check backend && mypy backend
```

El rol necesita `CREATEDB` para el test de ciclo de migraciones y el del CLI del
seed (usan una base temporal propia); sin ese permiso se saltan con motivo. Con
`docker compose up -d db redis` no se saltea nada.
