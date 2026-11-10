# Backend — Sistema de Turnos Odontológico

FastAPI + SQLAlchemy 2.x async + Alembic sobre PostgreSQL 15. Los comandos se
corren desde la raíz del repo salvo que se indique otra cosa.

## Base de datos y migraciones

> **Con Docker (dev) no hace falta correr nada a mano**: `.\dev.ps1` (raíz del repo) levanta
> el stack y el servicio `migrate` aplica `alembic upgrade head` y el seed idempotente de la
> clínica demo antes de que arranquen `api` y `worker`. Después de traer un change con
> migraciones nuevas alcanza con volver a correr `.\dev.ps1`; `.\dev.ps1 reset` borra los
> datos de dev y arranca de cero. Los comandos de abajo son para correr fuera de Docker.

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

## Gestión por token (C-08)

Superficie anónima, sin `Principal` ni sesión: el turno y su clínica se resuelven
**solo por el token** del link `/g/{token}` que emitió la reserva (C-07), y todo se
filtra por el `clinic_id` del turno.

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/api/manage/{token}` | vista de gestión |
| `GET` | `/api/manage/{token}/availability?from&to` | huecos del mismo profesional para reprogramar |
| `PATCH` | `/api/manage/{token}` | `{"action": "confirm"}` \| `{"action": "cancel", "reason"?, "note"?}` \| `{"action": "reschedule", "starts_at"}` |

- **Resolución**: formato `^[A-Za-z0-9_-]{43}$` (si no, 404 sin tocar la base) →
  `sha256(token)` → igualdad contra `uq_appointment_manage_token_hash`. El token
  **nunca** se compara ni se guarda en claro; no "optimizar" a comparar el token.
- **Vigencia**: `expires_at = ends_at + MANAGE_TOKEN_TTL_H` (72 h, calculado en cada
  request, sin columna). Antes de `starts_at` el link permite acciones; entre
  `starts_at` y `expires_at` es solo lectura; después, `410`. Cambiar el setting
  aplica a links ya emitidos.
- **Vista mínima**: clínica (nombre, teléfono, zona, slug), nombre de pila del
  paciente, inicio/fin en la zona de la clínica, profesional, estado, ventana,
  `actions{can_confirm, can_cancel, can_reschedule, blocked_reason}` y el catálogo
  de motivos. Sin ids de turno/paciente/sillón/profesional ni contacto del paciente.
- **Confirmar**: `pending → confirmed` con `actor_type=patient_token`.
- **Cancelar**: solo `pending|confirmed`, antes del inicio y con al menos
  `cancellation_window_hours` de anticipación. La causa guardada es siempre
  `paciente` (C-13 no cambia); el motivo fino va en el evento como `patient_reason`;
  la nota (≤ 200) se guarda en `cancellation_note` solo con `otro` y **nunca** entra
  al evento, a logs ni a exportaciones.
- **Reprogramar**: mismo profesional, mismo `appointment_id`, misma duración, solo a
  inicios de la grilla y dentro del horizonte; un intento por sillón candidato en un
  savepoint y el `EXCLUDE` como barrera final. Conserva origen y hash del token.
  **No se rota el token** (decisión 2026-11-05; ver `knowledge-base/10_preguntas_abiertas.md`).
- **Idempotencia por estado**: repetir una acción ya aplicada responde 200 y escribe
  un evento `updated` con `{idempotent_replay: true, action}`; nunca un segundo
  `confirmed`/`cancelled`/`rescheduled`.
- **Orden de locks**: profesional → sillones → turno, igual que recepción (lo
  contrario produce deadlock con una reprogramación simultánea de recepción).
- **Recordatorios**: `ReminderInvalidator` (`app/modules/reminders/invalidation.py`)
  se invoca dentro del savepoint de cada mutación (no en los replays); v1 es no-op y
  C-09 reemplaza `get_reminder_invalidator`.
- **Cabeceras**: `Cache-Control: no-store` y `Referrer-Policy: no-referrer` en todas
  las respuestas, también en los errores.

### Códigos de error de gestión

| Código | Cuándo |
|---|---|
| `404 manage_link_not_found` | token malformado o desconocido (cuerpo idéntico) |
| `410 manage_link_expired` | pasó `ends_at + TTL`; trae `clinic{name, phone}` para la pantalla de contacto |
| `409 invalid_transition` | estado no operable (p. ej. confirmar un cancelado, cancelar un presente) |
| `409 appointment_started` | confirmar un turno que ya empezó |
| `422 appointment_in_past` | cancelar un turno ya iniciado, o reprogramar a un inicio no futuro |
| `409 cancellation_window_closed` | cancelar o reprogramar con menos horas que la ventana (derivar a la clínica) |
| `422 slot_not_offered` | inicio fuera de grilla/horizonte, o profesional ya no reservable online |
| `409 slot_taken` | hueco ocupado: `{alternatives:[{starts_at, ends_at}]}` (≤ 3, sin `conflicts`, sillón ni profesional) |
| `409 appointment_changed` | recepción movió el turno mientras se procesaba la acción |
| `422 invalid_range` | disponibilidad con `to <= from`, > 14 días o más allá del horizonte |
| `422 invalid_request` | cuerpo inválido: solo nombres de campo, nunca valores (la nota no se ecoa) |
| `429 rate_limited` | cupo agotado, con `Retry-After` |
| `503 manage_unavailable` | Redis caído (falla cerrada) |

### Cupos de gestión

`MANAGE_READ_IP_RATE_LIMIT` (`120/60s`) y `MANAGE_WRITE_IP_RATE_LIMIT` (`30/60s`) se
consumen antes de resolver el token (frenan el barrido); `MANAGE_READ_TOKEN_RATE_LIMIT`
(`60/60s`) y `MANAGE_WRITE_TOKEN_RATE_LIMIT` (`10/60s`) usan el **SHA-256** del token
como clave (Redis nunca ve el token) y solo se consumen con un token bien formado.
Las escrituras se consumen antes de validar el cuerpo (un 422 gasta).

### Transporte del token y access log (requisito de despliegue)

El token va en el **path** (no en query string ni header): es el contrato del link
`/g/{token}` ya emitido. La app no loguea el path ni el token, pero el **access log**
de uvicorn y de nginx sí registraría la URL: en producción hay que **redactar
`/g/` y `/api/manage/`** con un formato de log propio (p. ej. en nginx un `map` que
reemplace el segmento del token por `***`, o deshabilitar el access log de esas
`location`), y el healthcheck del despliegue no debe tocar esas rutas.

### Teléfono de contacto de la clínica

`clinic.contact_phone` (E.164, opcional) se edita con `PATCH /api/clinic/policies`
(`contact_phone`, solo admin; se normaliza con la región AR; inválido o `null` → 422).
Lo muestran las pantallas que derivan a la clínica (ventana cerrada, link vencido).
El seed lo carga con un número ficticio solo al crear la clínica.

### Revisión `c08_manage_token` (C-08)

`ADD COLUMN contact_phone text` (nullable, sin default: metadata-only) y CHECK de
largo `NOT VALID` → `VALIDATE` (regla 11). `appointment` no cambia. El downgrade
quita la columna y pierde el teléfono cargado.

## Motor de recordatorios (C-09)

Persistente sobre Postgres: `reminder_job` (clave única `(appointment_id, step, channel)`),
`delivery_event` y `consent` append-only, `notification_template` por clínica. Todas llevan
`clinic_id` y FKs compuestas. El diseño completo está en
`openspec/changes/c-09-motor-recordatorios/design.md`.

### Plantillas por defecto

El seed (`python -m app.seed`) y la migración `c09_reminder_engine` cargan, para cada clínica, las
plantillas de **alta de turno + 72 h + 24 h + 3 h**, en WhatsApp y en email (8 filas, `es_AR`,
activas). Los textos viven en una sola fuente, `app/modules/reminders/templates.py`, y solo usan
las variables `{{nombre}} {{clinica}} {{fecha}} {{hora}} {{profesional}} {{link}}`: nunca datos
personales. Los nombres de WhatsApp (`turno_creado_v1`, `recordatorio_72h_v1`,
`recordatorio_24h_v1`, `recordatorio_3h_v1`) son placeholders hasta que Meta apruebe los reales
(C-10); `{{direccion}}` queda fuera hasta que la clínica guarde su dirección.

Reejecutar el seed **repone** una plantilla faltante y **no pisa** el texto ni el estado que el
admin haya editado (`ON CONFLICT DO NOTHING`).

```bash
SEED_CLINIC_SLUG=clinica-demo SEED_CLINIC_NAME="Clínica Demo Ficticia" SEED_ADMIN_EMAIL=admin@example.com SEED_ADMIN_PASSWORD='<clave provisoria>' python -m app.seed
```

### Consentimiento

`ConsentService` (`app/modules/reminders/consent.py`) es el **único** escritor de `consent` y de
`patient.whatsapp_opt_in`: ambos cambian en la misma transacción. Sin opt-in vigente no se envía
nada por WhatsApp; una baja salta (`skipped`, `no_consent`) los jobs pendientes del paciente y
canal, y un alta posterior no los revive. Las fuentes son `booking`, `reception`,
`whatsapp_reply` (C-10) y `legacy` (el backfill de la migración, porque el origen real de un opt-in
previo no se conoce).

### Link de gestión firmado (`MANAGE_LINK_SECRET`)

Para escribir `{{link}}` en un mensaje el motor necesita el token en claro, pero la base solo
guarda el SHA-256 del token aleatorio de C-07 y un turno de recepción no tiene token. Por eso
`GET/PATCH /api/manage/{token}` acepta un **segundo formato**, firmado y sin estado:

```
token = "v1." + base64url( appointment_id[16 bytes] ‖ HMAC-SHA256(MANAGE_LINK_SECRET,
                            "manage-link/v1" ‖ appointment_id)[:16] )      # 46 caracteres
