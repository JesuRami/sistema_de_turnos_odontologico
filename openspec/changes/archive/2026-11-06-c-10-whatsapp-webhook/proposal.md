# Proposal — C-10 `whatsapp-webhook`

## Why

C-09 dejó el motor de recordatorios programando y despachando jobs, pero WhatsApp
—el canal diferencial del MVP— sigue en `disabled|fake`: no hay adaptador de la
Cloud API de Meta, nadie recibe los estados `delivered/read/failed` ni las
respuestas del paciente, y "SÍ/NO/STOP" no hacen nada. Sin este change el
paciente no puede confirmar desde el chat (US-031), la baja por WhatsApp no
existe (RN-WA-01) y no hay forma de medir cuánto cuesta el canal por clínica
(RN-WA-05), que es la base del pricing antes del piloto.

## What Changes

- **Envío real por Cloud API**: proveedor `meta` para `REMINDER_WHATSAPP_PROVIDER`
  detrás del puerto `ReminderSender` de C-09. Plantillas `es_AR` categoría
  `utility` (`turno_creado_v1`, `recordatorio_72h_v1`, `recordatorio_24h_v1`,
  `recordatorio_3h_v1`) con botones de respuesta rápida (Confirmar/SÍ,
  Cambiar/NO, Cancelar) y fecha/hora en formato argentino explícito. Errores de
  Meta mapeados a `SendError` reintentable o definitivo.
- **Número por clínica o compartido**: `clinic.whatsapp_phone_number_id`
  opcional; vacío usa el número compartido de `META_PHONE_NUMBER_ID`. La
  decisión de negocio (pregunta abierta Alta) queda abierta; el sistema soporta
  ambas.
- **Webhook `GET/POST /webhooks/whatsapp`**: handshake de verificación de Meta;
  firma `X-Hub-Signature-256` obligatoria (401 + registro sin PII si falta o no
  coincide); deduplicación por id de evento del proveedor; estados
  `delivered/read/failed` actualizan el job de forma monótona y quedan en
  `delivery_event`.
- **Respuestas del paciente**:
  - "SÍ"/Confirmar → misma transición que el link de gestión
    (`pending → confirmed`, actor `patient_token`), idempotente.
  - "NO"/Cambiar/Cancelar → nunca cancela solo: responde con el link de gestión
    si la ventana de cancelación sigue abierta, o con el teléfono de la clínica si
    no (RN-CX-01).
  - "STOP"/"BAJA"/"no me escriban" → opt-out de WhatsApp inmediato (fuente
    `whatsapp_reply`) con mensaje de confirmación.
  - Enrutamiento por el mensaje respondido (`context.id` → `provider_message_id`);
    sin contexto, por número + teléfono; ante ambigüedad no se toca ningún turno
    (salvo STOP, que se aplica a todas las fichas con ese teléfono en ese número).
- **Mensajes entrantes y respuestas**: tabla `whatsapp_inbound` (solo intención y
  metadatos, nunca el texto) que habilita la ventana de 24 h real (RN-WA-03), y
  outbox `whatsapp_outbound_reply` que el worker envía como mensaje libre dentro
  de esa ventana.
- **Consentimiento por personal**: `PUT /api/patients/{id}/consent/{channel}`
  (admin/recepción) registra opt-in/opt-out con fuente `reception` y usuario.
- **Reporte WhatsApp por clínica** (diferido de C-13): enviados, entregados,
  leídos y fallidos por paso + costo atribuido, solo admin, JSON y CSV, calculado
  sobre `delivery_event`; pestaña "WhatsApp" en `/admin/reportes`.
- **Excepción documentada a la regla dura 2**: el sobre del webhook de Meta usa
  `extra='ignore'` (solo tras verificar la firma); se agrega la excepción
  explícita en `AGENTS.md` y `CLAUDE.md`. Todo otro borde sigue con `forbid`.
- Migración `c10_whatsapp_channel`.

## Capabilities

### New Capabilities

- `reminders/whatsapp-channel`: envío por la Cloud API de Meta — proveedor,
  número por clínica o compartido, plantillas `es_AR` con botones, mapeo de
  errores y configuración obligatoria.
- `reminders/whatsapp-webhook`: recepción de eventos de Meta — verificación,
  firma, deduplicación, estados de entrega, interpretación de SÍ/NO/STOP,
  enrutamiento a clínica/turno y respuestas dentro de la ventana de 24 h.
