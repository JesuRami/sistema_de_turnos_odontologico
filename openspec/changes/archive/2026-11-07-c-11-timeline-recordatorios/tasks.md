# Tasks — C-11 `timeline-recordatorios`

> TDD estricto rojo → verde: cada tarea **RED** escribe el test, lo corre y deja
> registrado que falla por la razón esperada; la **GREEN** siguiente escribe el
> mínimo código para pasarlo. Tests de invariantes y API con pytest + httpx
> contra Postgres 15 + Redis 7 reales (regla 9, sin mocks de DB); el proveedor de
> WhatsApp se simula con el sender `fake` o `httpx.MockTransport`. El `.venv`
> local no importa `asyncpg` (py3.14): el gate se corre en el contenedor py3.12
> como CI. Datos solo sintéticos: nombres inventados, teléfonos `+54 11
> 5555-01xx`, emails `@example.com`, DNI ficticios (regla 13); ni teléfonos,
> textos, links ni nombres en logs, `last_error`, eventos ni notas. Antes de
> tocar archivos existentes, correr su suite como red de seguridad. Cada grupo
> deja sus tests y su documentación.
>
> **Implementado el 2026-11-07 con `/opsx:apply`.** El usuario aprobó los seis
> defaults de las Open Decisions y pidió saltear los mockups de UI (la UI usa los
> componentes existentes del design system). Ver "Notas de implementación".

## 0. Red de seguridad

- [x] 0.1 Correr `pytest -q` en `backend/` (contenedor py3.12) y `npm test` en
  `frontend/`, y anotar el baseline (N passed / N failed, con las fallas de
  entorno preexistentes). Verifica: tabla de baseline al final de este archivo;
  nada se arregla acá.
- [x] 0.2 Confirmar con un script descartable que el payload real de Meta puede
  traer `delivered` y `failed` del mismo mensaje, y `read` sin `delivered`
  (Context7, 2026-11-07). Verifica: nota en este archivo; si el timeline asume
  un único estado, ajustar D2 antes de seguir.

## 1. Migración `c11_reminder_timeline` y modelos (D1)

- [x] 1.1 RED — `backend/tests/models/test_reminder_timeline_db.py` (Postgres
  real): `reminder_manual_resend` rechaza `UPDATE` y `DELETE` (trigger
  append-only); rechaza un `appointment_id`, `reminder_job_id` o `actor_user_id`
  de otra clínica (FK compuestas); acepta una nota de 200 caracteres y rechaza
  201; `reminder_job.manual_resend_at` acepta NULL y un instante; el índice
  parcial `failed` existe. Verifica: falla por tabla/columna inexistente.
- [x] 1.2 GREEN — modelo `ReminderManualResend`, columna `manual_resend_at` en
  `ReminderJob`, `Index` parcial `failed`, y revisión
  `alembic/versions/c11_reminder_timeline.py` con
  `down_revision="c10_whatsapp_channel"`: `ADD COLUMN` nullable, `CREATE TABLE`
  con FKs e índices, trigger append-only, índice `CONCURRENTLY` en
  `autocommit_block` (regla 11). Verifica: 1.1 verde.
- [x] 1.3 Extender `tests/test_migrations.py`: `upgrade head` → `downgrade
  c10_whatsapp_channel` → `upgrade head` sin errores sobre una base con datos
  sintéticos de C-10; el índice parcial queda `VALID`; la tabla y la columna
  desaparecen en el downgrade. Verifica: test verde.

## 2. Recálculo y reenvío manual (D5)

- [x] 2.1 RED — `tests/modules/test_reminder_reconcile_manual.py` (Postgres
  real): un job `scheduled` con `manual_resend_at` no nulo y `starts_at_snapshot`
  igual al turno sobrevive a un `reconcile` que antes lo cancelaba por
  `STEP_ELAPSED`; si el turno se reprograma a fecha futura donde el paso vuelve
  a aplicar, el job se recalcula con `scheduled_for` nuevo y `manual_resend_at`
  limpio; si se reprograma con el paso vencido, queda `cancelled` con `STEP_ELAPSED`;
  si el paso se elimina de `clinic.reminder_steps`, queda `cancelled`; si el turno
  se cancela, queda `cancelled`; al enviarse, `manual_resend_at` queda NULL.
  Verifica: el primer escenario falla porque hoy se cancela.
- [x] 2.2 GREEN — `scheduling.py`: guarda de `manual_resend_at` +
  `starts_at_snapshot` en la rama de paso vencido; limpieza del marcador en
  `dispatch._record_success/_record_failure`, `close_scheduled` y `_claim_batch`
  cuando el job deja de estar `scheduled`. Verifica: 2.1 verde y la suite de C-09/C-10 verde.

