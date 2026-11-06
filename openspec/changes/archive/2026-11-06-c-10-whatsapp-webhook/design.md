# Design — C-10 `whatsapp-webhook`

Motivación y alcance: `proposal.md`. Comportamiento exigido: `specs/`.

## Context

- **Cabeza de Alembic**: `c09_reminder_engine`. Esta revisión es
  `c10_whatsapp_channel`.
- **Motor de C-09** (`app/modules/reminders/`): `ReminderSender` (puerto por
  canal, `OutboundMessage` sin PII en `repr`, `SendError(code, retryable)`),
  `build_senders(settings)` con `REMINDER_WHATSAPP_PROVIDER = disabled | fake`,
  `run_tick` (lease, re-chequeo, `_record_success/_record_failure`, escalado a
  email en `_escalate_to_email`), `choose_message_kind(last_inbound_at, now)`
  siempre llamado con `None`, y `build_manage_url` (token firmado `v1.` estable
  por turno, también para turnos de recepción).
- `delivery_event` ya tiene los tipos `delivered`, `read`, `failed` y el único
  parcial `(reminder_job_id, provider_event_id)`; `reminder_job.provider_message_id`
  se guarda pero **no tiene índice**.
- `ConsentService.record(...)` es el único escritor de `consent` y de
  `patient.whatsapp_opt_in`; `ConsentSource.WHATSAPP_REPLY` ya existe. No hay
  endpoint para cambiar el consentimiento de un paciente existente.
- `ManageService.confirm` (C-08) bloquea el turno, rechaza turnos iniciados,
  hace replay auditado si ya está `confirmed` y llama a `apply_transition` con
  `Actor(type=patient_token)`. `apply_transition` ya dispara `reconcile`, así que
  confirmar cancela los pasos que piden confirmación (72/24 h, alta).
- `app/modules/notifications/` es un stub de C-01 montado en `/notifications`.
- `Settings` ya declara `WHATSAPP_TOKEN`, `META_APP_SECRET`,
  `META_PHONE_NUMBER_ID`, `META_API_VERSION` (`v19.0`), `META_VERIFY_TOKEN` como
  `str` sin uso. `httpx` es dependencia de runtime.
- `GlobalRateLimitMiddleware` (en memoria, por IP, `BOOKING_RATE_LIMIT=30/minute`)
  se aplica a todo salvo `/health` y `/ready`.
- `patient.phone_e164` está normalizado con `phonenumbers`; Meta entrega el
  remitente como dígitos sin `+` (`wa_id`).

## Goals / Non-Goals

**Goals:**
- Ningún evento de Meta sin firma válida cambia datos; ningún evento firmado se
  aplica dos veces.
- Una respuesta del paciente nunca toca un turno de otra clínica ni un turno
  elegido por adivinanza.
- El webhook no llama a Meta: responde rápido y las respuestas salen por el worker.
- Reusar las transiciones de C-05/C-08 y el escritor de consentimiento de C-09;
  ninguna regla de negocio duplicada.

**Non-Goals:**
- Mensajes salientes de texto libre que no sean respuesta a un entrante.
- Procesamiento de multimedia, reacciones, ubicaciones: se clasifican `unknown`.
- Persistir el contenido de los mensajes del paciente.

## Decisions

### D1. Modelo de datos (migración `c10_whatsapp_channel`)

| Cambio | Detalle | Regla 11 |
|---|---|---|
| `clinic.whatsapp_phone_number_id text NULL` | CHECK `^[0-9]{5,32}$` | `ADD COLUMN` nullable; CHECK `NOT VALID` → `VALIDATE` |
| `uq_clinic_whatsapp_phone_number_id` | único parcial `WHERE … IS NOT NULL` (un número propio es de una sola clínica; compartido = NULL) | `CONCURRENTLY` en `autocommit_block` |
| `uq_reminder_job_provider_message_id` | único parcial `WHERE provider_message_id IS NOT NULL` (búsqueda del webhook) | `CONCURRENTLY` |
| `whatsapp_inbound` (nueva) | `id, clinic_id, provider_message_id, phone_number_id, patient_id NULL, appointment_id NULL, intent, routed_by, occurred_at, received_at`; UNIQUE `(clinic_id, provider_message_id)`; índice `(clinic_id, patient_id, received_at DESC)` | tabla nueva: índices y FK en el `CREATE` |
| `whatsapp_outbound_reply` (nueva) | `id, clinic_id, inbound_id, patient_id, appointment_id NULL, kind, status, reason, attempts, available_at, expires_at, claimed_at, sent_at, provider_message_id, last_error, timestamps`; UNIQUE `(inbound_id, kind)`; índice de cola `(available_at) WHERE status='pending'` | idem |

