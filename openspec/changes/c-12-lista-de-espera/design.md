# Design — C-12 `lista-de-espera`

## Context

Motivación y alcance: ver `proposal.md`. Requisitos: `specs/waitlist/**`,
`specs/web/**` y los deltas de `agenda/appointments`, `reminders/*` y `core/*`.

Estado actual que condiciona el diseño:

- `AppointmentsService.book()` es el único camino de escritura de turnos: lock
  de profesional y sillón (`FOR UPDATE`, ordenados), validación de regla,
  bloqueos y colisiones, savepoint con traducción del EXCLUDE a `409
  slot_taken` + alternativos, evento y `schedule_new` en la misma transacción.
  Hoy decide `pending` vs `confirmed` por `origin is ONLINE`.
- Toda cancelación (recepción, token de C-08, flujos de WhatsApp de C-10) pasa
  por `apply_transition()` en `appointments/states.py`, que ya llama a
  `reconcile()` de recordatorios dentro de la transacción.
- El motor de C-09/C-10 envía `reminder_job` con `FOR UPDATE SKIP LOCKED`,
  lease, backoff, escalado a email, `delivery_event`, costo por paso, estados de
  Meta por `provider_message_id` y ruteo de respuestas por contexto. Supone que
  todo job tiene `appointment_id` (`NOT NULL`).
- `reminders/links.py` firma links sin estado con HMAC sobre
  `MANAGE_LINK_SECRET` y un contexto `manage-link/v1`.
- `clinic.waitlist_offer_ttl_hours` (default 4) existe desde C-04;
  `appointment_origin` no tiene `waitlist`; `app/modules/waiting_list/` y
  `features/waiting-list/` son stubs de C-01.
- Cabeza de migraciones: `c11_reminder_timeline`.

## Goals / Non-Goals

**Goals:**

- Que la evaluación al cancelar sea atómica con la cancelación y no pueda
  generar dos ofertas pendientes para la misma entrada ni bloquear la
  cancelación esperando locks.
- Reutilizar el motor de envío existente en vez de construir un segundo outbox:
  mismas garantías, mismo reporte de costo, mismo webhook.
- Que aceptar una oferta sea exactamente un alta de agenda (`book()`): la
  lista de espera nunca tiene un camino de escritura de turnos propio.

**Non-Goals:**

- Difusión de un hueco a varias entradas a la vez, ni ofertas "en espera"
  encadenadas: una oferta automática por hueco a la vez.
- Recalcular ofertas cuando cambia la configuración (TTL, reglas): el TTL se
  fija al crear la oferta.
- Cancelar proactivamente las ofertas cuyo hueco ocupó recepción por otro
  camino: lo detecta la aceptación (D5) y el envío (D2).

## Decisions

### D1 — Modelo de datos y migración `c12_waiting_list`

Tres tablas nuevas, todas con `clinic_id` obligatorio y FKs compuestas
`(clinic_id, x_id)` (regla 4):

- `waiting_list_entry`: `patient_id`, `professional_id` (nullable =
  "cualquiera"), `date_from`/`date_to` (`date`), `time_from`/`time_to` (`time`,
  ambos o ninguno), `weekdays` (`smallint[]`, nullable, valores 0–6, no vacío),
  `notes` (≤ 200), `status` (enum `waiting_list_status`: `waiting, offered,
  converted, expired, withdrawn`), `source` (`reception|online`),
  `prioritized_at`/`priority_reason`, `consecutive_expired` (`smallint ≥ 0`),
  `closed_reason` (código), `created_by_user_id`, timestamps.
  - Unicidad RN-LE-01: índice único parcial `(clinic_id, patient_id,
    professional_id) NULLS NOT DISTINCT WHERE status IN ('waiting','offered')`.
    PostgreSQL 15 soporta `NULLS NOT DISTINCT`; así "cualquiera" es un valor más
    sin inventar un UUID centinela.
  - Orden de la cola: índice parcial `(clinic_id, prioritized_at NULLS LAST,
    created_at, id) WHERE status IN ('waiting','offered')`.