link  = {FRONTEND_PUBLIC_URL}/g/{token}
```

- Es estable: todos los mensajes de un turno llevan el mismo link. Los tokens aleatorios ya
  emitidos siguen valiendo; nada se rota.
- Mismas guardas que C-08: TTL `ends_at + MANAGE_TOKEN_TTL_H`, vista mínima, ventana de
  cancelación, `404 manage_link_not_found` uniforme (firma inválida = token desconocido) y cupo
  por `sha256(token)`. El token no se loguea (ver "Transporte del token").
- `MANAGE_LINK_SECRET`: ≥ 32 bytes (`openssl rand -hex 32`), obligatorio salvo `ENV=dev`, donde
  vacío deshabilita los links firmados. **Rotarlo invalida todos los links firmados vivos**
  (los mensajes ya enviados dejan de abrir): es la palanca de emergencia, no una operación de
  rutina. Un link firmado no se puede revocar suelto; el límite es el TTL absoluto.

### Programación de los recordatorios

Al crear un turno se programan el **alta** (`created`, sale al instante) y un paso por cada entrada
de `clinic.reminder_steps` (por defecto 72, 24 y 3 h por WhatsApp), con `scheduled_for = starts_at −
offset`. Solo se programan pasos cuya hora todavía no pasó (un turno creado 2 h antes solo recibe el
alta). La programación es **estado-basada** (`reconcile`): se recalcula contra el estado actual del
turno, así que es idempotente y la dispara el núcleo de escritura de turnos (`book`,
`_reschedule`, `apply_transition`) en su misma transacción, sea cual sea el camino (recepción,
reserva pública, bloqueo de agenda, link de gestión).

- **Reprogramar** recalcula los pendientes; los pasos ya enviados no se tocan ni se reenvían.
- **Cancelar** (o registrar asistencia) cancela los pendientes.
- **Confirmar** un turno online cancela solo los pasos que piden confirmar (alta, 72 h y 24 h); el
  de 3 h sigue. Un turno de recepción nace confirmado y recibe todos los pasos.

### Worker y proveedores

El worker (`python -m app.worker.entrypoint`, ARQ) corre un tick por minuto: recupera leases
vencidos, reclama hasta `REMINDER_BATCH_SIZE` jobs con `FOR UPDATE SKIP LOCKED`, valida cada uno
(turno vigente y no iniciado, horario vigente, consentimiento, destinatario, plantilla activa),
envía **fuera** de la transacción y registra el resultado. Los reintentos esperan 5 y 30 minutos
(`REMINDER_BACKOFF_MINUTES`); al tercer fallo el job queda `failed` y, si el paciente tiene email y
no se dio de baja de ese canal, se crea el job de email del mismo paso. Cada intento, envío, salto,
cancelación y escalado queda en `delivery_event` (sin datos personales).

| Variable | Valores | Efecto |
|---|---|---|
| `REMINDER_WHATSAPP_PROVIDER` | `disabled` (default), `fake`, `meta` | `disabled`: el worker no reclama jobs de WhatsApp ni los marca enviados. `meta`: Cloud API (ver «Canal WhatsApp (C-10)»). |
| `REMINDER_EMAIL_PROVIDER` | `disabled` (default), `smtp`, `fake` | `smtp` usa `EMAIL_HOST/PORT/USER/PASSWORD/FROM`: puerto 465 = TLS implícito, 587 = STARTTLS, otro = sin cifrar (solo desarrollo). |
| `REMINDER_MAX_ATTEMPTS` · `REMINDER_BACKOFF_MINUTES` | `3` · `5,30,120` | Intentos totales y espera tras cada fallo. |
| `REMINDER_LEASE_MINUTES` · `REMINDER_TICK_BUDGET_S` · `REMINDER_BATCH_SIZE` | `5` · `50` · `100` | Plazo del lease, presupuesto de tiempo del tick y tamaño del lote. |
| `REMINDER_COST_WHATSAPP_MICROS` · `REMINDER_COST_EMAIL_MICROS` | `0` | Costo estimado por mensaje en USD × 10⁻⁶, copiado a `reminder_job.cost_micros` y, desde C-10, al evento `sent` (`payload.cost_micros`), que es lo que suma el reporte (RN-WA-05). |

Para probar el flujo en desarrollo sin proveedor real, poné `REMINDER_WHATSAPP_PROVIDER=fake` (los
envíos se descartan y solo se loguean metadatos) o `REMINDER_EMAIL_PROVIDER=smtp` apuntando a un
servidor local de captura. Con ambos en `disabled` el motor programa pero no envía: se puede
desplegar sin riesgo.

Garantías y límites: el envío es **al menos una vez** (si el worker muere entre el envío y el
registro del resultado, el lease reenvía); un job de un turno ya iniciado se salta, nunca se
marca `sent`; una cancelación que llega entre el re-chequeo y el envío puede dejar salir un
mensaje (ventana de milisegundos). Un paso ya enviado no se reenvía al reprogramar (hace falta una
plantilla "turno reprogramado"; quedó fuera de C-10 y no tiene change asignado). Los pasos salen a `starts_at − offset` aunque
caigan de madrugada: no hay ventana de silencio nocturno todavía.

### Revisión `c09_reminder_engine` (C-09)

Tablas nuevas y vacías (`notification_template`, `reminder_job`, `delivery_event`, `consent`): sus
índices, FKs y CHECKs se crean junto con la tabla, sin `CONCURRENTLY` ni `NOT VALID` (regla 11).
Carga el consentimiento previo (`legacy`) y las plantillas de las clínicas existentes. Downgrade:
`alembic downgrade c08_manage_token` elimina las cuatro tablas y sus enums; `patient.whatsapp_opt_in`
no se toca.

## Canal WhatsApp (C-10)

Envío por la WhatsApp Cloud API de Meta y webhook de respuestas. Diseño completo:
`openspec/changes/c-10-whatsapp-webhook/design.md` (o su copia archivada).

### Configuración

| Variable | Uso |
|---|---|
| `REMINDER_WHATSAPP_PROVIDER=meta` | Activa el envío real. Exige las cuatro siguientes (el arranque falla nombrando la que falta, sin mostrar valores). |
| `WHATSAPP_TOKEN` | Token de acceso de sistema de Meta (secreto; solo viaja en `Authorization`). |
| `META_APP_SECRET` | Secreto de la app: firma `X-Hub-Signature-256` del webhook (secreto). Vacío → todo POST al webhook es 401. |
| `META_PHONE_NUMBER_ID` | `phone_number_id` del **número compartido**, usado por las clínicas sin número propio. |
| `META_VERIFY_TOKEN` | Token del handshake de suscripción. Vacío → todo GET al webhook es 403. |
| `META_API_VERSION` · `META_GRAPH_BASE_URL` | `v19.0` · `https://graph.facebook.com`. |
| `WHATSAPP_HTTP_TIMEOUT_S` · `WHATSAPP_WEBHOOK_MAX_BYTES` · `WHATSAPP_REPLY_MAX_ATTEMPTS` | `10` · `1048576` (413 si se excede) · `3`. |

