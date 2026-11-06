# Tasks — C-10 `whatsapp-webhook`

> TDD estricto rojo → verde: cada tarea **RED** escribe el test, lo corre y deja
> registrado que falla por la razón esperada; la **GREEN** siguiente escribe el
> mínimo código para pasarlo. Tests de invariantes y API con pytest + httpx contra
> Postgres 15 + Redis 7 reales (regla 9, sin mocks de DB); la Cloud API de Meta se
> simula con `httpx.MockTransport` (es HTTP externo, no la base). El `.venv` local
> no importa `asyncpg` (py3.14): el gate se corre en el contenedor py3.12 como CI.
> Datos solo sintéticos: nombres inventados, teléfonos `+54 11 5555-01xx`, emails
> `@example.com`, `phone_number_id` ficticios (regla 13); ni teléfonos, textos ni
> links en logs, `last_error`, eventos ni tablas nuevas. Antes de tocar archivos
> existentes, correr su suite como red de seguridad. Cada grupo deja sus tests y
> su documentación.

## 0. Red de seguridad

- [x] 0.1 Correr `pytest -q` en `backend/` (contenedor py3.12) y `npm test` en
  `frontend/`, y anotar el baseline (N passed / N failed, con las fallas de entorno
  preexistentes). Verifica: tabla de baseline al final de este archivo; nada se
  arregla acá.
- [x] 0.2 Confirmar con un script descartable el formato vigente del payload de
  webhook y de la respuesta de error de la Cloud API para `META_API_VERSION`
  (campos `entry[].changes[].value.{metadata,statuses,messages,contacts}`,
  `context.id`, `button.payload`, `interactive.button_reply.id`,
  `error.code`). Verifica: nota en este archivo con la forma real; si difiere de
  `design.md` D4–D7, ajustar el diseño antes de seguir.

## 1. Configuración (D3)

- [x] 1.1 RED — `backend/tests/core/test_settings_whatsapp.py`:
  `REMINDER_WHATSAPP_PROVIDER=meta` se acepta; con `meta` y cualquiera de
  `WHATSAPP_TOKEN`, `META_APP_SECRET`, `META_PHONE_NUMBER_ID`,
  `META_VERIFY_TOKEN` vacío falla con `SettingsError` que nombra la variable y no
  imprime valores; `WHATSAPP_TOKEN` y `META_APP_SECRET` no aparecen en
  `repr(settings)`; los settings nuevos (`META_GRAPH_BASE_URL`,
  `WHATSAPP_HTTP_TIMEOUT_S`, `WHATSAPP_WEBHOOK_MAX_BYTES`,
  `WHATSAPP_REPLY_MAX_ATTEMPTS`) tienen default. Verifica: el test falla por
  settings inexistentes.
- [x] 1.2 GREEN — `app/core/settings.py` (Literal con `meta`, `SecretStr`,
  validación) y `.env.example` con las claves nuevas y valores ficticios (regla 6).
  Ajustar los lectores existentes de esos campos a `.get_secret_value()`.
  Verifica: 1.1 verde, `tests/test_env_example.py` y
  `tests/core/test_settings_reminders.py` verdes.

## 2. Migración `c10_whatsapp_channel` y modelos (D1)

- [x] 2.1 RED — `backend/tests/models/test_whatsapp_tables_db.py` (Postgres
  real): `clinic.whatsapp_phone_number_id` con letras falla por CHECK y repetido
  entre dos clínicas falla por único; `reminder_job.provider_message_id`
  repetido falla; `whatsapp_inbound` rechaza `(clinic_id, provider_message_id)`
  duplicado, `UPDATE` y `DELETE` (trigger); `whatsapp_outbound_reply` rechaza
  `(inbound_id, kind)` duplicado; FK compuestas rechazan paciente, turno o
  entrante de otra clínica (regla 4). Verifica: falla por tablas inexistentes.