- `waitlist_offer`: `entry_id`, `professional_id`, `chair_id`, `starts_at`,
  `ends_at`, `expires_at`, `status` (enum `waitlist_offer_status`: `pending,
  accepted, declined, expired, cancelled`), `mode` (`auto|manual`),
  `source_appointment_id` (turno cancelado, nullable para manuales),
  `appointment_id` (turno creado, nullable), `closed_reason`, `responded_at`,
  `created_by_user_id`, timestamps.
  - Una pendiente por entrada: único parcial `(entry_id) WHERE status =
    'pending'`.
  - Tick: parcial `(expires_at) WHERE status = 'pending'`.
  - `CHECK (status = 'accepted') = (appointment_id IS NOT NULL)`,
    `ends_at > starts_at`, `expires_at <= starts_at`.
- `waitlist_event` (append-only con trigger `BEFORE UPDATE OR DELETE`, como
  `appointment_event`): `entry_id`, `offer_id` (nullable), `event` (enum
  `waitlist_event_type`), `actor_type` (reusa `actor_type`), `actor_user_id`,
  `payload jsonb` sin PII, `created_at`. Índice `(clinic_id, event,
  created_at)` para el reporte.

Cambios sobre tablas existentes (regla 11):

- `appointment_origin` suma `waitlist` con `ALTER TYPE … ADD VALUE` dentro de
  `op.get_context().autocommit_block()` (el valor no se puede usar en la misma
  transacción que lo crea). Lo mismo para los valores nuevos de
  `whatsapp_intent` y `whatsapp_reply_kind` (D8).
- `appointment`: `CHECK origin <> 'waitlist' OR (NOT is_overbooking AND
  manage_token_hash IS NULL)` como `NOT VALID` → `VALIDATE`, después del
  autocommit del enum.
- `reminder_job`: `ADD COLUMN waitlist_offer_id uuid NULL`; `ALTER COLUMN
  appointment_id DROP NOT NULL` (solo metadato, sin reescritura); FK compuesta a
  `waitlist_offer` `NOT VALID` → `VALIDATE`; `CHECK num_nonnulls(appointment_id,
  waitlist_offer_id) = 1` y `CHECK (step = 'waitlist_offer') = (waitlist_offer_id
  IS NOT NULL)` `NOT VALID` → `VALIDATE`; único parcial `(waitlist_offer_id,
  channel) WHERE waitlist_offer_id IS NOT NULL` con `CREATE UNIQUE INDEX
  CONCURRENTLY`. La unicidad existente `(appointment_id, step, channel)` sigue
  valiendo (con `appointment_id` NULL no colisiona).
- `STEP_FORMAT_SQL` pasa a `^(created|waitlist_offer|t_[0-9]+h)$`: se reemplaza
  el CHECK `step_format` de `reminder_job` y de `notification_template` (drop +
  add `NOT VALID` + `VALIDATE`).
- `whatsapp_inbound` y `whatsapp_outbound_reply`: `ADD COLUMN waitlist_offer_id
  uuid NULL` + FK compuesta `NOT VALID` → `VALIDATE`.

`downgrade` revierte todo salvo los valores de enum (PostgreSQL no los quita):
se documenta, como en C-09/C-10, y el downgrade borra antes las filas que los
usan solo en la base de pruebas del test de migraciones.

*Alternativa descartada*: guardar las preferencias como `tstzrange`. Mezcla el
período (fechas) con la franja (horas del día) y no expresa "martes y jueves de
14 a 18"; las columnas separadas validan con CHECKs simples.

### D2 — El envío de la oferta es un `reminder_job` del paso `waitlist_offer`

