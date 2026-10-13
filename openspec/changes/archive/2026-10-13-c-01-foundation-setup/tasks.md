# Tasks — c-01-foundation-setup

## 1. Backend scaffolding (FastAPI async + dominios)

- [x] 1.1 Crear layout `backend/app/` (`main.py` con CORS + rate-limit global +
  `GET /health`/`GET /ready`, `core/` settings/security/deps, `common/`
  exceptions/pagination/dependencies, `modules/<9 dominios>/{router,service,schemas}.py`
  stub con `extra='forbid'`, `models/base.py`, `worker/entrypoint.py`) y verificar
  con `python -c "import app.main"` + `pytest backend/tests/test_health.py` verde
  (test: `/health` 200 `{"status":"ok"}` vía httpx).
- [x] 1.2 Añadir `pyproject.toml` (+ `requirements.txt` generado o `uv.lock` si se
  elige `uv`; deps: fastapi, sqlalchemy[asyncio], asyncpg, alembic, redis,
  pydantic-settings, pytest, httpx) y verificar con install limpio + `ruff check`
  + `black --check` + `mypy` limpios.
- [x] 1.3 Añadir test de contrato `.env.example` (claves requeridas de `Settings`
  ⊆ `.env.example`, sin secretos reales) y verificar con `pytest` verde tras
  borrar cualquier clave del ejemplo.

## 2. Base de datos y migraciones (Alembic-only)

- [x] 2.1 Inicializar Alembic (`alembic.ini` + `backend/alembic/`, revisión base
  vacía, `AsyncSession`/`DateTime(timezone=True)` en base de modelos) y verificar
  con `alembic upgrade head` + `downgrade -1` + `upgrade head` limpios contra
  Postgres 15 real (contenedor/servicio CI, sin mocks).

## 3. Worker async (entrypoint ocioso sano)

- [x] 3.1 Crear entrypoint worker (misma imagen, comando distinto; conecta Redis +
  Postgres, logea y queda idle; default ARQ recomendado, swappable a
  Celery/Dramatiq — registrar elección del Tech Lead) y verificar con arranque
  del worker en Compose sano sin jobs (healthcheck `healthy`, sin errores en logs).

## 4. Frontend scaffolding (React 18 + TS estricto + Vite + Tailwind 3)

- [x] 4.1 Crear app Vite (`src/features/{agenda,booking,manage,waiting-list,reminders,admin,reports}/`,
  `src/shared/`, `src/pages/` + routes `/b/:slug` y `/g/:token` públicas vs.
  autenticadas, stub "Agenda" + wiring API client) con `tsconfig` estricto
  (`strict`, `noImplicitAny`, `noUnusedLocals`, PascalCase) y verificar con
  `tsc --noEmit` limpio + `vite build` que emite bundle servido con 200 en `/`.
- [x] 4.2 Configurar Tailwind 3 (tokens mínimos, sin kit genérico) y verificar con
  build que incluye las clases usadas y el smoke visual del stub.

## 5. Compose + env + Docker (tags pineados + healthchecks)

- [x] 5.1 Escribir `.env.example` completo (`DATABASE_URL`, `REDIS_URL`,
  `JWT_SECRET`, `JWT_ACCESS_MINUTES`, `WHATSAPP_TOKEN`, `META_*`, `EMAIL_*`,
  `CLINIC_TZ_DEFAULT`, `BOOKING_RATE_LIMIT`, `MANAGE_TOKEN_TTL_H`,
  `FRONTEND_PUBLIC_URL`, `CORS_ORIGINS`, + `JWT_REFRESH_DAYS`,
  `REMINDER_WORKER_CONCURRENCY`, `ENV`) con valores ejemplo no secretos y
  verificar con el test de 1.3 + `git check-ignore .env` (nunca commiteado).
- [x] 5.2 Escribir `Dockerfile` backend (api + worker, un proceso por contenedor,
  tag base Python 3.12 pineado) + `compose.yaml` / `compose.override.yaml` (dev)
  / `compose.prod.yaml` (servicios `api`, `db` postgres:15.x, `redis` 7.x,
  `worker`, `frontend`; healthchecks `pg_isready`/`redis-cli ping`/`/ready`;
  `depends_on` con condición; redes `backend` internal + `frontend`) y verificar
  con `docker compose config` válido + `up -d --build` con los 5 servicios
  `healthy` en < 5 min + `GET /health` 200.

## 6. CI paralelo + stub Playwright

- [x] 6.1 Añadir workflows CI (job backend: pytest+httpx contra servicios
  Postgres/Redis, ruff/black, mypy; job frontend: `tsc --noEmit` + `vite build`;
  stub Playwright del circuito reserva→recordatorio→confirmación→presente
  permitido-fallar hasta C-14) y verificar con pipeline verde en un PR de prueba
  y gate rojo ante un test roto intencional (revertido tras la prueba).

## 7. Verificación integral de foundation

- [x] 7.1 Ejecutar verificación E2E del scaffolding (`compose up` limpio →
  `alembic upgrade head` → `/health` 200 → `/ready` 200 → pytest verde →
  frontend 200) y registrar evidencia (logs + `openspec validate --strict`)
  antes de pedir `/opsx:apply` readiness.