- [x] 2.2 GREEN — modelos `WhatsAppInbound`, `WhatsAppOutboundReply`, enums
  (`WhatsAppIntent`, `WhatsAppReplyKind`, `WhatsAppReplyStatus`), columna en
  `Clinic`; revisión `alembic/versions/c10_whatsapp_channel.py` con
  `down_revision="c09_reminder_engine"`: columna nullable, CHECK `NOT VALID` →
  `VALIDATE`, dos únicos parciales `CONCURRENTLY` en `autocommit_block`, tablas,
  enums y trigger append-only (regla 11). Verifica: 2.1 verde.
- [x] 2.3 Extender `tests/test_migrations.py`: `upgrade head` →
  `downgrade c09_reminder_engine` → `upgrade head` sin errores sobre una base con
  datos sintéticos de C-09, y el índice/CHECK quedan `VALID`. Verifica: test verde.

## 3. Catálogo de plantillas y adaptador Cloud API (D4)

- [x] 3.1 RED — `tests/modules/test_reminder_templates_catalog.py`: cada
  plantilla de WhatsApp del catálogo declara `param_order` que cubre exactamente
  sus variables y `buttons` (`confirm`+`change` en alta/72 h/24 h, solo `cancel`
  en 3 h). Verifica: falla por campos inexistentes.
- [x] 3.2 GREEN — `app/modules/reminders/templates.py` con `param_order` y
  `buttons`. Verifica: 3.1 y `tests/test_seed_templates.py` verdes.
- [x] 3.3 RED — `tests/modules/test_reminder_meta_sender.py` con
  `httpx.MockTransport`: el request va a
  `{base}/{version}/{sender_id}/messages` con `Bearer`, `type=template`,
  `language.code=es_AR`, parámetros posicionales en orden y botones
  `quick_reply` con payload; 200 devuelve el `messages[0].id`; la tabla de
  errores de D4 produce `SendError` con el `retryable` y el código esperados
  (timeout, 5xx, 429, 131026, 132001, 190, 131047); un cuerpo de error con un
  teléfono sintético no aparece en el código, en `str(error)` ni en `caplog`;
  el token no aparece en logs. `send_text` arma un mensaje `type=text`.
  Verifica: falla por módulo inexistente.
- [x] 3.4 GREEN — `app/modules/reminders/senders/meta.py`
  (`MetaWhatsAppSender`), `OutboundMessage.sender_id`, `send_text` también en
  `FakeSender`, `build_senders` con `meta`. Verifica: 3.3 verde y
  `tests/modules/test_reminder_*.py` sin regresiones.

## 4. Despacho con número por clínica y costo en el evento (D4, D8, D10)

- [x] 4.1 RED — `tests/modules/test_reminder_dispatch_whatsapp_number.py`
  (Postgres real, sender fake que captura): un job de una clínica con
  `whatsapp_phone_number_id` sale con ese `sender_id`; uno de una clínica sin él,
  con `META_PHONE_NUMBER_ID`; el evento `sent` lleva `payload.cost_micros`; un
  recordatorio con un entrante reciente del paciente sigue saliendo como
  plantilla. Verifica: falla por `sender_id`/payload ausentes.
- [x] 4.2 GREEN — `dispatch.py`: columna de la clínica en el contexto de reclamo,
  `sender_id` en `_build_message`, `cost_micros` en el payload del evento `sent`,
  sin `choose_message_kind` en recordatorios. Extraer `_escalate_to_email` a
  `reminders/jobs.py` (`escalate_to_email`) sin cambiar comportamiento.
  Verifica: 4.1 verde y toda la suite de reminders de C-09 verde.

## 5. Webhook: verificación, firma y parseo (D2, D5)

