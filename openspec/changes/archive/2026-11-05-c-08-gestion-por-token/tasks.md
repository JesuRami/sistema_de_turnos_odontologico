# Tasks — C-08 `gestion-por-token`

> TDD estricto rojo → verde: cada tarea **RED** escribe el test, lo corre y deja
> registrado que falla por la razón esperada; la **GREEN** siguiente escribe el
> mínimo código para pasarlo. Tests de invariantes y API con pytest + httpx
> contra Postgres 15 + Redis 7 reales (regla 9, sin mocks de DB). Datos solo
> sintéticos: nombres inventados, teléfonos `+54 11 5555-01xx`, emails
> `@example.com` (regla 13). Antes de tocar archivos existentes, correr su suite
> como red de seguridad y anotar el baseline. **No** se toca
> `openspec/changes/c-13-reportes-admin-export/` ni `backend/app/modules/reports/`.

## 0. Red de seguridad

- [x] 0.1 Correr `pytest -q` en `backend/` y `npx vitest run` en `frontend/` y
  anotar el baseline (N passed / N failed, con las fallas de entorno
  preexistentes de C-07: `test_auth_redis_url_usa_la_base_logica_configurada`).
  Verifica: tabla de baseline al final de este archivo; nada se arregla acá.

## 1. Migración `c08_manage_token` (D12)

- [x] 1.1 RED — `backend/tests/models/test_clinic_contact_phone_db.py`:
  `clinic.contact_phone` acepta `NULL` y un E.164 de 13 caracteres; rechaza 5 y
  33 caracteres por CHECK; el drift modelo↔migración no detecta diferencias.
  Verifica: `cd backend; pytest tests/models/test_clinic_contact_phone_db.py -q`
  → falla (columna inexistente).
- [x] 1.2 GREEN — Revisión `c08_manage_token` (`down_revision =
  c07_booking_public`): `ADD COLUMN contact_phone text` nullable; CHECK
  `clinic_contact_phone_length` `NOT VALID` → `VALIDATE CONSTRAINT`; sin
  índices; downgrade inverso. Columna y CHECK en el modelo `Clinic`. Verifica:
  `cd backend; pytest tests/models/test_clinic_contact_phone_db.py -q` verde y
  `cd backend; alembic upgrade head; alembic downgrade -1; alembic upgrade head`
  limpio.

## 2. Settings, claves de rate-limit y redacción del 422 (D10, D13)

- [x] 2.1 RED — `backend/tests/core/test_settings_manage.py`: los cuatro
  settings nuevos tienen default; un spec inválido (`"10/60"`, `"0/60s"`,
  `"abc"`) falla al instanciar `Settings` con mensaje de formato;
  `MANAGE_TOKEN_TTL_H=0` falla; `.env.example` contiene las cinco claves.
  Verifica: `cd backend; pytest tests/core/test_settings_manage.py -q` → falla.
- [x] 2.2 GREEN — Settings + `.env.example` (sin secretos, regla 6). Verifica:
  `cd backend; pytest tests/core/test_settings_manage.py -q` verde.
- [x] 2.3 RED — `backend/tests/common/test_manage_validation_redaction.py`: un
  422 de `/api/manage/{token}` con `note` de 300 caracteres devuelve
  `{"detail": "invalid_request", "fields": [...]}` y **no** incluye la nota ni
  el token; `/api/booking/` sigue redactando igual. Verifica:
  `cd backend; pytest tests/common/test_manage_validation_redaction.py -q` →
  falla (eco de FastAPI).
- [x] 2.4 GREEN — `app/common/exceptions.py`: `_PUBLIC_PREFIXES =
  ("/api/booking/", "/api/manage/")`. Verifica: el test de 2.3 verde y la suite
  de C-07 (`tests/modules/test_booking_public_*.py`) sigue verde.

## 3. Resolución del token y vista de gestión (D2, D3, D4, D5)

