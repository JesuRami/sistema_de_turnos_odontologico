# Tasks — C-06 `agenda-spa-recepcion`

> TDD rojo → verde en cada tarea: primero el test que falla (y se corre para
> verlo fallar), luego el mínimo código. Backend contra Postgres 15 + Redis 7
> reales (regla 9). Datos solo sintéticos (regla 13). TypeScript sin `any`
> (regla 5).

## 1. Backend: migración `c06_patient_merge`

- [x] 1.1 Test de base: `merged_into_patient_id` con FK compuesta intra-tenant,
  CHECKs (`<> id`, fusionado ⇒ archivado) y `patient_merge` rechaza UPDATE y
  DELETE. Verifica: `tests/models/test_patient_merge_db.py` en rojo y luego
  verde.
- [x] 1.2 Implementar la revisión (D9) con encabezado de regla 3/11, `NOT VALID`
  → `VALIDATE` y downgrade inverso; actualizar `test_migrations.py`.
  Verifica: `upgrade → downgrade -1 → upgrade` limpio y drift vacío.

## 2. Backend: perfil de clínica y detalle de paciente

- [x] 2.1 `GET /api/clinic` para todo el personal (`{id, name, timezone}`),
  `401` sin token. Verifica: `tests/modules/test_clinic_profile_api.py` verde.
- [x] 2.2 `GET /api/patients/{id}` (admin, recepción; odontólogo `403`; otra
  clínica `404`) con `archived_at`, `merged_into_patient_id` y
  `appointments_count`. Verifica: tests nuevos en `test_patients_api.py`.

## 3. Backend: fusión de pacientes

- [x] 3.1 `POST /api/patients/{id}/merge`: reasigna turnos de todos los estados
  con evento `updated` por turno, completa contactos nulos, archiva el
  duplicado y escribe `patient_merge`, todo en una transacción. Verifica:
  `tests/modules/test_patient_merge_api.py` verde.
- [x] 3.2 Validaciones `422 invalid_merge` (mismo, archivado, fusionado, otra
  clínica sin revelar), `extra='forbid'`, odontólogo `403`, payloads de
  auditoría sin PII. Verifica: mismo archivo verde.
- [x] 3.3 Carrera fusión vs. alta de turno del duplicado (dos sesiones con
  commits reales; `FOR SHARE` en `_assert_patient`): el turno queda en el
  conservado o el alta recibe `422 invalid_patient`, nunca colgado del
  duplicado. Verifica: `tests/modules/test_patient_merge_concurrency.py`.
- [x] 3.4 Rendimiento de la consulta de agenda: semana con 500 turnos responde
  bajo 500 ms en la API y usa índice. Verifica:
  `tests/modules/test_appointments_week_perf.py` verde.

## 4. Frontend: tooling de tests

- [x] 4.1 Agregar `@tanstack/react-query` y dev `vitest`, `jsdom`,
  `@testing-library/react`, `@testing-library/user-event`,
  `@testing-library/jest-dom`, `msw`, `@playwright/test`; `npm run test`
  (Vitest con `TZ=UTC`) y `npm run e2e`; job CI frontend corre `npm run test`.
  Verifica: un test de humo falla y luego pasa; `npm run typecheck` limpio.

## 5. Frontend: base compartida

- [x] 5.1 `shared/time/zoned.ts` (D4): partes en zona, hora de pared → instante,
  inicio de día/semana; DST de Europe/Madrid y Buenos Aires con navegador en
  UTC. Verifica: `zoned.test.ts` verde.
- [x] 5.2 `shared/api/client.ts` + `types.ts` + `errors.ts` (D2, D8):
  `ApiError` con extras, catálogo de mensajes y genérico para lo desconocido.
  Verifica: `client.test.ts`, `errors.test.ts` verdes.
- [x] 5.3 `shared/auth/session.ts` (D1): access en memoria, single-flight en
  pestaña y entre pestañas (`navigator.locks` + `BroadcastChannel` simulados),
  reintento único, logout ante `401` del refresh, nada en storage. Verifica:
  `session.test.ts` verde.

## 6. Frontend: sesión y rutas

- [x] 6.1 Pantallas de login (genérico ante `401`, `Retry-After` ante `429`),
  cambio de contraseña obligatorio y logout (aun con la API caída). Verifica:
  `LoginPage.test.tsx`, `ChangePasswordPage.test.tsx` verdes.
- [x] 6.2 `RequireSession`/`RequireRole` y rutas de D6 con recuperación de la
  sesión al recargar y vuelta a la ruta pedida tras el login. Verifica:
  `routes.test.tsx` verde.

## 7. Frontend: agenda

- [x] 7.1 Layout de grilla puro (día por sillón, semana por día con carriles,
  rango horario de las reglas) y tabla `allowedActions`. Verifica:
  `layout.test.ts`, `allowedActions.test.ts` verdes.
- [x] 7.2 `AgendaPage`: vista día/semana, navegación, filtros, color y
  distintivos (estado, sobreturno, bloqueo, pendiente < 24 h), carga paginada
  del rango y vista del odontólogo. Verifica: `AgendaPage.test.tsx` verde.
- [x] 7.3 Formulario de turno: búsqueda y alta rápida (`409 patient_duplicate`
  → usar existente), `409 slot_taken` con alternativos y sobreturno con
  motivo, `409 overbooking_limit`. Verifica: `AppointmentForm.test.tsx` verde.
