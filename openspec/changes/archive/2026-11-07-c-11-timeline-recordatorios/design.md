# Design — C-11 `timeline-recordatorios`

Motivación y alcance: `proposal.md`. Comportamiento exigido: `specs/`.

## Context

- **Cabeza de Alembic**: `c10_whatsapp_channel`. Esta revisión es
  `c11_reminder_timeline`.
- **Motor de C-09** (`app/modules/reminders/`): `reminder_job` con la clave única
  `(appointment_id, step, channel)`, estado mutable y `delivery_event`
  append-only (trigger `BEFORE UPDATE OR DELETE`). `reconcile` recalcula los
  jobs `scheduled` a partir del estado del turno y cancela con `STEP_ELAPSED` los
  pasos cuya hora ya pasó.
- **Canal de C-10**: `delivered/read/failed` actualizan el job de forma monótona
  y quedan en `delivery_event`; `provider_message_id` es único parcial y el
  webhook busca el job por ese id. El reporte lee eventos, pero su cohorte
  agrupa por job.
- **Turnos de C-05/C-06**: `AppointmentsService._scoped` aplica clínica y, para
  odontólogo, su `professional_id`; `apply_transition` ya escribe
  `appointment_event` en la misma transacción (RN-GL-01) y la matriz de estados
  limita `pending → confirmed` a admin/recepción (`_FRONT_DESK`).
- **Agenda SPA**: `AppointmentDetail` ya confirma turnos `pending` con
  `POST /api/appointments/{id}/transitions`; `allowedActions` oculta acciones
  según rol. `AgendaPage` ya filtra por estado y destaca pendientes próximos.
- **Meta (Context7, 2026-11-07)**: no garantiza exactamente-una-entrega ni orden;
  puede reenviar webhooks, un mismo mensaje puede generar `delivered` y `failed`,
  y un `read` puede llegar sin `delivered` previo. El timeline no puede confiar
  en un único estado mutable.

## Goals / Non-Goals

**Goals:**

- Que recepción vea, por turno y paso, qué se programó, qué salió, qué se
  entregó/leyó y qué falló, sin abrir la base ni cruzar clínicas.
- Que pueda reenviar un recordatorio o confirmar un turno sin salirse de la
  agenda, con auditoría y sin duplicar el mensaje por doble clic.
- Que los turnos que necesitan llamada aparezcan solos, con el motivo correcto
  (no respondió vs. fallo de envío).
- Reusar el motor, la transición y el reporte existentes; no duplicar reglas.

**Non-Goals:**

- Cambiar la secuencia automática de pasos ni el texto de las plantillas.
- Enviar desde la request: el reenvío solo reencola y el worker despacha.
- Persistir contenido de mensajes ni datos personales nuevos.
- Implementar el change, generar mockups o archivar en esta etapa.

## Decisions

### D1. Modelo de datos (migración `c11_reminder_timeline`)

| Cambio | Detalle | Regla 11 |
|---|---|---|
| `reminder_manual_resend` (nueva) | `id, clinic_id, appointment_id, reminder_job_id, actor_user_id, note NULL, created_at`; FKs compuestas `(clinic_id, appointment_id) → appointment`, `(clinic_id, reminder_job_id) → reminder_job`, `(clinic_id, actor_user_id) → user`; `note` con CHECK `char_length(note) <= 200` | tabla nueva: índices y FK en el `CREATE` |
| `reminder_job.manual_resend_at timestamptz NULL` | Marcador del último reenvío manual del job; el recálculo lo usa para no cancelar por paso vencido | `ADD COLUMN` nullable (sin rewrite) |
| `ix_reminder_job_failed` | Parcial `(clinic_id, scheduled_for) WHERE status = 'failed'` para la lista de seguimiento | `CONCURRENTLY` en `autocommit_block` |
| `ix_reminder_manual_resend_job` | `(clinic_id, reminder_job_id, created_at DESC)` | índice de tabla nueva |
| `ix_reminder_manual_resend_appointment` | `(clinic_id, appointment_id, created_at DESC)` | índice de tabla nueva |
| Trigger append-only | `BEFORE UPDATE OR DELETE` sobre `reminder_manual_resend`, patrón de `appointment_event` | tabla nueva |

- **Por qué una tabla y no solo columnas**: US-032 CA-2 pide auditoría del
  reenvío. `manual_resend_at` solo guarda el último; la tabla conserva cada
  acción con su actor. No se toca `delivery_event` ni el enum
  `delivery_event_type`, así el downgrade es limpio.
