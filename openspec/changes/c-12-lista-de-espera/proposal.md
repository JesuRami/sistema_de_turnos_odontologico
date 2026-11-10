# Proposal — C-12 `lista-de-espera`

## Why

Hoy un turno cancelado deja un hueco que nadie llena: no hay dónde anotar a un
paciente que quería un horario antes, y recepción no tiene a quién avisar. La
Épica 5 (US-040), la anotación del paciente (US-022) y el Flujo 5 de la KB
—hueco liberado → oferta con expiración → turno— no tienen implementación; solo
existe un stub `GET /waiting-list/ping` de C-01 y la política
`clinic.waitlist_offer_ttl_hours` de C-04. Es el último change del MVP que falta
antes de C-14 (hardening del piloto) y la promesa comercial v1 es "huecos
llenos".

## What Changes

- **Anotación en la lista de espera** (`waiting_list_entry`): por paciente, con
  profesional preferido o "cualquiera", un **período de fechas obligatorio**
  (`date_from`–`date_to`) y, opcional, una **franja horaria** y **días de la
  semana**. Una sola entrada `waiting/offered` por paciente y profesional (o
  "cualquiera"), impuesta en la base (RN-LE-01). La crea recepción desde el panel
  o el paciente desde la página pública `/b/:slug` cuando ningún horario le sirve.
- **Evaluación automática al cancelar** (RN-LE-02, RN-CX-03): toda cancelación
  de un turno futuro (recepción, link de gestión o WhatsApp) busca, en la misma
  transacción, la primera entrada compatible —prioritarias primero, después por
  antigüedad— y le crea una oferta (`waitlist_offer`) para ese hueco exacto. La
  reprogramación no dispara la evaluación (decisión del usuario, 2026-11-08).
- **Oferta con expiración y rotación** (RN-LE-03/04): vence a las
  `waitlist_offer_ttl_hours` (default 4 h) o antes si el turno está cerca;
  vencida o rechazada, pasa a la siguiente entrada compatible para el mismo
  hueco. Rechazar no penaliza; tres vencimientos consecutivos dejan la entrada
  `expired`. Una entrada cuyo período terminó también vence.
- **Aceptar crea el turno** (RN-LE-04/05): turno `confirmed` con origen nuevo
  `waitlist`, por el mismo camino de escritura que recepción (`book`), validando
  horario, bloqueos y la exclusión de la base: no es sobreturno. Dos
  aceptaciones del mismo hueco: gana la primera; la segunda recibe "hueco
  ocupado" y su entrada vuelve a la cola como prioritaria.
- **Envío de la oferta por WhatsApp o email**: plantilla `hueco_lista_espera_v1`
  (y su par de email) con link de la oferta y botones "Tomarlo" / "Paso". El
  envío reutiliza el motor de recordatorios de C-09/C-10 (cola, reintentos,
  escalado a email, estados de Meta, costo), con un `reminder_job` cuyo paso es
  `waitlist_offer`.
- **Respuesta del paciente**: página pública `/o/:token` para aceptar, rechazar
  o rechazar y salir de la lista, y respuesta por los botones de WhatsApp
  interpretada por el webhook de C-10 (decisión del usuario, 2026-11-08).
- **Panel de recepción** `/lista-de-espera`: cola ordenada con filtros por
  profesional y período, ofertas pendientes y vencidas, alta, edición, retiro,
  ofrecimiento manual de un hueco, aceptar/rechazar en nombre del paciente que
  llamó, y **priorización con motivo auditado** como excepción a FIFO (decisión
  del usuario, 2026-11-08; cierra la pregunta abierta Media de `10`).
- **Auditoría append-only** (`waitlist_event`): cada alta, edición, oferta,
  respuesta, vencimiento, prioridad y retiro, con actor y sin PII.
- **Reporte de conversión** lista de espera → turno (diferido de C-13), solo
  admin, con CSV, calculado sobre `waitlist_event`; nueva pestaña en
  `/admin/reportes`. Las ofertas enviadas aparecen como un paso más en el
  reporte de WhatsApp (costo atribuido, RN-WA-05).
- **Migración `c12_waiting_list`**: tablas `waiting_list_entry`,
  `waitlist_offer`, `waitlist_event`; valor `waitlist` en `appointment_origin`;
  `reminder_job` admite un job de oferta (`appointment_id` o `waitlist_offer_id`,
  exactamente uno); paso `waitlist_offer` en las plantillas; `whatsapp_inbound`
  puede apuntar a una oferta.

## Capabilities

### New Capabilities

- `waitlist/entries`: anotación (recepción y pública), unicidad, preferencias,
  edición, retiro, vencimiento por período, prioridad con motivo, cola
  consultable con alcance por rol y aislamiento por clínica.
- `waitlist/offers`: evaluación FIFO con filtro al cancelar, oferta manual,
  expiración y rotación, aceptación que crea el turno `waitlist`, rechazo,
  carrera de aceptaciones y auditoría append-only.
- `waitlist/offer-link`: credencial firmada de la oferta y endpoints públicos
  para verla, aceptarla o rechazarla, con rate-limit y sin PII.
- `waitlist/offer-delivery`: envío de la oferta por el motor de recordatorios
  (canal, plantilla, consentimiento, validación previa y cierre del job cuando
  la oferta deja de estar pendiente).