La oferta se envía como un `reminder_job` con `waitlist_offer_id`, sin
`appointment_id`, `step='waitlist_offer'`, `scheduled_for = available_at =
created_at` y `starts_at_snapshot` = inicio del hueco. El canal se elige al crear
la oferta (D3: WhatsApp con opt-in o email); el escalado a email existente
(`escalate_to_email`) crea el par de email para la misma oferta.

Cambios en el motor, todos acotados a la rama "job de oferta":

- `dispatch._claim_batch` / `_context_query`: hoy hacen `JOIN appointment`. Se
  separan en dos consultas (turnos y ofertas) y la de ofertas une `waitlist_offer
  → waiting_list_entry → patient`. Validación previa: oferta `pending` y
  `expires_at > now`; si no, `cancelled` con `offer_closed`. Consentimiento,
  destinatario y plantilla igual que hoy.
- `_recheck`: misma verificación de la oferta justo antes de enviar.
- `_build_message`: parámetros `nombre, clinica, fecha, hora, profesional,
  vence, link`; `link` es el link de la oferta (D6); botones
  `offer_accept`/`offer_decline`. `ALLOWED_VARIABLES` suma `vence`.
- `escalate_to_email` y `statuses.apply_status` copian `waitlist_offer_id`
  cuando el job no tiene turno.
- `reconcile`, el timeline y la lista de seguimiento ya filtran por
  `appointment_id`: los jobs de oferta quedan fuera sin cambios, y un test lo
  fija (spec `offer-delivery`).
- Reporte de WhatsApp: `_configured_steps` suma `waitlist_offer` al final.
- `ReminderJob.appointment_id` pasa a `Mapped[uuid.UUID | None]`: mypy marca
  cada uso que asumía un turno, que es la lista de puntos a revisar.

*Alternativa descartada*: un outbox propio de ofertas (como
`whatsapp_outbound_reply`). Duplicaría lease, backoff, escalado, estados de Meta,
costo y reporte, y el webhook tendría que buscar el `provider_message_id` en dos
tablas. El costo de reusar es relajar `appointment_id NOT NULL`, que se
compensa con el CHECK de exactamente uno.

### D3 — Evaluación de un hueco (`waiting_list/engine.py`)

`evaluate_slot(session, slot, *, now, actor, exclude_entry_ids=())` sin commit
propio. La llaman:

1. `apply_transition()` cuando el destino es `cancelled`, después de
   `reconcile()` (spec `agenda/appointments`). `slot` = profesional, sillón,
   `starts_at`, `ends_at` del turno cancelado, `source_appointment_id` = su id.
2. El tick tras un vencimiento (D4) y el rechazo, con el mismo hueco.

Pasos:

1. **Ventana**: `expires_at = min(now + ttl, starts_at − WAITLIST_MIN_LEAD_MINUTES)`;
   si `expires_at − now < WAITLIST_MIN_OFFER_WINDOW_MINUTES`, termina.
2. **Hueco libre**: ningún turno vigente del profesional o del sillón que
   intersecte `[starts_at, ends_at + buffer)` y ningún bloqueo activo. No toma
   locks de recursos: si alguien lo ocupa después, la aceptación lo detecta.
3. **Candidata**: una sola consulta con `FOR UPDATE OF waiting_list_entry SKIP
   LOCKED LIMIT 1`, filtrando por clínica, `status='waiting'`, profesional o
   NULL, `date_from ≤ fecha local ≤ date_to`, franja (`time_from ≤ hora local
   inicio` y `hora local fin ≤ time_to`), `weekday = ANY(weekdays)`, paciente no
   archivado ni fusionado, canal utilizable (opt-in de WhatsApp vigente con
   teléfono, o email sin baja), `NOT EXISTS` turno vigente superpuesto del
   paciente y `NOT EXISTS` oferta previa de la entrada con el mismo
   `(professional_id, chair_id, starts_at)`; orden `prioritized_at NULLS LAST,
   created_at, id`. La fecha y hora locales se calculan en SQL con la zona de la
   clínica (`AT TIME ZONE`), no en Python, para que el filtro y el índice
   coincidan.