- Enums nativos nuevos: `whatsapp_intent` (`confirm, change, stop, unknown`),
  `whatsapp_reply_kind` (`confirmed, change_link, change_contact, inactive,
  ambiguous, stop_ack`), `whatsapp_reply_status` (`pending, sending, sent,
  failed, expired, skipped`). `routed_by` es `text` con CHECK
  (`context|phone`).
- **Regla 4**: ambas tablas con `clinic_id NOT NULL` y FK compuestas
  `(clinic_id, patient_id)`, `(clinic_id, appointment_id)`,
  `(clinic_id, inbound_id)`; test de aislamiento cross-tenant por tabla.
- **Regla 7**: `whatsapp_inbound` es append-only (trigger `BEFORE UPDATE OR
  DELETE`, patrón de `appointment_event`). `whatsapp_outbound_reply` es un outbox
  operativo con estados (como `reminder_job`); nunca se borra.
- **Regla 13**: ninguna tabla guarda teléfono ni texto. El destinatario de una
  respuesta se lee de `patient.phone_e164` al enviar.
- **Dedup multi-clínica**: con número compartido, un STOP sin contexto genera una
  fila por clínica afectada; por eso la unicidad es `(clinic_id,
  provider_message_id)` y no global. El "ya procesado" se decide por
  `INSERT … ON CONFLICT DO NOTHING RETURNING id` en la clínica correspondiente.

**Alternativa descartada**: reutilizar `reminder_job` para las respuestas. Su
clave `(appointment_id, step, channel)` y el CHECK de `step` no admiten respuestas
sin turno (STOP, ambiguo) ni varias por turno, y mezclaría el costo de plantillas
con mensajes de sesión en el reporte.

### D2. Excepción a la regla 2 (decisión del usuario, 2026-11-06)

Los modelos Pydantic del payload de Meta (`MetaWebhookEnvelope` y anidados) usan
`ConfigDict(extra="ignore")`. Condiciones de la excepción, a transcribir en
`AGENTS.md` y `CLAUDE.md` (regla 2) y en el docstring del módulo:

1. Solo aplica a modelos que parsean el cuerpo **después** de verificar
   `X-Hub-Signature-256`; antes de la firma no se parsea nada.
2. Los campos que el sistema consume siguen tipados y validados (ids, tipos,
   timestamps); lo ignorado nunca se persiste ni se loguea.
3. Ningún otro borde (incluidos los query params del GET de verificación) se
   relaja.

Un payload firmado que no valida (estructura mínima ausente) responde **200** y
se registra como `webhook_payload_invalid` (contador + log sin PII): un 4xx haría
que Meta reintente y termine desactivando la suscripción.

### D3. Configuración y validación

- `REMINDER_WHATSAPP_PROVIDER: Literal["disabled", "fake", "meta"]`.
- `WHATSAPP_TOKEN` y `META_APP_SECRET` pasan a `SecretStr` (regla 6; nunca en
  `repr`). Con `meta`, `_validar_seguridad` exige no vacíos `WHATSAPP_TOKEN`,
  `META_APP_SECRET`, `META_PHONE_NUMBER_ID` y `META_VERIFY_TOKEN`
  (`SettingsError` que nombra la variable y no el valor).
- Nuevas: `META_GRAPH_BASE_URL` (default `https://graph.facebook.com`, para tests
  con transporte local), `WHATSAPP_HTTP_TIMEOUT_S` (default 10),
  `WHATSAPP_WEBHOOK_MAX_BYTES` (default 1 MiB), `WHATSAPP_REPLY_MAX_ATTEMPTS`
  (default 3). `.env.example` y `test_env_example.py` se actualizan.
