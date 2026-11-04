# Backend — Sistema de Turnos Odontológico

FastAPI + SQLAlchemy 2.x async + Alembic sobre PostgreSQL 15. Los comandos se
corren desde la raíz del repo salvo que se indique otra cosa.

## Base de datos y migraciones

```bash
# DATABASE_URL acepta postgresql:// o postgresql+asyncpg:// (se fuerza asyncpg)
alembic upgrade head      # c01_base -> c02_core_models -> c03_auth_rbac -> c04_agenda_config
alembic downgrade c03_auth_rbac
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

### Revisión `c04_agenda_config` (C-04)

- `btree_gist` (extensión *trusted* PG13+) + constraint
  `ex_schedule_rule_no_overlap`: `EXCLUDE USING gist` sobre `(clinic_id,
  professional_id, chair_id, weekday)` con franja horaria (`tsrange` sobre una
  fecha fija, `[)`) y vigencia (`daterange(valid_from, valid_to, '[]')`)
  intersectadas, solo entre reglas `active`.
- **Excepción acotada a la regla 11**: PostgreSQL no admite `NOT VALID` ni
  `CONCURRENTLY` para un `EXCLUDE`; el `ADD CONSTRAINT` toma `ACCESS EXCLUSIVE`
  sobre `schedule_rule` (tabla de configuración, decenas de filas por clínica).
  Si ya hubiera reglas solapadas la migración **falla** (fail-fast): resolverlas
  antes de migrar. En producción, ventana de baja actividad.
- `clinic`: `max_overbookings_per_day` (2) y `waitlist_offer_ttl_hours` (4) como
  `ADD COLUMN … DEFAULT` metadata-only + `CHECK … NOT VALID` → `VALIDATE`.
- Tablas nuevas `block` (enum `block_reason`) y `agenda_config_event`
  (append-only por trigger `trg_agenda_config_event_no_mutate`).

⚠️ **El downgrade pierde bloqueos y auditoría de configuración**: `alembic
downgrade c03_auth_rbac` hace `DROP TABLE block` y `DROP TABLE
agenda_config_event`. Exportarlos antes con `COPY … TO STDOUT CSV HEADER` (igual
que `auth_event` en C-03).

## Configuración de agenda (C-04)

Todos los endpoints exigen access token; el tenant sale siempre del principal
(un `clinic_id` en el body es `422`). Listados con paginación por cursor
(`cursor`, `limit` ≤ 200, respuesta `{items, next_cursor}`).

| Recurso | admin | recepción | odontólogo |
|---|---|---|---|
| `GET/POST/PATCH /api/professionals[/{id}]` | CRUD | R | R (solo el propio) |
| `GET/POST/PATCH /api/chairs[/{id}]` | CRUD | R | R |
| `GET/POST/PATCH /api/schedules[/{id}]` | CRUD | R | R (propias) |
| `GET/POST /api/blocks[/{id}]` | CR | CR | CR (solo con su `professional_id`) |
| `PATCH/DELETE /api/blocks/{id}` | UD | — | — |
| `POST /api/blocks/closure` | C | — | — |
| `GET/PATCH /api/clinic/policies` | RU | R | — |

- **Bajas lógicas**: profesionales, sillones y reglas se desactivan con
  `PATCH active=false`; los bloqueos se retiran con `DELETE` (marca
  `removed_at`). Nunca hay borrado físico.
- **Bloqueos (RN-BL-03)**: terminado = inmutable; en curso = solo se mueve
  `ends_at` (a un instante no pasado); futuro = editable o retirable.
- **Feriado / cierre (RN-BL-04)**: `POST /api/blocks/closure` crea un bloqueo por
  cada sillón **activo en ese momento**. Un sillón dado de alta después no queda
  bloqueado: cargar el cierre después de dar de alta los sillones.
- **Auditoría**: cada mutación escribe `agenda_config_event` con actor y
  `{campo: [anterior, nuevo]}` en la misma transacción.
- **Bloqueo sobre turnos (RN-BL-02, C-05)**: ver [Turnos](#turnos-c-05). El
  rechazo de reservas online sobre recursos inactivos llega con C-07; el
  snapshot de pasos de recordatorio, con C-09.

| HTTP | `detail` | Cuándo |
|---|---|---|
| `404` | `not_found` | recurso de otra clínica o fuera del alcance del odontólogo |
| `403` | `forbidden_scope` | odontólogo bloqueando una agenda que no es la suya |
| `409` | `schedule_overlap` | regla solapada; incluye `conflicts: [ids]` |
| `409` | `block_immutable` | edición/retiro de un bloqueo iniciado o terminado |
| `422` | `invalid_resource` / `resource_inactive` | profesional o sillón ajeno, inexistente o inactivo |
| `422` | `block_in_past` / `invalid_block_range` | bloqueo que termina en el pasado o rango invertido |
| `422` | `invalid_schedule_rule` / `no_active_chairs` / `invalid_range` | regla inválida, cierre sin sillones, rango de listado invertido |

## Turnos (C-05)

Invariante central (regla dura 1): dos turnos **vigentes** (`pending`,
`confirmed`, `present`) que no son sobreturno nunca comparten profesional ni
sillón con rangos ocupados intersectados. La garantiza la base con
`ex_appointment_professional_no_overlap` y `ex_appointment_chair_no_overlap`
(`EXCLUDE USING gist` sobre `tstzrange(starts_at, occupied_until, '[)')`).
`occupied_until = ends_at + buffer_min` del profesional, **snapshot** al crear o
reprogramar: cambiar el buffer después no reacomoda turnos existentes.

| Endpoint | admin | recepción | odontólogo |
|---|---|---|---|
| `GET /api/appointments?from&to` (≤ 31 días, `professional_id`, `chair_id`, `status` repetible, `cursor`, `limit` ≤ 500) | R | R | R (solo los suyos, sin contacto del paciente) |
| `GET /api/appointments/{id}` | R | R | R (propio; ajeno → `404`) |
| `POST /api/appointments` | C | C | — |
| `PATCH /api/appointments/{id}` (reprogramar y/o `notes`) | U | U | — |
| `POST /api/appointments/{id}/transitions` (`{to, reason?, note?}`) | todas | todas | `present`/`absent`/`no_show` de los suyos |
| `GET /api/appointments/{id}/events` | R | — | — |
| `GET /api/patients?q=` · `POST /api/patients` | RC | RC | — |

No existe `DELETE /api/appointments/{id}` (`405`): la única baja es cancelar con
motivo (regla 7).

- **Alta**: recepción nace `confirmed`; el servicio con `origin=online` (C-07)
  nace `pending` y nunca es sobreturno (también por `CHECK`). Duración por
  defecto = `slot_duration_min` de la regla que contiene el inicio. El turno
  debe caer completo en una regla activa y vigente del par profesional-sillón,
  en la zona de la clínica; no puede caer en un bloqueo; no se aceptan días
  locales pasados (hoy sí, para registrar a quien ya llegó). Datetimes sin zona
  → `422`.
- **Lock por recurso**: alta, reprogramación y bloqueos toman `SELECT … FOR
  UPDATE` sobre `professional` y luego `chair` (ordenados por id). Serializa lo
  que el EXCLUDE no cubre (bloqueos, sobreturnos, tope diario). **Todo camino
  que escriba turnos debe pasar por `AppointmentsService.book`** (contrato C-07).
- **Sobreturno (RN-SB)**: `is_overbooking=true` + `overbooking_reason`, solo
  admin/recepción y solo si el horario colisiona. Queda fuera del EXCLUDE; un
  turno normal tampoco puede caer sobre un sobreturno vigente. Tope diario por
  profesional (`max_overbookings_per_day`): recepción `409`, el admin lo excede
  y el evento registra `over_limit=true`.
- **Estados**: `pending→confirmed`, `confirmed→present` (desde el día local del
  turno), `confirmed→absent|no_show` (desde `starts_at`),
  `pending|confirmed→cancelled` (antes de `starts_at`, motivo del catálogo
  `paciente|profesional|clinica|bloqueo|otro`, nota ≤ 500). `absent` = no vino
  pero avisó (tarde o con justificación); `no_show` = no vino y no avisó.
  `cancelled`, `absent` y `no_show` son terminales y liberan el hueco. El evento
  de cancelación indica `late` según `cancellation_window_hours`.
- **Bloqueo sobre turnos (RN-BL-02)**: `POST/PATCH /api/blocks` y
  `POST /api/blocks/closure` aceptan `cancel_appointments: [{appointment_id,
  reason, note?}]`. Si el rango pisa turnos `pending/confirmed` del profesional
  o del sillón, la lista debe cubrirlos **exactamente**: faltantes → `409
  block_conflicts`, sobrantes → `422 invalid_cancellation`. Cancelación y
  bloqueo van en la misma transacción. Cancelar exige admin o recepción.
- **Auditoría**: `appointment_event` append-only (trigger
  `trg_appointment_event_no_mutate`), escrito en la misma transacción que cada
  mutación, con actor, estados y antes/después. Nunca nombre, teléfono ni email
  del paciente. La agenda lee `appointment`; los reportes (C-13) leen eventos.
- **Pacientes**: búsqueda por teléfono normalizado (E.164) o por similitud de
  nombre (trigram, máximo 20); alta rápida con `409 patient_duplicate` si
  coinciden teléfono y nombre normalizado (familias con otro nombre se aceptan).
  Los errores de teléfono/email no incluyen el valor enviado.

| HTTP | `detail` | Cuándo |
|---|---|---|
| `409` | `slot_taken` | colisión; `conflicts: [ids]` + `alternatives: [{starts_at, ends_at, professional_id, chair_id}]` (≤ 3, 14 días) |
| `409` | `slot_blocked` | el turno pisa un bloqueo; `blocks: [ids]` |
| `409` | `resource_inactive` | profesional o sillón con `active=false` |
| `409` | `overbooking_limit` | recepción supera el tope diario de sobreturnos |
| `409` | `invalid_transition` | transición fuera de la tabla, o reprogramar un turno no vigente |
| `409` | `appointment_started` / `attendance_too_early` | guardas temporales de cancelar/confirmar/reprogramar o de asistencia |
| `409` | `appointment_changed` | el turno se movió en paralelo mientras se esperaba el lock |
| `409` | `block_conflicts` | bloqueo que pisa turnos sin resolver; `appointments: [ids]` |
| `409` | `patient_duplicate` | mismo teléfono y nombre; `patient_id` |
| `422` | `outside_schedule` / `appointment_in_past` / `overbooking_not_needed` | fuera de plantilla, día pasado, sobreturno sin colisión |
| `422` | `invalid_patient` / `invalid_resource` | paciente, profesional o sillón ajeno o inexistente (sin revelar cuál) |
| `422` | `invalid_range` | rango de listado invertido o > 31 días |
| `422` | `query_too_short` / `query_too_long` / `invalid_phone` / `invalid_email` / `contact_required` | búsqueda y alta de pacientes |
| `422` | `invalid_cancellation` | `cancel_appointments` con turnos no afectados o repetidos |

### Revisión `c05_appointments_core` (C-05)

- `patient`: UNIQUE `uq_patient_id_clinic_id` para la FK compuesta desde
  `appointment` (regla 4), construido con `CREATE UNIQUE INDEX CONCURRENTLY`
  fuera de transacción y promovido con `ADD CONSTRAINT … USING INDEX` (regla 11).
- Tablas nuevas `appointment` (2 EXCLUDE, CHECKs de coherencia, índices) y
  `appointment_event` (trigger append-only); enums `appointment_status`,
  `appointment_origin`, `cancellation_reason`, `appointment_event_type`,
  `actor_type`.
- Inmutabilidad de eventos: hoy la garantiza el trigger; un rol `app_writer`
  separado del owner llega con C-14 (la app se conecta como owner).

⚠️ **El downgrade pierde todos los turnos y su auditoría**: `alembic downgrade
c04_agenda_config` hace `DROP TABLE appointment_event` y `DROP TABLE
appointment`. Exportarlos antes con `COPY … TO STDOUT CSV HEADER`.

## Perfil de clínica y fusión de pacientes (C-06)

| Endpoint | admin | recepción | odontólogo |
|---|---|---|---|
| `GET /api/clinic` → `{id, name, timezone}` | R | R | R |
| `GET /api/patients/{id}` (incluye archivados: `archived_at`, `merged_into_patient_id`, `appointments_count`) | R | R | — |
| `POST /api/patients/{id}/merge` `{into_patient_id}` | C | C | — |

- **Zona horaria**: la SPA dibuja la agenda con `timezone` de `GET /api/clinic`,
  nunca con la del navegador.
- **Fusión** (Flujo 4, caso de error): el paciente de la ruta es el duplicado;
  `into_patient_id`, el que se conserva. En una transacción y con `FOR UPDATE`
  sobre ambos: completa los contactos vacíos del conservado (`phone_e164`,
  `email`, `dni`; `whatsapp_opt_in` no se hereda), reasigna los turnos del
  duplicado de **todos** los estados con un evento `updated` por turno
  (`{patient_id: [anterior, nuevo], reason: "patient_merge", merge_id}`),
  archiva el duplicado con `merged_into_patient_id` y escribe `patient_merge`
  (append-only, sin datos personales). Respuesta: `{merge_id,
  source_patient_id, target_patient_id, moved_appointments, appointment_ids,
  filled_fields}`. Mismo paciente, archivado, ya fusionado, de otra clínica o
  inexistente → `422 invalid_merge` (no revela cuál). Irreversible.
- **Carrera con el alta de turnos**: `AppointmentsService` lee al paciente con
  `FOR SHARE`; un alta para el duplicado espera a la fusión y responde `422
  invalid_patient`. **Contrato C-09/C-12**: jobs de recordatorio y lista de
  espera del duplicado se reasignan o cancelan en la misma transacción.

### Revisión `c06_patient_merge` (C-06)

- `patient.merged_into_patient_id` (`ADD COLUMN` nullable: metadata-only), FK
  compuesta `(merged_into_patient_id, clinic_id) → patient(id, clinic_id)` y
  CHECKs (`<> id`, fusionado ⇒ archivado) con `NOT VALID` → `VALIDATE` (regla 11).
- Tabla nueva `patient_merge` con trigger `trg_patient_merge_no_mutate`.

⚠️ **El downgrade pierde la auditoría de fusiones**: `alembic downgrade
c05_appointments_core` hace `DROP TABLE patient_merge` y elimina el puntero; los
fusionados quedan archivados pero sin saber en quién se fusionaron. Exportar
antes con `COPY … TO STDOUT CSV HEADER`.

## Reserva pública (C-07)

Superficie anónima, sin `Principal`: la clínica se resuelve **solo por slug**
(`clinic.booking_enabled=true`) y todo se filtra por ese `clinic_id`.

| Método | Ruta | Cupo Redis (clave) |
|---|---|---|
| `GET` | `/api/booking/{slug}` | lecturas por IP (`rl:booking:read:ip:{ip}`) |
| `GET` | `/api/booking/{slug}/availability?professional_id&from&to` | lecturas por IP |
| `POST` | `/api/booking/{slug}/appointments` | reservas por IP + por clínica |

- **Catálogo**: nombre, zona horaria y profesionales reservables (solo `id` y
  `display_name`). Reservable = activo, `booking_enabled`, con regla semanal
  activa no vencida sobre un sillón activo.
- **Disponibilidad**: huecos `{starts_at, ends_at, professional_id}`, unión por
  sillón de `suggest_slots` (plantilla − bloqueos − turnos vigentes − buffer, desde
  ahora). Sin sillones, ids de turnos, estados ni conteos. Rango ≤ 14 días y
  `to` dentro del horizonte (`PUBLIC_BOOKING_HORIZON_DAYS`, default 60).
- **Reserva**: cuerpo `extra='forbid'` con `professional_id`, `starts_at` (con zona)
  y `patient{full_name, phone?, email?, whatsapp_opt_in?, privacy_accepted}`. El
  servidor elige el sillón (orden de id) y escribe solo vía
  `AppointmentsService.book(origin=ONLINE)`: turno `pending`, sin sobreturno, con la
  duración de la regla. Respuesta `201 {starts_at, ends_at, professional_id, channel,
  warnings, manage_url}` con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`.
