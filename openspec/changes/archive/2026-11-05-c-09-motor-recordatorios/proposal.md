# Proposal — C-09 `motor-recordatorios`

## Why

El diferencial del MVP son recordatorios que llegan, se miden y bajan el
ausentismo (`11_whatsapp_y_recordatorios.md`). Hoy el sistema sabe crear,
mover, cancelar y confirmar turnos (C-05/C-07/C-08), pero **no programa ni
envía nada**: `clinic.reminder_steps` es solo configuración, el worker está
ocioso y el punto de invalidación que dejó C-08 es un no-op. C-10 (webhook y
envío real por Cloud API) necesita un motor persistente, idempotente y
reintentable sobre el que enchufarse, y C-13 ya espera `reminder_job` y
`delivery_event` para el reporte mensual de costos. Es **ALTO** porque un
defecto acá manda mensajes duplicados, a quien no dio consentimiento o sobre un
turno que ya no existe (RN-WA-01, RN-CX-03, regla 13).

## What Changes

- **Persistencia del motor** (una sola migración `c09_reminder_engine`, regla 3):
  `notification_template`, `reminder_job` (clave única
  `(appointment_id, step, channel)`), `delivery_event` (append-only) y `consent`
  (append-only), todas con `clinic_id` obligatorio y FK compuesta (regla 4).
  La migración carga las plantillas por defecto de las clínicas existentes y
  hace backfill del consentimiento de los pacientes con `whatsapp_opt_in=true`.
- **Programación**: al crear un turno se insertan sus `reminder_job` (alta de
  turno + los pasos de `clinic.reminder_steps`, hoy 72/24/3 h), con
  `scheduled_for` calculado desde `starts_at`. Solo se programan pasos cuya
  hora todavía no pasó (anti-ruido). Reprogramar recalcula los pendientes y
  cancelar los marca `cancelled`. Confirmar cancela solo los pasos que piden
  confirmar (72 h y 24 h); el de 3 h sigue (decisión del usuario, ver Open
  Decisions).
- **Worker**: tick cada 60 s con `FOR UPDATE SKIP LOCKED LIMIT 100`. Reclama
  con un lease corto (`sending`), valida **antes** de enviar (turno vigente y
  no iniciado, opt-in del canal, plantilla activa, el horario sigue siendo el
  del job, elección plantilla/sesión por la ventana de 24 h de Meta) y recién
  entonces envía. Un job vencido de un turno ya iniciado pasa a `skipped`,
  nunca a `sent`.
- **Fallos**: backoff 5 min → 30 min → 2 h; al tercer fallo el job queda
  `failed` y, si hay email y el paciente no se dio de baja de ese canal, se
  escala creando el job de email del mismo paso. Se guarda
  `provider_message_id`, el intento y el costo atribuible por clínica y paso
  (RN-WA-05).
- **Canales detrás de un puerto** `ReminderSender`: C-09 entrega el contrato,
  un sender `fake` para dev/tests y un adaptador SMTP para el email de
  respaldo. El adaptador real de Cloud API es de C-10; con
  `REMINDER_WHATSAPP_PROVIDER=disabled` (default) el worker no reclama jobs de
  WhatsApp y nada se marca como enviado en falso.
- **Consentimiento**: `ConsentService` único escritor de `consent` y de
  `patient.whatsapp_opt_in` (misma transacción). Los tres lugares que hoy
  escriben el opt-in (reserva pública, alta de paciente por recepción, helper de
  clínica) pasan por él, para que el motor lea un solo dato y cada cambio quede
  auditado con fuente.
- **Link de gestión reproducible**: los mensajes necesitan el link, pero la base
  solo guarda el SHA-256 del token (C-07 D8). Se agrega un segundo formato de
  credencial **firmado y sin estado** (`HMAC` con `MANAGE_LINK_SECRET`) que
  `GET/PATCH /api/manage/{token}` acepta además del token aleatorio, con el
  mismo TTL y las mismas guardas. Resuelve también los turnos de recepción,
  que no tienen token.
- **Reemplazo del puerto de C-08**: `get_reminder_invalidator` devuelve la
  implementación real. El router, el servicio de gestión y la superficie
  pública no cambian.
- **Seed**: `app.seed` crea las plantillas placeholder de cada clínica nueva
  (alta + 72/24/3 h por WhatsApp y su par de email).
- **No es BREAKING** para ningún cliente: no cambia ningún endpoint existente;
  `/api/manage/{token}` solo acepta además un formato nuevo.

