# Design — c-03-auth-rbac

## Context

Ver `proposal.md` (Why) y `specs/identity/*`, `specs/core/staff-users`.
Estado observado tras C-02:

- `backend/app/modules/auth/*` y `.../users/*` son stubs (`ping`/`echo`).
  `app/common/dependencies.py::require_roles` responde `501` y
  `app/core/deps.py::get_db` levanta `NotImplementedError`: **no existe
  todavía ninguna ruta que toque la base**.
- `app/core/security.py` tiene hashing argon2id real (RFC 9106 low-memory:
  `m=64 MiB`, `t=3`, `p=4`) y `create_access_token`/`decode_token` de
  juguete: sin `iss`/`aud`/`type`/`roles`/`sid`, `leeway` ni verificación de
  sesión.
- `app/core/settings.py` ya trae `JWT_ALGORITHM/ISSUER/AUDIENCE/ACCESS_MINUTES/
  REFRESH_DAYS`; no hay flags de cookie ni límites de auth. `JWT_SECRET` no se
  valida en longitud.
- `app/models/user.py`: `clinic_id`, `email` único por clínica, rol enum
  nativo, `professional_id` obligatorio si `odontologo`, `active`,
  `must_change_password`, `last_login_at`. No hay `password_changed_at`.
- Redis se usa ad hoc (`from_url` por llamada) en `app/main.py` y en el
  worker; no hay cliente compartido ni inyección.
- Alembic head = `c02_core_models`. CI (`ci-backend.yml`) ya levanta Postgres
  15.8 **y Redis 7.4**, y corre `upgrade → downgrade -1 → upgrade` + pytest +
  ruff/black/mypy strict.
- `backend/tests/conftest.py` fija `JWT_SECRET="test-secret-no-produccion"`
  (26 bytes, por debajo del mínimo que este change exige) y no tiene fixture
  de Redis. `tests/test_edges.py` usa `/auth/echo` como borde de validación.

Restricciones: reglas duras 2, 3, 4, 6, 7, 8, 9, 10, 11, 13; DD-03 (RBAC
simple, evolución a políticas), DD-07 (una DB por clínica, `clinic_id`
obligatorio igual), RN-GL-01 (auditoría en la misma transacción) para las
mutaciones administrativas; governance **CRITICO** (sin código hasta aprobar
este diseño).

## Decisiones ya aprobadas (no se reabren)

- Almacenamiento de refresh tokens / familias / lista negra: **Redis** (Redis
  7 ya es servicio de Compose y de CI). Este design lo desarrolla en §2–§4.
- Worker: **ARQ**. C-03 no necesita jobs asíncronos; la revocación y la
  auditoría se hacen en el request.
- Gestor de paquetes: **uv** preferido, con `pip`/venv como fallback en esta
  máquina; no se agregan dependencias nuevas (se usa `python-jose` y
  `redis.asyncio` ya presentes).

## Goals / Non-Goals

**Goals:**

- Una sesión revocable de inmediato (logout, baja, cambio de rol, cambio de
  clave) sin renunciar a access tokens cortos.
- Un único punto de autorización (`Principal` + `require_roles` + helper de
  alcance) que C-04…C-13 consuman sin reimplementar reglas ni filtros.
- Modos de falla explícitos: Redis caído, refresh concurrente, replay,
  enumeración de cuentas, reloj desfasado.
- Migración 002 reversible y probada contra Postgres 15 real, y sesiones
  probadas contra Redis 7 real (sin mocks de infraestructura, regla 9).

**Non-Goals:**

- MFA, recuperación de contraseña por email, login con Google/WhatsApp,
  bloqueo de cuenta por intentos fallidos.
- Permisos por registro más allá de "odontólogo solo lo suyo" (DD-03),
  RLS (DD-07 la descarta), multi-sucursal.
- Endpoints de agenda/turnos (C-04/C-05), guards de la SPA (C-06),
  automatización de rotación de `JWT_SECRET` con `kid` (C-14).
- Retención/exportación de la auditoría de seguridad (C-13/C-14).

## Decisions

### 1. Modelo de sesión: `sid` en el access + registro de sesión en Redis

El access token lleva `sid` (identificador de familia de refresh). En cada
request autenticado se valida firma/claims y **además** se comprueba que
`auth:sess:{sid}` exista. Eso convierte el access en "stateless-lite": la
firma prueba integridad, el registro Redis prueba que la sesión no fue
cerrada.