- **Token de gestión**: `secrets.token_urlsafe(32)` (256 bits), devuelto **una sola
  vez** en `manage_url`; la base guarda solo `sha256(token)` (`appointment.manage_token_hash`,
  `bytea(32)`, único). Nunca va a eventos ni logs. TTL y rotación: C-08.
- **Paciente**: match por teléfono E.164 + nombre normalizado (RN-ON-05); sin
  teléfono válido siempre se crea uno nuevo; un paciente existente nunca pierde ni
  cambia nombre/contactos y su opt-in de WhatsApp solo pasa de `false` a `true`.
- **Auditoría**: evento `created` con `actor_type=patient_token`, `origin=online` y
  `channel`, sin datos personales.

### Códigos de error públicos

| Código | Cuándo |
|---|---|
| `404 booking_not_found` | slug inexistente o reserva deshabilitada (cuerpo idéntico) |
| `404 professional_not_found` | profesional ajeno, inactivo, deshabilitado o sin regla |
| `422 invalid_range` | `to <= from`, > 14 días o más allá del horizonte |
| `422 contact_required` | sin teléfono válido ni email válido |
| `422 whatsapp_opt_in_required` | teléfono válido sin elegir/aceptar WhatsApp y sin email |
| `422 privacy_consent_required` | `privacy_accepted=false` |
| `422 slot_not_offered` / `appointment_in_past` | inicio fuera de grilla/horizonte / no futuro |
| `422 invalid_request` | campo no permitido o tipo inválido (solo nombres de campo, sin valores) |
| `409 slot_taken` | hueco ocupado: `{alternatives:[{starts_at, ends_at, professional_id}]}` (≤ 3, sin `conflicts` ni sillón) |
| `429 rate_limited` | cupo agotado, con `Retry-After` |
| `503 booking_unavailable` | Redis caído (falla cerrada) |
| `403 bot_check_failed` | el `BotGuard` configurado rechazó la solicitud |