- [x] 5.1 RED — `tests/modules/test_whatsapp_webhook_auth.py` (API):
  `GET` con token correcto devuelve el challenge en `text/plain`; token
  incorrecto, modo distinto o `META_VERIFY_TOKEN` vacío → 403; `POST` sin firma,
  con firma de otro cuerpo, con prefijo distinto de `sha256=` o con
  `META_APP_SECRET` vacío → 401 sin cambios en la base y con un log
  `webhook_signature_invalid` sin cuerpo ni IP; cuerpo mayor a
  `WHATSAPP_WEBHOOK_MAX_BYTES` → 413; payload firmado con campos extra
  desconocidos → 200 y se procesa; payload firmado sin estructura mínima o con
  `field` desconocido → 200 sin cambios y log `webhook_payload_invalid`; 40
  POST firmados seguidos no reciben 429 del rate-limit global. Verifica: falla
  (rutas inexistentes).
- [x] 5.2 GREEN — `notifications/signature.py`, `payload.py` (modelos
  `extra="ignore"` con docstring de la excepción D2), `router.py` en
  `/webhooks/whatsapp` (sin el `ping` del stub), exclusión del path en
  `GlobalRateLimitMiddleware`, procesamiento por evento en su propia transacción
  y 500 final ante error inesperado. Verifica: 5.1 verde.
- [x] 5.3 RED → GREEN — `tests/test_edges.py` (o test nuevo de bordes): ningún
  `BaseModel` de `app/` declara un `extra` distinto de `"forbid"` salvo los de
  `notifications/payload.py` (los modelos de respuesta previos sin `extra` declarado no
  cuentan: hay 51 y no son bordes de entrada). Verifica: el test falla si se agrega `ignore` en
  otro módulo (probarlo con un modelo temporal) y queda verde con el código real.
- [x] 5.4 Documentar la excepción de la regla 2 (D2) en `AGENTS.md` y
  `CLAUDE.md` con el mismo texto. Verifica: `diff AGENTS.md CLAUDE.md` no muestra
  diferencias en la sección de reglas duras.

## 6. Estados de entrega (D6)

- [x] 6.1 RED — `tests/modules/test_whatsapp_webhook_statuses.py`
  (Postgres real, POST firmados): `delivered` y luego `read` dejan el job `read`
  con dos eventos; `read` antes que `delivered` deja `read` y ambos eventos; el
  mismo `delivered` dos veces deja un solo evento; estado de un id desconocido →
  200 sin cambios; `failed` de un job `sent` lo deja `failed`
  (`provider_rejected`, `last_error=meta_<código>`) y crea el job de email del
  paso si hay email sin baja; `failed` de un job `delivered` solo agrega el
  evento; ningún evento ni log contiene el teléfono del destinatario. Verifica:
  falla.
- [x] 6.2 GREEN — manejo de `statuses[]` en `notifications/service.py`.
  Verifica: 6.1 verde.

## 7. Respuestas del paciente: intención, enrutamiento y acciones (D7)

- [x] 7.1 RED — `tests/modules/test_whatsapp_intents.py` (unitario puro):
  "Sí!", "si", "SI", "confirmo" y botón `confirm` → confirm; "NO", "reprogramar",
  botones `change`/`cancel` → change; "STOP", "baja", "no me escriban más" →
  stop (prioridad sobre change); "si no puedo", "a qué hora era?", imagen →
  unknown. Verifica: falla.
- [x] 7.2 GREEN — `notifications/intents.py`. Verifica: 7.1 verde.
- [x] 7.3 RED — `tests/modules/test_manage_confirm_by_patient.py`: la función
  compartida confirma `pending`, hace replay auditado sobre `confirmed`, rechaza
  turno iniciado y escribe `source` en el payload del evento. Verifica: falla por
  función inexistente.
- [x] 7.4 GREEN — `app/modules/manage/actions.py` (`confirm_by_patient`) y
  `ManageService.confirm` delegando en ella con `source="manage_link"`.
  Verifica: 7.3 verde y todo `tests/modules/test_manage_*.py` (C-08) verde sin cambios en
  sus asserts.
