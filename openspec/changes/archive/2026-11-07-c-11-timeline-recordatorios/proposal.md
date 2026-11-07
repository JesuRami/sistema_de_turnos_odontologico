# Proposal — C-11 `timeline-recordatorios`

## Why

C-09 dejó el motor de recordatorios y C-10 el canal WhatsApp bidireccional, pero
recepción sigue sin poder **ver** qué pasó con cada mensaje ni **actuar** cuando
el paciente no responde o el envío falla. US-032 —"operar recordatorios desde
recepción"— y el paso 3 del Flujo 4 (confirmación manual / reenvío para
no-respondedores) no tienen dónde ejecutarse: los jobs y los eventos existen en
la base, pero no hay timeline, no hay reenvío manual, no hay una lista de
"pendientes sin confirmar" y una falla reiterada solo escala a email, sin alerta
visible en la agenda.

Sin este change, el día operativo de recepción sigue dependiendo de abrir la
base o de llamar a todos los turnos `pending` sin saber si el recordatorio salió,
se entregó, se leyó o falló.

## What Changes

- **Timeline de recordatorios por turno**: `GET /api/appointments/{id}/reminders`
  devuelve, por paso y canal, el estado vigente, las fechas relevantes, los
  intentos, el último error (código, sin PII) y la lista cronológica de eventos
  (`scheduled`, `sent`, `delivered`, `read`, `failed`, `skipped`, `cancelled`,
  `manual_resend`). Admin y recepción ven todo lo de su clínica; el odontólogo,
  solo sus turnos y sin acciones.
- **Estado efectivo derivado de eventos**: la UI no confía en el estado mutable
  del job. Si existe un evento `read` el estado efectivo es `read`; si existe
  `delivered`, es `delivered`; si el último intento falló, es `failed`. Esto
  cubre los estados contradictorios que Meta puede enviar (un mensaje
  `delivered` y `failed` a la vez) y los `read` sin `delivered` previo.
- **Reenvío manual**: `POST /api/appointments/{id}/reminders/{step}/{channel}/resend`
  (admin/recepción) reencola el mismo job para el próximo tick, con guardas de
  turno vigente, no iniciado, consentimiento del canal, destinatario, cooldown y
  tope diario. Cada reenvío se registra en una tabla append-only
  (`reminder_manual_resend`) con actor y nota opcional (sin PII).
- **Reenvío compatible con el recálculo**: un job reenviado manualmente no se
  cancela por "paso vencido" en el siguiente `reconcile` si el turno no cambió
  de horario; sí se cancela si el turno se reprograma o se cancela.
- **Confirmación manual auditada**: se reutiliza
  `POST /api/appointments/{id}/transitions` con `to=confirmed`, que ya escribe
  `appointment_event` en la misma transacción (RN-GL-01) y ya está limitado a
  admin/recepción por la máquina de estados. No se agrega un endpoint nuevo.
- **Pendientes sin confirmar y alerta de fallos**:
  `GET /api/reminders/follow-up?from=&to=` devuelve los turnos del rango que
  requieren llamada: turnos `pending` cuyo paso de confirmación ya se envió y
  siguen sin confirmar, y turnos con un job `failed` sin reenvío exitoso
  posterior. La agenda muestra el contador, un filtro y el motivo por turno.
- **Reporte de entregas ajustado**: un reenvío manual cuenta como un envío más
  (evento `sent`) y suma su costo; entregados/leídos se siguen contando una vez
  por job. El reporte no queda desfasado entre mensajes enviados y costo.
- **Migración `c11_reminder_timeline`**: tabla `reminder_manual_resend`
  append-only, columna `reminder_job.manual_resend_at` (marcador para el
  recálculo y el cooldown) e índice parcial de jobs `failed`.
- **UI en la agenda**: timeline dentro del detalle del turno, botón "Reenviar"
  por paso accionable, confirmación manual existente y panel/filtro "Sin
  confirmar / Fallos de envío" en la agenda del día.

## Capabilities

### New Capabilities

- `reminders/delivery-timeline`: lectura del timeline de recordatorios de un
  turno, con estado efectivo derivado de eventos, RBAC y aislamiento por
  clínica.
- `reminders/manual-actions`: reenvío manual con guardas, límites, auditoría
  append-only y confirmación manual auditada por la transición existente.
- `reminders/followup-board`: lista operativa de pendientes sin confirmar y de
  fallos de entrega para el día, con su alerta visible.

### Modified Capabilities

- `reminders/job-scheduling`: un reenvío manual pendiente sobrevive al
  recálculo de jobs mientras el turno no cambie; se cancela al reprogramar o
  cancelar.