- El webhook no depende del proveedor de envío: con `META_APP_SECRET` vacío todo
  POST responde 401 y con `META_VERIFY_TOKEN` vacío todo GET responde 403 (falla
  cerrada).

### D4. Adaptador Cloud API (`senders/meta.py`)

- `MetaWhatsAppSender(channel=WHATSAPP)` con un `httpx.AsyncClient` compartido
  (creado en `on_startup` del worker y cerrado en `on_shutdown`), autenticación
  `Bearer` en encabezado.
- `POST {base}/{version}/{phone_number_id}/messages` con `type=template`,
  `language.code=es_AR`, componente `body` con parámetros **posicionales** en el
  orden que declara el catálogo (`templates.py` suma `param_order` y `buttons` por
  `meta_template_name`) y componentes `button` `quick_reply` con payload
  `confirm` / `change` / `cancel`. El link va en el cuerpo (no botón URL: evita
  aprobar un dominio por plantilla).
- `OutboundMessage` suma `sender_id: str | None` (phone_number_id) que arma
  `dispatch` desde `clinic.whatsapp_phone_number_id` o `META_PHONE_NUMBER_ID`. El
  contexto de reclamo ya carga la clínica: una columna más en la consulta.
- `send_text(sender_id, to, body)` para respuestas de sesión (D7); el fake la
  implementa también.
- **Mapeo de errores** → `SendError(code="meta_<código>"|"timeout"|"http_5xx"|…)`:

| Respuesta | `retryable` |
|---|---|
| timeout, error de red, HTTP 5xx, 429, códigos 4, 80007, 130429, 131056 (tasa) | sí |
| 401/403, código 190 (token), 131005 (permiso) | sí (se arregla la credencial y siguen saliendo) |
| 131026 (no es usuario), 131021, 131030/131009/131008 (parámetros), 132000–132016 (plantilla), 131047 (fuera de ventana), otro 4xx | no |

  Solo se lee el código numérico del cuerpo de error; el mensaje de Meta (que
  puede traer el teléfono) se descarta sin loguearse.

**Alternativa descartada**: SDK de terceros para WhatsApp — dependencia nueva para
una sola llamada HTTP y otra superficie de logs a auditar.

### D5. Webhook: pipeline

`app/modules/notifications/` deja de ser stub: `router.py` (fino),
`signature.py`, `payload.py` (modelos D2), `intents.py`, `routing.py`,
`service.py` (`WhatsAppWebhookService`), `replies.py`. Router montado sin prefijo
en `/webhooks/whatsapp`; el `ping` del stub se elimina.

1. `GET`: compara `hub.verify_token` con `compare_digest`; responde el challenge
   (`text/plain`) o 403.
2. `POST`: lee el cuerpo crudo con tope `WHATSAPP_WEBHOOK_MAX_BYTES` (413 si se
   excede), verifica `sha256=<hex>` con `hmac.compare_digest` sobre los bytes
   exactos. Fallo → 401 + `logger.warning("webhook_signature_invalid")` sin IP ni
   cuerpo.
3. Parsea el sobre (D2) y separa `statuses[]` y `messages[]` por
   `value.metadata.phone_number_id`.
4. **Cada evento en su propia transacción.** Un error de dominio se registra y se
   sigue; un error inesperado (p. ej. base caída) revierte ese evento y, al final,
   la respuesta es 500 para que Meta reintente el lote (la dedup hace inocuo
   reprocesar lo ya aplicado).
5. El path queda fuera de `GlobalRateLimitMiddleware`: la firma es la
   autenticación y un 429 provocaría reintentos de Meta en ráfaga.

**Alternativa descartada**: encolar el payload en Redis/ARQ y procesar en el
worker. Agrega un salto y un estado intermedio sin beneficio: el procesamiento es
solo SQL (sin HTTP a Meta, D7) y Meta tolera respuestas de cientos de ms.

### D6. Estados de entrega