## 3. Timeline (D2, D3)

- [x] 3.1 RED — `tests/modules/test_reminder_timeline_api.py` (API, Postgres
  real): recepción ve pasos y eventos de su clínica; turno de otra clínica →
  `404`; odontólogo ajeno → `404`; odontólogo propio → `200`; sin sesión →
  `401`; el orden es alta, 72, 24, 3 h y WhatsApp antes que email; la respuesta
  no incluye `provider_message_id`, teléfono, email, nombre ni link; dos
  lecturas seguidas devuelven lo mismo. Verifica: falla por ruta inexistente.
- [x] 3.2 RED — `tests/modules/test_reminder_timeline_states.py` (unitario del
  read model): `sent→delivered→read` da `read`; `delivered+failed` da
  `delivered` con ambos eventos; `read` sin `delivered` da `read`; último
  intento `failed` da `failed`; job reseteado por reenvío da `scheduled` acotando
  la precedencia a la última generación (los eventos del intento anterior no
  contaminan el estado efectivo actual). Verifica: falla por función inexistente.
- [x] 3.3 GREEN — `app/modules/reminders/timeline.py` (read model con una
  consulta de jobs y una de eventos, sin N+1), schemas en `schemas.py` y ruta
  `GET /api/appointments/{id}/reminders` en `router.py`; alcance reutilizando el
  helper de `AppointmentsService` o una consulta equivalente con
  `clinic_id`/`professional_id`. Verifica: 3.1 y 3.2 verdes.

## 4. Reenvío manual (D4, D6)

- [x] 4.1 RED — `tests/modules/test_reminder_resend_guards.py` (API, Postgres
  real): recepción reenvía un job `failed` → `202`; odontólogo → `403`; turno de
  otra clínica → `404`; turno cancelado → `409 appointment_inactive`; turno
  iniciado → `409 appointment_started`; job inexistente → `404
  reminder_not_found`; paso no configurado → `409 step_not_applicable`; job
  `scheduled` → `409 reminder_pending`; job `sending` → `409 reminder_in_flight`;
  paso de confirmación sobre turno online confirmado → `409
  step_not_applicable`; sin opt-in → `409 no_consent`; sin email → `409
  no_recipient`; nota con DNI/teléfono → `422 invalid_note` y sin fila.
  Verifica: falla por ruta inexistente.
- [x] 4.2 RED — `tests/modules/test_reminder_resend_effect.py` (Postgres real):
  el `202` deja el job `scheduled` con `available_at`, `attempts=0`, sin
  `sent_at`/`provider_message_id`/`cost_micros`/`last_error`/`reason`, conserva
  `scheduled_for`/`starts_at_snapshot` y crea una fila de auditoría con actor y
  nota; no hay evento `sent` nuevo en la request; con el worker deshabilitado el
  job queda `scheduled`; un `delivered` del `provider_message_id` anterior no
  cambia el job; un job `skipped (no_consent)` se puede reenviar tras el opt-in.
  Verifica: falla por lógica incompleta.
- [x] 4.3 RED — `tests/modules/test_reminder_resend_limits.py` (Postgres real):
  doble clic dentro del cooldown → `409 resend_cooldown` con `retry_after_s`;
  tope diario → `409 resend_limit`; dos requests concurrentes → un `202`, un
  `409` y una sola fila de auditoría; el conteo diario usa la zona de la
  clínica. Verifica: falla por límites inexistentes.
- [x] 4.4 GREEN — `app/modules/reminders/manual.py` (servicio con `FOR UPDATE`
  del turno y del job, guardas, reset, inserción de auditoría, cooldown y tope),
  schemas `extra='forbid'`, ruta `POST .../resend`, settings
  `REMINDER_MANUAL_RESEND_COOLDOWN_S` y
  `REMINDER_MANUAL_RESEND_MAX_PER_DAY`, `.env.example`. Verifica: 4.1–4.3
  verdes.
- [x] 4.5 RED → GREEN — `tests/modules/test_manual_confirm.py`: recepción
  confirma un `pending` por `POST /transitions` → `200`, turno `confirmed` y
  evento con `actor_type=user`; odontólogo → `403` y sin evento; confirmar un
  `confirmed` → rechazo sin segundo evento. Verifica: contrato del endpoint
  existente; si algo falla, se corrige la guarda, no se agrega un endpoint
  nuevo.

## 5. Lista de seguimiento (D8)

