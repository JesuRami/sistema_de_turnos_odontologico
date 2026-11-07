# Sistema de Turnos Odontológico

Sistema de gestión de turnos para consultorios y clínicas odontológicas argentinas.
MVP **agenda-first**: agenda multi-profesional y multi-sillón, reserva online 24/7,
gestión por token y recordatorios por WhatsApp.

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy 2.x async + Alembic.
- **Base de datos**: PostgreSQL 15 (constraints `EXCLUDE` para solapamientos) + Redis 7.
- **Frontend**: React 18 + TypeScript + Vite + Tailwind 3.
- **Infra**: Docker Compose (`api`, `db`, `redis`, `worker`, `frontend`).
- **Tests**: pytest + httpx/TestClient + Playwright.

## Documentación

- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md): instrucciones canónicas para agentes,
  stack, skills y reglas duras. **Leer primero.**
- [`knowledge-base/README.md`](knowledge-base/README.md): índice de la base de conocimiento
  (visión, actores, modelo de datos, reglas de negocio, flujos, WhatsApp).
- [`CHANGES.md`](CHANGES.md): roadmap de changes C-01…C-19 y dependencias.
- [`openspec/`](openspec/): changes activos, specs principales y archivo.
- [`docs/skills-mcp/`](docs/skills-mcp/): investigación, aplicación y evidencias del TP de
  skill propia + MCP.

## Skill propia

[`auditoria-escenarios-turnos`](.agents/skills/auditoria-escenarios-turnos/SKILL.md):
audita los escenarios de un change OpenSpec contra la KB y las reglas duras, clasifica
funcionamiento/error de negocio/borde y detecta `THEN` no verificables, reglas huérfanas
y tasks sin verificación. Está registrada en [`.atl/skill-registry.md`](.atl/skill-registry.md)
y referenciada en `AGENTS.md`.

## MCP integrado

**Context7** (documentación oficial de librerías y APIs), configurado en
[`opencode.json`](opencode.json). Requisitos, pasos de conexión, comprobación,
solución de problemas y límites: [`docs/skills-mcp/mcp-context7.md`](docs/skills-mcp/mcp-context7.md).

## Puesta en marcha

```bash
# 1. Variables de entorno (nunca commitear .env)
cp .env.example .env

# 2. Stack completo
docker compose up -d --build

# 3. Backend (si se corre fuera de Docker)
cd backend && pytest -q

# 4. Frontend
cd frontend && npm install && npm run dev
```

La guía operativa de WhatsApp (plantillas, webhook, número) está en
[`backend/README.md`](backend/README.md).