### Número propio o compartido

`clinic.whatsapp_phone_number_id` (solo dígitos, único) es el número propio de la clínica; vacío
= usa el compartido. La decisión comercial (quién paga el Business Manager y el número) sigue
abierta en `knowledge-base/10_preguntas_abiertas.md`; el sistema soporta ambos. No hay UI para
cargarlo todavía:

```sql
UPDATE clinic SET whatsapp_phone_number_id = '<phone_number_id de Meta>' WHERE slug = '<slug>';
```

### Alta del webhook en Meta

1. En la app de Meta → WhatsApp → Configuración → Webhook: URL
   `https://<api>/webhooks/whatsapp`, token de verificación = `META_VERIFY_TOKEN`.
2. Suscribir el campo `messages` (trae mensajes entrantes y estados de entrega).
3. El path está fuera del rate-limit global: la firma es la autenticación.

Respuestas: 200 si se procesó o si el payload firmado no tiene la estructura esperada (se
registra `webhook_payload_invalid`, para que Meta no reintente); 401 sin firma válida; 413 si
excede el tope; 500 si un evento falló por un error inesperado (Meta reintenta y la
deduplicación descarta lo ya aplicado). **Excepción a la regla 2**: el payload de Meta se parsea
con `extra='ignore'` y solo después de verificar la firma (ver `AGENTS.md`).