- [x] 5.1 RED — `tests/modules/test_reminder_followup.py` (Postgres real):
  turno `pending` con `sent` de 24 h → `no_response`; `confirmed` → no aparece;
  clínica sin 24 h → fallback al último paso de confirmación enviado; job `failed`
  → `delivery_failed` y no `no_response`; reenvío exitoso → desaparece; turno
  cancelado o pasado → no aparece; odontólogo → `403`; otra clínica → no
  aparece; rango > 31 días → `422 range_too_large`; `from > to` → `422
  invalid_range`; borde 23:30 local → cae en el rango correcto; la respuesta no
  incluye teléfono/email/DNI/provider ids. Verifica: falla por ruta inexistente.
- [x] 5.2 GREEN — `app/modules/reminders/followup.py` (consulta con lateral por
  turno, cursor `starts_at,id`, `limit` 1..200), schemas y ruta
  `GET /api/reminders/follow-up`; índice parcial `failed`. Verifica: 5.1 verde.

## 6. Reporte de entregas (D9)

- [x] 6.1 RED — extender `tests/modules/test_reports_whatsapp.py`: un job con
  dos eventos `sent` (original + reenvío) cuenta enviados 2 y suma dos costos;
  si el primer envío falló y el reenvío se entregó, fallidos 0; un reenvío
  reencolado sin `sent` no suma enviados ni costo; un job sin reenvío mantiene
  las cifras de C-10. Verifica: el test nuevo falla con el conteo por job.
- [x] 6.2 GREEN — `app/modules/reports/whatsapp.py`: cohorte por evento `sent`
  para enviados y costo; `delivered/read/failed` por job con la regla del último
  intento. Verifica: 6.1 verde y la suite de C-10 verde.

## 7. Frontend: timeline (D10)

- [x] 7.1 RED — `frontend/src/features/agenda/ReminderTimeline.test.tsx` (Vitest
  + MSW): muestra pasos en orden con chip de estado, fechas, intentos y último
  error; `scheduled` como primer hito; `manual_resend` como "Reenviado por
  recepción"; no muestra `provider_message_id` ni datos de contacto; odontólogo
  no ve "Reenviar"; error de red muestra mensaje y conserva el turno. Verifica:
  `npm test -- ReminderTimeline` falla.
- [x] 7.2 RED — `AppointmentDetail.test.tsx`: el detalle incluye el timeline;
  recepción reenvía → `202` → "Reenvío en cola" y refresca; `409
  resend_cooldown` → mensaje con segundos; doble clic deshabilita el botón.
  Verifica: falla por componente/acción inexistente.
- [x] 7.3 GREEN — `ReminderTimeline.tsx`, tipos en `shared/api/types.ts` (sin
  `any`), query keys y `AppointmentDetail.tsx`. Verifica: 7.1 y 7.2 verdes y
  `npm run typecheck` limpio.

## 8. Frontend: panel de seguimiento (D10)

- [x] 8.1 RED — `AgendaPage.test.tsx`: recepción ve el panel con contadores de
  "sin confirmar" y "fallos"; el toggle filtra la grilla por los ids devueltos;
  sin turnos muestra 0 y no filtra; odontólogo no ve el panel; el refresco
  periódico actualiza el panel. Verifica: `npm test -- AgendaPage` falla.
- [x] 8.2 GREEN — panel/toggle en `AgendaPage.tsx`, consulta de follow-up y
  filtro por ids; sin `any`. Verifica: 8.1 verde, `npm run typecheck` y
  `npm run build` limpios (sin ejecutar build si el usuario no lo pide).

## 9. Documentación y configuración (D11)

- [x] 9.1 `backend/README.md` §Recordatorios: estados del timeline, cómo
  reenviar, guardas, cooldown/tope, qué pasa con los estados tardíos del mensaje
  anterior y cómo probar con el sender `fake`. Verifica: los textos coinciden
  con `design.md` D2/D4/D5 y con los tests 3.2/4.2.
- [x] 9.2 `.env.example` con `REMINDER_MANUAL_RESEND_COOLDOWN_S=60` y
  `REMINDER_MANUAL_RESEND_MAX_PER_DAY=3`; `tests/test_env_example.py` verde.
  Verifica: no hay secretos ni valores reales.
- [x] 9.3 Si el usuario aprueba los defaults de las Open Decisions 1 y 5,
  anotarlos en `knowledge-base/10_preguntas_abiertas.md`; si no, dejar la
  decisión pendiente y no inventar la regla. Verifica: la KB no contradice la
  spec.

## 10. Gate de integración

- [x] 10.1 En el contenedor py3.12: `pytest -q`, `ruff check`, `black --check` y
  `mypy` limpios en `backend/`; `npm test`, `npm run typecheck` y `npm run
  build` en `frontend/` (build solo si el usuario lo pide). Verifica: comparar
  con el baseline de 0.1, sin regresiones.
