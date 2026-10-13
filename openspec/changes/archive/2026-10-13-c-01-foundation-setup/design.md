# Design — c-01-foundation-setup

## Context

Ver `proposal.md` (Why). Estado actual: repo con solo docs (`knowledge-base/`,
`CHANGES.md`, `AGENTS.md`), `openspec/` raíz existente, sin código. Restricciones:
DD-01 (stack fijo), DD-06 (Redis + worker async, estado en Postgres), DD-07 (1 DB
por clínica, `clinic_id` obligatorio siempre), 12 reglas duras de `AGENTS.md`, y
compact rules del registry (fastapi, sqlalchemy-alembic, postgres, compose,
react, tdd). Fase 1 = single cloud deploy por tenant.

## Goals / Non-Goals

**Goals:**

- Layout backend/frontend que los changes C-02…C-14 usen sin reestructurar.
- `docker compose up` → stack sano y observable (health/readiness por servicio).
- Config 12-factor vía env con falla rápida; `.env.example` como contrato.
- Alembic operativo desde el día 1 (una migración por change, DDL listo).
- CI paralelo con gates que impongan TDD + lint + tipos por change.
- Decisiones abiertas registradas con recomendación, sin bloquear el scaffolding.

**Non-Goals:**

- Lógica de dominio (modelos, auth, agenda, booking, reminders): stubs vacíos.
- Envío WhatsApp/email real, plantillas, número remitente (C-09/C-10).
- Endurecimiento (headers, CAPTCHA, backups, E2E completo): C-14.
- Multi-tenant real/RLS, on-premise, portal paciente, circuito clínico-fiscal.

## Decisions

1. **Layout backend `app/modules/<dominio>/{router,service,schemas}` + `app/models/` plano.**
   Por qué: refleja `08` §Directorios y la frontera monolito-modular (extraer
   `reminders`→worker sin reescribir). Alternativas: `app/routers|services|schemas`
   planos por capa (descartado: cruza dominios, dificulta extracción) y los 9
   dominios de CHANGES conviven con los 8 módulos de `08` — se adoptan los 9 de
   CHANGES (`booking_public`, `waiting_list` separados) por ser el índice operativo.
   Modelos en `app/models/` compartido (api+worker usan los mismos).
2. **Worker: misma imagen que `api`, entrypoint distinto, librería ARQ (recomendada).**
   Por qué: un proceso por contenedor (regla dura 12), async nativo, liviano para
   tick 60 s + outbox; Celery/Dramatiq son pesados para < 50 concurrentes; asyncio
   custom reinventa reintentos/backoff. En C-01 solo entrypoint + conexión sana
   (idle); el scheduler llega en C-09. Decisión final pendiente del Tech Lead
   (pregunta abierta 1).
3. **Config con pydantic-settings + falla rápida.**
   Por qué: valida tipos en arranque (`DATABASE_URL`, `JWT_SECRET` sin defaults
   inseguros), `.env.example` completo como contrato versionado. Alternativa:
   `os.getenv` disperso (descartado: errores tardíos, sin tipos).
4. **Alembic con revisión base vacía + convención una-migración-por-change.**
   Por qué: impone la regla dura 3 desde el inicio; DDL para EXCLUDE en C-05 sin
   deuda. `upgrade head` / `downgrade -1` verificados en CI contra Postgres real
   (regla 9: sin mocks de DB para invariantes — el hábito empieza aquí).
5. **Compose con tags pineados, healthchecks y redes segregadas.**
   `db: postgres:15.x`, `redis: 7.x`; `api`/`worker` esperan `db` healthy +
   `redis` started; red `backend` interna (`internal:true`) para db/redis y red
   `frontend` para api↔frontend. Base `compose.yaml` + `compose.override.yaml`
   (dev, hot-reload) + `compose.prod.yaml` (límites, `restart: always`, logs).
   Alternativa: un solo archivo (descartado: mezcla dev/prod).
6. **`uv` como gestor recomendado (fallback pip/venv).**
   Por qué: lockfile + velocidad, compatible `pyproject.toml`; pip/venv queda como
   fallback documentado. Pendiente del equipo (pregunta abierta 3).
7. **Blacklist refresh-tokens en Redis (recomendada, se materializa en C-03).**
   Por qué: TTL natural + reuse-detection rápida; Postgres solo si se exige
   auditoría persistente. En C-01 solo se deja el setting y el cliente Redis
   compartido. Pendiente Tech Lead (pregunta abierta 2).
8. **Frontend: Vite build → estático servido por `frontend`; `tsconfig` estricto,
   `features/` por dominio espejando el backend.**
   Por qué: paridad backend/frontend acelera a los agentes; `noUnusedLocals`,
   `noImplicitAny`, componentes PascalCase, tipos en bordes API (regla 5).
   Agenda con grid custom en C-06 (librería dedicada solo si el piloto lo pide).
9. **CI: dos jobs paralelos + stub Playwright.**
   Backend: pytest+httpx (contra Postgres/Redis de servicio), ruff/black, mypy.
   Frontend: `tsc --noEmit` + `vite build`. Playwright: un smoke del circuito
   crítico (reserva→confirmación) marcado `skip`/permitido-fallar hasta C-14,
   para no bloquear C-01…C-13 con E2E inmaduro.

## Risks / Trade-offs

- [Riesgo] `asyncpg` + `pg_isready` en CI/Compose con versiones pineadas
  divergentes → Mitigación: pinear `postgres:15.x` exacto en Compose y en el
  servicio CI; `docker compose config` validado en CI.
- [Riesgo] ARQ/uv decididos después obligan a tocar `Dockerfile`/`worker`
  → Mitigación: entrypoint y `pyproject.toml` aíslan la decisión (una línea de
  dependencia + un módulo); tasks marcan el swap como trivial.
- [Riesgo] `.env.example` se desincroniza con `Settings`
  → Mitigación: test que compara claves requeridas de `Settings` contra
  `.env.example` (falla si falta alguna).
- [Riesgo] Frontend estricto frena velocidad inicial
  → Mitigación: aceptado (regla dura 5); el stub inicial es mínimo.
- [Trade-off] Una DB por clínica (DD-07) multiplica costo operativo
  → aceptado en fase 1; `clinic_id` obligatorio deja la consolidación mecánica.

## Migration Plan

No hay migración (repo sin código): C-01 crea archivos nuevos. Rollback = revert
del commit. Despliegue: `docker compose up -d --build`; verificación: todos
`healthy` + `GET /health` 200 + `alembic upgrade head` limpio + CI verde.
C-02 continúa sobre este layout sin pasos intermedios.

## Open Questions

1. Worker Redis: ¿ARQ? (recomendado sí; si el Tech Lead elige Celery/Dramatiq,
   cambian solo dependencia + entrypoint — specs y tasks intactos).
2. Blacklist refresh: ¿Redis? (se implementa en C-03; C-01 solo deja cliente).
3. ¿pip/venv o `uv`? (recomendado `uv`; tasks contemplan ambos).
4. Deferrables sin impacto en C-01 (dueños en `10_preguntas_abiertas.md`):
   CAPTCHA booking (Tech Lead, antes de C-07), titularidad plantillas/número
   (PO/Dueño, antes de C-10), resguardos Ley 27.706/26.529 (legal+PO, diseño C-02).