- [x] 3.1 RED — `backend/tests/modules/test_manage_resolve_api.py`: token válido
  → 200 con la vista; token desconocido y token malformado (10 chars) → 404
  `manage_link_not_found` con cuerpo idéntico; token de un turno terminado hace
  73 h → 410 `manage_link_expired`; hace 2 h → 200 sin acciones; cabeceras
  `Cache-Control: no-store` y `Referrer-Policy: no-referrer` en las tres rutas.
  Verifica: `cd backend; pytest tests/modules/test_manage_resolve_api.py -q` →
  falla (router inexistente).
- [x] 3.2 GREEN — `app/modules/manage/{router,service,schemas}.py`: router
  montado en `main.py`, `resolve()` con formato + SHA-256 + índice único y
  `expires_at = ends_at + MANAGE_TOKEN_TTL_H`. Verifica: el test de 3.1 verde.
- [x] 3.3 RED — Mismo archivo, minimización: la vista trae solo
  `patient_first_name`; el JSON crudo no contiene ids de turno/paciente/sillón/
  profesional, ni teléfono/email del paciente, ni `chair_id`; un turno
  `is_overbooking=false` se informa tal cual; `blocked_reason` es `past` para un
  turno ya iniciado. Verifica: `cd backend; pytest
  tests/modules/test_manage_resolve_api.py -q` → falla.
- [x] 3.4 GREEN — `ManageView` con `select` de columnas necesarias (regla 8) y
  armado de `actions`/`blocked_reason` en el servidor. Verifica: el test de 3.3
  verde.
- [x] 3.5 RED — Mismo archivo: el `reason_options` de la vista tiene exactamente
  los cinco valores del catálogo con etiqueta, en el orden del catálogo.
  Verifica: falla (lista inexistente). 3.6 GREEN — `manage/reasons.py`:
  `PatientReason` (StrEnum) + `REASON_OPTIONS` exportados y usados por el schema.
  Verifica: verde.

## 4. Disponibilidad para reprogramar (D8)

- [x] 4.1 RED — `backend/tests/modules/test_manage_availability_api.py`: huecos
  del **mismo** profesional (un turno ocupado a las 10:00 no se ofrece; las
  15:00 del turno propio sí); rango > 14 días, `to <= from` y más allá del
  horizonte → 422 `invalid_range`; token vencido → 410; respuesta sin ids de
  turnos, sillones ni pacientes; `no-store`. Verifica: `cd backend; pytest
  tests/modules/test_manage_availability_api.py -q` → falla.
- [x] 4.2 GREEN — `ManageService.availability()` reutilizando
  `BookingPublicService.offerable()` y `bookable_professional()` (mismo
  profesional del turno), con `ManageSlotRead` sin ids. Verifica: el test de 4.1
  verde y `tests/modules/test_booking_public_read_api.py` sigue verde.

## 5. Confirmar (D6)

- [x] 5.1 RED — `backend/tests/modules/test_manage_confirm_api.py`:
  `pending→confirmed` con 200 y evento `confirmed` (`actor_type=patient_token`,
  `actor_user_id` nulo, `from_status=pending`, `source=manage_link`); turno ya
  `confirmed` → 200 sin segundo evento `confirmed`; `cancelled` → 409
  `invalid_transition`; turno ya iniciado → 409 `appointment_started`; token
  vencido → 410 sin cambios. Verifica: `cd backend; pytest
  tests/modules/test_manage_confirm_api.py -q` → falla.
- [x] 5.2 GREEN — `ManageService.confirm()` con `Actor(type=PATIENT_TOKEN)` y
  `apply_transition`. Verifica: el test de 5.1 verde y
  `tests/modules/test_appointments_transitions_api.py` sigue verde.

## 6. Idempotencia auditada de las tres acciones (D9)

