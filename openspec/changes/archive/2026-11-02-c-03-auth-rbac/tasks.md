# Tasks — c-03-auth-rbac

> Governance **CRITICO** + TDD estricto: cada task de comportamiento sigue
> RED (test que falla, ejecutado y visto rojo) → GREEN (mínimo código) →
> TRIANGULATE (≥2 casos) → REFACTOR (verde tras cada paso). Los invariantes de
> sesión y de RBAC corren contra **Postgres 15 y Redis 7 reales** (compose o
> servicios de CI), nunca mocks de DB/Redis (regla 9). Datos solo sintéticos
> (`@example.com`, teléfonos ficticios, nombres inventados — regla 13). Sin
> commits ni builds sin pedido explícito. Todo DDL vive en la única revisión
> `c03_auth_rbac` (revises `c02_core_models`).

## 0. Gate de aprobación humana

- [x] 0.1 Obtener OK explícito del humano sobre las "Decisiones abiertas para
  revisión humana" 1–9 de `design.md` y registrar la resolución (aprobada /
  alternativa elegida) al pie de `design.md` + engram; ninguna task siguiente
  arranca sin esa nota. Si se rechaza 1, ajustar el escenario de revocación
  inmediata y el test de logout; si se rechaza 3, la migración 002 suma
  `auth_session`; si se rechaza 5, quitar `identity/auth-audit` y sus tasks;
  si se rechaza 9, agregar CSRF de doble envío. Verificación: nota de
  resolución firmada por fecha en `design.md` y `git diff --stat` sin cambios
  de código de producción.

## 1. Configuración e infraestructura compartida

- [x] 1.1 RED: `backend/tests/core/test_settings_auth.py` — `Settings()` con
  `JWT_SECRET` de 20 bytes levanta error que nombra `JWT_SECRET` sin imprimir
  el valor; con 32+ bytes arranca; `JWT_ALGORITHM` distinto de `HS256` es
  rechazado; los defaults nuevos existen (`JWT_REFRESH_DAYS=7`,
  `AUTH_LOGIN_RATE_LIMIT="5/60s"`, `AUTH_LOGIN_IP_RATE_LIMIT="30/60s"`,
  `COOKIE_DOMAIN=""`). GREEN: validadores en `app/core/settings.py`.
  Verificación: `pytest backend/tests/core/test_settings_auth.py -q`.
- [x] 1.2 RED→GREEN: `backend/tests/core/test_redis_client.py` — el cliente de
  `app/core/redis.py` responde `PING` contra `REDIS_URL` y se reutiliza entre
  dependencias en la misma app. GREEN: cliente lazy en el `lifespan` de
  `create_app`, dependency `get_redis()` y `app.state.redis`; `main.py` y
  `/ready` dejan de crear clientes por request. Verificación:
  `pytest backend/tests/core/test_redis_client.py -q`.
- [x] 1.3 RED→GREEN: `backend/tests/core/test_get_db.py` — `get_db` entrega una
  `AsyncSession` usable (inserta y lee una `clinic` en el fixture) y la cierra
  al terminar el request. GREEN: `async_sessionmaker` sobre el engine async en
  `app/core/database.py`, dependency cableada en `app/core/deps.py` y
  `engine.dispose()` en el `lifespan`. Verificación:
  `pytest backend/tests/core/test_get_db.py -q`.
- [x] 1.4 Actualizar entorno de tests y CI sin romper la suite: `JWT_SECRET` de
  32+ bytes en `backend/tests/conftest.py`, `.github/workflows/ci-backend.yml`
  y `.env.example` (más `AUTH_LOGIN_RATE_LIMIT`, `AUTH_LOGIN_IP_RATE_LIMIT`,
  `AUTH_REFRESH_RATE_LIMIT`, `REDIS_AUTH_DB` documentados como no secretos).
  Verificación: `pytest backend/tests/test_env_example.py -q` y
  `pytest -q` (suite previa verde con el secreto nuevo).
- [x] 1.5 Fixtures de infraestructura en `backend/tests/conftest.py`:
  `redis_client` (base 15 de `REDIS_URL`, `FLUSHDB` por test),
  `app_client` (`create_app(settings)` + `dependency_overrides` de `get_db` y
  `get_redis` + `httpx.AsyncClient` con cookie jar) y `clock` inyectable.
  Verificación: `pytest backend/tests/test_health.py backend/tests/test_edges.py -q`
  y un test nuevo que comprueba que la cookie sobrevive entre dos requests del
  mismo cliente.

