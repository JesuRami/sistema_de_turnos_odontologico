# Tasks — C-12 `lista-de-espera`

> TDD estricto rojo → verde: cada tarea **RED** escribe el test, lo corre y deja
> registrado que falla por la razón esperada; la **GREEN** siguiente escribe el
> mínimo código para pasarlo. Invariantes y API con pytest + httpx contra
> Postgres 15 + Redis 7 reales (regla 9, sin mocks de DB); el proveedor se
> simula con el sender `fake` o `httpx.MockTransport`. El `.venv` local no
> importa `asyncpg` (py3.14): el gate corre en el contenedor py3.12 como CI.
> Datos solo sintéticos: nombres inventados, teléfonos `+54 11 5555-01xx`,
> emails `@example.com` (regla 13); ni teléfonos, notas, links ni tokens en
> logs, eventos ni `last_error`. Antes de tocar un archivo existente, correr su
> suite como red de seguridad. Cada grupo deja sus tests y su documentación.
>
> Decisiones del usuario (2026-11-08): preferencia = período de fechas + franja y
> días opcionales; priorización con motivo auditado; respuesta por link y por
> botones de WhatsApp; solo la cancelación dispara la evaluación. Las Open
> Decisions 1–7 de `proposal.md` quedaron aprobadas tal como están (usuario,
> 2026-11-08).

## 0. Red de seguridad

- [x] 0.1 Correr `pytest -q` en `backend/` (contenedor py3.12) y `npm test` en
  `frontend/` y anotar el baseline al final de este archivo. Verifica: tabla de
  baseline; nada se arregla acá.
- [x] 0.2 Confirmar con Context7 que la Cloud API devuelve el `context.id` del
  mensaje citado en las respuestas de botón de una plantilla y que una plantilla
  utility admite dos botones de respuesta rápida. Verifica: nota en este
  archivo; si no, ajustar D8 antes del grupo 6.

## 1. Migración `c12_waiting_list` y modelos (D1)

- [x] 1.1 RED — `tests/models/test_waiting_list_db.py` (Postgres real): unicidad
  `waiting/offered` por paciente y profesional con "cualquiera" como valor
  (`NULLS NOT DISTINCT`), entrada cerrada no bloquea; CHECKs de período, franja
  (ambos o ninguno, `time_to > time_from`), `weekdays` 0–6 no vacío, nota ≤ 200;
  FK compuestas rechazan paciente, profesional o entrada de otra clínica; una sola
  oferta `pending` por entrada; `accepted ⇔ appointment_id`; `expires_at <=
  starts_at`; `waitlist_event` rechaza `UPDATE`/`DELETE`. Verifica: falla por
  tablas inexistentes.
- [x] 1.2 RED — `tests/models/test_waitlist_existing_tables_db.py`: turno
  `origin=waitlist` con sobreturno o con `manage_token_hash` rechazado;
  `reminder_job` con turno y oferta a la vez, o con ninguno, rechazado; paso
  `waitlist_offer` sin oferta (y oferta con otro paso) rechazado; único
  `(waitlist_offer_id, channel)`; `notification_template` acepta el paso
  `waitlist_offer`; `whatsapp_inbound.waitlist_offer_id` de otra clínica
  rechazado. Verifica: falla por columnas y valores inexistentes.
- [x] 1.3 GREEN — modelos `WaitingListEntry`, `WaitlistOffer`, `WaitlistEvent`,
  enums nuevos en `app/models/enums.py` (`AppointmentOrigin.WAITLIST`, estados,
  tipos de evento, `ReminderReason.OFFER_CLOSED`, intenciones y respuestas de
  WhatsApp), `ReminderJob.appointment_id` opcional + `waitlist_offer_id`,
  `STEP_FORMAT_SQL` nuevo y `alembic/versions/c12_waiting_list.py`
  (`down_revision="c11_reminder_timeline"`): enums en `autocommit_block`,
  `CREATE TABLE`, `ADD COLUMN` nullable, `DROP NOT NULL`, FKs y CHECKs `NOT
  VALID` → `VALIDATE`, índices sobre tablas existentes `CONCURRENTLY`, trigger
  append-only. Verifica: 1.1 y 1.2 verdes.
