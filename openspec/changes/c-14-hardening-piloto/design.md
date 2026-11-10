# Design — C-14 `hardening-piloto`

## Context

El MVP agenda-first está completo (C-01…C-13 archivados). C-14 no agrega dominio: endurece
los bordes, deja medible el piloto y cierra los diferidos con contrato de C-05 (rol
`app_writer`) y C-06 (Playwright de recepción en CI). Restricciones que pesan:

- Reglas duras 2, 6, 7, 9, 10, 11, 12 y 13 de `AGENTS.md`.
- La app ya resuelve la invariante de solapamiento en la base (EXCLUDE) y las carreras
  de reserva/oferta con locks `FOR UPDATE` (C-05, C-07, C-12). C-14 no las re-diseña:
  acota cuánto puede esperar un request y traduce los errores de Postgres a respuestas
  limpias.
- Auth y reserva pública ya son fail-closed ante Redis caído (C-03, C-07): no se toca.

## Goals / Non-Goals

**Goals**: ningún 500 crudo ni traza al cliente; ninguna PII ni token en logs o errores;
headers y hosts endurecidos; la app no puede borrar ni reescribir historia aunque se
equivoque el código; recepción opera un corte de red corto sin perder clics; el piloto
tiene sus métricas y su alarma de costo; el circuito crítico tiene E2E en CI.

**Non-Goals**: offline real, WAF/CDN, APM externo, purga por retención, multi-sede.

## Decisions

### D1 — Middlewares ASGI puros, en este orden

`BaseHTTPMiddleware` copia el cuerpo y rompe `contextvars` entre la app y el middleware;
los nuevos son ASGI puros (`app/core/middleware.py`). Orden efectivo (de afuera hacia
adentro):

1. `RequestContextMiddleware`: toma `X-Request-ID` si cumple `^[A-Za-z0-9._-]{8,64}$`,
   si no genera `uuid4().hex`; lo guarda en un `ContextVar`, lo devuelve en la respuesta y
   escribe **un** log de acceso al terminar (`method`, `route` = plantilla de la ruta
   resuelta, `status`, `duration_ms`, `request_id`). Nunca el path real: `/api/manage/{token}`
   y `/api/waitlist-offer/{token}` llevan secretos. Sin ruta resuelta (404) se loguea
   `route="<unmatched>"`.