- [x] 10.2 Escenario punta a punta con proveedor `fake`: turno online `pending`
  → tick envía 24 h → `delivered` y `read` por webhook firmado → timeline
  muestra `read` → recepción reenvía el paso de 3 h → `202` → el worker envía →
  timeline muestra dos `sent` y el `manual_resend` → reporte WhatsApp cuenta 2
  enviados y el costo de ambos. Verifica: test de integración
  `tests/modules/test_reminder_timeline_e2e.py` verde.
- [x] 10.3 `openspec validate c-11-timeline-recordatorios --strict` sin errores.
  Verifica: comando verde.

## Workflow follow-up

- ~~Aprobar las Open Decisions 1–6~~: aprobadas tal como están (usuario,
  2026-11-07). Las 1 y 5 quedaron anotadas en `knowledge-base/10_preguntas_abiertas.md`.
- ~~Mockups~~: salteados por decisión del usuario (2026-11-07).
- Actualizar `CHANGES.md` con las notas de cierre y archivar con
  `/opsx:archive c-11-timeline-recordatorios`.

## Notas de implementación

### Baseline (0.1, 2026-11-07, antes de tocar código)

| Suite | Resultado |
|---|---|
| Backend `pytest -q` (contenedor py3.12, Postgres 15.8, Redis 7.4) | 1411 passed, 0 failed |
| Frontend `npm test` (Vitest) | 181 passed, 0 failed (24 archivos) |

### Cierre (10.1, 2026-11-07)

| Suite | Resultado |
|---|---|
| Backend `pytest -q` | 1495 passed, 0 failed (+84 de C-11, sin regresiones) |
| `ruff check backend` · `black --check backend` · `mypy backend` | limpios |
| Frontend `npm test` | 199 passed, 0 failed (25 archivos; +18) |
| Frontend `npm run typecheck` | limpio |
| Frontend `npm run build` | no ejecutado (regla: solo si el usuario lo pide) |
| `openspec validate c-11-timeline-recordatorios --strict` | válido |

### 0.2 — Estados de Meta

Confirmado contra el código del webhook de C-10 (`app/modules/notifications/statuses.py`): cada
estado se registra como un `delivery_event` propio, `read` sin `delivered` avanza el job a `read`
y un `failed` posterior a la entrega queda solo como evento. D2 no asume un único estado. Hallazgo
extra: Meta informa `timestamp` en segundos enteros, así que un `delivered` puede quedar con
`occurred_at` unos milisegundos *antes* del `sent` del motor. El timeline y el reporte comparan
contra el `sent` truncado al segundo (requisito y escenario agregados a la delta-spec
`delivery-timeline`, test `test_entrega_con_timestamp_truncado_de_meta_cuenta`).

### Desvíos y decisiones durante la implementación

- **Orden TDD en el grupo 4**: el servicio de reenvío y las guardas se escribieron antes que sus
  tests (el router los necesitaba para importar al hacer el GREEN 3.3). Se compensó con un
  chequeo de mutación: sin la ruta fallan 23/23 tests de guardas y efecto; sin cooldown y tope
  fallan 4/5 de límites (el restante, día local, espera `202` en ambos casos). Lo mismo en el
  grupo 5: quitar la preferencia por `t_24h` o la exclusión de fallidos rompe 2 tests.
- **Generación vigente**: el corte es el `created_at` del último `reminder_manual_resend`, que el
  servicio fija con el reloj de la request (cooldown y día local coherentes con `get_now`).
- **Marca `manual_resend_at`**: se conserva mientras el job está `sending` o vuelve a
  `scheduled` por un reintento/lease (si se limpiara en el reclamo, un `reconcile` posterior lo
  cancelaría por paso vencido); se limpia en cada estado final.
- **`no_consent` vs `no_recipient`**: WhatsApp sin opt-in → `no_consent`, sin teléfono →
  `no_recipient`; email sin dirección → `no_recipient`, con baja → `no_consent`.
- **Seguimiento**: `no_response` no cuenta un job del paso de confirmación que quedó `failed`
  (pasa a `delivery_failed`); solo turnos futuros.
- **10.2**: el e2e reenvía el paso de 24 h y no el de 3 h, porque a esa hora el de 3 h todavía
  no se intentó y la guarda correcta es `409 reminder_pending`.
- **10.3**: `--strict` marcaba cuatro requisitos de más de 500 caracteres. Se dividieron sin
  cambiar lo que exigen (estado efectivo / generación / hito `scheduled` / evento de reenvío;
  recálculo vs. reprogramación; límites vs. orden de guardas), con escenarios para cada parte. Al sincronizar, la spec principal `delivery-report` marcó lo mismo para «Cifras por paso y canal»: se separó «Fallidos del último intento».
- **Tipos del frontend**: `ReminderTimelineStep` (no `ReminderStep`, que ya existía para la
  configuración de pasos de la clínica).