- [x] 6.1 RED — `backend/tests/modules/test_manage_idempotency_api.py`: repetir
  `confirm`, `cancel` y `reschedule` (mismo horario actual) responde 200 y deja
  **un** evento `updated` con `idempotent_replay=true` y `action` correcta;
  `COUNT(*)` de eventos `confirmed`/`cancelled` no aumenta; el reporte de
  cancelaciones (`GET /api/reports/cancellations`) sigue contando 1.
  Verifica: `cd backend; pytest tests/modules/test_manage_idempotency_api.py -q`
  → falla.
- [x] 6.2 GREEN — Detección de estado ya alcanzado + `record_event(UPDATED, …)`
  en la misma transacción (helper `_replay()`). Verifica: 6.1 verde, 20 corridas
  seguidas.

## 7. Cancelar (D7)

- [x] 7.1 RED — `backend/tests/modules/test_manage_cancel_api.py`: dentro de la
  ventana (5 días) → 200 `cancelled`, evento con `reason=paciente`, `late=false`,
  `patient_reason=viaje`; sin `reason` → 200 y sin `patient_reason`; nota de 201
  caracteres → 422 `invalid_request` y turno intacto; motivo fuera del catálogo
  → 422; `present` → 409 `invalid_transition`; turno de ayer → 422
  `appointment_in_past`; ventana 24 h con turno en 3 h → 409
  `cancellation_window_closed` y turno vigente; `cancellation_note` guardada solo
  con `otro`. Verifica: `cd backend; pytest
  tests/modules/test_manage_cancel_api.py -q` → falla.
- [x] 7.2 GREEN — `ManageService.cancel()` con el orden de validaciones de D7 y
  el mapeo causa/detalle. Verifica: 7.1 verde.
- [x] 7.3 RED — Mismo archivo: cancelar libera el hueco en
  `GET /api/manage/{token}/availability` de otro turno del mismo profesional y
  en la agenda de recepción (`GET /api/appointments`). Verifica: falla si la
  transición no commitea antes de la lectura. 7.4 GREEN — Ajustes que surjan.
  Verifica: verde.

## 8. Reprogramar (D8)

- [x] 8.1 RED — `backend/tests/modules/test_manage_reschedule_api.py`: mover
  10:00 → 11:00 responde 200 con el **mismo id**, `starts_at` nuevo y evento
  `rescheduled` con `before/after`; el origen y el `manage_token_hash` se
  conservan; fuera de ventana → 409 `cancellation_window_closed`; inicio fuera de
  grilla (09:10) → 422 `slot_not_offered`; inicio pasado → 422
  `appointment_in_past`; hueco ocupado → 409 `slot_taken` con `alternatives`
  (solo `starts_at`/`ends_at`) y el turno conserva horario, estado y sillón.
  Verifica: `cd backend; pytest tests/modules/test_manage_reschedule_api.py -q`
  → falla.
- [x] 8.2 GREEN — `AppointmentsService.reschedule(...)` sin commit (promoción de
  `_reschedule`, con `update()` delegando), candidatos con `chairs_on_grid`,
  reintento por sillón en un `begin_nested()` y traducción de
  `outside_schedule`/`slot_blocked`/`resource_inactive`. Verifica: 8.1 verde y
  `tests/modules/test_appointments_reschedule_api.py` +
  `tests/modules/test_appointments_overbooking_api.py` siguen verdes.
- [x] 8.3 RED — Dos sillones con regla a la misma hora, uno ocupado → se mueve al
  libre; el turno cae completo dentro de la plantilla (el borde no se sale de la
  franja). Verifica: falla. 8.4 GREEN — Orden por `chair_id` y revalidación de
  duración en `_resolve`. Verifica: verde.

## 9. Invariante de base y concurrencia (regla 1)

- [x] 9.1 RED — `backend/tests/modules/test_manage_concurrency.py`: dos turnos
  reprogramados al mismo hueco en paralelo (`asyncio.gather`, dos sesiones) →
  exactamente un 200 y un 409 `slot_taken`, y ningún turno queda en horario
  intermedio; recepción creando un turno mientras el paciente reprograma →
  uno solo gana. Verifica: `cd backend; pytest
  tests/modules/test_manage_concurrency.py -q` → falla.