### Plantillas a aprobar en Meta

Categoría `utility`, idioma `es_AR`, parámetros **posicionales** en este orden y botones de
respuesta rápida con estos payloads (el catálogo vive en `app/modules/reminders/templates.py`; un
test verifica orden y botones):

| Nombre | Paso | Cuerpo | Parámetros | Botones (payload) |
|---|---|---|---|---|
| `turno_creado_v1` | `created` | Hola {{1}}, tu turno en {{2}} es el {{3}} a las {{4}} con {{5}}. Confirmalo acá: {{6}} | {{1}} nombre, {{2}} clinica, {{3}} fecha, {{4}} hora, {{5}} profesional, {{6}} link | `confirm` · `change` |
| `recordatorio_72h_v1` | `t_72h` | Hola {{1}}, te recordamos tu turno del {{2}} {{3}} con {{4}}. ¿Confirmás? {{5}} | {{1}} nombre, {{2}} fecha, {{3}} hora, {{4}} profesional, {{5}} link | `confirm` · `change` |
| `recordatorio_24h_v1` | `t_24h` | Mañana {{1}} tenés turno con {{2}} en {{3}}. Respondé SÍ para confirmar o tocá para cambiar: {{4}} | {{1}} hora, {{2}} profesional, {{3}} clinica, {{4}} link | `confirm` · `change` |
| `recordatorio_3h_v1` | `t_3h` | Hoy {{1}} te esperamos en {{2}}. Llegá 10 min antes. {{3}} | {{1}} hora, {{2}} clinica, {{3}} link | `cancel` |
Textos de los botones sugeridos: `confirm` → «Confirmar» / «Sí, confirmo» / «SÍ»; `change` →
«Cambiar» / «Reprogramar»; `cancel` → «Cancelar». Si Meta rechaza un texto se puede cambiar el
cuerpo sin tocar código mientras se respeten el orden de parámetros y los botones. Sin
`{{direccion}}` ni «Cómo llegar» (la clínica no guarda dirección).

