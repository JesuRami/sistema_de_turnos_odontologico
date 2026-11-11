# Proposal — C-14 `hardening-piloto`

## Why

C-01…C-13 dejaron el MVP agenda-first funcional (agenda multi-sillón, reserva online,
gestión por token, recordatorios WhatsApp con timeline y lista de espera). Antes de
poner el sistema delante de 1-2 clínicas amigas (IN-02: nada de cadenas multi-sede)
faltan los resguardos que no son funcionalidad pero sin los cuales un piloto real es
riesgoso:

- La API no manda headers de seguridad, acepta cualquier `Host`, el CORS deja pasar
  cualquier header y el rate-limit global vive en memoria de cada proceso.
- Una excepción no prevista devuelve el 500 crudo de Starlette; el 422 de las rutas
  del personal ecoa el `input` (puede llevar nombre, teléfono o DNI: regla 13); los
  errores de concurrencia de Postgres (serialización, deadlock, lock) salen como 500.
- No hay logging estructurado ni correlación por request, y nada impide que un
  `logger.info` futuro escriba un teléfono o un token.
- La app corre con el usuario dueño del schema: el append-only de los eventos solo lo
  sostienen los triggers (diferido de C-05: rol `app_writer`).
- Ante un corte de red recepción se queda sin agenda (SU-06) y un clic de "Presente"
  se pierde; las pantallas críticas muestran "Cargando…" en texto plano y no hay
  manejo global de errores de red ni límite de errores de render.
- El circuito crítico reserva → recordatorio → confirmación → presente no tiene E2E y
  el job de Playwright en CI está `continue-on-error`.
- No hay forma de medir las métricas de éxito del piloto (`01` §Métricas) ni de avisar
  cuando el costo de WhatsApp del mes se dispara (SU-07).

## What Changes

### Backend (FastAPI + PostgreSQL)

- **Borde HTTP endurecido**: middleware ASGI de headers seguros (`nosniff`,
  `frame-ancestors 'none'`, `Referrer-Policy`, `Permissions-Policy`, COOP, HSTS en
  prod), `TrustedHost` con `ALLOWED_HOSTS`, CORS con lista cerrada de headers y
  métodos, y validación de arranque en prod (sin `*`, solo `https://`).
- **Request-ID + logs estructurados sin PII**: cada request lleva `X-Request-ID`
  (propagado o generado); los logs salen en JSON con `request_id` y pasan por un
  filtro que enmascara teléfonos, emails, DNI, tokens de gestión/oferta y bearer. El
  log de acceso usa la **plantilla de la ruta** (`/api/manage/{token}`), nunca el path
  real (que lleva el token).
- **Manejo global de errores**: 500 uniforme `{"detail":"internal_error","request_id"}`
  sin traza; errores de concurrencia de Postgres (`40001`, `40P01`, `55P03`) →
  `409 concurrent_update` con `Retry-After`; `57014` (statement timeout) →
  `503 db_timeout`; `IntegrityError` no manejado → `409 conflict`; el 422 del personal
  deja de ecoar `input`/`ctx`; `/api/waitlist-offer/` se suma a los bordes públicos.
- **Concurrencia acotada**: `lock_timeout`, `statement_timeout` e
  `idle_in_transaction_session_timeout` por conexión (configurables); una carrera
  sobre el mismo turno u oferta nunca deja a un request colgado.
- **Rate-limit global en Redis** compartido entre procesos (fallback en memoria si
  Redis cae; el de auth sigue fail-closed) con `Retry-After`, y cupo por IP de firmas
  inválidas en el webhook de Meta.
- **Bearer estricto**: tope de largo, charset JWT y `WWW-Authenticate` en el 401.
- **Rol DB `app_writer`** (migración `c14_hardening_pilot`): `SELECT, INSERT, UPDATE`
  en tablas operativas, `SELECT, INSERT` en las append-only, **sin `DELETE` en
  ninguna** (regla 7) y `DEFAULT PRIVILEGES` para tablas futuras;
  `MIGRATION_DATABASE_URL` separado; comando `python -m app.ops.db_roles` que crea o
  actualiza el usuario de login desde el entorno.