- Por qué: la regla 10 exige refresh revocable y la operación real (personal
  despedido, recepción que cambia de puesto) necesita corte inmediato, no
  "hasta 15 minutos".
- Alternativa A (descartada): access 100 % stateless y aceptar ventana de
  revocación ≤ `JWT_ACCESS_MINUTES`. Menos dependencias, pero deja un token
  vivo tras el logout, que es exactamente el escenario que un piloto en salud
  va a auditar.
- Alternativa B (descartada): lista negra de `jti` en Redis. Misma latencia
  que la opción elegida, pero cada logout deja una clave por token y no
  permite revocar "todas las sesiones del usuario" de forma barata.
- Costo: Redis pasa a ser dependencia dura del camino autenticado (ver
  decisión 12 y riesgos).

### 2. Refresh opaco `<sid>.<secreto>` con hash en Redis

El refresh **no** es un JWT: es `sid` (UUIDv4) + `.` + 32 bytes aleatorios
(`secrets.token_urlsafe(32)`, 256 bits). En Redis se guarda **solo**
`sha256(secreto)`, nunca el valor en claro ni en logs.

- Por qué: no hay nada que "decodificar" de un refresh; su única función es
  probar posesión y permitir rotación atómica. Con el `sid` en el token, la
  detección de reuso no necesita índice inverso por hash.
- Alternativa (descartada): refresh JWT firmado. Habría que mantener además
  un registro de revocación por `jti`, es decir, el mismo estado que ya
  tenemos, más criptografía que no aporta.
- Nota: `sid` no es secreto; la seguridad descansa en los 256 bits del
  secreto. Un `sid` adivinado sin secreto produce `401` genérico y **no**
  revoca la familia (ver decisión 3), así que no sirve como DoS.

### 3. Rotación y detección de reuso en una sola operación atómica

Clave única por familia: `auth:rt:{sid}` (Hash) con
`cur_hash`, `prev_hash`, `gen`, `uid`, `cid`, `exp`. Un script Lua
(`EVALSHA`) hace compare-and-swap:

| Caso | Acción | Respuesta |
|------|--------|-----------|
| clave ausente | nada | `401 invalid_session` |
| `sha256(secreto) == cur_hash` | `prev=cur`, `cur=nuevo`, `gen+=1`, `exp` sin mover | `200` + nuevo refresh |
| `sha256(secreto) == prev_hash` | `DEL auth:rt:{sid}`, `DEL auth:sess:{sid}`, `SREM auth:user:{uid}`, auditar `refresh_reuse_detected` | `401 refresh_reuse` |
| cualquier otro hash | nada (no revoca) | `401 invalid_refresh` |

- Por qué Lua: dos pestañas que refrescan a la vez no pueden emitir dos
  refresh válidos (lo que rompería la detección de reuso); el script corre
  serializado en el servidor Redis.
- Por qué solo `prev` revoca: un intento con secreto basura y `sid` conocido
  no debe poder matar la sesión de otro (DoS trivial desde el propio token
  filtrado). El reuso real siempre coincide con la generación anterior.
- Vigencia **absoluta**: `exp` de la familia no se renueva en cada rotación
  (7 días desde el login). Alternativa sliding (renovar en cada refresh)
  descartada: una pestaña abierta mantendría sesiones eternas, difícil de
  explicar en auditoría.

### 4. Esquema de claves y TTLs en Redis

| Clave | Tipo | Contenido | TTL |
|-------|------|-----------|-----|
| `auth:sess:{sid}` | Hash | `uid`, `cid`, `created_at`, `gen` | `JWT_REFRESH_DAYS` (7 d), no se renueva |
| `auth:rt:{sid}` | Hash | `cur_hash`, `prev_hash`, `gen`, `uid`, `cid`, `exp` | ídem sesión |
| `auth:user:{uid}` | Set | `sid` de todas las sesiones del usuario | ídem sesión (se refresca al crear sesión) |
| `rl:login:pair:{sha256(ip\|email)}` | String (int) | contador ventana fija | 60 s |
| `rl:login:ip:{ip}` | String (int) | contador ventana fija | 60 s |
| `rl:refresh:ip:{ip}` | String (int) | contador ventana fija | 60 s |
| `rl:pwd:{uid}` | String (int) | contador de cambio de clave | 60 s |

- Sin `KEYS`/`SCAN` en el camino caliente; el set por usuario evita tener que
  escanear para revocar todo.
- `auth:user:{uid}` puede quedar con `sid` vencidos: se limpian en el `SREM`
  de revocación y con `EXPIRE` al crear cada sesión; un `sid` vencido no
  valida nada igual.