- [x] 1.4 Extender `tests/test_migrations.py`: `upgrade head` → `downgrade
  c11_reminder_timeline` → `upgrade head` sobre una base con datos sintéticos de
  C-11; índices `VALID`; constraints validados; el downgrade elimina tablas y
  columnas y deja los valores de enum (documentado). Verifica: test verde.
- [x] 1.5 Correr `mypy backend` y anotar cada uso de `ReminderJob.appointment_id`
  que pasó a opcional; cada uno queda cubierto por una tarea del grupo 4 o se
  corrige acá si es trivial (aserción con comentario). Verifica: `mypy` limpio y
  suites de C-09/C-10/C-11 verdes.

## 2. Entradas de la lista (spec `waitlist/entries`)

- [x] 2.1 RED — `tests/modules/test_waitlist_entries_api.py`: alta de recepción
  `201`; `invalid_range` (invertido, fecha pasada), `range_too_large`
  (horizonte), `invalid_time_window`; `already_waiting` con id de la existente;
  distinto profesional `201`; carrera de dos altas → un `201` y un `409`;
  paciente de otra clínica `422 invalid_patient`; profesional inactivo `409
  resource_inactive`; nota con teléfono `422 invalid_note`; odontólogo `403`; sin
  sesión `401`. Verifica: falla por ruta inexistente.
- [x] 2.2 RED — `tests/modules/test_waitlist_entries_manage.py`: edición de
  `waiting` con evento antes/después (nota auditada como `notes_changed`); editar
  `offered` → `409 entry_offered`; retiro de `offered` cierra su oferta
  (`cancelled`) y su job de envío; retirar `converted` → `409 entry_closed`;
  prioridad con motivo, sin motivo `422 priority_reason_required`, quitar
  prioridad; eventos con actor; entrada ajena `404`. Verifica: falla por rutas
  inexistentes.
- [x] 2.3 RED — `tests/modules/test_waitlist_queue.py`: orden prioridad →
  antigüedad; filtro por profesional incluye "cualquiera"; filtro por período por
  intersección; default `waiting`+`offered`; oferta pendiente embebida;
  paginación de 2×50 = 1×100; odontólogo ve sus entradas y "cualquiera" sin
  teléfono, email ni notas; aislamiento entre clínicas. Verifica: falla.
- [x] 2.4 GREEN — mover el validador anti-PII de `reminders/manual.py` a
  `app/common/` (sin cambiar su comportamiento: suite de C-11 verde);
  `waiting_list/entries.py`, `schemas.py` (`extra='forbid'`) y rutas en
  `router.py`; eliminar el stub `/waiting-list/ping` y su test. Verifica: 2.1–2.3
  verdes.
- [x] 2.5 Documentar en `backend/README.md` §Lista de espera: modelo de
  preferencias, unicidad, estados de la entrada y RBAC. Verifica: coincide con
  la spec `waitlist/entries`.

## 3. Anotación pública (D7)

- [x] 3.1 RED — `tests/modules/test_waitlist_public.py`: anotación `201` sin ids
  internos y origen `online`; sin contacto `422`; paciente reutilizado por
  teléfono+nombre; opt-in registrado con fuente `booking` en la misma
  transacción; duplicado `409 already_waiting` sin datos del paciente; slug
  inexistente o reserva deshabilitada `404 booking_not_found` con el cuerpo de la
  reserva; cupo por IP `429` con `Retry-After`; Redis caído `503
  booking_unavailable`; `BotGuard` invocado; ni el teléfono ni el nombre en logs.
  Verifica: falla por ruta inexistente.
- [x] 3.2 GREEN — extraer `_contact`, `_match_or_create` y `_stamp_privacy` de
  `BookingPublicService` a funciones compartidas (suite de C-07 verde antes y
  después), ruta `POST /api/booking/{slug}/waiting-list`, settings
  `WAITLIST_PUBLIC_IP_RATE_LIMIT` y `WAITLIST_PUBLIC_SLUG_RATE_LIMIT` en
  `Settings` y `.env.example`; `tests/test_env_example.py` verde. Verifica: 3.1
  verde.