- **Regla 4**: `clinic_id NOT NULL` y FKs compuestas; test de aislamiento
  cross-tenant.
- **Regla 7**: la tabla es append-only; el job sigue siendo la máquina de
  estados operativa y nunca se borra.
- **Regla 13**: `note` es una nota operativa corta; el endpoint y los tests
  rechazan un `note` con teléfono/email/DNI. No se guarda ningún dato del
  paciente.

### D2. Estado efectivo del timeline (eventos, no estado mutable)

El timeline devuelve por job:

- `status`: estado efectivo para la **última generación de envío**:
  1. si hay un evento `read` posterior al último `sent` → `read`;
  2. si no, si hay un `delivered` posterior al último `sent` → `delivered`;
  3. si no, si hay un `failed` posterior al último `sent` → `failed`;
  4. si no, el `status` del job (`scheduled`, `sending`, `sent`, `skipped`,
     `cancelled`).
- `events`: todos los eventos del job en orden cronológico, incluidos los de
  intentos anteriores y los `manual_resend` de la tabla D1.
- `scheduled` no es un evento: se sintetiza como primer hito con
  `scheduled_for` y `available_at`, para que la UI muestre la secuencia completa
  que pide US-032 CA-1.

**Por qué no `job.status` solo**: Meta puede mandar `delivered` y `failed` del
mismo mensaje, y `read` sin `delivered` (Context7). El job conserva el último
estado que aplicó C-10; el timeline muestra lo que realmente ocurrió. La regla
`read > delivered > failed` refleja que "entregado a al menos un dispositivo"
gana sobre una falla posterior, y que un `read` implica entrega.

**Reenvío**: al limpiar `provider_message_id`, los estados tardíos del mensaje
anterior no encuentran job y se ignoran (C-10 D6). El evento `sent` anterior
queda en el timeline; el nuevo intento arranca en `scheduled`. Es una pérdida
consciente de la trazabilidad del mensaje viejo a cambio de no atribuir un
`delivered/read` viejo al mensaje nuevo; se documenta en la UI como "envío
anterior".

### D3. Contrato del timeline

`GET /api/appointments/{appointment_id}/reminders`

- Roles: admin, recepción y odontólogo. El odontólogo solo ve sus turnos
  (mismo alcance SQL que `AppointmentsService._scoped`); turno de otra clínica o
  ajeno → `404 not_found`. Sin sesión → `401`.
- Respuesta (sin PII ni ids del proveedor):

```json
{
  "appointment_id": "…",
  "timezone": "America/Argentina/Buenos_Aires",
  "pending_confirmation": true,
  "steps": [
    {
      "step": "t_24h",
      "channel": "whatsapp",
      "status": "delivered",
      "reason": null,
      "scheduled_for": "…",
      "available_at": "…",
      "sent_at": "…",
      "attempts": 1,
      "last_error": null,
      "manual_resends_today": 0,
      "last_manual_resend_at": null,
      "can_resend": true,
      "resend_blocked_reason": null,
      "events": [
        {"type": "sent", "occurred_at": "…", "detail": {"attempt": 1, "kind": "template"}},
        {"type": "delivered", "occurred_at": "…", "detail": {}}
      ]
    }
  ]
}
```

- `detail` solo expone un subconjunto seguro del `payload`: `attempt`, `kind`,
  `reason`, `cost_micros`, `to` y `manual`; nunca `provider_message_id`, links,
  nombre, teléfono ni email.
- `can_resend` y `resend_blocked_reason` los calcula el servidor con las mismas
  guardas de D4, para que la UI no invente reglas. Razones: `no_consent`,
  `no_recipient`, `appointment_started`, `appointment_inactive`,
  `step_not_applicable`, `reminder_in_flight`, `reminder_pending`,
  `resend_cooldown`, `resend_limit`.
- Orden: pasos `created`, `t_72h`, `t_24h`, `t_3h` y luego cualquier paso con
  jobs; dentro de cada paso, canales `whatsapp`, `email`; eventos por
  `occurred_at` ascendente.
- Una sola consulta de jobs y una de eventos por turno (sin N+1); se seleccionan
  columnas explícitas (regla 8). El número de jobs por turno es acotado por la
  configuración de pasos.

### D4. Reenvío manual: guardas, transacción y auditoría

`POST /api/appointments/{appointment_id}/reminders/{step}/{channel}/resend`

- Roles: admin y recepción. Odontólogo → `403 forbidden_role`.
  Sin sesión → `401`. Turno de otra clínica → `404 not_found`.