- [x] 9.2 GREEN — Ajustes de locking (profesional → sillón, orden por id) hasta
  verde. Verifica: 9.1 verde, 20 corridas seguidas.
- [x] 9.3 RED — Test de defensa en profundidad: desactivar el pre-chequeo de
  conflictos (mutación local, sin commitear) y comprobar que la carrera sigue
  produciendo 409 por `23P01` del `EXCLUDE`; restaurar. Verifica: el test pasa
  con la mutación aplicada (la garantía es de la base).

## 10. Invalidación de recordatorios (D11)

- [x] 10.1 RED — `backend/tests/modules/test_manage_reminders_hook.py`: con un
  `ReminderInvalidator` espía por override de dependencia, `confirm`, `cancel` y
  `reschedule` lo invocan exactamente una vez con el turno y la acción correcta;
  una excepción del hook revierte la mutación; con el no-op las tres acciones
  funcionan igual. Verifica: `cd backend; pytest
  tests/modules/test_manage_reminders_hook.py -q` → falla.
- [x] 10.2 GREEN — `app/modules/reminders/invalidation.py` (Protocol +
  `NoopReminderInvalidator` + `get_reminder_invalidator`), invocado dentro de la
  transacción. Verifica: 10.1 verde y la suite de `reminders` verde.

## 11. Rate-limit estricto (D10)

- [x] 11.1 RED — `backend/tests/modules/test_manage_rate_limit.py`: superar
  `MANAGE_WRITE_TOKEN_RATE_LIMIT` con un token → 429 `rate_limited` con
  `Retry-After` y turno intacto; barrido de muchos tokens desde una IP → 429
  antes que 404; otra IP no se ve afectada; un 422 gasta cupo de escritura; Redis
  caído → 503 `manage_unavailable` sin mutación; las claves en Redis contienen
  el hash y **no** el token. Verifica: `cd backend; pytest
  tests/modules/test_manage_rate_limit.py -q` → falla.
- [x] 11.2 GREEN — Claves en `core/rate_limit.py`, `consume` en el router
  (IP antes de resolver, token antes de la DB) y 503 fail-closed. Verifica: 11.1
  verde.

## 12. Aislamiento cross-tenant (regla 4)

- [x] 12.1 RED — `backend/tests/modules/test_manage_tenancy.py`: token de un
  turno de B usado contra recursos de A → 404 y ninguna de las dos cambia; la
  disponibilidad de A no se ve afectada por turnos de B; un turno de B no aparece
  en la vista de A; mutar por token escribe eventos solo en la clínica del turno.
  Verifica: `cd backend; pytest tests/modules/test_manage_tenancy.py -q` → falla
  o pasa por construcción; en ese caso se demuestra con una mutación (quitar el
  filtro `clinic_id` de una consulta rompe el test) y se restaura.
- [x] 12.2 GREEN — Filtros y ajustes que surjan. Verifica: 12.1 verde.

## 13. Higiene del token y de los datos (reglas 13 y D2)

- [x] 13.1 RED — `backend/tests/modules/test_manage_token_hygiene.py`: el token
  no aparece en `caplog` (nivel DEBUG durante toda la request), ni en
  `appointment_event.payload`, ni en el cuerpo de errores 404/409/410/422/429;
  las claves de Redis no lo contienen; la vista no trae `phone_e164` ni `email`
  del paciente; un 422 con `note` no la ecoa. Verifica: `cd backend; pytest
  tests/modules/test_manage_token_hygiene.py -q` → falla.
- [x] 13.2 GREEN — Logging del módulo sin path ni token y cabeceras en el
  router. Verifica: 13.1 verde.

## 14. Teléfono de contacto de la clínica (D12)

