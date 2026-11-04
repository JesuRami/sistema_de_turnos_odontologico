# Tasks — C-07 `booking-publico`

> TDD estricto rojo → verde: cada tarea **RED** escribe el test, lo corre y deja
> registrado que falla por la razón esperada; la tarea **GREEN** siguiente escribe
> el mínimo código para pasarlo. Tests de invariantes y API con pytest + httpx
> contra Postgres 15 + Redis 7 reales (regla 9, sin mocks de DB). Datos solo
> sintéticos: nombres inventados, teléfonos ficticios, emails `@example.com`
> (regla 13). Antes de tocar archivos existentes, correr su suite como red de
> seguridad y anotar el baseline.

## 0. Red de seguridad

- [x] 0.1 Correr `pytest -q` completo y la suite de frontend (`vitest run`) y
  anotar el baseline (N passed) en la evidencia al final de este archivo; si algo
  falla antes de empezar, reportarlo como falla preexistente y no arreglarlo.
  Verifica: tabla de evidencia con el baseline.

## 1. Migración `c07_booking_public` (D10)

- [x] 1.1 RED — `tests/models/test_appointment_manage_token_db.py`: turno
  `online` sin hash → violación de CHECK; hash de 31 bytes → CHECK; dos turnos con
  el mismo hash → unicidad; turno de recepción sin hash → OK. Verifica: el test
  falla (columna inexistente).
- [x] 1.2 GREEN — Revisión `c07_booking_public` (`down_revision` = cabeza vigente
  al aplicar, hoy `c13_event_slot`) con encabezado de reglas 3/11: columna
  nullable, CHECKs `NOT VALID → VALIDATE`, índice único parcial `CONCURRENTLY` en
  `autocommit_block`; downgrade inverso. Columna, CHECKs e índice en el modelo
  `Appointment`. Verifica: 1.1 verde, `alembic upgrade head → downgrade -1 →
  upgrade head` limpio y test de drift modelo↔migración verde.

## 2. Piezas comunes y configuración

- [x] 2.1 RED — Tests de settings: los seis settings nuevos de D14 tienen
  default, `PUBLIC_BOOKING_*_RATE_LIMIT` inválido falla al arrancar con mensaje
  de formato; `.env.example` contiene todas las claves (test que parsea el
  archivo). Verifica: tests fallan.
- [x] 2.2 GREEN — Settings + `.env.example` (sin secretos, regla 6). Verifica:
  2.1 verde.
- [x] 2.3 RED — Tests de `app/common/rate_limit_guard.py`: consumo dentro de
  cupo pasa; excedido → `429 rate_limited` con `Retry-After`; Redis caído →
  `503` con el código pedido (`booking_unavailable`). Contra Redis real (y un
  cliente apuntado a un puerto cerrado para la caída). Verifica: tests fallan.
- [x] 2.4 GREEN — Extraer `_consume` de auth a `rate_limit_guard` parametrizado y
  `client_ip` a `app/common/request_meta.py` (D11); auth los reutiliza. Verifica:
  2.3 verde y la suite de auth (baseline de 0.1) sigue verde.

## 3. Disponibilidad pública (D3)

- [x] 3.1 RED — `tests/modules/test_public_availability.py` (unit, sin DB) sobre
  la función pura: escenario del spec (franja 09:00–12:00/30 min, buffer 10, turno
  10:00, bloqueo 11:00–12:00 → solo 09:00); unión de dos sillones con dedupe por
  inicio; sillón ocupado y otro libre → el hueco se ofrece; turno vigente del
  profesional en otro sillón bloquea el hueco; nada antes de `now`; salto de
  horario de una zona simulada. Verifica: tests fallan (módulo inexistente).
- [x] 3.2 GREEN — `booking_public/availability.py` reutilizando `suggest_slots`.
  Verifica: 3.1 verde.
- [x] 3.3 RED — `tests/modules/test_booking_public_read_api.py`: `GET
  /api/booking/{slug}` (catálogo solo con profesionales reservables, solo `id` +
  `display_name`); slug inexistente y `booking_enabled=false` → `404
  booking_not_found` con cuerpo idéntico; `availability` descuenta
  turnos/bloqueos/buffers y libera al cancelar; respuesta sin ids de turnos,
  pacientes, sillones, estados ni PII (assert sobre el JSON crudo con los datos
  sintéticos sembrados); `422 invalid_range` (> 14 días, `to <= from`, más allá
  del horizonte); `404 professional_not_found` (ajeno, inactivo,
  `booking_enabled=false`, sin regla); `Cache-Control: no-store`. Verifica: tests
  fallan (rutas inexistentes).