### Respuestas del paciente

| Mensaje | Efecto | Respuesta (texto libre dentro de las 24 h) |
|---|---|---|
| «SÍ», «si», «confirmo», botón `confirm` | `pending → confirmed` (misma transición que el link, fuente `whatsapp`); ya confirmado = no-op auditado | «¡Listo! Tu turno … quedó confirmado.» |
| «NO», «cambiar», «reprogramar», «cancelar», botones `change`/`cancel` | **nunca cancela** | link de gestión si la ventana de cancelación sigue abierta; si no, teléfono de la clínica |
| «STOP», «BAJA», «no me escriban» | opt-out de WhatsApp (`whatsapp_reply`), jobs pendientes `skipped` | confirmación de baja (una sola) |
| cualquier otra cosa | solo se registra (habilita la ventana de 24 h) | ninguna |

Enrutamiento: por el mensaje citado (`context.id` → `reminder_job.provider_message_id`); sin
contexto, por teléfono entre las clínicas del número que recibió el mensaje. Con cero o varios
turnos candidatos no se toca ninguno y se responde que use el link; un STOP sin contexto da de
baja todas las fichas con ese teléfono en ese número. Las respuestas van al outbox
`whatsapp_outbound_reply` y las envía el worker en el mismo tick que los recordatorios.
`whatsapp_inbound` no guarda el texto ni el teléfono.

El personal cambia el consentimiento con `PUT /api/patients/{id}/consent/{whatsapp|email}`
(`{"status": "opt_in" | "opt_out"}`, admin/recepción).

### Reporte

`GET /api/reports/whatsapp?from=&to=[&format=csv]` (solo admin): enviados, entregados, leídos y
fallidos por paso y canal más el costo atribuido, calculado sobre `delivery_event`. Pestaña
«WhatsApp» en `/admin/reportes`.

### Probar en desarrollo

`REMINDER_WHATSAPP_PROVIDER=fake` registra los envíos y las respuestas sin llamar a Meta. Para
simular un webhook firmado:

```bash
BODY='{"object":"whatsapp_business_account","entry":[{"changes":[{"field":"messages","value":{"metadata":{"phone_number_id":"<META_PHONE_NUMBER_ID>"},"statuses":[]}}]}]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$META_APP_SECRET" | sed 's/^.* //')
curl -X POST localhost:8000/webhooks/whatsapp -H "X-Hub-Signature-256: sha256=$SIG" -H 'Content-Type: application/json' -d "$BODY"
```

Antes del piloto: validar un payload real del número de prueba de Meta contra
`app/modules/notifications/payload.py`.

### Revisión `c10_whatsapp_channel` (C-10)

`clinic.whatsapp_phone_number_id` (nullable, CHECK `NOT VALID` → `VALIDATE`), únicos parciales
`CONCURRENTLY` sobre `clinic.whatsapp_phone_number_id` y `reminder_job.provider_message_id`, tablas
nuevas `whatsapp_inbound` (append-only) y `whatsapp_outbound_reply` y tres enums. Downgrade:
`alembic downgrade c09_reminder_engine` (los `consent` de fuente `whatsapp_reply` quedan).

## Timeline y reenvío manual de recordatorios (C-11)

Operación diaria de recepción sobre los recordatorios (US-032). Detalle completo:
`openspec/changes/c-11-timeline-recordatorios/design.md`.

### Timeline por turno

`GET /api/appointments/{id}/reminders` (admin, recepción y odontólogo; el odontólogo solo ve sus
turnos, un turno ajeno o de otra clínica es `404 not_found`). Devuelve un elemento por paso y
canal, en el orden alta → 72 h → 24 h → 3 h, con WhatsApp antes que email.