- [x] 14.1 RED — `backend/tests/modules/test_clinic_contact_phone_api.py`: admin
  guarda `+54 11 5555-0100` → `ClinicPolicies` devuelve `+541155550100`;
  recepción → 403; teléfono inválido → 422 y valor anterior conservado;
  `contact_phone: null` → 422 (no se borra en v1). Verifica: `cd backend;
  pytest tests/modules/test_clinic_contact_phone_api.py -q` → falla.
- [x] 14.2 GREEN — `ClinicPolicies`/`ClinicPoliciesUpdate` +
  `update_policies` normalizando con `normalize_phone_e164`. Verifica: 14.1
  verde y `tests/modules/test_clinic_policies_api.py` sigue verde.
- [x] 14.3 RED — `backend/tests/test_seed_manage.py`: el seed de la clínica demo
  deja un `contact_phone` sintético y es idempotente al reejecutar. Verifica:
  falla. 14.4 GREEN — Extender `app.seed`. Verifica: verde.

## 15. Frontend `/g/:token` (D14, `web/manage-token`)

> **Criterio de aceptación visual (aprobado 2026-11-05, by user):** la
> implementación se compara contra `mockups/01-pending.html` … `06-expired.html`
> y sus capturas en `mockups/previews/` (390×844 y 1440×900), usando el design
> system revisión 1. Cualquier desvío intencional se anota en `design.md`
> (`## UI Mockups`) antes de tocar el mockup; no se modifica un mockup aprobado
> en silencio.
>
> Mapa mockup → tarea: `01-pending`/`02-confirmed` → 15.2/15.4; `03-cancel` →
> 15.4 `CancelDialog`; `04-window-closed` → 15.4 `ManageError`
> (`409 cancellation_window_closed`); `05-reschedule` → 15.4 `ReschedulePanel`;
> `06-expired` → 15.4 `ManageContact` (`404`/`410`).

- [x] 15.1 RED — `frontend/src/features/manage/ManagePage.test.tsx` (Vitest +
  Testing Library + MSW): vista `pending` con las tres acciones; `confirmed` sin
  botón de confirmar; ventana cerrada deshabilita cancelar/reprogramar y muestra
  el teléfono; `cancelled` sin acciones y con "volver a reservar"; estados de
  carga con `aria-live` y fechas en la zona de la clínica con el navegador en
  UTC. Verifica: `cd frontend; npx vitest run src/features/manage` → falla.
- [x] 15.2 GREEN — `api.ts`, `types.ts` (sin `any`), `queries.ts`,
  `useManageActions`, `ManageSummary` y `ManagePage` con QueryClient propio.
  Verifica: 15.1 verde.
- [x] 15.3 RED — `ManageActions.test.tsx`: confirmar envía una sola request con
  doble toque; cancelar pide motivo (opcional) y confirma la acción destructiva;
  `409 cancellation_window_closed` deriva a la clínica; `409 slot_taken` muestra
  alternativos y reenvía con el horario elegido; `410`/`404` muestran la pantalla
  de contacto; después de usar la página `localStorage`/`sessionStorage` están
  vacíos de token y datos. Verifica: falla.
- [x] 15.4 GREEN — `ConfirmAction`, `CancelDialog`, `ReschedulePanel`,
  `ManageContact`, `ManageError` y copy según `frontend-design`. Verifica: 15.3
  verde.
- [x] 15.5 RED — `frontend/src/features/admin/PoliciesPage.test.tsx`: el admin ve
  y guarda el teléfono de contacto; recepción no ve el campo. Verifica: falla.
- [x] 15.6 GREEN — Campo en `PoliciesPage` + tipos. Verifica: verde.

## 16. E2E crítico (Playwright)