- El email nunca aparece en claro en una clave: se hashea junto con la IP.

### 5. Contrato del access token

| Claim | Valor |
|-------|-------|
| `sub` | UUID del usuario (string) |
| `clinic_id` | UUID de la clínica del usuario |
| `roles` | lista con el rol vigente (`["admin"]`, `["recepcion"]`, `["odontologo"]`) |
| `email` | email del usuario (lo pide CHANGES; ver decisión abierta 8) |
| `jti` | UUIDv4 único del token |
| `sid` | UUID de la familia de sesión |
| `type` | `"access"` |
| `iat` / `exp` | ahora / ahora + `JWT_ACCESS_MINUTES` (≤15) |
| `iss` / `aud` | `JWT_ISSUER` / `JWT_AUDIENCE` de settings |

Validación: `jwt.decode(..., algorithms=[settings.JWT_ALGORITHM],
audience=..., issuer=..., options={"require": ["exp","iat","sub","type"]},
leeway=30)`. Se rechaza `type != "access"` (un refresh nunca sirve como
access) y se exige `sid` presente. `algorithm` se valida contra una constante
`HS256` y el `Settings` sólo admite `HS256` en v1 (si alguien configura otro,
el arranque falla en vez de degradar).

- `roles` como lista aunque la DB guarde un rol único: DD-03 anticipa el
  pasaje a permisos/políticas y así el contrato no rompe clientes.
- Alternativa considerada: claims mínimos (`sub`, `sid`, `type`) y pedir todo
  lo demás por `/auth/me`. Se descarta porque cada request ya carga el usuario
  de la DB (decisión 9); los claims son informativos, no fuente de verdad.

### 6. Logout y revocación

`POST /api/auth/logout` (autenticado, idempotente): `DEL auth:rt:{sid}`,
`DEL auth:sess:{sid}`, `SREM auth:user:{uid} {sid}`, borra cookie, audita
`logout`, responde `204` aunque el `sid` ya no exista. Si no hay access válido
pero sí cookie de refresh, se revoca la familia de la cookie (mismo
resultado): el logout no debe fallar por un access vencido.

Revocación masiva (baja, cambio de rol, reseteo, cambio de contraseña):
`SMEMBERS auth:user:{uid}` → `DEL` de cada `auth:sess`/`auth:rt` →
`DEL auth:user:{uid}`. Se ejecuta en el servicio, no en un job, para que la
baja sea efectiva antes de responder.

### 7. Contraseñas: hashing, rehash y política

- argon2id RFC 9106 low-memory (`m=65536 KiB`, `t=3`, `p=4`) ya implementado;
  se mantiene como único hasher y se agrega `needs_rehash` en el login
  exitoso (rehash perezoso, transaccional con `last_login_at`).
- Sin contraseñas en claro en ningún punto: el borde Pydantic las declara
  `SecretStr`, se hashea antes de tocar la sesión y los errores de dominio
  usan mensajes fijos (`Datos de usuario inválidos`).
- Política: 12–128 caracteres, sin reglas de composición (NIST SP 800-63B),
  distinta de la actual en `change-password`, y `password_changed_at` para
  trazabilidad. Todo se valida en el servidor; el cliente no es autoridad.
- Login con email inexistente verifica contra un hash señuelo generado una vez
  al importar el módulo, para que el tiempo de respuesta no delate cuentas.

### 8. Rate-limit de autenticación (Redis, ventana fija)

`app/core/rate_limit.py`: `hit(key, limit, window_s) -> (allowed, retry_after)`
con `INCR` + `EXPIRE` en un único script Lua (evita el `INCR` sin TTL cuando
el proceso muere entre comandos). Claves de la decisión 4:

- Login: par IP+email 5/60 s **y** tope por IP 30/60 s. Se evalúa antes de
  hashear (protege CPU) y después de normalizar email (nunca se guarda el
  email en claro: la clave usa `sha256(ip|email)`).
- Refresh y logout: 60/60 s por IP (evita bucles de rotación).
- `change-password`: 5/60 s por usuario.
- Respuesta `429` con `Retry-After` y `detail` genérico; el middleware global
  en memoria de C-01 se mantiene para el resto de la API (no se toca).
- Alternativa (descartada): `slowapi`. Su backend por defecto es memoria por
  proceso, justo el bug que hay que evitar con `worker` + varios `api`;
  configurarlo en Redis es más código que este helper. Alternativa sliding
  window: más precisa pero más comandos y claves; ventana fija permite un
  burst de 2× en el borde, aceptable con 5 intentos.