- Cuerpo: `{"note": "…"}` opcional, `extra='forbid'`, `note` ≤ 200 y sin
  teléfono/email/DNI (validación explícita; el mensaje de error no repite el
  valor).
- Guardas, en este orden riguroso, dentro de una transacción con `SELECT … FOR UPDATE`
  del turno y del job:
  1. turno vigente (`pending` o `confirmed`) → si no, `409 appointment_inactive`;
  2. `now < starts_at` → si no, `409 appointment_started`;
  3. job existe para `(appointment_id, step, channel)` → si no,
     `404 reminder_not_found`;
  4. el paso sigue configurado en `clinic.reminder_steps` (o es `created`) → si
     no, `409 step_not_applicable`;
  5. si el job está `cancelled` → `409 step_not_applicable` (paso no aplicable);
  6. si el paso pide confirmación y el turno es online + `confirmed` → no se
     reenvía (`409 step_not_applicable`), porque la secuencia ya lo canceló por
     confirmación;
  7. consentimiento y destinatario: WhatsApp exige `whatsapp_opt_in`; email exige
     `email` y no estar dado de baja → si no, `409 no_consent` / `409 no_recipient`;
  8. cooldown y tope diario (D6): evaluados antes de inspeccionar si está en vuelo
     o en curso. Si `now - max(created_at) < cooldown` o si el job tiene
     `status = 'scheduled' AND manual_resend_at IS NOT NULL` → `409 resend_cooldown`
     con `retry_after_s`; si ya alcanzó el tope diario local → `409 resend_limit`;
  9. estado del job: si está en `sending` → `409 reminder_in_flight`; si está
     `scheduled` ordinario (`manual_resend_at IS NULL`) → `409 reminder_pending`
     (evita adelantar un paso futuro aún no intentado).
- Efecto, en la misma transacción:
  - insertar `reminder_manual_resend` (actor, nota);
  - `UPDATE reminder_job SET status='scheduled', available_at=now, attempts=0,
    claimed_at=NULL, last_error=NULL, sent_at=NULL, provider_message_id=NULL,
    cost_micros=NULL, reason=NULL, manual_resend_at=now`;
  - mantener `scheduled_for` y `starts_at_snapshot` (trazabilidad del paso).
- Respuesta `202 Accepted` con `{job_id, status:"scheduled", available_at,
  manual_resends_today, cooldown_until}`. El worker lo envía en el próximo tick;
  la request no llama a Meta ni al SMTP.
- **Alternativa descartada**: enviar desde la request. Rompe el lease, el
  backoff y la idempotencia del worker, y deja la API expuesta a timeouts del
  proveedor.
- **Alternativa descartada**: crear un job nuevo con `generation`. Cambia la
  clave de idempotencia de RN-WA-04 y obliga a tocar `reconcile`, el webhook y
  el reporte; el reset conserva una sola fila por paso/canal y el histórico vive
  en los eventos.

### D5. Integración con `reconcile`

`reconcile` solo toca jobs `scheduled`. Un reenvío manual deja el job
`scheduled` con `available_at=now`, pero su `scheduled_for` original ya pasó. En
el siguiente `reconcile` (una confirmación, un cambio de configuración) el paso
caería en la rama `STEP_ELAPSED` y se cancelaría antes de que el worker lo envíe.
Para evitarlo:

- si `fila.manual_resend_at IS NOT NULL` y
  `fila.starts_at_snapshot == appointment.starts_at` y el turno sigue vigente y
  el paso sigue configurado, el job **no** se cancela por paso vencido;
- si el turno se reprograma (`starts_at` nuevo): conforme a la spec principal
  de `job-scheduling`, si el paso vuelve a quedar en el futuro respecto al nuevo
  horario, el job se recalcula (`scheduled_for = new_starts_at - offset`,
  `starts_at_snapshot = new_starts_at`, `manual_resend_at = NULL`) y sigue
  `scheduled`; si el paso ya no queda en el futuro respecto al nuevo horario,
  queda `cancelled` con `STEP_ELAPSED`;
- si el turno se cancela o el paso se elimina de la clínica, se cancela igual.

El marcador `manual_resend_at` se limpia cuando el job sale de `scheduled`
(envío exitoso, fallo definitivo, skip o cancelación) para no dejar protección
colgada.

### D6. Cooldown, tope y concurrencia