- `waitlist/conversion-report`: reporte de conversión para admin, sobre eventos,
  con CSV.
- `web/waiting-list`: panel de cola y ofertas para admin y recepción (lectura
  para el odontólogo).
- `web/waitlist-offer`: página pública `/o/:token` de la oferta.

### Modified Capabilities

- `agenda/appointments`: origen `waitlist` (nace `confirmed`, nunca sobreturno,
  sin token aleatorio) y la cancelación dispara la evaluación de la lista.
- `reminders/whatsapp-webhook`: intenciones de aceptar y rechazar una oferta y
  enrutamiento de la respuesta a la oferta citada.
- `reminders/delivery-report`: el reporte suma una fila para el paso
  `waitlist_offer`.
- `core/seed`: plantillas por defecto de la oferta (WhatsApp y email).
- `core/data-export`: la exportación completa incluye entradas, ofertas y
  eventos de la lista de espera.
- `web/public-booking`: opción "Anotarme en la lista de espera" cuando ningún
  horario sirve.
- `web/reports-admin`: pestaña "Lista de espera".

## Impact

- **Backend**: `app/modules/waiting_list/` (reemplaza el stub: `entries.py`,
  `engine.py`, `offers.py`, `links.py`, `public.py`, `router.py`, `schemas.py`),
  `app/modules/appointments/states.py` (gancho de cancelación) y `service.py`
  (origen `waitlist`), `app/modules/reminders/dispatch.py` (rama de jobs de
  oferta), `templates.py`, `app/modules/notifications/` (intenciones, ruteo,
  respuestas), `app/modules/reports/` (conversión y fila del paso),
  `app/modules/reports/exports.py`, `app/worker/settings.py` (tick de
  vencimientos), modelos nuevos y `app/models/enums.py`.
- **Datos**: migración `c12_waiting_list` (`down_revision="c11_reminder_timeline"`).
- **API nueva**: `/api/waiting-list` (cola, alta, edición, retiro, prioridad,
  ofertas, eventos), `POST /api/booking/{slug}/waiting-list`,
  `/api/waitlist-offer/{token}` (vista, aceptar, rechazar),
  `GET /api/reports/waitlist`. Se elimina `GET /waiting-list/ping`.
- **Frontend**: `features/waiting-list/` (panel), `features/waitlist-offer/`
  (página `/o/:token`), `features/booking/` (anotación), `features/reports/`
  (pestaña), rutas en `App.tsx`, tipos en `shared/api/types.ts`.
- **Config**: `WAITLIST_MIN_LEAD_MINUTES`, `WAITLIST_MIN_OFFER_WINDOW_MINUTES`,
  `WAITLIST_MAX_CONSECUTIVE_EXPIRED` y cupos de rate-limit de los endpoints
  públicos, en `.env.example`.
- **Docs**: `knowledge-base/10_preguntas_abiertas.md` (prioridad resuelta) y
  `05`/`04` solo con lo que se apruebe; `backend/README.md` §Lista de espera.

## Fuera de alcance

- Ofrecer automáticamente el hueco que libera una reprogramación, un `absent` o
  un `no_show` (solo cancelación, por KB y decisión del usuario).
- Mensaje de confirmación de la anotación o link para que el paciente gestione
  su entrada (no hay plantilla aprobada; se retira desde la oferta o llamando).
- Ofrecer el mismo hueco a varias personas a la vez (difusión): la oferta es de
  a una por hueco en el circuito automático.
- Mockups de UI: se usan los componentes existentes.

## Open Decisions (defaults aprobados)

> Los siete defaults fueron aprobados tal como están por el usuario
> (2026-11-08).

1. **Expiración real de la oferta** — *Default*: `min(ahora + ttl, inicio − 60
   min)`. Si quedan menos de 15 min de ventana, no se ofrece automáticamente
   (el hueco está demasiado cerca; recepción puede ofrecerlo a mano).
2. **Texto de la plantilla** — *Default*: cambiar "Tenés {{horas}} h" por
   "Tenés hasta las {{vence}}" para no redondear mal una ventana corta. La
   plantilla todavía no está aprobada en Meta.
3. **Estado `cancelled` de la oferta** (no está en la KB) — *Default*: se agrega
   para la oferta que se cierra sin respuesta del paciente: entrada retirada,
   convertida por otra oferta, hueco tomado por otro o retirada por recepción.
4. **"Cola prioritaria" tras perder la carrera** — *Default*: la entrada vuelve a
   `waiting` marcada prioritaria (motivo `slot_lost`), la respuesta muestra hasta
   3 horarios alternativos del mismo profesional como información y el link de
   reserva pública si la clínica la tiene habilitada.
5. **Paciente con otro turno a esa hora** — *Default*: la evaluación lo saltea y
   aceptar responde `409 patient_busy` sin cambios (la oferta sigue pendiente).
6. **Duplicado en la anotación pública** — *Default*: `409 already_waiting` con
   el teléfono de la clínica, como en recepción. Solo lo ve quien conoce nombre
   y teléfono exactos del paciente.
7. **Alcance del odontólogo** — *Default*: lee la cola de su profesional y de
   "cualquiera", sin teléfono ni email, sin acciones (RBAC de `03`: R).