### 9. RBAC: `Principal`, gate de contraseña provisoria y `require_roles`

`app/common/principal.py`:

```python
@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    clinic_id: UUID
    email: str
    roles: frozenset[UserRole]
    professional_id: UUID | None
    sid: str
    must_change_password: bool
```

- `get_current_principal` (en `app/core/deps.py`): lee `Authorization: Bearer`,
  decodifica/valida (decisión 5), verifica `auth:sess:{sid}`, carga el usuario
  por `(id, clinic_id)` con columnas explícitas y exige `active=true`. Si
  Redis no responde → `503` (no `401`, no fail-open). Si algo del token no
  cuadra → `401` con código corto (`token_expired`, `token_invalid`,
  `invalid_session`) sin detalle de la causa exacta en el log público.
- `require_active_password`: si el principal tiene `must_change_password` →
  `403 password_change_required`.
- `require_roles(*roles)`: dependency-factory que depende de
  `require_active_password` y compara contra `principal.roles`; `403
  forbidden_role` con la lista de roles requeridos sólo en el log, no en el
  body. El gate de contraseña vive **dentro** de `require_roles` para que
  ningún endpoint protegido pueda olvidarlo; `/auth/me`,
  `/auth/change-password` y `/auth/logout` usan `get_current_principal` sin
  el gate.
- Seam para DD-03: `require_roles` es la única puerta; pasar a políticas por
  recurso es reemplazar su cuerpo por `policy.allows(principal, action,
  resource)` sin tocar endpoints.
- Alternativa descartada: confiar en `roles` del JWT y evitar la carga de
  usuario. Ahorra una query, pero un rol cambiado o una baja quedarían
  vigentes hasta 15 min, y el `professional_id` para el alcance vendría de un
  claim. La regla "nunca confiar en claims de rol cuando existe lookup en
  servidor" se cumple recargando la fila.

### 10. Alcance "odontólogo solo lo suyo" en la query

`app/common/scoping.py`:

```python
def scope_by_professional(stmt, principal, professional_id_col):
    stmt = stmt.where(professional_id_col.table.c.clinic_id == principal.clinic_id)
    if principal.roles == {UserRole.ODONTOLOGO}:        # exactamente odontólogo
        if principal.professional_id is None:
            raise DomainError(403, "forbidden_scope")
        stmt = stmt.where(professional_id_col == principal.professional_id)
    return stmt
```

- Se aplica **siempre** en el servicio, antes de `execute`, nunca en el router
  ni en el cliente; `admin` y `recepcion` ven toda la clínica.
- Acceso por identificador (`GET /x/{id}`): se ejecuta la misma consulta
  acotada y, si no aparece, `404` (no `403`) para no revelar existencia de
  filas ajenas.
- Un odontólogo sin `professional_id` no filtra por `NULL` (que devolvería
  filas de nadie o de todos): se corta con `403`.
- C-03 no tiene `appointment` todavía; el contrato se prueba sobre tablas con
  `professional_id` existentes (`schedule_rule`, `professional`) y C-05 lo
  reutiliza sobre `appointment` sin cambios de firma. Se prohíbe en tests el
  patrón "traer todo y filtrar en Python": el test de aislamiento usa dos
  odontólogos con filas propias y comprueba que la sentencia generada incluye
  ambos predicados (`clinic_id` + `professional_id`) vía `str(stmt)`.

### 11. Tenant y bordes

- `clinic_id` sale **solo** del principal. Ningún schema acepta `clinic_id`;
  con `extra='forbid'` (regla 2) un body que lo incluya responde `422`.
- Login sin parámetro de tenant (DD-07: una DB por clínica). El lookup es por
  email en minúsculas; si devuelve exactamente un usuario activo, autentica;
  si devuelve cero o más de uno (DB de tests con varias clínicas), responde
  `401` genérico y audita `login_failed` con huella. En producción el caso
  ambiguo no existe; en tests evita autenticar contra la clínica equivocada.
- Todos los schemas de borde (`LoginRequest`, `RefreshResponse`,
  `ChangePasswordRequest`, `UserCreate`, `UserUpdate`, `PasswordReset`) usan
  `ConfigDict(extra="forbid")` y límites (`EmailStr`/`max_length=254`,
  `SecretStr` con `min_length=12, max_length=128`).
- `GET /api/users` es cursor-based (`app/common/pagination.CursorPage`),
  columnas explícitas y `ORDER BY created_at, id` (regla 8).