4. **Oferta**: inserta `waitlist_offer` (`pending`), pasa la entrada a
   `offered`, inserta el `reminder_job` (D2) y el evento `offer_created`.

`SKIP LOCKED` es lo que evita que la cancelación espere: si otra transacción
tiene tomada la entrada (otra cancelación, una aceptación, recepción editando),
se pasa a la siguiente. El único parcial de "una pendiente por entrada" es la
barrera final; un `IntegrityError` ahí no debería ocurrir (la entrada está
lockeada) y se deja propagar.

Orden de locks: la cancelación ya tiene el turno lockeado y después toma
entradas con `SKIP LOCKED` (nunca espera). La aceptación (D5) toma oferta →
entrada → profesional → sillón. No hay ciclo posible porque el único camino que
espera por una entrada es el que antes tomó su oferta.

*Alternativa descartada*: evaluar en el worker (asíncrono) tras la
cancelación. Cumple "huecos llenos" con un minuto de demora, pero rompe RN-CX-03
("en la misma transacción lógica") y obliga a un marcador de huecos pendientes
de evaluar.

### D4 — Tick de la lista de espera

Nuevo cron ARQ `waitlist_tick` cada minuto (`second=30`, `unique=True`), en el
mismo worker. En transacciones cortas por lote:

1. Ofertas `pending` con `expires_at <= now`, `FOR UPDATE SKIP LOCKED LIMIT
   batch`: oferta → `expired`; entrada `FOR UPDATE` → `waiting`,
   `consecutive_expired + 1`; si llega a `WAITLIST_MAX_CONSECUTIVE_EXPIRED`,
   entrada → `expired` (`no_response`); eventos; `evaluate_slot` con el mismo
   hueco y la entrada excluida.
2. Entradas `waiting` con `date_to <` hoy local → `expired` (`range_elapsed`).

La aceptación lee `expires_at` en el acto: una oferta vencida y todavía no
procesada por el tick ya responde `409 offer_expired` (spec `offer-link`), así
el tick es limpieza y rotación, no la fuente de verdad del vencimiento.

### D5 — Aceptar, rechazar, retirar (`waiting_list/offers.py`)

`OffersService(session, actor, now)` es el único que muta ofertas; lo usan el
link público, el panel de recepción y el webhook.

**Aceptar**:

1. `SELECT … FOR UPDATE` de la oferta (por id y clínica). `accepted` con turno →
   `200` idempotente; `declined|cancelled` → `409 offer_closed`; `expires_at <=
   now` → `409 offer_expired`.
2. `FOR UPDATE` de la entrada; turno vigente superpuesto del paciente → `409
   patient_busy` (oferta intacta).
3. `AppointmentsService(session, actor, now).book(Booking(...), origin=WAITLIST,
   event_extra={"waitlist_offer_id": …})`. `book()` cambia en dos puntos: el
   estado inicial es `pending` solo para `ONLINE` (ya es así: `WAITLIST` cae en
   `confirmed`) y el chequeo `appointment_in_past` se extiende a `WAITLIST`.
4. Si `book()` lanza `DomainError` de hueco (`slot_taken`, `slot_blocked`,
   `outside_schedule`, `resource_inactive`): la oferta → `cancelled`
   (`slot_taken` o `slot_unavailable`), la entrada → `waiting` + prioridad
   `slot_lost`, eventos, **commit** y recién entonces `409` con hasta 3
   alternativos (solo inicio y fin, como la reserva pública). Se hace commit
   antes de responder el error para que el cambio de prioridad persista.
5. Éxito: oferta `accepted` + `appointment_id`; entrada `converted`,
   `consecutive_expired = 0`; las demás ofertas `pending` de la entrada y las de
   otras entradas con el mismo `(professional_id, chair_id, starts_at)` →
   `cancelled` (sus entradas a `waiting`); eventos; commit.