- **Estado efectivo** (`status`): se deriva de los eventos, no solo del estado mutable del job.
  Dentro del intento vigente, respecto del último `sent`: `read` > `delivered` > `failed`; sin
  envío, el estado del job (`scheduled`, `sending`, `sent`, `skipped`, `cancelled`). Meta puede
  informar `delivered` y `failed` del mismo mensaje (gana `delivered`) o `read` sin `delivered`
  (es `read`). Como Meta informa con segundos enteros, el `sent` se compara truncado al segundo.
- **Intento vigente**: lo posterior al último reenvío manual. Los eventos anteriores, y los propios
  `manual_resend`, vienen con `previous: true` ("envío anterior") y no cambian el estado vigente.
- `scheduled` no es un evento: aparece como primer hito solo si el job está `scheduled`/`sending`.
- `detail` expone solo `attempt`, `kind`, `reason`, `cost_micros`, `to` y `manual` (el `sent` de un
  reenvío lleva `manual: true`); el `manual_resend` lleva `actor_role`. Nunca
  `provider_message_id`, links, nombre, teléfono, email ni la nota del reenvío.
- `can_resend` / `resend_blocked_reason` los calcula el servidor con las mismas guardas del
  reenvío; para el odontólogo `can_resend` es siempre `false`.

### Reenvío manual

`POST /api/appointments/{id}/reminders/{step}/{channel}/resend` (admin y recepción; odontólogo
`403 forbidden_role`), cuerpo opcional `{"note": "…"}` (≤ 200, sin teléfono, email ni DNI: si no,
`422 invalid_note` sin repetir el valor). Guardas, en este orden, dentro de una transacción con
`FOR UPDATE` del turno y del job:

| # | Condición | Respuesta |
|---|-----------|-----------|
| 1 | Turno `pending` o `confirmed` | `409 appointment_inactive` |
| 2 | El turno no empezó | `409 appointment_started` |
| 3 | Existe el job `(turno, paso, canal)` | `404 reminder_not_found` |
| 4–6 | Paso configurado (o alta), job no `cancelled`, y no es un paso de confirmación de un turno online ya confirmado | `409 step_not_applicable` |
| 7 | WhatsApp: opt-in y teléfono; email: dirección y sin baja | `409 no_consent` / `409 no_recipient` |
| 8 | Cooldown (`REMINDER_MANUAL_RESEND_COOLDOWN_S`, default 60) o reenvío ya en cola; tope por job y día local (`REMINDER_MANUAL_RESEND_MAX_PER_DAY`, default 3) | `409 resend_cooldown` + `retry_after_s` / `409 resend_limit` |
| 9 | El job no está `sending` ni es un paso futuro todavía no intentado | `409 reminder_in_flight` / `409 reminder_pending` |

Un `202` inserta la fila de auditoría (`reminder_manual_resend`, append-only, con actor y nota) y
resetea el job a `scheduled` con `available_at = now`, `attempts = 0` y sin `sent_at`,
`provider_message_id`, `cost_micros`, `last_error` ni `reason`; conserva `scheduled_for` y
`starts_at_snapshot` y marca `manual_resend_at`. **La request no envía**: el worker lo despacha en
su próximo tick (con el worker detenido, el job queda `scheduled`). Un reenvío no adelanta un paso
futuro: solo se reenvía lo ya intentado. Dos pedidos simultáneos se serializan en el lock del
turno: uno `202`, el otro `409 resend_cooldown`, una sola fila de auditoría.

- **Recálculo**: `reconcile` no cancela por paso vencido un job con `manual_resend_at` mientras el
  turno conserve su horario. Si se reprograma, el paso se recalcula para el nuevo horario (y pierde
  la marca) o queda `cancelled (step_elapsed)`; si el turno se cancela o se quita el paso, se
  cancela. La marca se limpia cuando el job sale de `scheduled`.
- **Estados tardíos del mensaje anterior**: el reset limpia `provider_message_id`, así que un
  `delivered`/`read`/`failed` del mensaje viejo no encuentra job y se ignora; el `sent` anterior
  queda en el timeline como envío anterior.

La confirmación manual usa la transición existente: `POST /api/appointments/{id}/transitions` con
`{"to": "confirmed"}` (admin/recepción; escribe `appointment_event` con el actor).

### Seguimiento del día

`GET /api/reminders/follow-up?from=&to=[&cursor=&limit=]` (admin y recepción; rango ≤ 31 días,
`422 range_too_large` / `422 invalid_range`): turnos vigentes y futuros con `starts_at` en
`[from, to)` que requieren llamada, por `starts_at` con cursor, más `totals`.

- `no_response`: turno `pending` con un `sent` del paso de 24 h (o, si la clínica no lo configura,
  de cualquier paso que pide confirmación) cuyo job no quedó `failed`.
- `delivery_failed`: algún job `failed` programado antes del inicio. Desaparece cuando el
  reenvío se envía bien.

La fila trae el nombre del paciente y el último recordatorio, sin teléfono, email ni ids del
proveedor. En la agenda, admin y recepción ven el panel con los dos contadores y el filtro
«Solo para llamar».