- [x] 3.4 GREEN — Router + servicio + schemas (`extra='forbid'`) de lectura;
  eliminar el stub `/booking-public/ping` y actualizar su test de cableado de
  C-01. Verifica: 3.3 verde.
- [x] 3.5 RED — Cupo de lecturas: superar `PUBLIC_BOOKING_READ_RATE_LIMIT` →
  `429` con `Retry-After`, también barriendo slugs inexistentes; Redis caído →
  `503 booking_unavailable`. Verifica: tests fallan.
- [x] 3.6 GREEN — Consumo del cupo de lectura antes de resolver el slug.
  Verifica: 3.5 verde.

## 4. Reserva: contacto, consentimiento y bordes (D4, D5)

- [x] 4.1 RED — `tests/modules/test_booking_public_create_api.py`, validación:
  sin contacto → `422 contact_required` (y no hay paciente ni turno nuevos);
  `privacy_accepted=false` → `422 privacy_consent_required`; teléfono válido +
  `whatsapp_opt_in=false` sin email → `422 whatsapp_opt_in_required`; teléfono
  inválido sin email → `422 contact_required`; cuerpo con `duration_min`,
  `chair_id`, `status`, `origin` o `clinic_id` → `422`; `starts_at` sin zona →
  `422`. En todos, ni la respuesta ni `caplog` contienen nombre ni teléfono
  enviados. Verifica: tests fallan.
- [x] 4.2 GREEN — Schema de reserva (`extra='forbid'`, `EmailStr`) y validación de
  contacto según la tabla de D5. Verifica: 4.1 verde.
- [x] 4.3 RED — Mismo archivo, éxito: teléfono nacional + opt-in → 201,
  `channel=whatsapp`, paciente con E.164 y opt-in; teléfono inválido + email →
  201, `channel=email`, aviso `phone_invalid_email_channel`, paciente sin
  teléfono; opt-in rechazado + email → aviso `whatsapp_declined_email_channel`;
  turno `pending`, `origin=online`, `is_overbooking=false`, duración = la de la
  regla (45 min); privacidad guardada con `PRIVACY_POLICY_VERSION`; el turno
  aparece en `GET /api/appointments` de recepción. Verifica: tests fallan.
- [x] 4.4 GREEN — `BookingPublicService.book`: resolución de clínica/profesional,
  candidatos por grilla, alta vía `AppointmentsService.book(origin=ONLINE)` con
  `Actor(type=PATIENT_TOKEN)`; extender `Booking` con `manage_token_hash` y `book()`
  con `event_extra` (D4). Verifica: 4.3 verde y suite de turnos de C-05 verde.
- [x] 4.5 RED — Grilla: inicio fuera de grilla (09:10) → `422 slot_not_offered`;
  fuera de horario → `422 slot_not_offered`; inicio pasado → `422
  appointment_in_past`; dos sillones con regla a la misma hora, uno ocupado → se
  crea en el libre. Verifica: tests fallan.
- [x] 4.6 GREEN — Selección de sillón en orden de id con reintento dentro de la
  transacción (D4). Verifica: 4.5 verde.

## 5. Match de paciente (D7, RN-ON-05)

- [x] 5.1 RED — `tests/modules/test_booking_public_patient_match.py`: mismo
  teléfono + mismo nombre con otras mayúsculas → reutiliza; mismo teléfono +
  otro nombre → paciente nuevo (familia); paciente archivado no se reutiliza;
  mismo teléfono y nombre solo en la clínica B → paciente nuevo en A; recurrente
  con email distinto conserva el suyo; opt-in `false → true` sí, `true → false`
  nunca; dos reservas concurrentes del mismo paciente nuevo en horarios distintos
  (`asyncio.gather`, dos sesiones) → un solo paciente. Verifica: tests fallan.
- [x] 5.2 GREEN — Match-o-alta con `pg_advisory_xact_lock` y criterio de nombre
  normalizado de C-05 D11. Verifica: 5.1 verde 20 corridas seguidas del test
  concurrente.

## 6. Token de gestión (D8)