## 4. Motor de envío para ofertas (D2, spec `waitlist/offer-delivery`)

- [x] 4.1 RED — `tests/modules/test_offer_dispatch.py` (Postgres real, sender
  `fake`): un job `waitlist_offer` se reclama y envía con los parámetros
  `nombre, clinica, fecha, hora, profesional, vence, link` y botones
  `offer_accept`/`offer_decline`; oferta `accepted`/`cancelled`/vencida antes del
  reclamo → job `cancelled` `offer_closed`; mismo caso entre el reclamo y el
  envío (`_recheck`); opt-out → `skipped no_consent`; plantilla inactiva →
  `skipped template_inactive`; tres fallos de WhatsApp → `failed` y job de email
  para la misma oferta; los jobs de turno se reclaman y envían igual que antes en
  el mismo tick. Verifica: falla por rama inexistente.
- [x] 4.2 RED — `tests/modules/test_offer_jobs_isolation.py`: el timeline y la
  lista de seguimiento de un turno no muestran jobs de oferta; `reconcile` de un
  turno del mismo paciente no toca el job de oferta; el estado `delivered` de Meta
  avanza el job de oferta; el costo se registra. Verifica: falla.
- [x] 4.3 GREEN — `dispatch.py` (consulta de contexto separada para ofertas,
  validación y `_recheck` de la oferta, `_build_message` con el link de oferta),
  `jobs.escalate_to_email` y `statuses.apply_status` con `waitlist_offer_id`,
  `templates.py` (`vence`, botones, plantillas por defecto del paso),
  `waiting_list/links.py` (D6) con su test unitario de firma, forma canónica y
  separación de contexto. Verifica: 4.1 y 4.2 verdes y suites de C-09/C-10/C-11
  verdes.
- [x] 4.4 RED → GREEN — seed: `tests/test_seed.py` espera diez plantillas en una
  clínica nueva y agrega las dos de oferta a una existente sin tocar las ocho
  anteriores ni pisar ediciones. Verifica: test verde.
- [x] 4.5 RED → GREEN — reporte de WhatsApp: extender
  `tests/modules/test_reports_whatsapp.py` con la fila `waitlist_offer` por canal
  (en 0 sin ofertas; envío leído; fallo escalado a email) y el total. Verifica:
  test verde y cifras de C-11 intactas.

## 5. Evaluación, ofertas y rotación (D3–D5, D10, spec `waitlist/offers`)

- [x] 5.1 RED — `tests/modules/test_waitlist_evaluation.py`: cancelación de
  recepción y por token crean la oferta en el mismo commit; sin compatibles no
  hay oferta; reprogramación y `no_show` no evalúan; filtros de profesional,
  período, franja (hueco completo), días, paciente archivado, sin canal, paciente
  ocupado y hueco ya ofrecido a esa entrada; orden prioritaria → FIFO; hueco
  bloqueado; TTL completo, TTL recortado a `inicio − 60 min` y hueco a 70 min sin
  oferta; canal elegido WhatsApp con opt-in o email; error inesperado en la
  evaluación revierte la cancelación; borde 23:30 local. Verifica: falla.
- [x] 5.2 RED — `tests/modules/test_waitlist_evaluation_concurrency.py`: dos
  cancelaciones simultáneas compatibles con la misma única entrada → una oferta;
  una cancelación no espera a una entrada lockeada por otra transacción (termina
  dentro de un timeout corto y ofrece a la siguiente); una cancelación con 1.000
  entradas no compatibles queda dentro del presupuesto del endpoint. Verifica:
  falla.
- [x] 5.3 GREEN — `waiting_list/engine.py` (`evaluate_slot`) y el gancho en
  `apply_transition()` después de `reconcile()`. Verifica: 5.1 y 5.2 verdes y
  suite de transiciones de C-05/C-08 verde.