### Reporte

`GET /api/reports/whatsapp` cuenta **enviados por evento** `sent` (incluye los reenvíos) y suma el
costo de cada uno; entregados y leídos cuentan una vez por job; fallidos, solo si el último intento
falló (una falla vieja ya reenviada no cuenta).

### Probar con el sender `fake`

Con `REMINDER_WHATSAPP_PROVIDER=fake`: dejar un job `failed`, reenviarlo desde el detalle del
turno («Reenviar»), esperar el próximo tick del worker y ver en el timeline el segundo `sent` con
el «Reenviado por recepción» previo. El test `tests/modules/test_reminder_timeline_e2e.py` recorre
el circuito completo (envío → `delivered`/`read` por webhook firmado → reenvío → reporte).

### Revisión `c11_reminder_timeline` (C-11)

`reminder_job.manual_resend_at` (nullable, metadata-only), tabla nueva `reminder_manual_resend`
(append-only, FKs compuestas a turno, job y usuario, CHECK de largo de la nota) con dos índices, e
índice parcial `ix_reminder_job_failed` creado `CONCURRENTLY`. Downgrade:
`alembic downgrade c10_whatsapp_channel` (se pierde el histórico de reenvíos; los jobs quedan como
estaban).

## Lista de espera (C-12)

Huecos liberados por cancelación → oferta con vencimiento → turno (US-022, US-040, Flujo 5).
Detalle completo: `openspec/changes/c-12-lista-de-espera/design.md`.

### Entradas

Una entrada (`waiting_list_entry`) es un paciente esperando un hueco con:

- **Profesional** o "cualquiera" (`professional_id` nulo).
- **Período** `date_from`–`date_to` (fechas locales de la clínica, inclusive, obligatorio): desde
  hoy y hasta el horizonte de reserva (`PUBLIC_BOOKING_HORIZON_DAYS`, default 60). Al editar una
  entrada ya empezada, `date_from` solo se valida si cambia.
- **Franja** `time_from`–`time_to` (opcional, ambos o ninguno) y **días** `weekdays` (opcional,
  0 = lunes … 6 = domingo, sin repetir). El hueco tiene que caer completo dentro.
- **Nota** operativa de recepción (≤ 200, sin teléfono, email ni DNI → `422 invalid_note`).

Estados: `waiting` → `offered` (tiene una oferta pendiente) → `converted`; o `expired`
(`range_elapsed`, `no_response`) y `withdrawn`. RN-LE-01: la base impide dos entradas
`waiting/offered` del mismo paciente y profesional, con "cualquiera" como un valor más (índice único
parcial `NULLS NOT DISTINCT`); el duplicado responde `409 already_waiting` con el `entry_id` de la
existente (al personal; nunca al público).

| Endpoint | Admin / recepción | Odontólogo |
|---|---|---|
| `GET /api/waiting-list?status=&professional_id=&from=&to=&cursor=&limit=` | todo | sus entradas y "cualquiera", sin contacto ni notas |
| `GET /api/waiting-list/{id}` | ✓ | idem |
| `POST /api/waiting-list`, `PATCH /api/waiting-list/{id}` | ✓ | `403` |
| `POST /api/waiting-list/{id}/withdraw` | ✓ (cierra su oferta pendiente) | `403` |
| `POST` / `DELETE /api/waiting-list/{id}/priority` (`{"reason": …}`, 10–200, sin PII) | ✓ | `403` |
| `GET /api/waiting-list/{id}/events` | ✓ | `403` |

La cola se ordena por prioridad (`prioritized_at`, primero las prioritarias) y luego por antigüedad,
con cursor opaco y `limit` 1–200. Filtro por profesional: incluye las de "cualquiera"; por período:
entradas cuyo período intersecta `[from, to]`. Editar una entrada `offered` → `409 entry_offered`;
editar o retirar una cerrada → `409 entry_closed`. Toda mutación escribe `waitlist_event`
(append-only, sin PII: la nota se audita como `notes_changed`).

### Evaluación al cancelar

Toda cancelación de un turno futuro (recepción, link de gestión, WhatsApp) evalúa la lista **en la
misma transacción** (`apply_transition` → `waiting_list.engine.evaluate_cancelled`); si la
evaluación falla, la cancelación revierte. Reprogramar, `absent` y `no_show` no evalúan.

1. **Ventana**: la oferta vence en `min(ahora + clinic.waitlist_offer_ttl_hours, inicio −
   WAITLIST_MIN_LEAD_MINUTES)`. Si quedan menos de `WAITLIST_MIN_OFFER_WINDOW_MINUTES` no hay
   oferta automática (recepción puede ofrecerlo a mano).