- [x] 6.1 RED — `tests/modules/test_booking_public_token.py`: el 201 trae
  `manage_url` = `FRONTEND_PUBLIC_URL/g/<token>` con token URL-safe ≥ 43
  caracteres y `Cache-Control: no-store` + `Referrer-Policy: no-referrer`; la
  base guarda `sha256(token)` (32 bytes) y ninguna columna de `appointment` ni
  `appointment_event.payload` contiene el token; `caplog` no lo contiene; dos
  reservas → tokens distintos. Valor esperado calculado con `hashlib` en el test
  a partir del token devuelto (verdad independiente). Verifica: tests fallan.
- [x] 6.2 GREEN — Generación `secrets.token_urlsafe(32)` + hash en la misma
  transacción. Verifica: 6.1 verde.

## 7. Auditoría

- [x] 7.1 RED — El turno online tiene un evento `created` con
  `actor_type=patient_token`, `actor_user_id` nulo, `origin=online`, `channel` y
  sin nombre/teléfono/email/token en el payload; una falla inyectada al escribir
  el evento revierte turno **y** paciente nuevo. Verifica: test falla.
- [x] 7.2 GREEN — `event_extra` con canal y `whatsapp_opt_in_granted`. Verifica:
  7.1 verde.

## 8. Carrera y 409 público (D6)

- [x] 8.1 RED — `tests/modules/test_booking_public_concurrency.py`: dos reservas
  online por el mismo hueco (dos sesiones, `asyncio.gather`) → exactamente un 201
  y un `409 slot_taken` con `alternatives` (solo `starts_at`, `ends_at`,
  `professional_id`; sin `conflicts` ni `chair_id`); recepción vs. online por el
  mismo hueco → uno solo gana; el perdedor no deja paciente nuevo. Verifica:
  tests fallan (hoy se filtraría `conflicts`).
- [x] 8.2 GREEN — Captura del 409 de `book()`, rollback y armado de
  alternativos públicos con D3 (`n=3`, 14 días); `resource_inactive` y
  `slot_blocked` se reducen a `slot_taken`. Verifica: 8.1 verde 20 rondas
  seguidas.

## 9. Anti-abuso (D2)

- [x] 9.1 RED — `tests/modules/test_booking_public_rate_limit.py`: 10 reservas
  desde una IP en la ventana y la undécima → `429 rate_limited` con `Retry-After`
  y sin turno; un 422 también consume cupo; otra IP sigue pudiendo reservar; cupo
  por slug agotado (setting bajo en el test) → `429` para cualquier IP; Redis
  caído → `503 booking_unavailable` sin turno. La IP se varía con el `client` del
  transport ASGI de httpx. Verifica: tests fallan.
- [x] 9.2 GREEN — Consumo de cupos IP (antes de validar) y slug (tras resolver).
  Verifica: 9.1 verde.
- [x] 9.3 RED — `BotGuard`: sin campo de CAPTCHA → 201 con el `NoopBotGuard`;
  override de dependencia con un guard que rechaza → `403 bot_check_failed` y no
  hay paciente ni turno. Verifica: tests fallan.
- [x] 9.4 GREEN — Protocolo `BotGuard`, `NoopBotGuard`, `get_bot_guard` por
  setting `BOT_GUARD`. Verifica: 9.3 verde.

## 10. Aislamiento cross-tenant (regla 4)

- [x] 10.1 RED — `tests/modules/test_booking_public_tenancy.py`: turno de B a
  las 10:00 no quita el hueco de A; slug de A + profesional de B → `404
  professional_not_found` en disponibilidad y reserva, y B no registra filas
  nuevas; el match nunca reutiliza pacientes de B; el cupo por slug de A no
  afecta a B. Verifica: tests fallan o, si ya pasan por construcción, se
  demuestra con una mutación (quitar el filtro `clinic_id` de una consulta rompe
  el test) y se restaura.
- [x] 10.2 GREEN — Ajustes que surjan de 10.1. Verifica: 10.1 verde.

## 11. Seed y documentación de backend

- [x] 11.1 RED — Test del seed: la clínica demo queda con `booking_enabled=true`
  y al menos un profesional reservable con regla vigente; reejecutar es
  idempotente. Verifica: test falla.
- [x] 11.2 GREEN — Extender `app.seed` (datos sintéticos). Verifica: 11.1 verde.
- [x] 11.3 `backend/README.md`: endpoints públicos, códigos de error, cupos y
  settings, decisión sin CAPTCHA + `BotGuard`, token (solo hash), advertencia de
  downgrade. Verifica: sección presente.

## 12. Frontend `/b/:slug` (D12, `web/public-booking`)