- `reminders/delivery-report`: el conteo de enviados pasa a basarse en eventos
  `sent` (incluye reenvíos manuales) y el costo suma todos los envíos.
- `web/agenda-board`: el detalle del turno suma el timeline y las acciones de
  reenvío; la agenda suma el panel de seguimiento y sus filtros.

## Impact

- **Backend**:
  - `app/modules/reminders/`: `timeline.py` (nuevo), `manual.py` (nuevo),
    `followup.py` (nuevo), `router.py` (rutas), `schemas.py` (contratos),
    `scheduling.py` (guard de `manual_resend_at` en `reconcile`).
  - `app/models/reminder_job.py` (columna `manual_resend_at` + índice parcial),
    `app/models/reminder_manual_resend.py` (nuevo), `app/models/__init__.py`.
  - `app/modules/reports/whatsapp.py` (conteo de enviados por evento).
  - `app/core/settings.py` y `.env.example` (cooldown y tope diario).
- **Datos**: migración `c11_reminder_timeline` — tabla nueva con FKs compuestas
  y trigger append-only, columna nullable en `reminder_job`, índice parcial
  `failed`. Sin cambios de enum.
- **API nueva**:
  - `GET /api/appointments/{id}/reminders`
  - `POST /api/appointments/{id}/reminders/{step}/{channel}/resend`
  - `GET /api/reminders/follow-up?from=&to=`
- **Frontend**: `features/agenda/ReminderTimeline.tsx` (nuevo),
  `AppointmentDetail.tsx`, `AgendaPage.tsx`, `shared/api/types.ts`,
  `shared/api/queries.ts`, tests Vitest + MSW.
- **Config**: `REMINDER_MANUAL_RESEND_COOLDOWN_S` (default 60) y
  `REMINDER_MANUAL_RESEND_MAX_PER_DAY` (default 3).
- **Docs**: `AGENTS.md`/`CLAUDE.md` no cambian (no hay regla nueva); se
  actualizan `backend/README.md` (operación del reenvío) y
  `knowledge-base/10_preguntas_abiertas.md` solo si se aprueban los defaults.

## Fuera de alcance

- Mockups de UI: salteados por decisión explícita del usuario (2026-11-07).
- UI de consentimiento en la ficha del paciente (diferida desde C-10): no entra
  en este change; el opt-in se registra con `PUT /api/patients/{id}/consent/{canal}`.
- Reenvío masivo o campañas; recordatorios de `recall` y plantilla "turno
  reprogramado".
- Botón de "descartar alerta" o silenciar fallos: la alerta desaparece cuando el
  job deja de estar `failed` o el turno deja de estar vigente/futuro.
- Edición del texto de la plantilla o del canal desde la UI.
- Cambios en C-09/C-10 ya archivados más allá de los puntos de integración
  listados (recálculo y reporte).

## Open Decisions (defaults a aprobar)

1. **Cooldown y tope de reenvíos** — *Default propuesto*: 60 s entre reenvíos
   del mismo job y 3 reenvíos manuales por job por día local de la clínica. No
   está en la KB; se propone para evitar doble clic y spam al paciente. Si se
   rechaza, el endpoint queda sin límite y el riesgo se documenta.
2. **Qué cuenta como "pendiente sin confirmar"** — *Default propuesto*: turno
   `pending` con un evento `sent` del paso que pide confirmación más cercano ya
   enviado (`t_24h` si está configurado; si no, el último paso de confirmación
   enviado). Un turno cuyo recordatorio falló se muestra como "fallo de envío",
   no como "no respondió".
3. **Estado efectivo ante eventos contradictorios** — *Default propuesto*:
   `read` > `delivered` > `failed` del último intento > estado del job. Meta
   documenta que un mismo mensaje puede generar `delivered` y `failed`, y que
   `read` implica `delivered` aunque no llegue el evento `delivered`.
4. **Reenvío y estados tardíos del mensaje anterior** — *Default propuesto*: el
   reenvío limpia `provider_message_id`; los `delivered/read/failed` tardíos del
   mensaje anterior se ignoran (no hay job que los mapee). El timeline conserva
   el evento `sent` anterior. Se evita atribuir un estado viejo al mensaje nuevo.
5. **Conteo del reporte** — *Default propuesto*: `sent` cuenta eventos `sent`
   (incluye reenvíos); `delivered/read` cuentan una vez por job; `failed` cuenta
   el último intento. El costo suma todos los `sent`.
6. **Alcance del odontólogo** — *Default propuesto*: puede leer el timeline de
   sus propios turnos (sin datos de contacto extra) pero no puede reenviar ni
   confirmar; la UI le oculta las acciones.