- Búsqueda del job por `provider_message_id` (índice D1). Sin job → se ignora
  (puede ser una respuesta de sesión o un mensaje de otro sistema); las respuestas
  de sesión no se trackean más allá de `sent` en v1.
- `provider_event_id = f"{message_id}:{status}"`; se inserta `delivery_event`
  con `ON CONFLICT DO NOTHING` sobre el único parcial existente. Si no se insertó,
  es duplicado: fin.
- Avance monótono con rango `sent=1 < delivered=2 < read=3`:
  `UPDATE … SET status=:nuevo WHERE id=:job AND status IN (estados de menor
  rango)`. `occurred_at` del evento es el `timestamp` de Meta.
- `failed`: solo si el job está `sent` pasa a `failed` (`reason=provider_rejected`,
  `last_error="meta_<código>"`) y se llama al escalado a email de C-09, que se
  extrae de `dispatch._escalate_to_email` a `reminders/jobs.py` para usarlo desde
  ambos lados. Si ya está `delivered/read`, solo se registra el evento.
- El evento `sent` del webhook se ignora (el motor ya registró el suyo).

### D7. Mensajes entrantes: intención, enrutamiento y acciones

**Intención** (`intents.py`, función pura): botón `quick_reply` por payload
(`confirm` → confirm; `change`/`cancel` → change); texto normalizado (minúsculas,
sin tildes ni signos, espacios colapsados) contra listas cerradas. `stop` se
evalúa **primero** ("no me escriban", "no quiero mas", "stop", "baja",
"desuscribir"), luego `confirm` ("si", "sí", "confirmo", "confirmar", "ok si"),
luego `change` ("no", "reprogramar", "cambiar", "cancelar", "no puedo"). Coincide
el mensaje completo normalizado, no subcadenas (evita que "si no puedo" confirme).
Cualquier otro tipo (imagen, audio…) → `unknown`.

**Enrutamiento** (`routing.py`):

1. `context.id` → job por `provider_message_id`. Válido solo si el teléfono del
   paciente del turno coincide con el remitente; si no, se ignora el contexto.
   `routed_by=context`.
2. Sin contexto válido: clínicas candidatas = la dueña del `phone_number_id` si
   es propio, o todas las que tienen `whatsapp_phone_number_id IS NULL` si es el
   compartido. Pacientes candidatos = `phone_e164` igual al remitente
   normalizado, no fusionados, en esas clínicas. Para `confirm`/`change`, turno
   candidato = único `pending|confirmed` con `starts_at > now` entre esos
   pacientes. `routed_by=phone`.
3. Remitente: `"+" + wa_id` normalizado con `app.common.phone`. **Argentina**: si
   `wa_id` empieza con `54` y no con `549`, se prueba también con el `9` móvil
   (Meta entrega ambas formas según el cliente).

**Acciones** (todas en la transacción del evento):

| Intención | Resultado del enrutamiento | Efecto | Respuesta |
|---|---|---|---|
| confirm | turno `pending` futuro | transición compartida con C-08 (abajo) | `confirmed` |
| confirm | turno `confirmed` futuro | replay auditado | `confirmed` |
| confirm/change | turno cancelado/iniciado/no operable | nada | `inactive` (teléfono de la clínica) |
| change | turno con ventana abierta | nada | `change_link` (link firmado de D9 de C-09) |
| change | ventana cerrada | nada | `change_contact` |
| confirm/change | 0 o >1 candidatos | nada | `ambiguous` (genérica, sin nombre de clínica) |
| stop | ≥1 paciente | `ConsentService.record(opt_out, WHATSAPP_REPLY)` por paciente | `stop_ack` una vez, si alguno cambió |
| unknown | — | solo registro | ninguna |

- **Transición compartida**: se extrae de `ManageService.confirm` una función
  `confirm_by_patient(session, appointment, *, now, tz, cancellation_window_hours,
  source)` en `app/modules/manage/actions.py` (lock `FOR UPDATE`, guarda de turno
  iniciado, replay `updated` o `apply_transition(CONFIRMED)` con
  `Actor(type=patient_token)` y `extra_payload={"source": source}`). C-08 la usa
  con `source="manage_link"` (comportamiento idéntico, sus tests deben seguir
  verdes) y el webhook con `source="whatsapp"`. Así se cumple el contrato que C-08
  dejó ("C-10 reutiliza ManageService/apply_transition") sin duplicar guardas.