- `reminders/delivery-report`: reporte de mensajes y costo por clínica y paso,
  solo admin, con CSV.

### Modified Capabilities

- `reminders/dispatch-worker`: el canal WhatsApp suma el proveedor `meta`; la
  ventana de 24 h deja de ser siempre "sin entrante" y usa el último mensaje
  entrante real; la trazabilidad incorpora `delivered/read` y la falla tardía
  informada por Meta.
- `reminders/channel-consent`: baja por respuesta de WhatsApp con efecto
  inmediato y confirmación; el personal puede cambiar el consentimiento de un
  paciente existente.
- `web/reports-admin`: la página suma la pestaña WhatsApp con su descarga CSV.

## Impact

- **Backend**: `app/modules/reminders/senders/meta.py` (nuevo),
  `senders/__init__.py`, `dispatch.py` (ventana real, outbox de respuestas,
  número por clínica), `consent.py`; `app/modules/notifications/` deja de ser stub
  (router del webhook, parser, intents, enrutamiento); `app/modules/reports/`
  (reporte WhatsApp); `app/modules/patients/` (endpoint de consentimiento);
  `app/core/settings.py` (`meta`, validación de credenciales).
- **Datos**: migración `c10_whatsapp_channel` — `clinic.whatsapp_phone_number_id`,
  tablas `whatsapp_inbound` y `whatsapp_outbound_reply` (con `clinic_id`),
  índice sobre `reminder_job.provider_message_id`, nuevos valores de enum.
- **API nueva**: `GET/POST /webhooks/whatsapp`,
  `PUT /api/patients/{id}/consent/{channel}`, `GET /api/reports/whatsapp`.
- **Frontend**: pestaña WhatsApp en `features/reports`.
- **Config**: `REMINDER_WHATSAPP_PROVIDER=meta`; `WHATSAPP_TOKEN`,
  `META_APP_SECRET`, `META_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN`,
  `META_API_VERSION` pasan a leerse (ya están en `.env.example`).
- **Dependencias**: ninguna nueva (`httpx` ya es dependencia de runtime).
- **Docs**: `AGENTS.md`/`CLAUDE.md` (excepción a la regla 2),
  `knowledge-base/10_preguntas_abiertas.md` (estado del número),
  `backend/README.md` (alta operativa de plantillas y del webhook en Meta).

## Fuera de alcance

Timeline de entregas por turno, reenvío/confirmación manual y alerta visible de
`failed` (C-11); oferta de lista de espera y `hueco_lista_espera_v1` (C-12);
`ausencia_recall_v1`; plantilla "turno reprogramado"; botón "Cómo llegar" y
`{{direccion}}` (la clínica no guarda dirección); re-alta (opt-in) por mensaje de
WhatsApp; alerta de umbral de costo mensual; tabla de precios de Meta por
país/categoría (sigue el costo fijo por mensaje de C-09); UI para cargar el
`whatsapp_phone_number_id` de la clínica (seed/DB); UI de consentimiento en ficha
de paciente (C-11).

## Open Decisions (defaults a aprobar)

1. **Regla 2 en el webhook** — *Resuelta por el usuario (2026-11-06)*: excepción
   documentada; `extra='ignore'` solo en los modelos del payload de Meta y solo
   después de verificar la firma.
2. **Número propio vs. compartido** — *Resuelta por el usuario (2026-11-06)*:
   soportar ambos. La decisión comercial sigue abierta para PO/Dueño antes del
   piloto.
3. **"NO" no cancela** — *Default propuesto*: responder con el link o el
   teléfono, nunca cancelar por chat (US-031 CA-2; un "no" suelto es ambiguo).
   *Aprobado por el usuario (2026-11-06).*
4. **STOP ambiguo** — *Default propuesto*: sin contexto y con varias fichas que
   comparten teléfono en el mismo número, la baja se aplica a todas (ante la duda,
   no escribir). *Aprobado por el usuario (2026-11-06).*
5. **Procesamiento síncrono** — *Default propuesto*: el webhook procesa el evento
   en la transacción de la request y responde 200; las respuestas salientes van a
   un outbox que despacha el worker (nada de HTTP a Meta dentro del webhook).
   *Aprobado por el usuario (2026-11-06).*