- [x] 5.4 RED — `tests/modules/test_waitlist_accept.py`: aceptar crea turno
  `confirmed` origen `waitlist` con evento que registra la oferta y recordatorios
  programados; entrada `converted`; ofertas paralelas del mismo hueco
  `cancelled` y sus entradas a `waiting`; doble aceptación del mismo paciente
  idempotente; vencida `409 offer_expired`; cerrada `409 offer_closed`; paciente
  ocupado `409 patient_busy` con la oferta pendiente; sobreturno encima → `409
  slot_taken`; hueco en el pasado `422 appointment_in_past`; hueco ocupado por
  recepción → `409 slot_taken` con ≤ 3 alternativos (solo inicio y fin), oferta
  `cancelled` y entrada prioritaria `slot_lost` persistidas. Verifica: falla.
- [x] 5.5 RED — `tests/modules/test_waitlist_accept_race.py`: dos aceptaciones
  simultáneas del mismo hueco → un turno, un `409`, la perdedora prioritaria;
  aceptación concurrente con el tick que vence la oferta → resultado consistente
  (o turno, u oferta vencida, nunca ambos). Verifica: falla.
- [x] 5.6 GREEN — `waiting_list/offers.py` (`OffersService`: aceptar, rechazar,
  retirar) y los dos cambios en `AppointmentsService.book()` (origen `WAITLIST`
  y chequeo de pasado). Verifica: 5.4 y 5.5 verdes y suites de C-05/C-07 verdes.
- [x] 5.7 RED — `tests/modules/test_waitlist_tick.py`: oferta vencida → `expired`,
  entrada `waiting` con contador +1 y rotación a la siguiente; rotación con hueco
  ya ocupado no ofrece; tercer vencimiento → entrada `expired no_response`;
  rechazo intermedio reinicia el contador; entrada con `date_to` pasado →
  `expired range_elapsed`, el último día sigue `waiting`; dos ticks concurrentes
  vencen una vez y rotan a lo sumo una vez; ningún turno ni `appointment_event`
  cambia. Verifica: falla.
- [x] 5.8 GREEN — tick `waitlist_tick` en `app/worker/settings.py` y su función
  en `waiting_list/engine.py`; settings `WAITLIST_MIN_LEAD_MINUTES`,
  `WAITLIST_MIN_OFFER_WINDOW_MINUTES`, `WAITLIST_MAX_CONSECUTIVE_EXPIRED`,
  `WAITLIST_TICK_BATCH_SIZE` y `.env.example`. Verifica: 5.7 verde y
  `tests/test_worker_settings.py` incluye el cron nuevo.
- [x] 5.9 RED → GREEN — `tests/modules/test_waitlist_manual_offer.py`: huecos
  ofrecibles respetan preferencia, "cualquiera" incluye todos los profesionales,
  rango > 14 días `422 range_too_large`; oferta manual a la primera sin motivo
  `201`; a la tercera sin motivo `422 fifo_skip_reason_required`, con motivo
  `201` y evento `fifo_skip=true`; hueco ocupado `409 slot_taken`; fuera de
  horario `422 outside_schedule`; segunda oferta a la misma entrada `409
  entry_offered`; aceptar, rechazar y retirar en nombre del paciente con el
  usuario como actor; listado de ofertas por estado y rango; odontólogo `403`.
  Verifica: test verde con las rutas de D11.
- [x] 5.10 RED → GREEN — `tests/modules/test_waitlist_events.py`: traza completa
  `offered → expired → offered → accepted` con actores; `GET
  /api/waiting-list/{id}/events` en orden; ningún payload contiene nombre,
  teléfono, email, DNI ni nota. Verifica: test verde.
- [x] 5.11 `backend/README.md` §Lista de espera: evaluación, ventana de la
  oferta, rotación, vencimientos, carrera, prioridad y FIFO. Verifica: coincide
  con D3–D5 y D10.

## 6. Link de la oferta y WhatsApp (D6, D8)

- [x] 6.1 RED — `tests/modules/test_waitlist_offer_link_api.py`: vista de oferta
  pendiente, aceptada (con horario del turno) y vencida antes del tick; sin ids
  del paciente, teléfono ni email; credencial alterada, de gestión o de oferta
  inexistente → `404 offer_not_found` con el mismo cuerpo; link 4 días después
  del hueco → `404`; aceptar `200` con link de gestión del turno nuevo; rechazar
  y rechazar con `leave_list`; campo desconocido `422`; `429` por token y por
  IP; `503` sin Redis; cabeceras `no-store` y `no-referrer`; el token no aparece
  en logs ni eventos. Verifica: falla por rutas inexistentes.