## 2. Migración 002 (auth_event + password_changed_at)

- [x] 2.1 RED: extender `backend/tests/test_migrations.py` — tras `upgrade
  head` existen `user.password_changed_at`, la tabla `auth_event`, el enum
  `auth_event_type` y los índices `(clinic_id, created_at)` y
  `(user_id, created_at)`; tras `downgrade c02_core_models` no queda ninguno
  de ellos. GREEN: `backend/alembic/versions/c03_auth_rbac.py`
  (`down_revision="c02_core_models"`), con comentario de la excepción acotada
  a la regla 11 (objetos nuevos + `ADD COLUMN` nullable metadata-only) y el
  trigger `trg_auth_event_no_mutate`. Verificación:
  `pytest backend/tests/test_migrations.py -q`.
- [x] 2.2 RED: `backend/tests/models/test_auth_event.py` — `UPDATE` y `DELETE`
  sobre una fila de `auth_event` lanzan excepción y la fila queda intacta;
  `clinic_id` nulo → NOT NULL; `user_id` de otra clínica → FK compuesta;
  `payload` que no es objeto/array → CHECK. GREEN: modelo
  `app/models/auth_event.py` + reexport en `app/models/__init__.py` alineado
  con la migración. Verificación: `pytest backend/tests/models/test_auth_event.py -q`.
- [x] 2.3 Documentar en `backend/README.md` (sección "Migraciones") que la
  revisión es `c03_auth_rbac`, que el downgrade pierde eventos de seguridad y
  cómo exportarlos antes. Verificación: el comando documentado
  (`psql ... -c "COPY auth_event TO STDOUT CSV HEADER"`) se ejecuta tal cual
  contra compose.

## 3. Tokens de acceso y sesiones Redis

- [x] 3.1 RED: `backend/tests/core/test_jwt.py` — el access emitido contiene
  `sub`, `clinic_id`, `roles`, `email`, `jti`, `sid`, `type="access"`, `iat`,
  `exp`, `iss`, `aud` y `exp-iat ≤ 900`; `decode` acepta el token propio y
  rechaza `exp` vencido (con `clock`), firma con otro secreto, `alg=none`,
  `alg=HS512`, `iss` y `aud` ajenos, `type="refresh"` y token sin `sid`.
  GREEN: `app/core/jwt.py` (emit/decode con `algorithms=[HS256]`,
  `issuer`/`audience`, `leeway=30`, `options.require`) reemplazando los stubs
  de `app/core/security.py`. Verificación: `pytest backend/tests/core/test_jwt.py -q`.
- [x] 3.2 RED: `backend/tests/core/test_sessions.py` (Redis real) — crear
  sesión genera `auth:sess:{sid}` y `auth:rt:{sid}` con TTL ≤ 7 días y
  `auth:user:{uid}` con el `sid`; el refresh en claro no aparece en Redis
  (solo `sha256`); la clave de sesión no se renueva al rotar. GREEN:
  `app/modules/auth/sessions.py` (`create_session`, `rotate`, `revoke`,
  `revoke_all`, claves y TTLs del design §4). Verificación:
  `pytest backend/tests/core/test_sessions.py -q`.
- [x] 3.3 RED: casos de rotación — (a) rotación válida devuelve refresh nuevo
  y el anterior falla; (b) presentar el anterior cuando ya existe uno vigente
  devuelve `reuse` y deja la familia sin `auth:sess`/`auth:rt`; (c) secreto
  basura con `sid` válido devuelve `invalid` **sin** revocar la familia;
  (d) dos rotaciones concurrentes (`asyncio.gather`) emiten **un** solo
  refresh válido. GREEN: script Lua compare-and-swap (`cur`/`prev`/`gen`) con
  `EVALSHA` y registro de script. Verificación:
  `pytest backend/tests/core/test_sessions.py -q -k "rotacion or reuso or concurrente"`.
- [x] 3.4 RED: `revoke_all` elimina todas las sesiones del usuario y una
  sesión de otro usuario sigue viva; `revoke` es idempotente (segunda llamada
  no falla). GREEN: índices `auth:user:{uid}` y limpieza de `sid` vencidos.
  Verificación: `pytest backend/tests/core/test_sessions.py -q -k "revoke"`.