- [x] 12.1 RED — Vitest + Testing Library + MSW en `features/booking`: catálogo →
  día → hora → datos → confirmación en ≤ 4 pasos; un solo profesional saltea el
  primer paso; volver atrás conserva selección; casilla de WhatsApp aparece sin
  marcar al escribir teléfono; no envía sin contacto ni privacidad; horarios en
  la zona de la clínica con el navegador en UTC. Verifica: tests fallan.
- [x] 12.2 GREEN — `api.ts` (`credentials: "omit"`, tipos de borde sin `any`),
  `useBookingFlow`, componentes de los pasos y `BookingPage`. Verifica: 12.1 verde.
- [x] 12.3 RED — Errores y confirmación: `409` muestra alternativos y elegir uno
  reenvía con los mismos datos; `422` marca el campo; `429` con `Retry-After: 600`
  dice "10 minutos"; `404` informa link no disponible; `503`; aviso
  `phone_invalid_email_channel`; confirmación con link de gestión y "Copiar
  link"; tras reservar, `localStorage`/`sessionStorage` vacíos de token y datos.
  Verifica: tests fallan.
- [x] 12.4 GREEN — `BookingError`, `Confirmation` y copy según
  `frontend-design`. Verifica: 12.3 verde.

## 13. Agenda de recepción (D13, `web/agenda-board`)

- [x] 13.1 RED — Test de la agenda (fake timers + MSW): con la pestaña visible
  vuelve a pedir el rango a los 30 s y muestra un turno `pending` nuevo; con
  `document.visibilityState="hidden"` no pide. Verifica: test falla.
- [x] 13.2 GREEN — `refetchInterval: 30_000` en la query del rango. Verifica:
  13.1 verde y la suite de C-06 sigue verde.

## 14. E2E crítico (Playwright)

- [x] 14.1 RED — `frontend/e2e/booking.spec.ts` contra el stack real (setup por
  API del global-setup, datos sintéticos): en viewport 360×740 sin scroll
  horizontal y botones ≥ 44 px, reservar un hueco en ≤ 4 pasos y ver la
  confirmación con link; recepción logueada en otra página ve el turno pendiente
  en ≤ 30 s sin recargar; una segunda reserva del mismo hueco desde otro contexto
  ve "Ese horario se acaba de ocupar" con alternativos. Verifica: el spec falla
  antes de 12–13 o, si se escribe después, se muestra rojo revirtiendo la ruta.
- [x] 14.2 GREEN — Ajustes que surjan del E2E. Verifica: `npm run e2e` verde.

## 15. KB y cierre

- [x] 15.1 `knowledge-base/10_preguntas_abiertas.md`: pregunta Alta de
  CAPTCHA/anti-bot marcada resuelta (2026-11-04: sin CAPTCHA en v1, rate-limit
  Redis + anti-enumeración + `BotGuard`). Verifica: diff del archivo. (Hecho en
  el propose; verificar que sigue vigente.)
- [x] 15.2 Gate backend: `alembic upgrade head → downgrade -1 → upgrade head`,
  `pytest -q` (Postgres 15 + Redis 7), `ruff check backend`, `black --check
  backend`, `mypy backend`. Verifica: todo verde, evidencia en la tabla final.
- [x] 15.3 Gate frontend: `tsc --noEmit` (estricto, sin `any`), `eslint`,
  `vitest run`, `npm run e2e`. Verifica: todo verde, evidencia en la tabla final.
- [x] 15.4 `openspec validate c-07-booking-publico --strict`. Verifica: válido.
- [x] 15.5 `CHANGES.md`: notas de cierre de C-07 y contratos diferidos (jobs y
  mensaje de alta → C-09/C-10 vía `book()`; uso, TTL y rotación del token → C-08;
  historial de consentimiento → C-09/C-10; toggle de `clinic.booking_enabled`
  desde la UI de admin → sin change asignado). Verifica: diff de CHANGES.md.

## Workflow follow-up

- `/opsx:archive c-07-booking-publico` y marcar `[x]` en CHANGES.md.

## Evidencia del apply

### Tramo 1 (grupos 0-11, backend) — 2026-11-04

Entorno: Python 3.12 en contenedor (`python:3.12-slim`, venv en volumen Docker), Postgres 15.8 y
Redis 7.4 reales en contenedores; sin mocks de DB. `down_revision` de la migración: `c13_event_slot`
(cabeza única verificada con `alembic heads`).