- [x] 6.2 GREEN — rutas públicas `/api/waitlist-offer/{token}` sobre
  `OffersService`, cupos con claves `waitlist-offer:*`. Verifica: 6.1 verde.
- [x] 6.3 RED — extender `tests/modules/test_whatsapp_inbound.py`: botón
  "Tomarlo" citando la oferta crea el turno y encola `offer_accepted`; "Paso" y
  "no" citando la oferta rechazan; "sí" citando la oferta acepta; "stop" citando
  la oferta da de baja sin tocarla; texto desconocido no la cambia; "si" sin
  contexto con oferta pendiente sigue el ruteo al turno; "Tomarlo" vencido →
  `offer_closed`; hueco ocupado → `offer_taken`; paciente ocupado →
  `offer_patient_busy`; reenvío de Meta no crea otro turno ni otra respuesta; el
  entrante guarda `waitlist_offer_id` sin texto ni teléfono. Verifica: falla.
- [x] 6.4 GREEN — `intents.py`, `routing.py` (contexto de oferta), `inbound.py`
  (`OffersService` en savepoint) y `replies.py` (textos de las respuestas nuevas,
  con link de gestión cuando hay turno). Verifica: 6.3 verde y suite de C-10
  verde.

## 7. Reporte de conversión y exportación (D9)

- [x] 7.1 RED — `tests/modules/test_reports_waitlist.py`: rotación que convierte
  (2 creadas, 1 vencida, 1 aceptada, 50,0 %); sin ofertas → ceros y tasa `null`;
  manual cuenta en manuales; pendiente cuenta solo en creadas; estado mutado sin
  evento no cambia el reporte; recepción `403`; rango invertido y > 366 días
  `422`; CSV con fila por profesional, total y neutralización de fórmulas;
  aislamiento entre clínicas. Verifica: falla.
- [x] 7.2 GREEN — `reports/waitlist.py`, ruta `GET /api/reports/waitlist` y
  schemas. Verifica: 7.1 verde.
- [x] 7.3 RED → GREEN — extender el test de exportación completa: seis archivos en
  CSV y JSON, lista vacía solo con encabezados, sin filas de otra clínica, lectura
  por lotes; `reports/exports.py`. Verifica: test verde.

## 8. Frontend: panel de recepción (D12, spec `web/waiting-list`)

- [x] 8.1 RED — `features/waiting-list/WaitingListPage.test.tsx` (Vitest + MSW):
  cola en el orden de la API con filtros, "Cargar más", vacío y error con
  reintento; marca y motivo de prioridad; oferta pendiente con vencimiento;
  odontólogo sin datos de contacto ni acciones; refresco periódico. Verifica:
  `npm test -- WaitingListPage` falla.
- [x] 8.2 RED — `EntryForm.test.tsx` y `OfferDialog.test.tsx`: alta con búsqueda de
  paciente, `409 already_waiting` ofrece ir a la existente, retiro con
  confirmación, edición; oferta manual con huecos de `…/slots`, `422
  fifo_skip_reason_required` pide motivo y reintenta; priorizar con motivo.
  Verifica: falla.
- [x] 8.3 RED — `OffersPanel.test.tsx`: aceptar por teléfono muestra el turno y el
  acceso a la agenda; `409 slot_taken` explica que la entrada quedó prioritaria;
  oferta vencida tras el refresco; mensajes por `detail` y genérico. Verifica:
  falla.
- [x] 8.4 GREEN — componentes de `features/waiting-list/`, ruta
  `/lista-de-espera` y entrada de menú en `App.tsx`, tipos en
  `shared/api/types.ts` sin `any`, `waitingListErrors.ts`. Verifica: 8.1–8.3
  verdes y `npm run typecheck` limpio.

## 9. Frontend: oferta pública y anotación (D12, specs `web/waitlist-offer`, `web/public-booking`)