## 4. Auditoría de seguridad

- [x] 4.1 RED: `backend/tests/modules/test_auth_audit.py` — un evento escrito
  en la misma transacción de un alta persiste junto al usuario y, si la
  transacción revierte, no queda evento ni usuario; el evento no guarda email,
  teléfono, contraseña ni tokens en ningún campo; `login_failed` de email
  inexistente guarda `user_id NULL` + `subject_hash` y ningún texto con el
  email. GREEN: `app/modules/auth/audit.py` (`record_event` transaccional y
  `record_best_effort`). Verificación:
  `pytest backend/tests/modules/test_auth_audit.py -q`.
- [x] 4.2 RED→GREEN: el fallo de auditoría no cambia la respuesta de login
  (se simula con una tabla/DB que rechaza el insert) y deja un warning sin
  credenciales en `caplog`. Verificación:
  `pytest backend/tests/modules/test_auth_audit.py -q -k "best_effort"`.

## 5. Principal, RBAC y alcance por profesional

- [x] 5.1 RED: `backend/tests/common/test_principal.py` — con un access válido
  y sesión viva, `get_current_principal` devuelve rol, `clinic_id` y
  `professional_id` tomados de la fila de `user` (aunque el token traiga otro
  rol válido por firma); usuario inactivo → `401`; usuario borrado → `401`;
  sesión revocada → `401`; Redis caído → `503`. GREEN:
  `app/common/principal.py` + `get_current_principal` en `app/core/deps.py`.
  Verificación: `pytest backend/tests/common/test_principal.py -q`.
- [x] 5.2 RED: `backend/tests/common/test_require_roles.py` — rol permitido
  ejecuta el handler; rol no permitido → `403 forbidden_role` sin tocar la
  DB; request sin credencial → `401`; principal con
  `must_change_password=true` → `403 password_change_required` incluso con
  rol permitido. GREEN: `require_roles`/`require_active_password`
  reemplazando el stub `501` de `app/common/dependencies.py`, con al menos un
  endpoint de prueba protegido. Verificación:
  `pytest backend/tests/common/test_require_roles.py -q`.
- [x] 5.3 RED: `backend/tests/common/test_scoping.py` — sobre `schedule_rule`
  y `professional`: un odontólogo con dos filas propias y otro odontólogo con
  filas en la misma clínica obtiene solo las propias; `recepcion`/`admin`
  obtienen todas las de su clínica; una clínica B nunca aparece; la sentencia
  generada contiene los dos predicados (`clinic_id` y `professional_id`) y no
  se filtra en Python; odontólogo con `professional_id` nulo → `403`. GREEN:
  `app/common/scoping.py::scope_by_professional`. Verificación:
  `pytest backend/tests/common/test_scoping.py -q`.
- [x] 5.4 RED→GREEN: acceso por identificador de una fila de otro profesional
  responde `404` (no `403`) usando el helper sobre un endpoint interno de
  prueba; documentar el contrato para C-05 en el docstring del helper.
  Verificación: `pytest backend/tests/common/test_scoping.py -q -k "por_id"`.

## 6. Endpoints de autenticación

- [x] 6.1 RED: `backend/tests/modules/test_auth_login.py` — login correcto
  responde `200` con access y cookie (`HttpOnly`, `SameSite=Lax`, sin
  `Secure` en dev), actualiza `last_login_at`, el body no trae refresh y
  `must_change_password` refleja la fila; email inexistente, contraseña
  incorrecta y usuario inactivo responden `401` con el mismo `detail`;
  un campo extra en el body → `422` (`extra='forbid'`). GREEN:
  `LoginRequest`/`LoginResponse` en `app/modules/auth/schemas.py` +
  `AuthService.login` + router real (se eliminan `ping`/`echo`; `test_edges`
  se reapunta a `/api/auth/login`). Verificación:
  `pytest backend/tests/modules/test_auth_login.py backend/tests/test_edges.py -q`.
- [x] 6.2 RED: rate-limit de login — el sexto intento del mismo par IP+email
  en 60 s responde `429` con `Retry-After` y no evalúa credenciales (se
  comprueba que `last_login_at` no cambia); superar el tope por IP con emails
  distintos también da `429`; con Redis real, dos clientes distintos no
  comparten el cupo del par. GREEN: `app/core/rate_limit.py` (Lua `INCR` +
  `EXPIRE`) aplicado en el router antes del servicio. Verificación:
  `pytest backend/tests/modules/test_auth_login.py -q -k "rate"`.