2. **Hueco libre**: sin turnos vigentes del profesional o del sillón (con el buffer) ni bloqueos.
3. **Candidata**: la primera entrada `waiting` compatible —profesional o "cualquiera", fecha local
   en el período, hueco completo dentro de la franja y en sus días, paciente no archivado con un
   canal utilizable (WhatsApp con opt-in o email sin baja), sin otro turno superpuesto y sin una
   oferta previa del mismo hueco— en el orden de la cola, con `FOR UPDATE SKIP LOCKED`: la
   cancelación nunca espera a otra transacción.
4. **Oferta**: `waitlist_offer` `pending`, entrada `offered`, evento `offer_created` y un
   `reminder_job` del paso `waitlist_offer` disponible ya (WhatsApp si hay opt-in, si no email).
   El motor de recordatorios lo envía con la plantilla `hueco_lista_espera_v1`, botones
   "Tomarlo"/"Paso" y el link `/o/{token}`; lo cancela (`offer_closed`) si la oferta ya no está
   pendiente al reclamarlo o al enviarlo.

### Respuestas, vencimiento y rotación

| Acción | Efecto |
|---|---|
| Aceptar (`POST /api/waiting-list/offers/{id}/accept`, link o botón) | Turno `confirmed` con origen `waitlist` por `AppointmentsService.book` (mismas reglas que recepción, nunca sobreturno); oferta `accepted`, entrada `converted`; las ofertas pendientes de otras entradas para el mismo hueco quedan `cancelled (slot_taken)` |
| Aceptar con el hueco ocupado | Oferta `cancelled`, entrada `waiting` **prioritaria** (`slot_lost`), confirmado antes de responder `409 slot_taken` con ≤ 3 alternativos (solo inicio y fin) |
| Aceptar vencida / cerrada / con otro turno a esa hora | `409 offer_expired` / `409 offer_closed` / `409 patient_busy` (la oferta sigue pendiente) |
| Rechazar (`…/decline`, `{"leave_list": true}` para salir) | Oferta `declined`, entrada `waiting` (o `withdrawn`) sin perder lugar, contador de vencimientos a 0; el hueco rota |
| Retirar (`…/cancel`, recepción) | Oferta `cancelled (withdrawn_by_staff)`, entrada `waiting`; el hueco rota |
| Vencer (tick `waitlist_tick` del worker, a los 30 s de cada minuto) | Oferta `expired`, entrada `waiting` con un vencimiento más; al llegar a `WAITLIST_MAX_CONSECUTIVE_EXPIRED` (3) la entrada queda `expired (no_response)`; el hueco rota. El tick también vence las entradas con `date_to` pasado (`range_elapsed`) |

Orden de locks: oferta → entrada → profesional → sillón; las ofertas hermanas se cierran con
`SKIP LOCKED`. Dos aceptaciones del mismo hueco dejan un solo turno. Ninguna automatización mueve
un turno existente (RN-GL-02).

### Oferta manual y prioridad

- `GET /api/waiting-list/{id}/slots?from=&to=` (≤ 14 días): huecos libres de las reglas vigentes que
  respetan profesional, período, franja y días de la entrada.
- `POST /api/waiting-list/{id}/offers` (`professional_id`, `chair_id`, `starts_at`): la duración es
  la de la regla; fuera de horario `422 outside_schedule`, ocupado `409 slot_taken`, entrada con
  oferta `409 entry_offered`. Si otra entrada compatible va antes en la cola, exige
  `fifo_skip_reason` (10–200, sin PII; si no, `422 fifo_skip_reason_required`) y el evento registra
  `fifo_skip=true`.
- `GET /api/waiting-list/offers?status=&from=&to=` lista las ofertas por fecha de creación.

### Probar en desarrollo

Con `REMINDER_WHATSAPP_PROVIDER=fake`: anotar a un paciente con opt-in para un profesional,
cancelar desde la agenda un turno compatible y ver la oferta en `GET /api/waiting-list`; el log del
worker muestra el envío `hueco_lista_espera_v1`. El test `tests/modules/test_waitlist_events.py`
recorre cancelación → oferta → vencimiento → rotación → aceptación.

### Revisión `c12_waiting_list` (C-12)

Tablas nuevas `waiting_list_entry`, `waitlist_offer` y `waitlist_event` (append-only), con sus
enums; valores nuevos en `appointment_origin`, `whatsapp_intent` y `whatsapp_reply_kind`
(`autocommit_block`); `reminder_job.appointment_id` pasa a nullable con `waitlist_offer_id` y los
CHECK `one_target`/`offer_step`; paso `waitlist_offer` en `step_format`; `waitlist_offer_id` en
`whatsapp_inbound` y `whatsapp_outbound_reply`; índice único `uq_reminder_job_offer_channel`
`CONCURRENTLY`; backfill de las dos plantillas de oferta en las clínicas existentes. Constraints
sobre tablas con filas `NOT VALID` → `VALIDATE`. Downgrade: `alembic downgrade
c11_reminder_timeline` (borra jobs y plantillas de oferta; los valores de enum quedan).

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