- [x] 9.1 RED — `features/waitlist-offer/OfferPage.test.tsx`: oferta pendiente con
  "Tenés hasta las HH:MM" y tres botones; vencida sin botones y con teléfono;
  aceptar muestra turno confirmado y link de gestión; doble toque envía una sola
  request; `409 slot_taken` con alternativos y acceso a reservar; `409
  offer_expired`, `409 patient_busy`, `404`, `429` y error de red con su mensaje;
  nada en `localStorage`/`sessionStorage`. Verifica: falla.
- [x] 9.2 GREEN — `OfferPage`, ruta `/o/:token` con `QueryClient` propio. Verifica:
  9.1 verde.
- [x] 9.3 RED → GREEN — `features/booking/WaitlistStep.test.tsx` y
  `BookingPage.test.tsx`: sin horarios se ofrece anotarse con el profesional
  preseleccionado; anotación exitosa con resumen; `409 already_waiting` con
  teléfono de la clínica; `429` conserva lo cargado; sin almacenamiento local;
  el flujo de reserva sigue en ≤ 4 pasos. Verifica: tests verdes.
- [x] 9.4 RED → GREEN — `features/reports/ReportsPage.test.tsx`: seis pestañas;
  pestaña Lista de espera con cifras, tasa "—" sin ofertas y "Descargar CSV" con
  el rango; la pestaña WhatsApp nombra "Oferta de lista de espera". Verifica:
  tests verdes y `npm run typecheck` limpio.
- [ ] 9.5 RED → GREEN — Playwright `frontend/e2e/waitlist.spec.ts` (circuito
  crítico, regla 9): recepción anota a un paciente ficticio → cancela un turno
  compatible → la oferta aparece en el panel → el paciente abre `/o/:token` en
  360 px y acepta → el turno `waitlist` aparece confirmado en la agenda.
  Verifica: E2E verde contra la pila de Docker Compose.

## 10. Documentación de dominio

- [x] 10.1 `knowledge-base/10_preguntas_abiertas.md`: marcar resuelta la pregunta
  Media de prioridad (decisión del usuario 2026-11-08) y anotar las Open
  Decisions 1–7 con su default (aprobadas el 2026-11-08). Verifica: la KB no
  contradice las specs.
- [x] 10.2 `knowledge-base/04_modelo_de_datos.md` §waiting_list_entry +
  waitlist_offer y `11_whatsapp_y_recordatorios.md` (texto de la plantilla) solo
  con lo aprobado; `AGENTS.md`/`CLAUDE.md` no cambian (no hay regla dura nueva).
  Verifica: `diff AGENTS.md CLAUDE.md` vacío.

## 11. Gate de integración

- [x] 11.1 En el contenedor py3.12: `pytest -q`, `ruff check`, `black --check` y
  `mypy` limpios en `backend/`; `npm test` y `npm run typecheck` en `frontend/`;
  `npm run build` solo si el usuario lo pide. Verifica: comparar con el baseline
  de 0.1, sin regresiones.
- [x] 11.2 Escenario punta a punta con proveedor `fake`:
  `tests/modules/test_waitlist_e2e.py` — anotación pública con opt-in → cancelación
  por link de gestión → oferta y job → tick envía por WhatsApp → vence sin
  respuesta → rota a la segunda entrada → la segunda toca "Tomarlo" por webhook
  firmado → turno `waitlist` confirmado con recordatorios → reporte de conversión
  (2 creadas, 1 vencida, 1 aceptada) y fila `waitlist_offer` del reporte de
  WhatsApp con 2 enviados. Verifica: test verde.
- [x] 11.3 `openspec validate c-12-lista-de-espera --strict` sin errores.
  Verifica: comando verde.

## Workflow follow-up

- ~~Aprobar las Open Decisions 1–7~~: aprobadas tal como están (usuario,
  2026-11-08).
- Actualizar `CHANGES.md` con las notas de cierre y archivar con
  `/opsx:archive c-12-lista-de-espera`.

## Notas de implementación

### Baseline (0.1, 2026-11-08, antes de tocar código)

| Suite | Resultado |
|---|---|
| Backend `pytest -q` (contenedor py3.12, Postgres 15.8, Redis 7.4) | 1495 passed, 0 failed |
| Frontend `npm test` (Vitest) | 199 passed, 0 failed (25 archivos) |