El actor del paciente es `Actor(clinic_id, ActorType.PATIENT_TOKEN)` como en
C-08; recepción usa `Actor.from_principal`.

**Rechazar**: oferta `declined`, entrada `waiting` (o `withdrawn` con
`leave_list`), `consecutive_expired = 0`, eventos y `evaluate_slot` para rotar.
**Retirar (recepción)**: oferta `cancelled` (`withdrawn_by_staff`), entrada
`waiting`, rota igual.

### D6 — Link de la oferta

`waiting_list/links.py` replica el esquema de `reminders/links.py` con otro
contexto y prefijo: `token = "w1." + base64url(offer_id ‖ HMAC(secret,
"waitlist-offer/v1" ‖ offer_id)[:16])`, con el mismo `MANAGE_LINK_SECRET` y la
misma verificación en forma canónica. El prefijo `w1.` y el contexto distinto
impiden usar un link de gestión como oferta y al revés (spec `offer-link`).
Validez de lectura: `ends_at + MANAGE_TOKEN_TTL_H`. URL:
`{FRONTEND_PUBLIC_URL}/o/{token}`.

Rate-limit: mismas cuotas que la gestión por token (`MANAGE_READ_*`,
`MANAGE_WRITE_*`) con claves `waitlist-offer:*`, sobre `consume()` de
`common/rate_limit_guard.py`. Cabeceras `no-store` / `no-referrer` con el mismo
helper que `manage/router.py`.

*Alternativa descartada*: token aleatorio con hash en `waitlist_offer`, como C-07.
El link se arma en el worker (D2), que no puede recuperar un token en claro; es
el mismo motivo por el que C-09 introdujo los links firmados.

### D7 — Anotación pública

`POST /api/booking/{slug}/waiting-list` en `booking_public/router.py`, para
reusar `resolve_clinic` (404 uniforme), `BotGuard`, `client_ip` y la
normalización de contacto. Del servicio de reserva se extraen a funciones
reutilizables `_contact`, `_match_or_create` y `_stamp_privacy` (hoy métodos
privados de `BookingPublicService`) sin cambiar su comportamiento: la suite de
C-07 es la red de seguridad. Cupos nuevos `WAITLIST_PUBLIC_IP_RATE_LIMIT`
(default `5/3600s`) y `WAITLIST_PUBLIC_SLUG_RATE_LIMIT` (`100/3600s`). El
consentimiento se registra con `ConsentService` fuente `booking`.

### D8 — WhatsApp: intenciones, ruteo y respuestas