2. `SecurityHeadersMiddleware`: agrega `X-Content-Type-Options: nosniff`,
   `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors
   'none'` (la API solo sirve JSON/CSV/ZIP), `Referrer-Policy: strict-origin-when-cross-origin`
   (los bordes con token ya fuerzan `no-referrer`, que no se pisa), `Permissions-Policy`
   mínima, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy:
   same-site` y `Strict-Transport-Security` solo con `ENV=prod` y
   `SECURITY_HSTS_SECONDS>0`. `/docs` y `/redoc` (solo existen fuera de prod) quedan
   fuera de la CSP estricta. Header ya presente en la respuesta → no se pisa.
3. `TrustedHostMiddleware` (Starlette) con `ALLOWED_HOSTS`; `*` solo se admite fuera de prod.
4. `CORSMiddleware` con `allow_headers=["Authorization","Content-Type","Accept","X-Request-ID"]`,
   `expose_headers=["X-Request-ID","Retry-After","Content-Disposition"]`, `max_age=600`.
5. `GlobalRateLimitMiddleware` (D5).

`/health` y `/ready` quedan fuera del log de acceso y del rate-limit (los golpea el
healthcheck cada 30 s).

### D2 — Logging estructurado con redacción obligatoria

`app/core/logging.py` (solo stdlib): `configure_logging(level, fmt)` instala en el root un
handler con `RedactingFilter` + `JsonFormatter` (o texto en dev, `LOG_FORMAT=text`). El filtro
reescribe `record.msg` ya formateado con `record.args` y los `extra` string, enmascarando:

| Patrón | Reemplazo |
|---|---|
| E.164 / teléfonos AR (`+?\d[\d\s-]{7,}\d`) | `+54******67` (conserva 2 últimos) |
| emails | `***@dominio` |
| DNI (`\b\d{7,8}\b`, `\d{2}\.\d{3}\.\d{3}`) | `[dni]` |
| `Bearer <x>` / JWT (`eyJ…`) | `Bearer [redacted]` / `[jwt]` |
| tokens de gestión/oferta (`w1.`/`m1.` + base64url, ≥ 22 chars) | `[token]` |

El traceback del 500 se loguea con `exc_info` pero el **mensaje** de la excepción pasa por
el mismo filtro (asyncpg incluye `Key (phone_e164)=(+54…)` en el detalle de un
`IntegrityError`). Cada registro lleva `request_id` (del `ContextVar`) y, si lo hay,
`clinic_id`. El worker usa la misma configuración.

### D3 — Envolvente de errores y mapeo de Postgres

`register_exception_handlers` suma:

- `Exception` → `500 {"detail":"internal_error","request_id":...}`; log `unhandled_error`
  con tipo y traza redactada.
- `sqlalchemy.exc.DBAPIError` por SQLSTATE (de `exc.orig.sqlstate`, `exc.orig.pgcode` o
  `exc.orig.__cause__.sqlstate`):
  - `40001` serialization_failure, `40P01` deadlock, `55P03` lock_not_available →
    `409 concurrent_update` + `Retry-After: 1`.
  - `57014` query_canceled (statement timeout) → `503 db_timeout` + `Retry-After: 5`.
  - `23xxx` (integridad) no manejado por el servicio → `409 conflict`.
  - Conexión (`08xxx`, `OperationalError` sin SQLSTATE) → `503 db_unavailable`.
  - Resto → 500 como arriba.
  La sesión del request se descarta (rollback por el context manager de `get_db`).
- `RequestValidationError` fuera de los bordes públicos: misma lista de FastAPI pero cada
  error solo con `loc`, `msg`, `type` (sin `input`, `ctx`, `url`). `/api/waitlist-offer/`
  pasa a la lista de prefijos públicos (`invalid_request` + `fields`).
- `StarletteHTTPException` (404/405 de ruteo) → `{"detail": "not_found" |
  "method_not_allowed" | <detail>}`, con los headers privados en las rutas con token.

`409 concurrent_update` y `503 db_*` entran al catálogo del frontend; el cliente los
reintenta (D9).

### D4 — Timeouts por conexión

`create_engine(url, settings)` pasa `connect_args={"server_settings": {"application_name":
"turnos-api|turnos-worker", "statement_timeout": ..., "lock_timeout": ...,
"idle_in_transaction_session_timeout": ...}}`. Defaults: `DB_STATEMENT_TIMEOUT_MS=15000`
(el export completo usa cursores por lote de 1000: cada sentencia es corta),
`DB_LOCK_TIMEOUT_MS=3000`, `DB_IDLE_TX_TIMEOUT_MS=60000`. `0` desactiva. Los locks de C-05
(`FOR UPDATE` profesional→sillón) y C-12 (oferta→entrada) se mantienen en el mismo orden;
un request que no consigue el lock en 3 s recibe `409 concurrent_update` en vez de colgar
el worker de uvicorn. Las migraciones no usan estos timeouts (`MIGRATION_DATABASE_URL` crea
su propio engine en `alembic/env.py`).

### D5 — Rate-limit global en Redis con degradación

El middleware global (C-01) pasa a ventana fija en Redis (`rl:global:ip:<ip>`, mismo
script Lua de `core/rate_limit.py`) usando el cliente de `app.state.redis`. Si Redis falla
cae a la ventana en memoria del proceso por 30 s (`circuit`), con log
`rate_limit_degraded` una vez por apertura. Respuesta `429 {"detail":"rate_limited"}` con
`Retry-After` (antes `"rate limit exceeded"` sin header). Exentos: `/health`, `/ready` y el
webhook de Meta.

Webhook (C-10 decía "rate-limit estricto en webhooks"): Meta no se limita (un 429 provoca
reintentos en ráfaga y puede desactivar la suscripción), pero las **firmas inválidas** sí:
`WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT=20/60s` por IP; al excederse, el webhook responde
`429` sin verificar la firma. Una firma válida nunca consume cupo.

### D6 — Bearer estricto

`_bearer_token`: exactamente `Bearer <token>`, `len(token) ≤ 4096`, charset
`[A-Za-z0-9._-]` y tres segmentos. Si no, `401 token_invalid` con `WWW-Authenticate:
Bearer` (también en `token_expired`/`invalid_session`). La validación de firma, `iss`,
`aud`, `exp`, `type` y la sesión viva en Redis de C-03 no cambian.

Guardia de RBAC: `tests/test_route_protection.py` recorre `app.routes` y exige que toda
ruta `/api/*` dependa de `get_current_principal`, salvo una lista blanca explícita
(login/refresh/logout, `/api/booking/*`, `/api/manage/*`, `/api/waitlist-offer/*`). Una ruta
nueva sin protección rompe el test.

### D7 — Rol `app_writer` y usuario de la app

Migración `c14_hardening_pilot` (un `DO` idempotente; los roles son del cluster):

```sql
CREATE ROLE app_writer NOLOGIN;                 -- si no existe
GRANT USAGE ON SCHEMA public TO app_writer;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_writer;
REVOKE UPDATE ON <append-only> FROM app_writer;  -- appointment_event, agenda_config_event,
                                                -- auth_event, patient_merge, delivery_event,
                                                -- consent, whatsapp_inbound,
                                                -- reminder_manual_resend, waitlist_event
REVOKE INSERT, UPDATE ON alembic_version FROM app_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO app_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_writer;
```

**Ningún `DELETE`** (verificado: la app no borra nada, regla 7; el `DELETE` HTTP de bloqueos
y prioridad es lógico). Los triggers append-only quedan como segunda barrera. El downgrade
revoca en la base actual y hace `DROP ROLE` solo si ninguna otra base lo referencia (si no,
lo deja, con `NOTICE`).

`python -m app.ops.db_roles` (lo corre `migrate` después de `alembic upgrade head`): con
`APP_DB_USER`/`APP_DB_PASSWORD` crea `CREATE ROLE <user> LOGIN PASSWORD … IN ROLE
app_writer` o `ALTER ROLE … PASSWORD …` si ya existe; nunca imprime la clave; el nombre se
valida (`^[a-z_][a-z0-9_]{2,62}$`). `alembic/env.py` usa `MIGRATION_DATABASE_URL` si está y si
no `DATABASE_URL` (compatibilidad con CI y tests).

### D8 — Alerta de costo WhatsApp (SU-07)

Columna `clinic.whatsapp_monthly_alert_micros BIGINT NULL` (`CHECK > 0`, `NOT VALID` →
`VALIDATE`, regla 11). Política `whatsapp_monthly_alert_usd` (string decimal, `0` = sin
alerta; hasta 6 decimales; ≤ 100 000) en `GET/PATCH /api/clinic/policies`, auditada como el
resto en `agenda_config_event`.

`GET /api/reports/whatsapp/budget` (admin): mes local de la clínica en curso, suma de
`payload.cost_micros` de los `delivery_event` `sent` del canal WhatsApp (misma fuente que el
reporte de C-10, regla 8), umbral, porcentaje y `status ∈ {disabled, ok, warning (≥ 80 %),
exceeded}`. El `StaffLayout` del admin muestra un banner en `warning`/`exceeded`. Sin corte
de envíos.

### D9 — Métricas del piloto

`GET /api/reports/pilot?from&to[&baseline_no_show_pct]` (admin, JSON/CSV). Todo sobre
eventos salvo la integridad:

| Métrica | Cálculo | Meta |
|---|---|---|
| `overlaps` | pares de turnos vigentes no sobreturno del rango que se pisan por profesional o por sillón (tabla `appointment`, `occupied_until`) | 0 |
| `no_show_rate` | `totals.no_show_rate` del reporte de ausentismo de C-13; `delta_vs_baseline_pct` si viene `baseline_no_show_pct` | −20 % |
| `confirmation_before_24h_rate` | D5 de la propuesta, sobre `appointment_event` | ≥ 60 % |
| `waitlist_recovery_rate` | ofertas `accepted` (`waitlist_event`) / cancelaciones de turnos del rango hechas antes del inicio | ≥ 10 % |
| `online_share` | eventos `created` con `payload.origin='online'` / todos los `created` (incluye sobreturnos) del rango por `slot_starts_at` | ≥ 30 % |

Cada métrica trae `value`, `target`, `met` (`null` si no hay base suficiente: denominador 0)
y el numerador/denominador. Sin datos personales.

### D10 — Exportación por paciente

`GET /api/exports/patients/{patient_id}` (admin): JSON con `patient`, `consents`,
`appointments`, `appointment_events` (de esos turnos), `waiting_list_entries` y
`waitlist_offers`, con las mismas columnas explícitas que la exportación completa de C-13
(regla 8). Paciente de otra clínica → `404`. Queda en `auth_event` (`data_exported`,
`payload={"scope":"patient","patient_id":…,"counts":…}`). `Cache-Control: no-store`.

### D10b — Retención y consentimiento

No se purga nada en v1. `docs/piloto/privacidad-y-retencion.md` documenta: qué datos se
guardan, base legal propuesta, consentimiento por canal (C-09, append-only), exportación
completa y por paciente, y la retención propuesta para validar con el asesor legal. La
pregunta de `10` queda abierta con este default.

### D11 — Frontend: resiliencia

- `shared/api/retry.ts`: `shouldRetry(n, error)` → sí para `network_error`, 5xx, `429`,
  `409 concurrent_update`, hasta 3; nunca otros 4xx. `retryDelay(n, error)` =
  `Retry-After` si vino, si no `min(1000·2ⁿ, 15000)` + jitter. Lo usan queries y la cola.
- `shared/network/status.ts`: store (`useSyncExternalStore`) con `online` (eventos del
  navegador) y `lastNetworkErrorAt` (lo marca el cliente API en cada `network_error`,
  lo limpia el próximo OK). `NetworkBanner` en `StaffLayout` y en las páginas públicas:
  "Sin conexión. Lo que ves puede estar desactualizado (último dato: HH:MM)". Al volver
  `online`, `queryClient.refetchQueries({type:"active"})`.
- `ErrorBoundary` envuelve `<App/>`: "Algo salió mal" + "Recargar", sin stack.
- `Skeleton`/`SkeletonRows` con `role="status"` y texto accesible (los tests existentes
  que buscan "Cargando agenda…" siguen pasando: el texto queda como `sr-only`).
- `shared/forms/validators.ts`: `validatePhoneAR`, `validateEmail`, `validateFreeText`
  (espejo de `app/common/free_text.py`: sin teléfonos, emails ni DNI, ≤ 200),
  `validateRequired`. Se usan antes de enviar; el backend sigue siendo la autoridad.
- `shared/offline/retryQueue.ts` (D3 de la propuesta): store en memoria con
  `enqueue({id, label, run})`, reintento con `retryDelay` al volver la red o cada 15 s,
  descarte a los 5 intentos o 30 min, y resultado visible en `RetryQueueIndicator`
  ("2 cambios pendientes de enviar"). `AppointmentDetail` encola `confirmed`, `present`,
  `absent` y `no_show` cuando la transición falla por `network_error`; un `409
  invalid_transition` al reintentar se toma como "ya aplicado" (otra persona lo hizo).
- `/agenda/imprimir?dia=YYYY-MM-DD`: lista por sillón (hora, paciente, profesional,
  estado, teléfono para recepción) con CSS `@media print`; botón "Imprimir agenda del día"
  en la agenda (admin/recepción).

### D12 — E2E y CI

`e2e/critical-circuit.spec.ts`: (1) el paciente reserva por `/b/:slug` en un celular de
360 px un horario de **hoy** (≥ 90 min adelante; si no queda franja en el día local, el test
se salta con el motivo); (2) el worker con `REMINDER_*_PROVIDER=fake` envía el paso
`created` y el timeline del turno lo muestra `sent` (poll por API, 60 s máx.); (3) el
paciente confirma desde su link `/g/:token`; (4) recepción ve el turno `Confirmado` en la
agenda y registra "Presente". Cada paso verifica el estado por API y por UI.

`.github/workflows/ci-e2e.yml`: servicios Postgres 15.8 + Redis 7.4, `alembic upgrade head`,
`python -m app.ops.db_roles`, seed demo, API (uvicorn) y worker en background **con el
usuario `app_writer`** (así el E2E también prueba los permisos), espera a `/ready`,
`npx playwright install --with-deps chromium`, `npx playwright test`, artefacto con trazas
si falla. Se borra el job stub `playwright-smoke` de `ci-frontend.yml` (Vitest pasa al job
principal).

## Risks / Trade-offs

- **CSP de nginx**: la SPA usa Tailwind compilado y Vite no inyecta scripts inline en
  build, así que `script-src 'self'` y `style-src 'self'` alcanzan. La grilla de agenda
  posiciona turnos con `style={{…}}`, y una CSP sin `'unsafe-inline'` bloquea los atributos
  `style`: se agrega `style-src-attr 'unsafe-inline'` (solo atributos, nunca `<style>` ni
  scripts). Verificar en el navegador del piloto que la consola no reporte violaciones.
- **`lock_timeout` de 3 s**: un export muy grande o una migración en caliente podría
  provocar `409` en recepción. Las migraciones van con su URL y fuera de horario.
- **Fail-open del rate-limit global**: un Redis caído deja solo el tope por proceso. Se
  acepta: los cupos que protegen datos (login, reserva, gestión) siguen fail-closed.
- **Cola en memoria**: si recepción cierra la pestaña sin red, se pierden los cambios
  encolados; el indicador lo avisa ("no cierres esta pestaña").
- **Grants y bases temporales de test**: el rol es del cluster; cada base de test agrega
  privilegios. El downgrade no puede dropear el rol mientras otra base lo referencie y lo
  deja (documentado).

## Migration Plan

1. `alembic upgrade head` con el usuario dueño (`MIGRATION_DATABASE_URL`).
2. `python -m app.ops.db_roles` crea/actualiza `turnos_app`.
3. Cambiar `DATABASE_URL` de `api`/`worker` a `turnos_app` y reiniciar.
4. Rollback: volver `DATABASE_URL` al dueño; `alembic downgrade c12_waiting_list` quita la
   columna y los privilegios.

## Open Questions

- Aprobación de los 8 defaults de la propuesta (usuario/Tech Lead).
- Retención y base legal: asesor legal + PO (`10`).
- Titularidad de plantillas/número de WhatsApp (sigue abierta en `10`; no bloquea C-14).