- La fila `whatsapp_inbound` se inserta **antes** de las acciones; si el
  `INSERT … ON CONFLICT` no devuelve id, el evento ya se procesó y no se hace
  nada más.
- Cuando la fila no tiene clínica (remitente sin paciente en ninguna clínica
  candidata), no se persiste nada y se incrementa el contador
  `whatsapp_inbound_unrouted` (log estructurado sin teléfono).
- **Ambiguo con varias clínicas**: se inserta una fila `whatsapp_inbound` por
  clínica candidata (cada una con su `clinic_id`) y la respuesta `ambiguous` se
  atribuye a la clínica candidata de menor `id` (determinista); su texto no
  nombra ninguna clínica.

### D8. Outbox de respuestas y ventana de 24 h

- `whatsapp_outbound_reply` con `expires_at = received_at del entrante + 24 h`
  (RN-WA-03) y `available_at = now`. `UNIQUE (inbound_id, kind)` hace idempotente
  la creación.
- `run_tick` suma una fase `run_replies` con el mismo patrón de C-09: reclamo
  `FOR UPDATE SKIP LOCKED` en tx corta → `sending` con lease → envío fuera de la
  transacción → tx de resultado. Reintentos con el backoff de C-09 hasta
  `WHATSAPP_REPLY_MAX_ATTEMPTS`; luego `failed` (sin escalado a email).
- Validación previa: `now ≥ expires_at` → `expired`
  (`choose_message_kind(last_inbound_at, now) != "session"`, ahora con el último
  entrante real de `whatsapp_inbound`); paciente sin `whatsapp_opt_in` y
  `kind != stop_ack` → `skipped (no_consent)`; paciente sin teléfono →
  `skipped (no_recipient)`.
- Textos fijos en `replies.py` (es_AR, sin PII salvo el link del propio turno y
  el nombre/teléfono de la clínica), uno por `kind`.
- **Recordatorios**: siguen siempre como plantilla aunque la ventana esté
  abierta (spec `dispatch-worker` → "Recordatorio con ventana abierta");
  `_build_message` deja de llamar a `choose_message_kind`.

### D9. Consentimiento por personal

`PUT /api/patients/{id}/consent/{channel}` con cuerpo `{"status": "opt_in" |
"opt_out"}` (`extra='forbid'`), roles admin/recepción, `clinic_id` del
`Principal`. Delegación directa a `ConsentService.record(..., source=RECEPTION,
user_id=principal.user_id)`. `opt_in` de WhatsApp sin `phone_e164` → `422
phone_required`; `opt_in` de email sin email → `422 email_required`. Paciente
fusionado o de otra clínica → `404 patient_not_found`. Respuesta: estado vigente
por canal.

### D10. Reporte WhatsApp (`GET /api/reports/whatsapp`)

- Mismos helpers de rango, `only_params` y CSV de C-13 (`csv_response`,
  neutralización de fórmulas). Parámetros `from`, `to`, `format`.
- **Cohorte**: jobs de la clínica con evento `sent` cuyo `occurred_at` cae en el
  rango local (`[from 00:00, to+1 00:00)` en `clinic.timezone`, convertido a UTC).
  Por job de la cohorte: `delivered` si tiene evento `delivered` o `read`; `read`
  si tiene `read`; `failed` si tiene `failed` posterior al `sent`. `step` y
  `channel` se leen de `reminder_job` (inmutables desde la inserción).
- **Costo sobre eventos** (regla 8): desde C-10 el evento `sent` lleva
  `payload.cost_micros`; el reporte suma ese valor (ausente → 0). `reminder_job.
  cost_micros` se sigue escribiendo para compatibilidad. Salida en USD con 6
  decimales (`Decimal`, string en JSON).
- Filas: `created` + pasos de `clinic.reminder_steps`, por canal `whatsapp` y
  `email`, con 0 si no hubo; más fila `total`.