- `classify()` suma `accept_offer` (botón `offer_accept`, "tomarlo", "lo
  tomo") y `decline_offer` (botón `offer_decline`, "paso"). `stop` sigue primero.
- `route()`: si `context_id` coincide con el `provider_message_id` de un job de
  oferta, devuelve un `Target` con `waitlist_offer_id`. En ese contexto,
  `confirm` se trata como `accept_offer` y `change` como `decline_offer` (spec:
  "sí"/"no" citando la oferta). Sin contexto de oferta, `accept_offer` y
  `decline_offer` se registran y no hacen nada (spec: sin contexto nunca acepta).
- `whatsapp_inbound.waitlist_offer_id` se guarda; la deduplicación por
  `(clinic_id, provider_message_id)` ya impide un segundo turno ante reenvíos.
- `_act` llama a `OffersService` dentro de un savepoint y encola una respuesta
  con los nuevos `WhatsAppReplyKind`: `offer_accepted` (con fecha, hora y link
  de gestión del turno nuevo), `offer_declined`, `offer_taken`,
  `offer_closed` (vencida o cerrada) y `offer_patient_busy`. `render_reply` arma
  los textos; la ventana de 24 h aplica sin cambios.

### D9 — Auditoría y reporte de conversión

`waitlist_event.event`: `entry_created, entry_updated, entry_prioritized,
entry_unprioritized, entry_withdrawn, entry_expired, entry_converted,
offer_created, offer_accepted, offer_declined, offer_expired,
offer_cancelled`. Payload: ids, horarios, `mode`, `fifo_skip`, motivos y
valores anterior/nuevo de las preferencias; nunca nombre, teléfono, email ni
notas (las notas se auditan como `notes_changed: true`).

`GET /api/reports/waitlist`: cohorte = eventos `offer_created` cuya fecha local
cae en el rango; resultado = último evento terminal de cada oferta
(`DISTINCT ON (offer_id) … ORDER BY created_at DESC, id DESC`); agrupado por
`payload.professional_id`, sin leer `waitlist_offer.status` (regla 8, spec
`conversion-report`). CSV con el helper de `reports/exports.py`. La exportación
completa suma tres archivos leídos por lotes con cursor.

### D10 — Prioridad y excepción a FIFO

La prioridad vive en la entrada (`prioritized_at`, `priority_reason`): ordena
antes en la cola y en la evaluación. Fuentes: recepción con motivo
(`entry_prioritized`, actor usuario) o el sistema al perder la carrera
(`slot_lost`). Quitarla limpia ambas columnas (`entry_unprioritized`).

Oferta manual: el servicio corre la consulta de candidatas de D3 sin `LIMIT 1`
para el hueco elegido; si la entrada pedida no es la primera, exige
`fifo_skip_reason` y lo guarda en el evento `offer_created` con
`fifo_skip=true`. El motivo usa el validador anti-PII de `reminders/manual.py`
(se mueve a `app/common/` para compartirlo).

### D11 — API y RBAC

| Endpoint | Admin | Recepción | Odontólogo |
|---|---|---|---|
| `GET /api/waiting-list`, `GET /api/waiting-list/{id}` | ✓ | ✓ | propios + "cualquiera", sin contacto |
| `POST /api/waiting-list`, `PATCH /api/waiting-list/{id}` | ✓ | ✓ | 403 |
| `POST /api/waiting-list/{id}/withdraw`, `/prioritize`, `DELETE …/priority` | ✓ | ✓ | 403 |
| `GET /api/waiting-list/{id}/slots`, `POST /api/waiting-list/{id}/offers` | ✓ | ✓ | 403 |
| `GET /api/waiting-list/offers`, `POST …/offers/{id}/accept|decline|cancel` | ✓ | ✓ | 403 |
| `GET /api/waiting-list/{id}/events` | ✓ | ✓ | 403 |
| `GET /api/reports/waitlist` | ✓ | 403 | 403 |

Públicos: `POST /api/booking/{slug}/waiting-list`, `GET
/api/waitlist-offer/{token}`, `POST …/accept`, `POST …/decline`. Todos los
schemas con `extra='forbid'` (regla 2). Listados con cursor `(prioritized_at,
created_at, id)` y `limit` 1–200; selects con columnas explícitas (regla 8). Se
elimina el stub `GET /waiting-list/ping` y su test.

### D12 — Frontend

- `features/waiting-list/`: `WaitingListPage` (cola + filtros + "Cargar más"),
  `EntryForm` (alta/edición, búsqueda de paciente reutilizando la de
  `AppointmentForm`), `OfferDialog` (huecos de `…/slots`, motivo FIFO ante
  `422`), `OffersPanel` (pendientes con cuenta regresiva, vencidas del día),
  `waitingListErrors.ts`. Refresco con `refetchInterval` de 30 s y
  `refetchIntervalInBackground: false`, como la agenda. Entrada de menú para los
  tres roles; acciones ocultas al odontólogo.
- `features/waitlist-offer/`: `OfferPage` en `/o/:token`, con `QueryClient`
  propio como `/b/:slug` y `/g/:token` (el `AuthProvider` limpia el cache del
  visitante anónimo, motivo documentado en C-07).
- `features/booking/`: `WaitlistStep` accesible desde los pasos de día y hora;
  reutiliza `ContactStep` para datos y consentimientos.
- `features/reports/`: panel "Lista de espera" en `Panels.tsx` y etiqueta del
  paso `waitlist_offer` en la pestaña WhatsApp.
- Tipos en `shared/api/types.ts` sin `any` (regla 5).

### D13 — Configuración

`WAITLIST_MIN_LEAD_MINUTES=60`, `WAITLIST_MIN_OFFER_WINDOW_MINUTES=15`,
`WAITLIST_MAX_CONSECUTIVE_EXPIRED=3`, `WAITLIST_TICK_BATCH_SIZE=100`,
`WAITLIST_PUBLIC_IP_RATE_LIMIT=5/3600s`, `WAITLIST_PUBLIC_SLUG_RATE_LIMIT=100/3600s`
en `Settings` (validados como los cupos existentes) y en `.env.example`. El TTL
sigue siendo la política por clínica `waitlist_offer_ttl_hours`.

## Risks / Trade-offs

- [Relajar `reminder_job.appointment_id NOT NULL` rompe supuestos del motor] →
  CHECK de exactamente uno + CHECK paso↔oferta en la base, tipo `Optional` para
  que mypy liste cada uso, y las suites de C-09/C-10/C-11 como red de seguridad
  antes de tocar `dispatch.py`.
- [La evaluación agrega latencia a cada cancelación] → una consulta indexada con
  `LIMIT 1` y `SKIP LOCKED`; test de que una cancelación con 1.000 entradas no
  compatibles sigue por debajo del presupuesto actual del endpoint.
- [Se envía una oferta de un hueco que recepción ya ocupó] → el job se cancela si
  la oferta se cerró; si sigue pendiente, la aceptación responde `slot_taken` y
  prioriza la entrada. Se acepta el mensaje "de más" a cambio de no lockear
  recursos en la cancelación.
- [`ALTER TYPE … ADD VALUE` no es reversible] → documentado; el downgrade deja
  los valores y elimina lo demás, como en C-09/C-10.
- [El paciente sin link para gestionar su anotación] → puede salir desde
  cualquier oferta o llamando; queda en "Fuera de alcance" y se revisa en el
  piloto.
- [Plantilla `hueco_lista_espera_v1` no aprobada por Meta] → el texto queda en el
  catálogo como placeholder; la aprobación es parte de la pregunta abierta Alta
  sobre titularidad de plantillas, ya registrada en `10`.
- [Zona horaria en el filtro SQL] → la fecha y hora locales se calculan con la
  zona de la clínica en la consulta; tests de borde 23:30 local y cambio de día.

## Migration Plan

1. `alembic upgrade head` aplica `c12_waiting_list`: enums en autocommit, tablas
   nuevas, columnas nullable, constraints `NOT VALID` → `VALIDATE`, índices
   `CONCURRENTLY`. Sin backfill: no hay datos previos de lista de espera.
2. Re-ejecutar el seed agrega las dos plantillas `waitlist_offer` a las clínicas
   existentes (idempotente).
3. Desplegar `api` y `worker` juntos (misma imagen): un worker anterior a C-12
   no sabe procesar jobs sin `appointment_id`. Detener el worker viejo antes de
   que la `api` nueva acepte cancelaciones: cómo se comporta el worker viejo con
   un job de oferta no está garantizado.
4. Rollback: `alembic downgrade c11_reminder_timeline` en una ventana sin
   ofertas pendientes (cerrarlas antes con un script de mantenimiento); los
   valores de enum quedan.

## Open Questions

- Texto definitivo de la plantilla de oferta y su aprobación en Meta: no cambia
  el diseño (el catálogo admite editar el texto) y depende de la decisión
  comercial sobre la titularidad de plantillas.