- [x] 7.4 Detalle de turno: reprogramar (turno intacto ante rechazo), cancelar
  con motivo obligatorio, confirmar, presente/ausente/no-show solo cuando
  corresponde. Verifica: `AppointmentDetail.test.tsx` verde.

## 8. Frontend: administración y fusión

- [x] 8.1 Profesionales y sillones (alta, edición, activar/desactivar, sin
  borrar). Verifica: `ResourcesAdmin.test.tsx` verde.
- [x] 8.2 Plantilla semanal con `409 schedule_overlap` señalando conflictos.
  Verifica: `SchedulesAdmin.test.tsx` verde.
- [x] 8.3 Bloqueos y cierres: `409 block_conflicts` lista afectados y permite
  cancelarlos (no al odontólogo). Verifica: `BlocksPage.test.tsx` verde.
- [x] 8.4 Políticas (admin edita, recepción lee). Verifica:
  `PoliciesPage.test.tsx` verde.
- [x] 8.5 Fusión de pacientes: elegir conservado, ver ambas fichas y turnos a
  mover, advertencia irreversible, resultado y errores. Verifica:
  `MergePatientsPage.test.tsx` verde.

## 9. E2E

- [x] 9.1 Seed E2E sintético y Playwright contra Docker Compose: login con
  cambio de clave → crear turno (con 409 y alternativo) → presente. Verifica:
  `e2e/agenda.spec.ts` verde.
- [x] 9.2 Semana con 500 turnos visible en < 2 s (US-010 CA-3). Verifica:
  `e2e/agenda-perf.spec.ts` verde con el tiempo medido en la evidencia.

## 10. Cierre

- [x] 10.1 Gate: `alembic upgrade/downgrade -1/upgrade`, `pytest -q`, `ruff`,
  `black --check`, `mypy`, `npm run typecheck`, `npm run test`, Playwright,
  `openspec validate c-06-agenda-spa-recepcion --strict`. Verifica: todo verde
  con evidencia en una tabla al final de este archivo.
- [x] 10.2 Docs: `backend/README.md` (`GET /api/clinic`, detalle y fusión de
  pacientes, advertencia de downgrade) y `frontend/README.md` (rutas, sesión
  single-flight, scripts de test). Verifica: secciones presentes.
- [x] 10.3 `CHANGES.md`: notas de cierre de C-06 y diferidos (ABM de usuarios,
  drag & drop, reasignación de lista de espera y jobs en la fusión → C-09/C-12,
  Playwright en CI → C-14). Verifica: diff de CHANGES.md.

## Workflow follow-up

- `/opsx:archive c-06-agenda-spa-recepcion` y marcar `[x]` en CHANGES.md.

## Evidencia del apply (2026-11-03)

Backend en la imagen `api` (`python:3.12.7`) contra `postgres:15.8` + `redis:7.4`
en una red Docker propia. Frontend con Node 22 local. E2E con la API en un
contenedor (repo montado) sobre una base `turnos_e2e` migrada con el seed, Vite
local y Chromium de Playwright con el navegador en UTC.

| Tarea | Rojo | Verde |
|---|---|---|
| 1 Migración | `test_patient_merge_db.py` no colecta (falta `PatientMerge`) | `c06_patient_merge`; 173 tests de modelos + migraciones, drift vacío |
| 2 Perfil y detalle | 8 fallan (rutas inexistentes) | 47 passed (pacientes, perfil, políticas) |
| 3.1–3.3 Fusión | 11 fallan, incluida la carrera fusión vs. alta (sin `FOR SHARE`) | 15 passed |
| 3.4 Semana 500 turnos (API) | caracterización: pasa a la primera, no requirió código | < 500 ms, una página, plan sin seq scan con 20 000 turnos de ruido |
| 4.1 Tooling | humo sin config: falla | Vitest + jsdom + MSW, `TZ=UTC` |
| 5 Base compartida | cada archivo falla al no existir el módulo | 34 passed (zona horaria con DST, cliente, errores, sesión entre pestañas) |
| 6 Sesión y rutas | 9 + 9 fallan | 53 passed acumulados; 2 bugs reales: perfil ausente al arrancar y 401 de dominio que disparaba renovación |
| 7 Agenda | 15 + 9 + 9 + 7 fallan | 94 passed acumulados |
| 8 Administración y fusión | 5 + 4 + 5 + 4 + 3 fallan | 115 passed; bug real: el `Modal` robaba el foco en cada render |
| 9 E2E | circuito: falla con alternativos dependientes de la hora real | `agenda.spec.ts` y `agenda-perf.spec.ts` verdes; **semana de 500 turnos visible en 319 ms** |

Gate 10.1: `alembic upgrade head → downgrade -1 → upgrade head` OK; `pytest -q`
**671 passed + 1 fallo de entorno** (`test_auth_redis_url_usa_la_base_logica_configurada`
asserta `localhost:6379`; corrido en la red del contenedor Redis: verde);
`ruff`, `black --check` y `mypy` (174 archivos) limpios; `npm run typecheck`
limpio; `npm run test` **115 passed** (18 archivos); Playwright 2 passed;
`openspec validate c-06-agenda-spa-recepcion --strict` válido. No se corrió
`npm run build` (regla: solo con pedido explícito).