- [x] 16.1 RED — `frontend/e2e/manage.spec.ts` contra el stack real (setup por
  API del global-setup, datos sintéticos): crear una reserva, abrir el
  `manage_url` a 360×740 sin scroll horizontal ni botones < 44 px, confirmar y
  ver el estado confirmado en la página y en la agenda de recepción sin
  recargar; cancelar otro turno con motivo y verlo `cancelled`; reprogramar y ver
  el nuevo horario; abrir un token vencido y ver la pantalla de contacto.
  Verifica: `cd frontend; npm run e2e -- manage.spec.ts` → falla antes de 15.x.
- [x] 16.2 GREEN — Ajustes que surjan del E2E. Verifica: `cd frontend; npm run
  e2e` verde.

## 17. Documentación, gates y cierre

- [x] 17.1 `backend/README.md`: endpoints de gestión, códigos de error, cupos,
  TTL, decisión de transporte del token y requisito de **redactar `/g/` y
  `/api/manage/` en el access log** de uvicorn/nginx. Verifica: sección presente.
- [x] 17.2 `knowledge-base/10_preguntas_abiertas.md`: la pregunta Alta de
  rotación del `manage_token` queda marcada como *resuelta con default (no
  rotar), pendiente de confirmación del Tech Lead + PO*, apuntando a la decisión
  abierta #1 de este change. Verifica: diff del archivo.
- [x] 17.3 Gate backend: `cd backend; alembic upgrade head; alembic downgrade -1;
  alembic upgrade head`, `pytest -q` (Postgres 15 + Redis 7 reales),
  `ruff check backend`, `black --check backend`, `mypy backend`. Verifica: todo
  verde, evidencia en la tabla final.
- [x] 17.4 Gate frontend: `cd frontend; npx tsc --noEmit`, `npx vitest run`,
  `npm run e2e`. Verifica: todo verde (el proyecto no tiene `eslint`; se cumple
  con `tsc` estricto + `grep` de `any` sin resultados).
- [x] 17.5 `openspec validate c-08-gestion-por-token --strict` y
  `openspec validate --changes --strict`. Verifica: válido.
- [x] 17.6 `CHANGES.md`: notas de cierre de C-08 y contratos diferidos
  (recordatorios reales → C-09; webhook "SI/NO" → C-10; reporte por motivo del
  paciente → change futuro; rotación del token → decisión abierta #1;
  reprogramación con otro profesional → sin change asignado). Verifica: diff de
  `CHANGES.md`.

## Workflow follow-up

- `/opsx:archive c-08-gestion-por-token` y marcar `[x]` en `CHANGES.md`.
- Antes del apply: crear `mockups/` y obtener `Approval: approved` (modo
  `system-and-mockups`).

## Evidencia del apply

