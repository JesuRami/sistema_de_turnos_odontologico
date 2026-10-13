# Spec Delta

## Purpose

Establece el contrato estructural e infraestructura base del monorepo para que todos los changes del MVP agenda-first partan de una base reproducible, sana y con calidad verificable.

## ADDED Requirements

### Requirement: Estructura monorepo por dominio

El sistema SHALL proveer la estructura `backend/` (FastAPI async con
`routers/`+`services/`+`schemas/` por dominio) y `frontend/` (React+TS+Vite)
según `08_arquitectura_propuesta.md` §Estructura de directorios.

#### Scenario: Layout verificable tras scaffolding

- **WHEN** se lista el árbol del repo tras aplicar C-01
- **THEN** existen `backend/app/main.py`, `backend/app/core/`,
  `backend/app/common/`, `backend/app/modules/{auth,clinic,agenda,booking_public,waiting_list,reminders,notifications,users,reports}/`,
  `backend/app/models/`, `backend/app/worker/`, `backend/alembic/`,
  `backend/tests/`, `frontend/src/{features,shared,pages}/`

#### Scenario: Dominios futuros tienen home sin refactors

- **WHEN** C-02 necesita el modelo `Clinic`
- **THEN** existe `backend/app/models/` y `backend/app/modules/clinic/` donde
  ubicarlo sin crear directorios nuevos ni mover código

### Requirement: API arranca con salud observable

La API SHALL exponer `GET /health` que responde 200 con estado de la app y
`GET /ready` que responde 200 solo si hay conectividad a Postgres y Redis.

#### Scenario: Health en arranque local

- **WHEN** la API corre con DB y Redis sanos y se pide `GET /health`
- **THEN** responde 200 con cuerpo `{"status":"ok"}` en < 1 s

#### Scenario: Readiness refleja dependencias

- **WHEN** Postgres o Redis están caídos y se pide `GET /ready`
- **THEN** responde 503 identificando la dependencia no disponible

### Requirement: Compose levanta el sistema completo

`docker compose up` SHALL levantar `api`, `db` (Postgres 15 pineado),
`redis` (Redis 7 pineado), `worker` y `frontend`, cada uno con healthcheck y
`depends_on` con condición hacia sus dependencias.

#### Scenario: Stack verde desde cero

- **WHEN** se ejecuta `docker compose up -d --build` en una máquina limpia
- **THEN** en < 5 min todos los servicios están `healthy` y `GET /health`
  vía `api` responde 200

#### Scenario: Orden de arranque respetado

- **WHEN** `api` o `worker` arrancan con `db` aún no listo
- **THEN** esperan (no crashean en loop) hasta `db` healthy (`pg_isready`) y
  `redis` responde `redis-cli ping`

### Requirement: Configuración solo vía entorno

La app SHALL leer toda configuración desde variables de entorno validadas
con pydantic-settings y fallar en arranque ante una requerida ausente; el
repo SHALL incluir `.env.example` completo y NUNCA un `.env` commiteado.

#### Scenario: Ejemplo de entorno completo

- **WHEN** se inspecciona `.env.example`
- **THEN** contiene `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`,
  `JWT_ACCESS_MINUTES`, `WHATSAPP_TOKEN`, `META_*`, `EMAIL_*`,
  `CLINIC_TZ_DEFAULT`, `BOOKING_RATE_LIMIT`, `MANAGE_TOKEN_TTL_H`,
  `FRONTEND_PUBLIC_URL`, `CORS_ORIGINS` con valores de ejemplo no secretos

#### Scenario: Falla rápida sin secreto

- **WHEN** falta `JWT_SECRET` o `DATABASE_URL` al arrancar la API
- **THEN** el proceso aborta con mensaje que nombra la variable ausente y
  NUNCA arranca con un default inseguro

### Requirement: Migraciones versionadas desde el día 1

El esquema SHALL evolucionar solo vía Alembic con una migración por change;
la base de C-01 SHALL aplicar limpiamente (`upgrade head`) sobre una DB
vacía y soportar `downgrade -1` sin error.

#### Scenario: Migración base reproducible

- **WHEN** se ejecuta `alembic upgrade head` contra Postgres 15 vacío
- **THEN** termina con éxito y `alembic current` muestra la revisión base

### Requirement: Bordes API con validación estricta y errores uniformes

Los routers SHALL validar request/response con Pydantic v2 (`extra='forbid'`)
y los errores SHALL usar una envolvente uniforme con CORS restrictivo y
rate-limit global activos desde `main.py`.

#### Scenario: Campo extra rechazado

- **WHEN** un cliente envía un campo no declarado a cualquier endpoint
  con schema (p. ej. `GET /health` no aplica; endpoints con body sí)
- **THEN** recibe 422 con envolvente `{"detail": ...}` y sin traza interna

### Requirement: Worker async arranca y queda ocioso sano

El servicio `worker` SHALL arrancar con la misma imagen que `api`
(entrypoint distinto), conectar a Redis y Postgres, y permanecer sano sin
jobs pendientes (el scheduler real llega en C-09).

#### Scenario: Worker sano sin trabajo

- **WHEN** el stack está levantado y no hay jobs encolados
- **THEN** el healthcheck del `worker` es `healthy` y sus logs muestran
  conexión a Redis y Postgres sin errores

### Requirement: CI paralelo con gates de calidad

El CI SHALL correr jobs paralelos backend (pytest+httpx, ruff/black, mypy) y
frontend (typecheck `tsc --noEmit`, build Vite) más un stub Playwright del
circuito crítico; un gate rojo SHALL bloquear el merge.

#### Scenario: Cambio roto no mergea

- **WHEN** un PR rompe un test pytest o el typecheck estricto del frontend
- **THEN** el job correspondiente falla y el PR no es mergeable

### Requirement: Frontend estricto compila y sirve

El frontend SHALL compilar con TypeScript estricto (sin `any` implícito ni
explícito) y servirse como estático tras `vite build` desde el servicio
`frontend`.

#### Scenario: Build limpio

- **WHEN** se ejecuta el build de producción del frontend
- **THEN** `tsc --noEmit` pasa sin errores y `vite build` emite el bundle
  que el servicio `frontend` sirve con 200 en `/`