- Una sola consulta agregada (`COUNT(*) FILTER (WHERE …)` sobre un `GROUP BY
  job` con `bool_or` por tipo de evento); columnas nombradas.

### D11. Frontend

`features/reports`: pestaña WhatsApp en `ReportsPage` (orden: Ocupación,
Ausentismo, Cancelaciones, WhatsApp, Auditoría), `api.ts` con tipo
`WhatsAppReport` (sin `any`), etiquetas de paso legibles (`created` → "Alta de
turno", `t_72h` → "72 h antes"), costo formateado en USD y "Descargar CSV" con el
helper existente. Tests con Vitest + MSW como el resto de la página.

### D12. Documentación operativa

- `backend/README.md` §WhatsApp: alta del webhook en Meta (URL, verify token,
  campos `messages`), alta de las 4 plantillas `utility` `es_AR` con sus cuerpos
  posicionales y botones exactos, carga de `whatsapp_phone_number_id` por clínica
  (seed/SQL) y cómo probar con el proveedor `fake`.
- `knowledge-base/10_preguntas_abiertas.md`: el número queda "soportado ambos,
  decisión comercial pendiente".
- `AGENTS.md` y `CLAUDE.md`: excepción de la regla 2 (D2), idéntica en ambos.

## Risks / Trade-offs

- **[Excepción a una regla dura]** → acotada a modelos posteriores a la firma,
  documentada en ambos archivos de reglas y cubierta por un test que verifica que
  ningún otro schema del repo usa `extra` distinto de `forbid`.
- **[Formato del `wa_id` argentino con/sin `9`]** → doble intento de match (D7.3);
  si aun así no matchea, el mensaje queda como no enrutado y el paciente sigue
  teniendo el link.
- **[STOP ambiguo da de baja fichas de más]** → preferible a escribirle a quien
  pidió no recibir mensajes; recepción puede reactivar con el endpoint D9.
- **[Ventana entre `sent` y la llegada del contexto]** → si el paciente responde
  antes de que se registre `provider_message_id` (worker caído entre el envío y el
  resultado), el contexto no resuelve y se cae al enrutamiento por teléfono.
- **[Eventos de Meta fuera de orden]** → avance monótono por rango; los eventos se
  guardan siempre.
- **[Reintentos de Meta ante 500]** → reprocesar es inocuo por la dedup por
  clínica y por `(job, provider_event_id)`.
- **[Costo fijo por mensaje]** → el reporte es tan preciso como
  `REMINDER_COST_WHATSAPP_MICROS`; la tabla de precios por país/categoría queda
  fuera.
- **[Replay de un webhook firmado capturado]** → la dedup lo neutraliza; Meta no
  firma un timestamp, así que no hay ventana de frescura que verificar.

## Migration Plan

1. `alembic upgrade head` aplica `c10_whatsapp_channel` (columna nullable + CHECK
   `NOT VALID`/`VALIDATE`, dos índices `CONCURRENTLY`, dos tablas, tres enums,
   trigger append-only).
2. Desplegar `api` y `worker` con `REMINDER_WHATSAPP_PROVIDER=disabled`: el
   webhook ya verifica y procesa estados/respuestas, sin enviar.
3. En Meta: suscribir el webhook (`GET` de verificación) y aprobar las plantillas
   (README). Cargar `whatsapp_phone_number_id` de las clínicas con número propio.
4. Pasar a `REMINDER_WHATSAPP_PROVIDER=meta` en el entorno del piloto.
5. **Rollback**: volver a `disabled` detiene envíos al instante;
   `alembic downgrade c09_reminder_engine` borra las dos tablas, los enums, los
   índices y la columna (los `consent` de `whatsapp_reply` quedan: son historial
   válido).

## Open Questions

- Textos finales de las plantillas tras la revisión de Meta: pueden cambiar sin
  tocar código mientras se respeten el orden de parámetros y los botones del
  catálogo.
- ¿Respuesta a mensajes `unknown` dentro de la ventana (p. ej. "No entendí, usá tu
  link")? Es un `kind` más del outbox si el piloto lo pide.