**Baseline 0.1** (HEAD limpio): backend `713 passed, 1 failed, 1 error` — preexistentes y de
entorno, no se arreglaron: `test_auth_redis_url_usa_la_base_logica_configurada` exige
`localhost:6379` en `REDIS_URL` (aquí el host es `host.docker.internal`) y un error de *setup*
por `TimeoutError` de conexión a Postgres en `test_patient_merge_api` (no reproducible).
Frontend `vitest run`: 19 archivos, `129 passed`.

**Final tramo 1**: `865 passed, 1 failed` (la misma falla de entorno); `ruff check backend`,
`black --check backend` y `mypy backend` (211 archivos) limpios; `alembic upgrade head →
downgrade -1 → upgrade head` limpio sobre la DB compartida; test de drift modelo↔migración verde.

| Tarea | Test | Capa | Red de seguridad | RED | GREEN | Triangulación |
|---|---|---|---|---|---|---|
| 0.1 | suite completa | — | 713 backend / 129 frontend | n/a | n/a | n/a |
| 1.1/1.2 | `tests/models/test_appointment_manage_token_db.py` | DB | 54/54 (`test_appointment_db`, transiciones) | 8 failed (columna inexistente) | 8 passed + 209 en models/migraciones/drift | online sin hash, largo 0/31/33, recepción sin hash, hash repetido, NULL repetidos |
| 2.1/2.2 | `tests/core/test_settings_booking.py` | Unit | 156 (core, common, auth) | falla (settings inexistentes) | verde | defaults, 3 specs × 5 valores inválidos, horizonte ≤ 0, `.env.example` |
| 2.3/2.4 | `tests/common/test_rate_limit_guard.py`, `test_request_meta.py` | Integración (Redis real) | suite de auth 155/155 | error de colección (módulos inexistentes) | verde | dentro/excedido/claves distintas/Redis caído × 2 códigos; IP con y sin `X-Forwarded-For` |
| 3.1/3.2 | `tests/modules/test_public_availability.py` | Unit | — | error de colección | 17 passed | spec 09-12/buffer 10, unión/dedupe, sillones, now, cap, duraciones, salto DST NY, `chairs_on_grid` |
| 3.3/3.4 | `tests/modules/test_booking_public_read_api.py` | API | — | 23 failed | 23 passed | catálogo, 404 idénticos, buffer/bloqueo, cancelar libera, sin PII, 6 rangos inválidos, 5 profesionales no reservables |
| 3.5/3.6 | `tests/modules/test_booking_public_rate_limit.py` (lecturas) | API (Redis real) | — | 5 failed quitando el cupo (mutación) | 5 passed | 429, disponibilidad+catálogo comparten cupo, barrido de slugs, otra IP, Redis caído |
| 4.1-4.6 | `tests/modules/test_booking_public_create_api.py` | API | 209 + C-05 | 54 failed (rutas inexistentes) | 24 passed | 6 validaciones, 5 campos prohibidos, 3 canales + solo email, agenda de recepción, 4 inicios inválidos, pasado, 2 sillones |
| 5.1/5.2 | `tests/modules/test_booking_public_patient_match.py` | API + carrera | — | falla | 9 passed; 20 corridas del concurrente | reutiliza, familia, archivado, otra clínica, no pisa email, opt-in solo sube, solo email, 4 rondas concurrentes |
| 6.1/6.2 | `tests/modules/test_booking_public_token.py` | API | — | falla | 3 passed | URL-safe ≥ 43, hash con `hashlib` independiente, ausente de fila/eventos/logs/listado, tokens distintos |
| 7.1/7.2 | `tests/modules/test_booking_public_audit.py` | API + DB real | — | falla | 3 passed | evento `patient_token` whatsapp/email, falla inyectada revierte turno y paciente |
| 8.1/8.2 | `tests/modules/test_booking_public_concurrency.py` | Carrera (DB real) | — | falla | 6 passed; 20 rondas por corrida | 20 rondas online vs online, 10 recepción vs online, bloqueo→`slot_taken`, sin `conflicts`/sillón |
| 9.1/9.2 | `tests/modules/test_booking_public_rate_limit.py` (reservas) | API (Redis real) | — | falla | 14 passed | 10+1 por IP, 422 gasta cupo, otra IP, cupo por slug, slug inexistente sin clave, aislamiento entre slugs, Redis caído |
| 9.3/9.4 | idem (BotGuard) | API | — | error de colección (`guard` inexistente) | verde | guard noop → 201; override que rechaza → 403 sin escrituras |
| 10.1/10.2 | `tests/modules/test_booking_public_tenancy.py` | API | — | pasa por construcción → mutación: quitar `Patient.clinic_id` rompe 1 test | 3 passed | hueco no afectado por B, profesional de B (disp. y reserva) sin cambios en B, match sin pacientes de B |
| 11.1/11.2 | `tests/test_seed_booking.py` | DB | seed 23/23 | 9 failed (`booking_demo` inexistente) | 12 passed | demo reservable, idempotente, sin flag no queda pública, flag desde entorno |
| 11.3 | `backend/README.md` | docs | — | — | sección «Reserva pública (C-07)» | — |