- `REMINDER_MANUAL_RESEND_COOLDOWN_S` default 60:
  `now - max(created_at)` de `reminder_manual_resend` del job < cooldown →
  `409 resend_cooldown` con `retry_after_s`.
- `REMINDER_MANUAL_RESEND_MAX_PER_DAY` default 3: cuenta las filas del job cuya
  `created_at` cae en el día local de la clínica; al llegar al tope →
  `409 resend_limit`.
- **Doble clic / dos recepcionistas**: el `FOR UPDATE` del job serializa. La
  primera request inserta la fila y resetea; la segunda, al re-leer, ve la fila
  y cae en cooldown. Test con dos requests concurrentes: una `202`, una `409`, y
  una sola fila de auditoría.
- Los defaults no están en la KB; quedan como Open Decision 1 del proposal.

### D7. Confirmación manual

No se agrega endpoint. La UI usa
`POST /api/appointments/{id}/transitions` con `{"to": "confirmed"}`:

- `apply_transition` bloquea el turno, valida `pending → confirmed` con
  `_FRONT_DESK` (admin/recepción) y escribe `appointment_event` con
  `actor_type=user` y `actor_user_id` en la misma transacción (RN-GL-01).
- Odontólogo → `403 forbidden_role` (ya lo impone la matriz de estados).
- El timeline no duplica el evento de confirmación: muestra el estado del turno
  (`confirmed`) y deja la auditoría completa en `appointment_event` (solo admin
  la ve por `GET /events`, como en C-05).
- Test de contrato: recepción confirma un `pending` → 200, turno `confirmed`,
  evento con actor; odontólogo → 403 y sin evento.

### D8. Lista de seguimiento y alerta de fallos

`GET /api/reminders/follow-up?from=&to=` (admin/recepción; odontólogo → `403`):

- `from`/`to` son instantes ISO con zona (mismo contrato que
  `GET /api/appointments`), rango máximo 31 días; `from > to` → `422
  invalid_range`.
- Para cada turno del rango con `starts_at` en `[from, to)` y estado `pending` o
  `confirmed`, se calculan dos motivos:
  - **`no_response`**: `status = pending` y existe un evento `sent` del paso de
    confirmación más cercano ya enviado. Se prefiere `t_24h` si está
    configurado; si no, el último paso que `requests_confirmation` con un
    `sent`. No se exige que el job siga `sent`: si luego se reenvió, el evento
    anterior alcanza; lo que importa es que el paciente no confirmó.
  - **`delivery_failed`**: existe un job del turno con `status = failed` y
    `scheduled_for < starts_at`, sin un `sent` posterior exitoso del mismo
    `(step, channel)` (si el reenvío funcionó, el job ya no está `failed`).
- La fila devuelve: `appointment_id`, `starts_at`, `patient_id`,
  `patient_name`, `professional_id`, `status`, `reasons[]`, `last_reminder`
  (`step`, `channel`, `status`, `sent_at`, `last_error`), y `can_confirm`.
  `patient_name` es el único dato personal y solo para admin/recepción de la
  clínica; el odontólogo no accede a este endpoint.
- Orden por `starts_at` ascendente y cursor por `starts_at, id` (regla 8);
  `limit` 1..200 default 50.
- La alerta de la agenda usa `totals` (`no_response`, `delivery_failed`) del
  mismo endpoint; no hay tabla de alertas ni "descartar". Un fallo desaparece
  cuando el job deja de estar `failed` (reenvío exitoso) o el turno deja de ser
  vigente/futuro.
- **Sin PII en logs**: el endpoint no loguea nombres ni teléfonos; los tests
  usan datos sintéticos.

### D9. Reporte de entregas (ajuste de C-10)

La cohorte actual agrupa por `job_id`; un reenvío manual agrega un segundo
evento `sent` al mismo job. Se ajusta el cálculo:

- `sent` = cantidad de eventos `sent` en el rango (cada envío, incluido el
  manual).
- `delivered`/`read` = una vez por job con evento `delivered`/`read` en el rango
  (un job reenviado no infla entregados/leídos).
- `failed` = job con un evento `failed` posterior al último `sent` (el intento
  vigente); una falla vieja ya reenviada no cuenta.
- Costo = suma de `payload.cost_micros` de todos los `sent` del rango.
- Los pasos configurados siguen apareciendo con 0; el CSV no cambia de formato.

### D10. Frontend