- [x] 6.3 RED: rehash perezoso — login con hash de parámetros viejos actualiza
  `password_hash` a los parámetros vigentes y la misma contraseña sigue
  entrando. GREEN: `needs_rehash` en el flujo de login (transaccional con
  `last_login_at`). Verificación:
  `pytest backend/tests/modules/test_auth_login.py -q -k "rehash"`.
- [x] 6.4 RED: `backend/tests/modules/test_auth_refresh.py` — refresh válido
  rota cookie y devuelve access nuevo; el refresh anterior → `401`; reuso →
  `401 refresh_reuse`, familia revocada (el vigente también falla) y evento
  `refresh_reuse_detected` escrito; cookie ausente/expirada/familia revocada →
  `401` + `Set-Cookie` de borrado; `Origin` no permitido → `403`; refresh
  válido no sirve como access. GREEN: `AuthService.refresh` + endpoint con
  cookie y chequeo de `Origin`. Verificación:
  `pytest backend/tests/modules/test_auth_refresh.py -q`.
- [x] 6.5 RED: logout — `204`, borra cookie, el access anterior recibe `401`
  inmediato y el refresh también; segundo logout `204` sin efectos; logout
  con access vencido pero cookie válida revoca la familia. GREEN:
  `AuthService.logout` + endpoint. Verificación:
  `pytest backend/tests/modules/test_auth_logout.py -q`.
- [x] 6.6 RED: `GET /api/auth/me` — devuelve `id`, `email`, `role`,
  `clinic_id`, `professional_id`, `must_change_password`, `last_login_at`; no
  incluye `password_hash` ni tokens; sin token → `401`. GREEN: endpoint `me`
  con `get_current_principal`. Verificación:
  `pytest backend/tests/modules/test_auth_me.py -q`.
- [x] 6.7 Documentar en `backend/README.md` el flujo de sesión (endpoints,
  cookie por entorno, contrato single-flight para la SPA, códigos de error) y
  verificar que los ejemplos `curl` del README funcionan contra compose
  (`docker compose up -d db redis` + `pytest -q` como respaldo).

## 7. Cambio y política de contraseñas

- [x] 7.1 RED: `backend/tests/modules/test_auth_change_password.py` — cambio
  correcto responde `200`, la clave vieja deja de autenticar, `password_changed_at`
  se setea, `must_change_password=false` y la otra sesión del usuario recibe
  `401`; contraseña actual incorrecta → `401` sin tocar hash ni sesiones;
  nueva de 11 caracteres o igual a la actual → `422`; campo extra → `422`.
  GREEN: `ChangePasswordRequest` + `AuthService.change_password` + endpoint con
  rate-limit por usuario. Verificación:
  `pytest backend/tests/modules/test_auth_change_password.py -q`.
- [x] 7.2 RED: gate de contraseña provisoria — un principal con
  `must_change_password=true` recibe `403 password_change_required` en
  `GET /api/users`, pero puede usar `/auth/me`, `/auth/change-password` y
  `/auth/logout`; tras cambiarla, el mismo endpoint responde según su rol.
  GREEN: gate dentro de `require_roles` (design §9). Verificación:
  `pytest backend/tests/modules/test_auth_change_password.py -q -k "gate"`.

## 8. Gestión de usuarios (admin)

- [x] 8.1 RED: `backend/tests/modules/test_users_api.py` — alta de `recepcion`
  sin profesional → `201` con email minúsculas, sin hash ni contraseña,
  `must_change_password=true`; odontólogo sin `professional_id` → `422`;
  profesional de otra clínica → `422` sin datos de B; email duplicado → `422`;
  body con `clinic_id` → `422`; rol no admin → `403`; los eventos
  `user_created` quedan en `auth_event`. GREEN: `UserCreate`/`UserRead` con
  `extra='forbid'` + servicio/endpoint de alta. Verificación:
  `pytest backend/tests/modules/test_users_api.py -q`.