Notas: fallas esporádicas de conexión (`TimeoutError` de asyncpg vía `host.docker.internal`) en
tests de carrera bajo carga, ajenas a la lógica; quitar el filtro `Professional.clinic_id` no rompe
tests porque el filtro de reglas por clínica ya aísla (defensa en profundidad).

### Tramo 2 (grupos 12-15, frontend + E2E + cierre) — 2026-11-04

Entorno: vitest y Playwright (Chromium) nativos en Windows; API en contenedor `python:3.12-slim`
contra `turnos-test-pg` (DB aparte `turnos_e2e`) y Redis (`REDIS_AUTH_DB=14`), con la clínica sembrada
con `SEED_BOOKING_DEMO=true`; Vite en dev (`API_PROXY_TARGET=http://127.0.0.1:8000`). Sin builds.

**Finales**: backend `864 passed, 2 failed` (la falla de entorno `localhost:6379` del tramo 1 y un
`TimeoutError` de conexión a Postgres en la fixture de un test de carrera, que aislado pasó 22/22 y
en el tramo 1 20/20); `ruff`, `black --check`, `mypy` (211 archivos) limpios; `tsc --noEmit` limpio;
vitest `22 files / 158 passed` (baseline 129); Playwright `5 passed, 2 skipped` (los 2 stubs `smoke`
previos); `openspec validate c-07-booking-publico --strict` válido. El proyecto no tiene `eslint`
(15.3 se cumple con `tsc` estricto + `grep` de `any` sin resultados).

| Tarea | Test | Capa | Red de seguridad | RED | GREEN | Triangulación |
|---|---|---|---|---|---|---|
| 13.1/13.2 | `AgendaPage.test.tsx` (polling) | Componente (fake timers + MSW) | 9/9 de la agenda | 1 failed (visible no repite) | 11/11; agenda 43/43 ×3 | visible a los 30 s (no a los 29) con turno `pending` nuevo; oculta no pide en 65 s |
| 12.1/12.2 | `useBookingFlow.test.ts`, `BookingPage.test.tsx` | Unit + componente | 129 vitest | 11 failed (sin componentes) | 5 + 11 passed | 4 pasos, un profesional saltea, zona de la clínica, volver conserva, casilla WhatsApp, sin contacto/privacidad/opt-in, solo email, ventanas de 14 días, `credentials: omit` |
| 12.3/12.4 | `BookingErrors.test.tsx` | Componente | idem | escrito antes de los componentes (falla de import) | 11 passed | 409 con alternativo (reenvío con mismos datos) y sin alternativos, 422 ×3 campos, 429 «10 minutos», 404, 503, aviso de teléfono, link + copiar + storage vacío |
| 14.1/14.2 | `e2e/booking.spec.ts` | E2E real | 2 specs previos | 3 failed al quitar la ruta `/b/:slug` | 3 passed (5 con los previos) | mobile 360×740 sin scroll y botones ≥ 44 px, agenda ≤ 30 s sin recargar, carrera → 409 + alternativo |
| 15.1-15.5 | KB, gates, `openspec validate`, `CHANGES.md` | docs | — | — | verificados | KB ya marcada resuelta; notas de cierre y contratos diferidos en `CHANGES.md` |

Hallazgo del E2E (invisible en vitest): el `AuthProvider` ejecuta `queryClient.clear()` cuando el visitante
resulta anónimo, lo que dejaba el catálogo en vuelo colgado en «Cargando…». Se resolvió dándole a la reserva
pública su propio `QueryClient` (no comparte caché con el personal). Otros: en Windows `localhost` del proxy
de Vite se cuelga por IPv6 (usar `E2E_API=http://127.0.0.1:8000`).