### 12. Redis como cliente compartido y modo de falla

`app/core/redis.py`: cliente `redis.asyncio` creado en el `lifespan` de
`create_app` (una conexión pool por proceso), expuesto por dependency
`get_redis()` y por `app.state.redis` para el worker. `main.py` y `/ready`
dejan de crear clientes por request.

- Si Redis no responde en un endpoint de auth → `503 auth_unavailable`
  (fail-closed). Fail-open (tratar como "sin sesión" o "permitir") convertiría
  una caída de infraestructura en bypass de autenticación. `/ready` ya
  devuelve 503 cuando Redis cae, y Compose/CI tienen healthcheck.
- `get_db` (hoy `NotImplementedError`) se cablea con `async_sessionmaker`
  sobre el engine async existente, con `expire_on_commit=False` y cierre por
  request; el engine se dispone en el `lifespan`.

### 13. Cookie de refresh por entorno

| Aspecto | `ENV=dev` | `ENV=prod` |
|---------|-----------|------------|
| Nombre | `refresh_token` | `__Host-refresh_token` |
| `HttpOnly` | `true` | `true` |
| `Secure` | `false` (HTTP local) | `true` |
| `SameSite` | `Lax` | `Lax` |
| `Path` | `/` | `/` (obligatorio con `__Host-`) |
| `Domain` | ausente | ausente |
| `Max-Age` | `JWT_REFRESH_DAYS × 86400` | ídem |

- `__Host-` exige `Secure`, `Path=/` y sin `Domain`; por eso no se usa
  `Path=/api/auth`.
- CSRF: el refresh sólo se acepta en `POST /auth/refresh` y `/auth/logout`,
  con `SameSite=Lax` (un `POST` cross-site no envía la cookie) y un chequeo de
  `Origin`: si viene y no está en `CORS_ORIGINS` → `403`; si no viene (curl,
  tests, futuros clientes nativos) se acepta, porque sin navegador no hay CSRF
  de cookie. No se agrega token CSRF en v1; queda anotado para C-14 si se
  habilita `SameSite=None`.
- `SameSite=Lax` exige que SPA y API sean **same-site** en producción
  (dominio único con proxy inverso). Si el deploy queda en dominios distintos,
  hay que pasar a `SameSite=None; Secure` + CSRF token (decisión abierta 9).

### 14. Migración 002 (`c03_auth_rbac`, revises `c02_core_models`)

- `user.password_changed_at timestamptz NULL`: `ADD COLUMN` nullable sin
  default es metadata-only en PG11+ (no reescribe la tabla, no toma lock
  largo), así que la regla 11 no exige `CONCURRENTLY` aquí; se documenta en el
  archivo de migración.
- Enum nativo `auth_event_type` (`login_success`, `login_failed`,
  `refresh_reuse_detected`, `logout`, `password_changed`, `user_created`,
  `user_updated`, `user_deactivated`, `role_changed`).
- Tabla `auth_event`: `id uuid PK`, `clinic_id uuid NOT NULL FK`,
  `user_id uuid NULL FK (clinic_id,id)` a `user`, `actor_user_id uuid NULL`
  ídem, `event auth_event_type NOT NULL`, `subject_hash text NULL`,
  `payload jsonb NOT NULL DEFAULT '{}'`,
  `CHECK (jsonb_typeof(payload) = 'array' OR jsonb_typeof(payload) =
  'object')`, `created_at timestamptz NOT NULL DEFAULT now()`.
  Índices `(clinic_id, created_at)`, `(user_id, created_at)`.
- Trigger `trg_auth_event_no_mutate` (`BEFORE UPDATE OR DELETE`) que lanza
  excepción: la inmutabilidad no depende de privilegios del rol de app, y se
  mantiene aunque un futuro `GRANT` amplíe permisos.
- `clinic_id` obligatorio + FK compuesta a `user(clinic_id, id)` (regla 4): un
  evento no puede apuntar a un usuario de otra clínica. Eventos sin usuario
  conocido (login fallido) usan `user_id NULL` + `subject_hash`.
- Regla 11: todas las tablas/índices del change se crean en la misma revisión
  sobre objetos nuevos o con `ADD COLUMN` metadata-only; se aplica la misma
  excepción acotada aprobada en C-02 y se deja el comentario en el archivo. No
  hay `ALTER TYPE` ni cambios de tipo.
- Downgrade: dropea trigger, índices, tabla, enum y columna en orden inverso.
  Los eventos se pierden (traza operativa, no dato de negocio): en producción
  se exporta antes de un downgrade.