- **Alerta de costo WhatsApp** (SU-07): política `whatsapp_monthly_alert_usd` por
  clínica y `GET /api/reports/whatsapp/budget` (mes en curso vs. umbral); sin corte
  automático.
- **Métricas del piloto**: `GET /api/reports/pilot` (admin, CSV) con las 5 métricas de
  `01` calculadas sobre eventos + auditoría de integridad de solapamientos (debe dar 0).
- **Portabilidad por paciente** (resguardo mínimo Ley 25.326/26.529, pendiente de
  asesor legal): `GET /api/exports/patients/{id}` (admin), JSON con sus datos
  operativos, turnos, eventos, consentimientos y lista de espera; auditado.

### Frontend (React + Vite)

- **Red y errores globales**: política de reintentos (solo red/5xx/409 de
  concurrencia, backoff exponencial), banner "sin conexión / reconectando",
  `ErrorBoundary` de la app, `request_id` visible en el error genérico.
- **Estados de carga**: componente `Skeleton` en agenda, cola de espera, ofertas y
  timeline de recordatorios.
- **Validaciones de formulario** compartidas (teléfono, email, texto libre sin
  datos personales) en el alta de turno, la anotación en la lista de espera y el
  contacto de la reserva pública, espejo de las reglas del backend.
- **SU-06**: agenda del día imprimible (`/agenda/imprimir`), datos visibles aunque la
  red caiga (con hora del último dato) y **cola de reintentos** en memoria para
  confirmación y asistencia registradas sin red.
- **Integración paciente ↔ recepción**: aviso de datos desactualizados, refresco al
  reconectar, distintivo de origen en el detalle del turno y banner de presupuesto de
  WhatsApp para admin; pestaña "Piloto" en reportes; umbral en Políticas.

### Pruebas y CI

- pytest para cada borde nuevo (headers, request-id, redacción, errores, rate-limit,
  rol DB, migración, métricas, alerta, export, rutas protegidas) contra Postgres 15 +
  Redis 7 reales (regla 9).
- Vitest para reintentos, banner, `ErrorBoundary`, validadores, cola e impresión.
- Playwright: `critical-circuit.spec.ts` (reserva → recordatorio → confirmación →
  presente) y nuevo job `e2e` en CI que levanta el stack y corre **toda** la suite
  (incluido el circuito de recepción de C-06 y el de lista de espera de C-12), sin
  `continue-on-error`.

### Operación y documentación

- `docs/piloto/`: checklist del piloto (6 plantillas Meta + 2 variantes, métricas),
  runbook de backups cifrados con PITR (pgBackRest) y política de privacidad y
  retención v1; `ops/backup/` con la configuración de ejemplo.
- `nginx.conf` con headers seguros y CSP para la SPA; compose con usuario de app.

## Capabilities

### New Capabilities

- `platform/http-hardening`: headers, hosts, CORS, request-id, rate-limit global.
- `platform/error-handling`: envolvente uniforme de errores, mapeo de errores de DB,
  timeouts, logs sin PII.
- `platform/db-roles`: rol `app_writer` y separación migración/app.
- `reports/pilot-metrics`: métricas de éxito del piloto e integridad de agenda.
- `reports/whatsapp-budget`: umbral mensual y estado del mes en curso.
- `core/patient-export`: exportación por paciente auditada.
- `web/resilience`: red, errores, carga, cola de reintentos y agenda imprimible.

### Modified Capabilities

- `core/reports`, `web/reports-admin` (pestaña Piloto), `agenda/config`
  (política nueva), `web/agenda-board` (impresión, datos viejos, cola),
  `identity/staff-auth` (bearer estricto), `foundation/scaffolding` (CI e2e).

## Impact

- **Backend**: `app/core/{http,logging,middleware}.py` (nuevos), `app/main.py`,
  `app/common/exceptions.py`, `app/core/{settings,database,deps}.py`,
  `alembic/env.py`, `app/ops/db_roles.py`, `app/modules/reports/{pilot,budget,
  patient_export}.py`, router y schemas de reportes y de clínica,
  `notifications/router.py` (cupo de firmas inválidas), `app/models/clinic.py`.