- `features/agenda/ReminderTimeline.tsx`: recibe `appointmentId` y `canAct`
  (admin/recepción). Muestra un `details`/lista por paso con chip de estado,
  fechas, intentos, último error y eventos; `scheduled` como primer hito;
  `manual_resend` como "Reenviado por recepción". Botón "Reenviar" solo si
  `can_resend`; al `202`, invalida la query y muestra "Reenvío en cola".
- `AppointmentDetail.tsx`: inserta el timeline debajo de las acciones; no
  duplica el botón "Confirmar" (ya existe y sigue usando `allowedActions`).
- `AgendaPage.tsx`: consulta `follow-up` para el rango visible y muestra un
  banner con dos contadores y un toggle "Solo sin confirmar / fallos" que filtra
  la grilla por `appointment_id`. El odontólogo no ve el banner ni el toggle
  (la API igual responde `403`).
- `shared/api/types.ts` y `queries.ts`: tipos sin `any`, query keys nuevas.
- Tests Vitest + MSW: estados del timeline, reenvío `202` y `409`, filtro del
  panel, odontólogo sin acciones, error de red sin perder filtros.

### D11. Configuración y documentación

- `Settings`: `REMINDER_MANUAL_RESEND_COOLDOWN_S` (default 60, `ge=0`) y
  `REMINDER_MANUAL_RESEND_MAX_PER_DAY` (default 3, `ge=1`). `.env.example` con
  valores ficticios.
- `backend/README.md` §Recordatorios: cómo reenviar, qué significa cada estado,
  por qué un reenvío no adelanta un paso futuro y qué pasa con los estados
  tardíos del mensaje anterior.
- `AGENTS.md`/`CLAUDE.md`: sin cambios; no hay regla dura nueva. Si se aprueban
  los defaults, se anota en `knowledge-base/10_preguntas_abiertas.md`.

## UI Mockups

- Design system revision: 1 (`design-system/README.md`, aprobado 2026-11-05).
- Decision: no (el usuario pidió saltear los mockups al implementar, 2026-11-07).
- Mockups: none.
- Approval: n/a (skipped by user).
- Preview: none.
- Visual verify: no realizada; la UI reutiliza `Button`, `Alert` y los chips de
  estado existentes del design system.

La política del proyecto es `system-and-mockups`; para C-11 el usuario decidió
expresamente no hacer mockups (primero los difirió y, al implementar, los salteó).

## Risks / Trade-offs

- **[Reenvío y estados tardíos]** → se limpia `provider_message_id`; el estado
  viejo no se atribuye al mensaje nuevo. El timeline conserva el envío anterior
  sin `delivered/read`. Es preferible a un falso "leído".
- **[Reconciliación cancela el reenvío]** → `manual_resend_at` + guarda D5;
  cubierto por test de reprogramación y de mutación no relacionada.
- **[Spam al paciente]** → cooldown y tope diario; defaults a aprobar.
- **[Conflicto delivered/failed]** → estado efectivo por eventos con precedencia
  `read > delivered > failed`; se muestran ambos eventos.
- **[Reporte con unidades mezcladas]** → `sent` por evento y `delivered/read`
  por job; se documenta y se testea con un reenvío.
- **[Odontólogo ve datos de más]** → mismo alcance SQL y sin contacto; el
  endpoint de follow-up le responde 403.
- **[Consulta de follow-up costosa]** → se parte del rango de turnos (índice de
  agenda) y se hace un lateral por turno; índice parcial de `failed`; rango
  máximo 31 días.
- **[Auditoría de reenvío con nota libre]** → validación de PII y longitud; la
  nota no se loguea.

## Migration Plan

1. `alembic upgrade head` aplica `c11_reminder_timeline`: columna nullable,
   tabla nueva con FKs e índice, trigger append-only, índice parcial
   `CONCURRENTLY`.
2. Desplegar `api` y `worker`: el timeline y el follow-up leen datos existentes;
   el reenvío queda disponible aunque el worker esté detenido (los jobs quedan
   `scheduled`).
3. **Rollback**: `alembic downgrade c10_whatsapp_channel` borra la tabla, la
   columna y los índices. Los jobs reenviados conservan su estado operativo; se
   pierde el histórico de reenvíos, que es aceptable para una reversión.

## Open Questions

- Confirmar los defaults de cooldown/tope (Open Decision 1).
- ¿La nota del reenvío es obligatoria cuando el turno está a menos de 24 h? No
  está en la KB; se deja opcional.
- ¿El panel de seguimiento debe incluir turnos `confirmed` que no respondieron?
  No: un turno confirmado no necesita llamada; solo se incluye si tiene un fallo
  de entrega.