- [x] 7.5 RED — `tests/modules/test_whatsapp_webhook_routing.py`
  (Postgres real): con contexto de un recordatorio se resuelve su turno; contexto
  cuyo paciente no tiene el teléfono del remitente se ignora y cae a teléfono;
  sin contexto con un solo turno futuro vigente entre las clínicas del número se
  resuelve; con turnos en dos clínicas del número compartido → ambiguo; número
  propio de la clínica A no considera pacientes de B; `wa_id` argentino sin el
  `9` matchea un `phone_e164` con `+549`; remitente desconocido → 200, ninguna
  fila y log `whatsapp_inbound_unrouted` sin teléfono. Verifica: falla.
- [x] 7.6 GREEN — `notifications/routing.py`. Verifica: 7.5 verde.
- [x] 7.7 RED — `tests/modules/test_whatsapp_webhook_actions.py`
  (Postgres real): "SÍ" a un turno online `pending` lo deja `confirmed` con
  evento de fuente `whatsapp` y cancela los jobs de 72/24 h; "SÍ" a uno
  `confirmed` → replay; "SÍ" a uno cancelado/iniciado no cambia nada y encola
  `inactive`; "NO" dentro de la ventana encola `change_link`, fuera encola
  `change_contact`, y el turno no cambia; ambiguo encola `ambiguous` en la
  clínica de menor id y filas `whatsapp_inbound` en cada candidata; "BAJA" con
  contexto registra `opt_out/whatsapp_reply`, deja `skipped` los jobs de
  WhatsApp pendientes y encola un `stop_ack`; STOP ambiguo da de baja ambas
  fichas con un solo `stop_ack`; STOP repetido no agrega consentimiento ni
  `stop_ack`; el mismo mensaje reenviado no repite efectos; `whatsapp_inbound`
  no guarda texto ni teléfono. Verifica: falla.
- [x] 7.8 GREEN — manejo de `messages[]` en `notifications/service.py`
  (inserción de `whatsapp_inbound` con `ON CONFLICT`, acciones de la tabla D7,
  creación de respuestas en el outbox). Verifica: 7.7 verde.

## 8. Outbox de respuestas en el worker (D8)

- [x] 8.1 RED — `tests/modules/test_whatsapp_reply_outbox.py` (Postgres
  real, sender fake): una respuesta `pending` se envía como texto libre desde el
  número de su clínica y queda `sent`; con `expires_at` vencido queda `expired`
  sin enviar; paciente con opt-out → `skipped (no_consent)` salvo `stop_ack`, que
  se envía; fallo reintentable reprograma con backoff y tras
  `WHATSAPP_REPLY_MAX_ATTEMPTS` queda `failed`; doble tick concurrente envía una
  sola vez (`SKIP LOCKED`); lease vencido vuelve a `pending`; los textos de cada
  `kind` no contienen el nombre del paciente; `change_link` contiene el link
  firmado del turno y `change_contact` el teléfono de la clínica. Verifica: falla.
- [x] 8.2 GREEN — `notifications/replies.py` (textos y `run_replies`) y la fase
  nueva en `run_tick`, con `choose_message_kind` alimentado por el último
  entrante real. Verifica: 8.1 verde y los tests de `run_tick` de C-09 verdes.

## 9. Consentimiento por personal (D9)

- [x] 9.1 RED — `tests/modules/test_patient_consent_api.py`: recepción
  registra `opt_out` de WhatsApp (fila `reception` con usuario, flag `false`,
  jobs pendientes `skipped`); `opt_in` redundante → 200 sin fila; `opt_in` de
  WhatsApp sin teléfono → `422 phone_required`; de email sin email →
  `422 email_required`; paciente de otra clínica o fusionado → `404`;
  odontólogo → `403 forbidden_role`; sin sesión → 401; campo extra en el cuerpo
  → 422. Verifica: falla.