### 15. Auditoría: qué se escribe y cuándo

- Mutaciones administrativas (`user_created`, `user_updated`,
  `user_deactivated`, `role_changed`, `password_changed`): insert en la
  **misma transacción** que la mutación (RN-GL-01 por analogía). Si el insert
  falla, la mutación no persiste.
- Intentos de autenticación (`login_success`, `login_failed`, `logout`,
  `refresh_reuse_detected`): escritura best-effort en la misma sesión pero
  capturando `SQLAlchemyError` y logueando un warning; **nunca** cambian la
  respuesta. Un fallo de auditoría no puede convertir un login válido en 500 ni
  filtrar si el usuario existía.
- `refresh_reuse_detected` se audita desde el `AuthService` (no desde el Lua,
  que no habla SQL) con `sid`, `uid`, `cid` y `gen` anterior; sin tokens.
- Payload acotado y sin PII: `{"reason": "bad_password"}`, `{"fields":
  ["role"]}`, `{"from_role": "recepcion", "to_role": "odontologo"}`; para
  sujeto desconocido, `subject_hash = sha256(email_normalizado)` (huella, no
  reversible por diccionario trivial sólo si el email es raro; se documenta
  como pseudonimización, no anonimato).
- No se registran IPs ni emails en claro en `auth_event`, logs de aplicación ni
  mensajes de error (regla 13).

### 16. Superficie HTTP

| Método y ruta | Auth | Éxito | Errores relevantes |
|---------------|------|-------|--------------------|
| `POST /api/auth/login` | pública + rate-limit | `200` access + cookie | `401` genérico, `422`, `429`, `503` |
| `POST /api/auth/refresh` | cookie + Origin | `200` access + cookie rotada | `401 refresh_reuse`/`invalid_refresh`, `429`, `503` |
| `POST /api/auth/logout` | access o cookie | `204` | `503` |
| `GET /api/auth/me` | access | `200` perfil propio | `401`, `503` |
| `POST /api/auth/change-password` | access + rate-limit | `200` | `401`, `422`, `429`, `503` |
| `GET /api/users` | `require_roles("admin")` | `200` página cursor | `401`, `403` |
| `POST /api/users` | `require_roles("admin")` | `201` | `401`, `403`, `409`, `422` |
| `PATCH /api/users/{id}` | `require_roles("admin")` | `200` | `401`, `403`, `404`, `409`, `422` |
| `POST /api/users/{id}/password-reset` | `require_roles("admin")` | `204` | `401`, `403`, `404`, `409`, `422` |

- `409` para la salvaguarda del último admin y para transiciones de rol
  inválidas sobre el propio usuario.
- Los stubs `GET /auth/ping` y `POST /auth/echo` se eliminan; el test de borde
  estricto de `tests/test_edges.py` se reapunta a `POST /api/auth/login`.

### 17. Estrategia de pruebas (TDD, infra real)

- Postgres real (fixture `db_session` de C-02) + **Redis real**: fixture
  `redis_client` que usa `REDIS_URL` con base 15 y `FLUSHDB` por test, más
  `redis_dependency_override` para inyectar ese cliente en la app. Sin mocks
  de Redis ni de DB en los invariantes de sesión (regla 9).
- App de test por `create_app(settings)` con `settings.JWT_SECRET` de 32+
  bytes y `dependency_overrides[get_db]`/`[get_redis]` apuntando a los
  fixtures. `httpx.ASGITransport` + `AsyncClient` con cookie jar (la cookie
  viaja de verdad entre login/refresh/logout).
- Reloj inyectable: `now()` en `app/core/jwt.py` recibe un callable
  (`clock`) que en tests se sustituye para emitir tokens ya vencidos sin
  `sleep`; nunca se espera en tiempo real.
- Casos obligatorios del change: login correcto, login inválido genérico,
  usuario inactivo, `429` por par y por IP, token expirado, firma/alg/`iss`/
  `aud` inválidos, refresh rotado + reuso (familia revocada), refresh
  concurrente (una sola rotación gana), logout idempotente y revocación
  inmediata, `require_roles` (401 vs 403), aislamiento de odontólogo con dos
  profesionales y **test cross-tenant** (A/B), contraseña provisoria
  bloqueante, cambio de contraseña que cierra la otra sesión, y auditoría
  inmutable (UPDATE/DELETE rechazados).
- Gates: `pytest -q` contra Postgres 15 + Redis 7, `ruff check backend`,
  `black --check backend`, `mypy backend` strict, y
  `openspec validate --strict`.