- **Datos**: migración `c14_hardening_pilot` (`down_revision="c12_waiting_list"`).
- **API nueva**: `GET /api/reports/pilot`, `GET /api/reports/whatsapp/budget`,
  `GET /api/exports/patients/{patient_id}`; `PATCH /api/clinic/policies` admite
  `whatsapp_monthly_alert_usd`.
- **Frontend**: `shared/api/retry.ts`, `shared/network/*`, `shared/ui/{Skeleton,
  ErrorBoundary}.tsx`, `shared/forms/validators.ts`, `shared/offline/retryQueue.ts`,
  `features/agenda/PrintableDay.tsx`, `features/reports/PilotPanel.tsx`.
- **Config**: `ALLOWED_HOSTS`, `SECURITY_HSTS_SECONDS`, `LOG_LEVEL`, `LOG_FORMAT`,
  `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS`, `DB_IDLE_TX_TIMEOUT_MS`,
  `MIGRATION_DATABASE_URL`, `APP_DB_USER`, `APP_DB_PASSWORD`,
  `WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT`; `BOOKING_RATE_LIMIT` recalibrado.
- **CI**: `.github/workflows/ci-e2e.yml` (nuevo); `ci-frontend.yml` deja el stub.

## Fuera de alcance

- Offline real (service worker, IndexedDB): fase posterior (SU-06).
- Purga o anonimización automática por retención: requiere al asesor legal.
- Corte automático de envíos por presupuesto (explícito en CHANGES: sin corte en v1).
- Alta de las plantillas en Meta y contratación del número (decisión comercial
  abierta en `10`).
- WAF/CDN, secret manager y monitoreo externo (APM): se documentan como opcionales.

## Open Decisions (defaults propuestos)

> Governance ALTO. El usuario pidió avanzar de forma continua: se implementan estos
> defaults y quedan **pendientes de aprobación** del usuario/Tech Lead antes de
> archivar.

1. **Rate-limit global** — *Default*: `BOOKING_RATE_LIMIT=300/minute` por IP. Las
   recepciones suelen salir por una sola IP pública (NAT) y la agenda refresca cada
   60 s varias consultas por pestaña; 30/min cortaba a una clínica de 3 puestos.
   Los cupos estrictos de reserva/gestión/oferta (Redis) no cambian.
2. **Redis caído en el rate-limit global** — *Default*: fail-open a memoria por
   proceso (con log `rate_limit_degraded`). Es protección de disponibilidad, no de
   seguridad; auth y reserva siguen fail-closed como en C-03/C-07.
3. **Cola de reintentos del frontend** — *Default*: solo confirmación y asistencia
   (presente/ausente/no vino), en memoria (nada con datos del paciente queda en
   `localStorage`), máximo 5 intentos y 30 min. Alta, reprogramación y cancelación
   **no** se encolan: necesitan el estado vivo de la agenda y disparan efectos
   (lista de espera, recordatorios).
4. **Agenda "cacheada"** — *Default*: la última agenda cargada sigue visible sin red
   con la hora del dato; no se persiste en disco (regla 13). La copia en papel sale de
   `/agenda/imprimir`.
5. **Métrica de confirmación** — *Default*: sobre turnos `online` y `waitlist`
   (nacen `pending`), excluyendo los creados con menos de 24 h de anticipación; cuenta
   el primer evento `confirmed` con `created_at ≤ starts_at − 24 h`.
6. **Huecos recuperados** — *Default*: ofertas aceptadas / cancelaciones de turnos
   futuros del rango (por `waitlist_event` y `appointment_event`).
7. **Retención** — *Default*: sin purga en v1; se documenta la política propuesta
   (10 años para datos asociados a atención, Ley 26.529 art. 18) y queda abierta en `10`
   para el asesor legal. La portabilidad se cubre con la exportación completa (C-13) y
   la nueva exportación por paciente.
8. **Usuario de la app** — *Default*: `APP_DB_USER=turnos_app`, también en dev (así
   dev falla igual que prod si algo intenta un `DELETE`). El servicio `migrate` lo
   crea o le actualiza la clave desde el entorno después de migrar; en dev la clave
   tiene un default de ejemplo y en prod `compose.prod.yaml` la exige.

### Resolución (2026-11-11)

El usuario aprobó las 8 Open Decisions con sus defaults, sin cambios. La 7 (retención) sigue
pendiente de confirmación del asesor legal.