## Capabilities

### New Capabilities

- `reminders/job-scheduling`: ciclo de vida de los `reminder_job` frente a las
  mutaciones del turno (alta, reprogramación, cancelación, confirmación),
  reglas anti-ruido, clave de idempotencia y aislamiento por clínica.
- `reminders/dispatch-worker`: tick, reclamo con `SKIP LOCKED`, validaciones
  previas al envío, reintentos con backoff, escalado a email, tope de
  antigüedad, trazabilidad (`delivery_event`, `provider_message_id`) y costo por
  clínica y paso.
- `reminders/channel-consent`: registro append-only de consentimiento por canal
  y paciente, único escritor, sincronía con `patient.whatsapp_opt_in` y efecto
  inmediato sobre los jobs pendientes.

### Modified Capabilities

- `booking/manage-token`: la invalidación de recordatorios deja de ser no-op
  (ahora cancela y reprograma jobs en la misma transacción) y la resolución del
  token acepta además el formato firmado reproducible.
- `core/patients`: todo cambio de `whatsapp_opt_in` registra un consentimiento
  con fuente en la misma transacción.
- `core/seed`: el seed por clínica incluye las plantillas por defecto.

## Impact

- **Backend**: nuevos modelos `ReminderJob`, `DeliveryEvent`,
  `NotificationTemplate`, `Consent` y enums; `app/modules/reminders/`
  (`scheduling.py`, `dispatch.py`, `senders/`, `consent.py`, `links.py`);
  `app/worker/` (tick sobre ARQ, hoy ocioso); ajustes mínimos en
  `AppointmentsService` (`create`/`update`/`transition`), `agenda/blocks.py`,
  `booking_public/service.py`, `manage/service.py` (resolución) y los tres
  escritores del opt-in; `app/seed.py`; `core/settings.py`.
- **Datos**: migración `c09_reminder_engine` (`down_revision =
  c08_manage_token`, cabeza actual). Tablas nuevas, sin tocar columnas de
  tablas existentes: no hay `CREATE INDEX` ni validación sobre tablas con datos
  que requieran `CONCURRENTLY` (regla 11).
- **Configuración** (todo en `.env.example`, regla 6): `MANAGE_LINK_SECRET`,
  `REMINDER_WHATSAPP_PROVIDER`, `REMINDER_EMAIL_PROVIDER`, costos por canal,
  parámetros de backoff/tope; `EMAIL_*` y `REMINDER_WORKER_CONCURRENCY` ya
  existen.
- **Dependencias**: dev-only `aiosmtpd` para probar el adaptador SMTP contra un
  servidor real local.
- **Sin cambios**: frontend, `appointment`, `clinic.reminder_steps`, el reporte
  de C-13.

## Fuera de alcance

Webhook y envío por Cloud API, estados `delivered/read` entrantes, “SÍ/NO/STOP”
(C-10); plantillas aprobadas en Meta; reporte mensual de costos y alerta de
umbral (C-10); lista de espera (C-12); pantalla o alerta de recepción por
`failed` (UI posterior); ventana horaria de silencio nocturno; dirección de la
clínica en el mensaje; cambio de proveedor de email.

## Open Decisions (defaults a aprobar)

1. **Confirmar** — *Resuelta por el usuario (2026-11-05)*: cancela solo los
   pasos que piden confirmar (72 h y 24 h); el de 3 h se mantiene. Los turnos de
   recepción nacen `confirmed` y reciben los tres pasos.
2. **Link reproducible** — *Default propuesto*: token firmado sin estado
   (`D9` del diseño) en vez de rotar el `manage_token` al enviar cada mensaje
   (que mataría los links de mensajes anteriores) o de guardar el token cifrado
   (contradice C-07 D8). Costo: un secreto nuevo (`MANAGE_LINK_SECRET`) cuya
   rotación invalida los links firmados vivos. **Pendiente de aprobación.**
3. **Estado `sending`** — *Default propuesto*: el enum de estados suma
   `sending` (lease de reclamo) respecto de la lista de la KB, para no enviar
   por HTTP con locks de fila abiertos. **Pendiente de aprobación.**
4. **Plantillas seed** — *Default propuesto*: 8 filas por clínica (alta +
   72/24/3 h, WhatsApp y email) en vez de las 3 que nombra CHANGES.md, porque el
   alta de turno es parte del alcance y el escalado a email necesita plantilla.