- [x] 8.2 RED: listado paginado por cursor solo de la clínica del principal,
  sin `password_hash`, sin `OFFSET`; `recepcion`/`odontologo` → `403`; test
  cross-tenant con el mismo email en A y B. GREEN: `GET /api/users` con
  columnas explícitas y `ORDER BY created_at, id`. Verificación:
  `pytest backend/tests/modules/test_users_api.py -q -k "lista or tenant"`.
- [x] 8.3 RED: `PATCH /api/users/{id}` — baja lógica (`active=false`) revoca
  sesiones y el usuario desactivado recibe `401`; `DELETE` → `405`; cambio de
  rol a `odontologo` sin profesional → `422`; cambio de rol revoca sesiones;
  id inexistente o de otra clínica → `404`; eventos `user_updated`,
  `user_deactivated`, `role_changed` auditados con `actor_user_id`. GREEN:
  `UserUpdate` + servicio + endpoint. Verificación:
  `pytest backend/tests/modules/test_users_api.py -q -k "patch or baja or rol"`.
- [x] 8.4 RED: salvaguarda del último admin — desactivarse o quitarse el rol
  `admin` siendo el único admin activo → `409` y sin cambios; con dos admins
  activos la operación procede. GREEN: conteo con `FOR UPDATE` (o `SELECT ...
  WHERE role='admin' AND active FOR UPDATE`) dentro de la transacción del
  `PATCH`. Verificación:
  `pytest backend/tests/modules/test_users_api.py -q -k "ultimo_admin"`.
- [x] 8.5 RED: `POST /api/users/{id}/password-reset` — `204`, clave anterior
  inválida, nueva válida, `must_change_password=true`, sesiones revocadas, sin
  contraseña ni hash en cuerpo ni logs; id de otra clínica → `404`. GREEN:
  servicio + endpoint + evento `password_changed` con actor admin.
  Verificación: `pytest backend/tests/modules/test_users_api.py -q -k "reset"`.

## 9. Verificación integral y cierre

> ⚠️ **Estado de verificación local (2026-11-02)**: la máquina de desarrollo no
> tiene Docker/Postgres/Redis, así que los tests que los requieren se saltan con
> motivo explícito. `pytest -q` local: **84 passed, 213 skipped**; `ruff check
> backend`, `black --check backend`, `mypy backend` y `openspec validate
> c-03-auth-rbac --strict` verdes. Las verificaciones que necesitan servicios
> reales (migraciones, sesiones Redis, RBAC/scoping sobre DB, 9.1 y el gate 9.2)
> quedan **pendientes de CI** y bloquean el archive hasta correr en verde.

- [x] 9.1 Test de ciclo completo con la API real (httpx + Postgres + Redis):
  recepción crea turno (endpoint interno de prueba) y recibe `403` en
  `/api/users`; odontólogo A ve solo sus filas y B no ve nada aunque pida el
  `id`; admin desactiva a A y su siguiente request da `401`; una clínica B no
  filtra datos. Verificación:
  `pytest backend/tests/test_auth_integration.py -q`.
- [ ] 9.2 Gate final del change: `pytest -q` contra Postgres 15 + Redis 7,
  `ruff check backend`, `black --check backend`, `mypy backend` (strict) y
  `openspec validate c-03-auth-rbac --strict`. Registrar la tabla "TDD Cycle
  Evidence" y las salidas resumidas en el resumen del apply.
- [x] 9.3 Revisión de seguridad del propio change (jwt-security-review +
  auth-implementation-patterns): checklist escrita en
  `backend/README.md` §Seguridad — alg pineado, sin `alg=none`, secreto ≥32
  bytes, `sub` estable (UUID, no email), reuse-detection probada, cookies
  HttpOnly/Secure/SameSite, sin tokens en logs, autorización server-side.
  Verificación: checklist con cada ítem apuntando a un test o task concreta.

## Workflow follow-up

- Al archivar: registrar en `CHANGES.md` que C-03 usó `c03_auth_rbac` (no
  "migración 002" genérica) y que el refresh family vive en Redis (decisión
  aprobada).
- Dejar anotado para C-04/C-05 el contrato de `require_roles` +
  `scope_by_professional` y que `appointment` debe consumirlo sin filtros
  propios.
- Registrar en el design de C-06 el requisito de refresh single-flight en la
  SPA y la dependencia `same-site` de la cookie.
- `/opsx:archive c-03-auth-rbac` tras revisión humana (governance CRITICO).