| Tarea | Test | Capa | Red de seguridad | RED | GREEN | Triangulación |
|---|---|---|---|---|---|---|
| 0.1 | `pytest -q` (backend) | Backend | 866 passed / 0 failed (90 s) | — | — | — |
| 0.1 | `npx vitest run` (frontend) | Frontend | 22 files / 158 tests passed (34 s) | — | — | — |
| 1.1 | `tests/models/test_clinic_contact_phone_db.py` | DB | — | 5 failed (columna inexistente, CHECK ausente) | — | — |
| 1.2 | idem | DB | — | — | 6 passed | `test_migrations.py` 17 passed (ciclo + drift) |
| 2.1–2.4 | `test_settings_manage.py`, `test_manage_validation_redaction.py` | Backend | — | no registrado por el agente anterior | verificado en verde (2026-11-05, línea base 900 passed) | — |
| 3.1 | `test_manage_resolve_api.py` | API | 900 passed (Py 3.12 + PG 15 + Redis 7, sin `.env`) | 5 failed (router inexistente) | 5 passed | — |
| 3.3 | idem (minimización) | API | — | 4 failed (campos faltantes); el de no-filtración pasó por construcción | 10 passed | — |
| 3.5 | idem (catálogo) | API | — | 1 failed (`KeyError reason_options`) | 11 passed | — |
| 4.1 | `test_manage_availability_api.py` | API | — | 8 failed | 8 passed | suites de reserva pública C-07: 57 passed |
| 5.1 | `test_manage_confirm_api.py` | API + estados | — | 8 failed | 8 passed | `test_appointments_transitions_api.py` verde (29 passed en total) |
| 7.1 | `test_manage_cancel_api.py` | API | — | 6 failed (3 pasaban por la razón equivocada: 422 de cualquier cuerpo) | 9 passed | — |
| 7.3 | idem (libera el hueco) | API | — | pasó por construcción: con la sesión compartida el flush ya es visible; el commit lo cubren los tests de la sección 9 con commits reales | 10 passed | — |
| 8.1 / 8.3 | `test_manage_reschedule_api.py` | API | — | 7 failed | 7 passed (8.3 pasó con 8.2: orden por `chair_id` y duración en `_resolve`) | reprogramación de recepción + sobreturnos + reserva pública: 59 passed |
| 6.1 | `test_manage_idempotency_api.py` (hecha después de 7 y 8: necesita las tres acciones) | API | — | 3 failed (sin evento de replay) | 3 passed | 20/20 corridas seguidas |
| 9.1 | `test_manage_concurrency.py` | Invariante (commits reales) | — | deadlock real recepción↔paciente (`DeadlockDetectedError`) | 3 passed tras unificar el orden de locks | 20/20 corridas seguidas |
| 9.3 | idem, `find_conflicts` anulado por `monkeypatch` | Invariante | — | `MissingGreenlet` (bug latente de C-05 en `_write`) | 409 por `23P01` del EXCLUDE | concurrencia de C-05 verde |
| 10.1 | `test_manage_reminders_hook.py` | API | — | error de colección (módulo inexistente) | 7 passed (35 con las suites de acciones) | — |
| 11.1 | `test_manage_rate_limit.py` | API + Redis | — | 5 failed | 5 passed | — |
| 12.1 | `test_manage_tenancy.py` | API | — | pasó por construcción | 3 passed | mutación: sin el join por `clinic_id` → 3 failed; restaurado → 3 passed |
| 13.1 | `test_manage_token_hygiene.py` | API + logs | — | 2 failed: el 422 listaba las 3 variantes (discriminador perdido en `Body()`) | 2 passed | solo logs de la app (los de `httpx` son del cliente de test) |
| 14.1 | `test_clinic_contact_phone_api.py` | API | — | 5 failed | 6 passed | `test_clinic_policies_api.py` actualizado (+`contact_phone`) y verde |
| 14.3 | `test_seed_manage.py` | Seed | — | ImportError | 1 passed | suites del seed: 15 passed |
| 15.1 | `ManagePage.test.tsx` | Vitest + MSW | 158 passed | 6 failed | 6 passed | reserva pública (refactor a `publicFetch`) verde |
| 15.3 | `ManageActions.test.tsx` | Vitest + MSW | — | 11 failed | 11 passed tras corregir el doble envío (commit intermedio con el botón viejo) | 5/5 corridas |
| 15.5 | `PoliciesPage.test.tsx` | Vitest + MSW | — | 2 failed | 15 passed | — |
| 16.1 | `e2e/manage.spec.ts` | Playwright (stack real aislado) | — | no reproducible (escrito después de 15.x) | 4 passed | suite E2E completa: 9 passed, 2 skipped (stubs de C-14) |
| 17.3 | gate backend | — | — | — | `upgrade → downgrade -1 → upgrade` OK; 975 passed; ruff, black, mypy (235) limpios | — |
| 17.4 | gate frontend | — | — | — | `tsc --noEmit` 0; Vitest 177 passed (24 files); sin `any`; E2E 9 passed / 2 skipped | `session.test.ts` intermitente preexistente (aislado 3/3) |
| 17.5 | `openspec validate` | — | — | — | c-08 y `--changes --strict` válidos | — |