## Risks / Trade-offs

- [Riesgo] Redis pasa a ser dependencia dura del request autenticado → Mitigación:
  fail-closed con `503` explícito, `/ready` ya lo monitorea, healthcheck y
  Redis persistente en Compose; se documenta que una caída de Redis degrada la
  API a sólo lectura pública (booking llega en C-07 con su propio camino).
- [Trade-off] 2 round-trips extra por request (Redis + DB) → aceptado a <50
  concurrentes por tenant; mitigación con índices PK y pool; si el piloto
  muestra latencia, se cachea el principal por `sid` con TTL corto (no en v1).
- [Riesgo] Dos pestañas refrescando: la rotación estricta puede tratarse como
  reuso si el cliente no hace single-flight → Mitigación: contrato documentado
  para C-06 (`refresh` single-flight + reintento en `401`), y la ventana de
  gracia de 30 s queda como decisión abierta 2.
- [Trade-off] Sesión absoluta de 7 días: el personal reautentica semanalmente
  → aceptado; alternativa sliding descartada arriba.
- [Riesgo] argon2id 64 MiB × logins concurrentes puede inflar memoria (50
  logins simultáneos ≈ 3,2 GiB) → Mitigación: el rate-limit corta antes de
  hashear y el login no es un endpoint de alta frecuencia; parámetros finales
  se ajustan por tamaño de instancia en C-14.
- [Trade-off] Sin bloqueo de cuenta: un atacante puede seguir probando dentro
  del cupo (5/min por par) → aceptado para no habilitar DoS contra cuentas
  reales; la traza de `login_failed` permite detectar patrones.
- [Riesgo] `email` en el access token es PII dentro de un bearer token →
  aceptado por contrato de CHANGES y vida de 15 min; decisión abierta 8.
- [Trade-off] HS256 con secreto único: rotar `JWT_SECRET` invalida todas las
  sesiones → aceptado en v1 (rotación con `kid` y doble secreto es C-14).
- [Riesgo] `auth_event` crece sin poda → Mitigación: índice por fecha y nota
  para retención/partición en C-13/C-14; no se implementa ahora.
- [Trade-off] Excepción acotada a la regla 11 (misma que C-02) → aceptada sólo
  para objetos nuevos y `ADD COLUMN` nullable; queda escrita en la migración.

## Migration Plan

1. `alembic upgrade head` aplica `c03_auth_rbac` sobre `c02_core_models`
   (columna, enum, tabla, índices, trigger) en una transacción.
2. Orden de despliegue: migración → `api` (necesita `JWT_SECRET` ≥32 bytes y
   el nuevo cliente Redis) → `worker` sin cambios funcionales. No hay datos a
   migrar: las sesiones nacen vacías y todo el personal vuelve a loguearse.
3. CI: `upgrade → downgrade -1 → upgrade` + pytest contra Postgres 15 y Redis
   7 (`JWT_SECRET` de CI se alarga a 32+ bytes).
4. Rollback: `alembic downgrade c02_core_models` (pierde eventos de seguridad;
   exportar antes en producción) y redeploy de la imagen anterior, que ignora
   los endpoints nuevos. Las sesiones en Redis se pueden vaciar por prefijo
   `auth:*` sin tocar otros usos de Redis.

## Open Questions

- Parámetros argon2id definitivos por tamaño de instancia (C-14), sin cambiar
  contrato.
- Retención y exportación de `auth_event` (C-13/C-14): hoy sólo se escribe.
- Si el piloto pide "recordarme" más de 7 días, se evalúa sliding window con
  tope absoluto (no bloquea este diseño).

## Decisiones abiertas para revisión humana

> Governance **CRITICO**: ninguna se implementa sin OK explícito. Cada una
> trae recomendación; las tasks asumen la recomendación y marcan qué cambia si
> se rechaza.

1. **Access "stateless-lite" con chequeo de sesión por request** (decisión 1).
   **Recomendación: sí** — revocación inmediata para bajas/cambios de rol,
   costo de una lectura Redis + una query PK por request. *Si se rechaza*:
   access 100 % stateless, logout sólo borra refresh y la ventana de
   revocación pasa a ser ≤15 min; se ajusta el escenario "Access de una sesión
   cerrada deja de servir" y el test de revocación inmediata.
2. **Rotación estricta sin ventana de gracia** (decisión 3). **Recomendación:
   sí**, con contrato single-flight para la SPA de C-06. *Si se rechaza*: el
   Lua acepta `prev` durante 30 s emitiendo el refresh vigente (idempotente),
   y el escenario de reuso se acota a reusos fuera de esa ventana.