- [x] 9.2 GREEN — schema (`extra="forbid"`), servicio y ruta
  `PUT /api/patients/{id}/consent/{channel}`. Verifica: 9.1 verde.

## 10. Reporte WhatsApp (D10)

- [x] 10.1 RED — `tests/modules/test_reports_whatsapp.py` (Postgres
  real): tres envíos de 24 h (uno leído, uno entregado, uno fallido después de
  enviado) → `sent 3, delivered 2, read 1, failed 1`; paso sin envíos aparece en
  0; costo suma `payload.cost_micros` y se expresa en USD con 6 decimales;
  mensaje enviado a las 23:30 locales del 31/10 cae en el rango que termina el
  31/10; alterar `reminder_job.status` sin evento no cambia el reporte;
  aislamiento entre clínicas; recepción → 403; `from > to` → 422
  `invalid_range`; parámetro desconocido → 422; `format=csv` con mismas cifras,
  fila total, sin PII ni ids del proveedor; `format=xml` → 422. Verifica: falla.
- [x] 10.2 GREEN — servicio, schemas y ruta `GET /api/reports/whatsapp` en
  `app/modules/reports/`. Verifica: 10.1 verde y la suite de reports de C-13
  verde.

## 11. Frontend: pestaña WhatsApp (D11)

- [x] 11.1 RED — `frontend/src/features/reports/ReportsPage.test.tsx`: la página
  muestra cinco pestañas en el orden del spec; la pestaña WhatsApp muestra filas
  por paso con etiquetas legibles y total; rango sin envíos → mensaje de vacío;
  error 422 → mensaje claro conservando filtros; "Descargar CSV" pide
  `/api/reports/whatsapp?format=csv` con el rango activo. Verifica:
  `npm test -- ReportsPage` falla.
- [x] 11.2 GREEN — `api.ts` (tipo `WhatsAppReport`, sin `any`), panel en
  `Panels.tsx` y pestaña en `ReportsPage.tsx`. Verifica: 11.1 verde y
  `npm run typecheck` limpio (el frontend no tiene script `lint`; CI corre `typecheck`, `build`
  y `test`).

## 12. Documentación operativa (D12)

- [x] 12.1 `backend/README.md` §WhatsApp: suscripción del webhook en Meta
  (URL, verify token, campo `messages`), alta de las 4 plantillas `utility`
  `es_AR` con cuerpo posicional y botones exactos del catálogo, carga de
  `whatsapp_phone_number_id` por clínica y prueba local con `fake`. Verifica:
  los nombres, parámetros y botones del README coinciden con `templates.py`
  (revisión manual contra el test 3.1).