### Cierre (11.1, 2026-11-09)

| Suite | Resultado |
|---|---|
| Backend `pytest -q` | 1760 passed, 0 failed (+265 de C-12, sin regresiones) |
| `ruff check backend` · `black --check backend` · `mypy backend` | limpios |
| Frontend `npm test` | 234 passed, 0 failed (31 archivos; +35) |
| Frontend `npm run typecheck` | limpio |
| Frontend `npm run build` | no ejecutado (regla: solo si el usuario lo pide) |
| Playwright `e2e/waitlist.spec.ts` (9.5) | **escrito, no ejecutado**: necesita la pila de Docker con el `worker` reiniciado y las credenciales de E2E |
| `openspec validate c-12-lista-de-espera --strict` | válido |

### 0.2 — Contexto de los botones de WhatsApp

Context7 no estaba disponible en esta sesión. Se verificó contra el código de C-10: el parser del
webhook (`notifications/payload.py`) ya lee `context.id` y el `payload` de los botones de respuesta
rápida de una plantilla, y el ruteo por contexto ya funcionaba para los recordatorios. D8 no cambió.

### Desvíos y decisiones durante la implementación

- **Orden TDD**: en los grupos 2, 5, 7.2, 8 y 9 el código se escribió antes o junto con su test
  (RED corrido solo en 1.x, 2.x, 3.1, 4.1–4.2, 6.1, 7.3 y 9.4). Se compensó con un chequeo de
  mutación del gancho de cancelación (sin él fallan 10 de 23 tests de evaluación) y con los tests de
  frontend que fallaron por motivos reales antes de pasar.
- **Bug real hallado (C-09)**: la migración `c09_reminder_engine` siembra plantillas leyendo el
  catálogo vivo, que ahora incluye `waitlist_offer`, un paso que su CHECK todavía no admite: una
  base anterior a C-09 con clínicas no habría migrado. C-09 ahora siembra solo sus pasos y
  `c12_waiting_list` hace el backfill de las dos plantillas de oferta en las clínicas existentes.
- **Reutilización en vez de extracción (3.2)**: `_contact`, `_match_or_create` y `_stamp_privacy`
  no se extrajeron a funciones: la anotación pública es un método más de `BookingPublicService`
  (`join_waitlist`), que los usa tal cual. Suite de C-07 verde.
- **`409 already_waiting` público**: suma `clinic_phone` (dato público de la clínica) para que la
  página pueda mostrar el teléfono que pide la spec `web/public-booking`; el catálogo no lo trae.
- **Spec ajustada (offer-delivery)**: una plantilla de oferta inactiva queda `failed
  (template_inactive)` y escala a email, igual que un recordatorio (la spec decía `skipped`).
- **Spec ajustada (agenda/appointments)**: el escenario "hueco en el pasado" se prueba sobre el
  alta del turno `waitlist`: como `expires_at ≤ starts_at`, una oferta de un hueco pasado siempre
  responde `409 offer_expired` antes.
- **Edición de entradas**: `date_from ≥ hoy` solo se valida si `date_from` cambia, para poder editar
  la franja de una entrada cuyo período ya empezó.
- **Retiro con oferta pendiente**: además de cerrar la oferta, el hueco rota a la siguiente entrada.
- **Webhook**: `OffersService.accept/decline` aceptan `commit=False` para correr dentro de la
  transacción del evento de WhatsApp; el cierre por hueco perdido queda en esa transacción.
- **Reporte de conversión y reloj**: los eventos usan `clock_timestamp()` de la base; el e2e pide la
  conversión en la ventana de la fecha real y los envíos en la del reloj simulado.
- **Tests**: los de entrantes de WhatsApp quedaron en `test_whatsapp_offer_replies.py` (no existía
  `test_whatsapp_inbound.py`); el cron del worker se prueba en `test_worker_runtime.py`.
- **Despliegue**: el `worker` no recarga código. Con la pila de desarrollo levantada antes de C-12,
  hay que reiniciarlo (`.\dev.ps1`) antes de crear ofertas: un worker viejo no sabe reclamar jobs
  sin `appointment_id`.