Canal según D5: teléfono válido + opt-in → `whatsapp`; opt-in rechazado o teléfono
inválido con email válido → `email` con aviso (`whatsapp_declined_email_channel` /
`phone_invalid_email_channel`; un teléfono inválido se descarta).

### Cupos y settings

`PUBLIC_BOOKING_IP_RATE_LIMIT` (`10/3600s`, se consume **antes** de validar el cuerpo:
un 422 también gasta), `PUBLIC_BOOKING_SLUG_RATE_LIMIT` (`300/3600s`, solo con slug
resuelto), `PUBLIC_BOOKING_READ_RATE_LIMIT` (`120/60s`, antes de resolver el slug),
`PUBLIC_BOOKING_HORIZON_DAYS` (60), `PRIVACY_POLICY_VERSION` y `BOT_GUARD` (`noop`).
Formato `"<intentos>/<segundos>s"`, validado al arrancar. `BOOKING_RATE_LIMIT`
(`30/minute`) sigue siendo el tope **global en memoria** de C-01 y no se toca. La IP
es la que resuelve uvicorn (`--proxy-headers` + `FORWARDED_ALLOW_IPS`); la app no
parsea `X-Forwarded-For`.

### Sin CAPTCHA en v1 (decisión 2026-11-04)

La protección es rate-limit en Redis + anti-enumeración. `BotGuard`
(`app/modules/booking_public/guard.py`) es el punto de extensión: un futuro
Turnstile/reCAPTCHA lee su token de `X-Bot-Token` y solo cambia la implementación que
devuelve `get_bot_guard`, sin tocar el schema ni el router.

### Revisión `c07_booking_public` (C-07)

- `appointment.manage_token_hash` (`bytea`, `ADD COLUMN` nullable: metadata-only),
  CHECKs (largo 32; turno `online` ⇒ hash) `NOT VALID` → `VALIDATE`, e índice único
  parcial `uq_appointment_manage_token_hash` `CONCURRENTLY` (regla 11).

⚠️ **El downgrade pierde los hashes de los tokens**: `alembic downgrade
c13_event_slot` quita la columna y el índice; los links de gestión ya emitidos dejan
de servir. Deshabilitar `clinic.booking_enabled` corta la superficie pública sin
redeploy.

## Seed del tenant inicial

Crea una clínica, un admin con cambio de contraseña obligatorio, el sillón
"Sillón 1" y un profesional de ejemplo inactivo. Es idempotente por slug y no
imprime secretos. Con `SEED_BOOKING_DEMO=true` (opcional, C-07) la clínica nueva queda
con reserva pública habilitada, el profesional activo y una plantilla lunes-viernes
09:00-13:00 de 30 min (clínica demo / E2E); sin el flag no queda pública. Se ejecuta
desde `backend/`:

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