- [x] 12.2 `knowledge-base/10_preguntas_abiertas.md` (número: "ambos soportados,
  decisión comercial pendiente") y `knowledge-base/11_whatsapp_y_recordatorios.md`
  (STOP ambiguo, "NO" no cancela, outbox de respuestas). Verifica: las
  afirmaciones coinciden con los specs del change.

## 13. Gate de integración

- [x] 13.1 En el contenedor py3.12: `pytest -q`, `ruff check`, `black --check` y
  `mypy` limpios en `backend/`; `npm test` y `npm run typecheck`
  en `frontend/`. Verifica: comparar con el baseline de 0.1 (sin regresiones).
- [x] 13.2 Escenario punta a punta con proveedor `fake`: crear turno online →
  tick envía `turno_creado_v1` → POST firmado de `delivered` y `read` → POST
  firmado "SÍ" citando el mensaje → turno `confirmed`, jobs de 72/24 h
  `cancelled`, respuesta `confirmed` enviada en el siguiente tick → el reporte
  WhatsApp del mes muestra el envío leído. Verifica: test de integración
  `tests/modules/test_whatsapp_e2e.py` verde.
- [x] 13.3 `openspec validate c-10-whatsapp-webhook --strict` sin errores.

## Workflow follow-up

- Aprobar (o ajustar) las Open Decisions 3–5 de `proposal.md` antes de `/opsx:apply`.
- Archivar con `/opsx:archive c-10-whatsapp-webhook` y marcar C-10 `[x]` en
  `CHANGES.md` con sus notas de cierre.
- Antes del piloto: decisión comercial número propio vs. compartido (PO/Dueño) y
  aprobación de plantillas en Meta.

## Notas de implementación

### Baseline (0.1, 2026-11-06, contenedor py3.12 + Postgres 15.8 + Redis 7.4)

| Suite | Resultado |
|---|---|
| `pytest -q backend/tests` | 1187 passed, 1 failed (`test_booking_public_create_api.py::test_el_turno_aparece_en_la_agenda_de_recepcion`: `401 invalid_session`; corrido aislado pasa 26/26 → flaky por un pytest concurrente sobre la misma Redis, no se arregla acá) |
| `vitest run` (frontend, Node 24) | 24 archivos, 177 passed |
| `npm run typecheck` | limpio |

### Forma del payload de Meta (0.2)

Sin acceso a una cuenta de Meta desde el entorno de desarrollo, se tomó la forma documentada de
la Cloud API (Graph v19+), que coincide con `design.md` D4–D7:

- Webhook: `{"object": "whatsapp_business_account", "entry": [{"id", "changes": [{"field":
  "messages", "value": {"messaging_product", "metadata": {"display_phone_number",
  "phone_number_id"}, "contacts": [{"profile": {"name"}, "wa_id"}], "messages": [...],
  "statuses": [...]}}]}]}`.
- Mensaje: `{"from", "id", "timestamp" (epoch en string), "type": "text"|"button"|"interactive"|…,
  "text": {"body"}, "button": {"payload", "text"}, "interactive": {"type": "button_reply",
  "button_reply": {"id", "title"}}, "context": {"from", "id"}}`.
- Estado: `{"id", "status": "sent"|"delivered"|"read"|"failed", "timestamp", "recipient_id",
  "errors": [{"code", "title", …}], "conversation", "pricing"}`.
- Envío OK: `{"messaging_product", "contacts": [{"input", "wa_id"}], "messages": [{"id"}]}`;
  error: `{"error": {"message", "type", "code", "error_subcode", "fbtrace_id"}}`.

Validar contra un payload real del número de prueba de Meta antes del piloto (ver README).

### Desvíos de TDD

- 2.1: el test de tablas se corrió por primera vez con los modelos ya escritos (sin registrar el
  RED); falló igual por un nombre de FK truncado a 63 caracteres, que se corrigió.
- 7.7: `inbound.py` (7.8) se escribió junto con el enrutamiento (7.6), así que el test de acciones
  pasó en su primera corrida sin un RED observado. Sus 12 escenarios cubren la tabla de D7.
- 5.3: se acotó a "ningún modelo declara un `extra` relajado" (ver la tarea).

### Gate final (13.1, 2026-11-06)

| Suite | Resultado |
|---|---|
| `pytest -q backend/tests` (py3.12 + Postgres 15.8 + Redis 7.4) | 1411 passed, 0 failed (baseline 1187 + 224 nuevos) |
| `ruff check backend` · `black --check backend` · `mypy backend` | limpios (303 archivos) |
| `vitest run` | 181 passed en dos corridas seguidas; una corrida previa tuvo 1 falla intermitente fuera de `reports` (suite lenta, ~12 s por archivo de booking) que no se reprodujo |
| `npm run typecheck` | limpio |
| `openspec validate c-10-whatsapp-webhook --strict` | válido |

Hallazgo durante 13.2: el evento `sent` del motor tomaba `clock_timestamp()` de la base en lugar
del reloj del tick que fija `sent_at`; se alineó (`occurred_at = now`) para que el reporte filtre
el envío por el mismo instante que el job.
