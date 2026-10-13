# Proposal — c-01-foundation-setup (C-01 `foundation-setup` · CHANGES.md)

> Nota de nombre: el CLI de OpenSpec exige kebab-case minúsculas; el change
> `c-01-foundation-setup` corresponde a `C-01 foundation-setup` de CHANGES.md
> (GATE 0, governance BAJO, sin dependencias — primero del camino crítico
> C-01→C-02→C-03→C-04→C-05→C-07→C-08→C-10→C-14).

## Why

Sin scaffolding monorepo + infraestructura base (API, DB, Redis, worker,
frontend, migraciones, CI) ningún change posterior (C-02…C-14) puede
implementarse ni verificarse. C-01 existe para dar a todos los agentes una
base idéntica, reproducible y con los contratos duros del proyecto ya
impuestos (Alembic-only, `clinic_id`, env-only secrets, tags pineados +
healthchecks, TS estricto, pytest+httpx verde).

## What Changes

- Estructura `backend/` (Python 3.12+ FastAPI async): `app/main.py` con CORS +
  rate-limit global, paquetes vacíos `routers/`+`services/`+`schemas/` por
  dominio (`auth`, `clinic`, `agenda`, `booking_public`, `waiting_list`,
  `reminders`, `notifications`, `users`, `reports`), `app/models/` (base
  SQLAlchemy 2.x async), `app/core/` (settings pydantic-settings, security
  JWT stub, deps), `app/common/` (exceptions, pagination, dependencies),
  `app/worker/` entrypoint async, `backend/tests/` (pytest + httpx).
- Estructura `frontend/` (React 18 + TS + Vite 5 + Tailwind 3): `src/features/`
  (`agenda`, `booking`, `manage`, `waiting-list`, `reminders`, `admin`,
  `reports`), `src/shared/`, `src/pages/` + routes (públicas `/b/:slug`,
  `/g/:token` vs. autenticadas), `tsconfig` estricto (`strict`, `noAny`).
- Infra datos: Postgres 15 + Redis 7 vía Compose; Alembic inicializado
  (una migración base vacía/versionada, DDL listo para EXCLUDE en C-05);
  `pyproject.toml`/`requirements.txt` (fastapi, sqlalchemy[asyncio], asyncpg,
  alembic, redis, pydantic-settings, pytest, httpx).
- `.env.example` completo: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`,
  `JWT_ACCESS_MINUTES`, `WHATSAPP_TOKEN`, `META_*`, `EMAIL_*`,
  `CLINIC_TZ_DEFAULT`, `BOOKING_RATE_LIMIT`, `MANAGE_TOKEN_TTL_H`,
  `FRONTEND_PUBLIC_URL`, `CORS_ORIGINS` (+ `JWT_REFRESH_DAYS`,
  `REMINDER_WORKER_CONCURRENCY`, `ENV` según `08` §Variables de entorno).
  Nunca se commitea `.env`.
- `Dockerfile` backend (api + worker, un proceso por contenedor, tags
  pineados) + `docker-compose.yml` (`api`, `db`, `redis`, `worker`,
  `frontend`) con healthchecks y `depends_on` con condición
  (`pg_isready`, `redis-cli ping`).
- CI con jobs paralelos backend/frontend (pytest + httpx verde, ruff/black +
  mypy limpios como gate por change; build Vite; stub Playwright para el
  circuito crítico reserva→recordatorio→confirmación→presente).
- Documentación en español + convención conventional commits (sin co-autoría IA).

Fuera de alcance (changes posteriores): modelos/entidades (C-02), auth/RBAC
(C-03), reglas de agenda, EXCLUDE (C-04/C-05), booking/token (C-07/C-08),
motor WhatsApp (C-09/C-10), espera/reportes (C-12/C-13), hardening (C-14).
Envío real WhatsApp NO entra en C-01 (solo claves `.env`).

## Capabilities

### New Capabilities

- `foundation/scaffolding`: contrato estructural e infra del monorepo — layout
  backend/frontend, servicios Compose sanos, config vía env, CI verde,
  disciplina Alembic y pisos de calidad (tests/lint/tipos). Todos los changes
  futuros presuponen esta capability.

### Modified Capabilities

(none — primer change, `openspec list --specs` vacío.)

## Impact

- Código nuevo: `backend/`, `frontend/`, `docker-compose.yml`,
  `Dockerfile(s)`, `.env.example`, CI workflows. Nada existente que romper
  (repo contiene solo docs/KB/CHANGES).
- Sistemas afectados: desarrolladores (entorno `docker compose up`),
  CI (nuevos jobs), futuros changes (dependen de este layout).
- Reglas duras aplicadas al diseño: Alembic-only (NUNCA schema fuera de
  migración), `clinic_id` obligatorio (preparado desde base), secrets solo env,
  tags pineados + healthchecks, TS estricto sin `any`, pytest+httpx verde por
  change, sin borrado físico (base lista para máquina de estados + eventos).

## Preguntas abiertas (NO se deciden unilateralmente en C-01)

1. **Librería del worker Redis** (10_preguntas_abiertas + DD-06): ARQ vs
   Celery vs Dramatiq vs asyncio custom. Recomendación del diseño: **ARQ**
   (async nativo, liviano, justo para tick 60 s + outbox; Celery es pesado
   para < 50 concurrentes) — decisión explícita pendiente del Tech Lead.
2. **Blacklist de refresh-tokens** (C-03 la necesitará): Postgres vs Redis.
   Recomendación: **Redis** (TTL natural + reuse-detection rápida; Postgres
   como respaldo si se exige auditoría) — pendiente Tech Lead.
3. **Gestor de paquetes Python**: pip/venv vs `uv`. Recomendación: **`uv`**
   (lockfile + velocidad, compatible con `pyproject.toml`) con fallback
   pip/venv — pendiente equipo.
4. Heredadas de `10` (Alta, condicionan pero no bloquean C-01): CAPTCHA/
   anti-bot del booking (C-07), titularidad plantillas/número WhatsApp (C-10),
   resguardos Ley 27.706/26.529 desde v1 (consentimiento/retención en C-02).