3. **Redis como dependencia dura con fail-closed `503`** (decisión 12).
   **Recomendación: sí** (ya está en Compose/CI y es requisito de la cola).
   *Si se rechaza*: sesiones en una tabla `auth_session` de Postgres
   (migración 002 crece: tabla + índices + limpieza por job), con el mismo
   contrato HTTP.
4. **`must_change_password` bloqueante + `POST /api/auth/change-password`**
   (enriquecimiento sobre el scope literal de CHANGES, necesario porque el
   seed de C-02 crea el admin con cambio obligatorio). **Recomendación: sí**,
   servidor-side. *Si se rechaza*: el flag sólo se informa en `/auth/me`, el
   admin del seed queda operativo sin cambiar la clave y se elimina el
   requirement "El cambio obligatorio de contraseña bloquea el resto de la
   API" y su task.
5. **Tabla `auth_event` + trigger de inmutabilidad** (decisión 14).
   **Recomendación: sí** — es la parte "tablas" que CHANGES pide en la
   migración 002 y deja traza consultable sin PII. *Si se rechaza*: la
   migración sólo agrega `password_changed_at`, la auditoría queda en logs
   estructurados y desaparecen `identity/auth-audit` y sus tasks.
6. **Política de contraseñas 12–128 sin composición y distinta de la actual**
   (la KB no la fija). **Recomendación: sí** (NIST SP 800-63B; el mínimo de 12
   es lo que hoy usa el proyecto en tests y seeds). *Si se rechaza*: se
   parametriza el mínimo en `Settings` y se ajustan los escenarios de política.
7. **Tope agregado por IP además del par IP+email** (decisión 8).
   **Recomendación: sí** (30/60 s; frena pulverización de emails). *Si se
   rechaza*: queda sólo 5/60 s por par y se elimina el escenario de
   pulverización.
8. **`email` como claim del access token** (lo exige CHANGES).
   **Recomendación: mantenerlo** (vida 15 min, lo consume la SPA sin llamar a
   `/auth/me`) y documentarlo como PII en bearer. *Si se rechaza*: se quita del
   claim y el contrato de `/auth/me` queda como única fuente.
9. **Cookie `__Host-` en producción y despliegue same-site** (decisión 13).
   **Recomendación: sí** con SPA y API bajo el mismo sitio vía proxy inverso;
   `/auth` público en `FRONTEND_PUBLIC_URL`. *Si se rechaza* (dominios
   separados): `SameSite=None; Secure` + token CSRF de doble envío, que suma
   un requirement y dos tasks.

## Resolución de las decisiones abiertas

**Decisiones aprobadas: 1–9, 2026-11-02 by user.**

Se aprueban las nueve recomendaciones tal como están escritas; ninguna se
reabre durante el apply:

1. Access **stateless-lite** con `sid` y verificación de `auth:sess:{sid}` en
   Redis por request (revocación inmediata).
2. Rotación **estricta, sin ventana de gracia**; el single-flight del refresh
   es responsabilidad de la SPA de C-06 (anotado en el README del backend y en
   el design de C-06).
3. Redis como dependencia dura del camino autenticado: falla → **503
   fail-closed** (`auth_unavailable`); se documenta la dependencia de
   disponibilidad en `backend/README.md`.
4. Se incluye el gate `must_change_password` y `POST
   /api/auth/change-password` (enriquecimiento necesario porque el admin del
   seed de C-02 nace con cambio obligatorio).
5. Se incluye la tabla append-only `auth_event` + trigger `BEFORE UPDATE OR
   DELETE`.
6. Política de contraseñas **12–128 caracteres**, sin reglas de composición y
   distinta de la actual.
7. Tope adicional por IP en login (**30/60 s**) además del par IP+email
   (5/60 s).
8. `email` se mantiene como claim del access token (contrato de CHANGES);
   trade-off PII en bearer ya documentado en *Risks / Trade-offs*.
9. Cookie `__Host-` en producción y despliegue **same-site** con allowlist de
   `Origin` en refresh/logout.

Nota de implementación (decisión 2): al no existir ventana de gracia, dos
refreshes concurrentes desde la misma pestaña pueden provocar
`refresh_reuse`. El contrato para C-06 exige refresh **single-flight** en la
SPA y un único reintento de login ante `401 refresh_reuse`; el backend no
relaja la rotación para acomodar clientes.
