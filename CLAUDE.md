# Sistema de Turnos Odontológico — Instrucciones para Agentes

> Este archivo (y su copia `CLAUDE.md`) es lo PRIMERO que todo agente lee al entrar al repo.
> Generado a partir de `knowledge-base/` y `CHANGES.md` (12 reglas duras confirmadas por el usuario). No editar a mano sin re-sincronizar ambos archivos (`diff AGENTS.md CLAUDE.md`).

---

## Stack Tecnológico

| Capa | Tecnología | Versión mínima | Notas |
|------|-----------|----------------|-------|
| Backend | Python + FastAPI | Python 3.12+ / FastAPI 0.110+ | API REST, routers por dominio, validación con Pydantic v2 |
| Frontend | React + TypeScript + Vite | React 18 / Vite 5 | SPA browser-first; TypeScript estricto |
| UI | Tailwind CSS + componentes propios | Tailwind 3 | Agenda (calendario) con librería dedicada o custom sobre grid |
| Base de datos | PostgreSQL | 15 | Exclusion constraints para solapamientos; `tstzrange` |
| ORM / Migraciones | SQLAlchemy 2.x async + Alembic | SQLAlchemy 2.x | `AsyncSession`, `DateTime(timezone=True)`, constraints vía DDL; migraciones versionadas con Alembic |
| Jobs programados / Cola | Redis + worker async | Redis 7 | Reminder scheduler, WhatsApp queue/outbox y waiting-list jobs (idempotentes y reintentables) |
| Auth | JWT (access corto + refresh rotativo) | — | Solo personal de clínica; paciente opera por token de un solo uso |
| Email transaccional | Proveedor SMTP/API (a definir) | — | Canal de respaldo de recordatorios |
| WhatsApp | WhatsApp Business API (Cloud API de Meta) | Graph API v19+ | Único canal WhatsApp soportado; plantillas aprobadas |
| Despliegue | Docker / Docker Compose: `api` + `db` + `redis` + `worker` + `frontend` | — | Single cloud deploy por tenant (fase 1); `frontend` estático servido tras build Vite |
| Tests | pytest (unit) + httpx/TestClient (API) + Playwright (E2E crítico) | — | Cobertura obligatoria en invariantes de agenda |

MVP agenda-first v1.0: agenda multi-sillón + reserva online 24/7 + recordatorios WhatsApp. Historia clínica, cobros, ARCA y obras sociales son fases posteriores (C-15 a C-19).

Detalle completo: [knowledge-base/02_descripcion_general.md](knowledge-base/02_descripcion_general.md)

---

## Base de Conocimiento

La fuente de verdad del dominio vive en `knowledge-base/`. **Leé el archivo relevante ANTES de implementar.**

| Archivo | Cuándo leerlo |
|---------|---------------|
| [README.md](knowledge-base/README.md) | Índice de la KB + resumen ejecutivo + quick start |
| [01_vision_y_objetivos.md](knowledge-base/01_vision_y_objetivos.md) | Entender propósito, alcance v1.0 y métricas de éxito |
| [02_descripcion_general.md](knowledge-base/02_descripcion_general.md) | Stack, arquitectura, integraciones, API REST |
| [03_actores_y_roles.md](knowledge-base/03_actores_y_roles.md) | Auth, RBAC, permisos (admin/recepción/odontólogo, paciente por token) |
| [04_modelo_de_datos.md](knowledge-base/04_modelo_de_datos.md) | Entidades, ERD, migraciones, seed |
| [05_reglas_de_negocio.md](knowledge-base/05_reglas_de_negocio.md) | Reglas codificadas (RN-AG/SB/BL/LE/CX/ST/ON/WA/GL) |
| [06_funcionalidades.md](knowledge-base/06_funcionalidades.md) | 6 épicas, 16 historias US-001…US-051 (solo MVP agenda) |
| [07_flujos_principales.md](knowledge-base/07_flujos_principales.md) | Flujos E2E (reserva, token, recordatorios, recepción, espera) |
| [08_arquitectura_propuesta.md](knowledge-base/08_arquitectura_propuesta.md) | Patrones, directorios, seguridad, variables de entorno |
| [09_decisiones_y_supuestos.md](knowledge-base/09_decisiones_y_supuestos.md) | Decisiones DD-01…DD-07 + supuestos SU-01…SU-07 |
| [10_preguntas_abiertas.md](knowledge-base/10_preguntas_abiertas.md) | ⚠️ Inconsistencias a resolver ANTES de codear |
| [11_whatsapp_y_recordatorios.md](knowledge-base/11_whatsapp_y_recordatorios.md) | Canal WhatsApp Cloud API, plantillas, reminder engine, costos |
| [discovery/discovery.md](discovery/discovery.md) | Research de competidores (22 fuentes, 2026-10-08) |

> ⚠️ Resolver las preguntas de prioridad **Alta** de `10_preguntas_abiertas.md` antes de arrancar el primer change.

---

## Skills Disponibles

| Agente | Rol | Skills que carga |
|--------|-----|------------------|
| **Backend Core** | FastAPI / SQLAlchemy / agenda / turnos | `python-fastapi-development`, `sqlalchemy-alembic-expert-best-practices-code-review`, `supabase-postgres-best-practices`, `sql-optimization`, `tdd` |
| **Backend Aux** | Auth / servicios / integraciones / infra | `auth-implementation-patterns`, `jwt-security-review`, `docker-compose-orchestration`, `code-review` |
| **Frontend** | React / TS / Tailwind / agenda SPA | `vercel-react-best-practices`, `frontend-design`, `web-design-guidelines` |
| **Orquestación** | OPSX / SDD / docs | Resolver en runtime |

Cargá la skill correspondiente al contexto ANTES de escribir código.

> Los compact rules de cada skill los resuelve el orquestador desde `.atl/skill-registry.md` (generado por `skill-registry`; no versionado — no está en el repo). Esta tabla solo mapea skill→rol.

---

## Roadmap de Changes

El plan de implementación completo está en [CHANGES.md](CHANGES.md). Resumen:

- **Total**: 19 changes (C-01…C-19) en 6 fases (Fase 0 cimientos, Fase 1 agenda core, Fase 2 reserva online, Fase 3 recordatorios WhatsApp, Fase 4 lista de espera/reportes/piloto, Fase 5 circuito clínico-financiero posterior).
- **Camino crítico** (9 changes): `C-01 → C-02 → C-03 → C-04 → C-05 → C-07 → C-08 → C-10 → C-14`.
- **Primer change**: `C-01 foundation-setup` — scaffolding completo del monorepo + infraestructura base (DD-01, DD-06, DD-07): estructura `backend/` (FastAPI async, routers/services/schemas por dominio) + `frontend/` (React 18 + TS + Vite + Tailwind 3) + `backend/tests/` (pytest); Postgres 15 + Redis 7 + Alembic; worker async; `.env.example` completo; `Dockerfile` + `docker-compose.yml` (`api`, `db`, `redis`, `worker`, `frontend`); CI con jobs paralelos backend/frontend.

**Antes de cualquier `/opsx:propose`**: leé [CHANGES.md](CHANGES.md), identificá las dependencias del change y los archivos de "Leer antes".

---

## Reglas Duras

> Este proyecto hereda las reglas globales de `~/.claude/CLAUDE.md` (actualmente inexistente: este archivo opera como su resolución efectiva). Las reglas universales aplicables se transcriben abajo para que ningún contrato quede en el limbo.

**Reglas universales (heredadas del global):**

- Flujo orquestador obligatorio: KB → CHANGES → `/opsx:propose` → implementar → `/opsx:archive`. Nunca implementar un change sin proposal aprobada ni archivar sin completar sus tasks.
- Respetar el nivel de governance declarado por change (BAJO / MEDIO / ALTO / CRITICO): a mayor nivel, mayor rigor de revisión y evidencia antes de avanzar.
- Uso de engram obligatorio: guardar decisiones, fixes y descubrimientos con `mem_save`; consultar contexto previo con `mem_search`/`mem_context` al iniciar trabajo.
- TDD estricto rojo → verde: escribir primero el test que falla, luego el mínimo código para pasarlo; sin funcionalidades especulativas.
- NUNCA compilar/buildear ni commitear sin pedido explícito del usuario → solo ejecutar builds/commits cuando se soliciten.
- Commits en formato conventional commits, sin co-autoría de IA → mensajes `tipo(ámbito): descripción`, sin líneas `Co-Authored-By` ni firmas de asistente.

**Reglas específicas del proyecto (12 confirmadas por el usuario; son contrato, romperlas es un defecto):**

1. NUNCA validar solapamientos solo en backend → imponer EXCLUDE USING gist sobre tstzrange por (profesional, sillón) WHERE estado vigente; colisión → 409 + turnos alternativos.
2. NUNCA schema Pydantic v2 sin extra='forbid' → ConfigDict(extra='forbid') en bordes (booking público, webhooks, admin).
3. NUNCA cambio de schema fuera de Alembic → una migración versionada por change; DDL para EXCLUDE.
4. NUNCA tabla operativa sin clinic_id obligatorio + test de aislamiento cross-tenant.
5. NUNCA any en TypeScript → tsconfig estricto; componentes PascalCase; tipos en bordes API.
6. NUNCA secretos hardcodeados → solo vía env (.env.example completo); nunca commitear .env.
7. NUNCA borrado físico de turnos/pacientes → máquina de estados + appointment_event append-only en la misma transacción.
8. NUNCA SELECT * en producción ni query de agenda/reportes sobre estado mutado → leer appointment_event; paginación por cursor, batch inserts.
9. NUNCA mocks de DB para invariantes → Postgres real/contenedor; pytest+httpx verde + ruff/black + mypy limpios por change; Playwright en circuito crítico.
10. NUNCA JWT largo ni en localStorage → access ≤15 min, refresh rotativo con reuse-detection, cookie HttpOnly Secure SameSite=Lax; pin de alg, validar iss/aud/exp.
11. NUNCA CREATE INDEX bloqueante ni FK/CHECK sin validación diferida → CONCURRENTLY + NOT VALID → VALIDATE; cambios de tipo en 3 pasos.
12. NUNCA imagen Docker :latest ni contenedor sin healthcheck → tags pineados, depends_on con pg_isready/redis-cli ping, un proceso por contenedor.

---

## Flujo de Trabajo

```
1. Leer la KB relevante (knowledge-base/)        → entender el dominio
2. Identificar el change en CHANGES.md           → respetar dependencias
3. /opsx:propose C-NN-nombre                     → proposal + design + specs + tasks
4. Implementar las tasks (cargando skills)       → respetando las reglas duras
5. /opsx:archive C-NN-nombre + marcar [x]        → cerrar el change
```

Aplicar TODAS las reglas duras en cada paso. Ante conflicto entre la KB y este archivo, las reglas duras prevalecen.

⚠️ **Inconsistencias de prioridad Alta** (`knowledge-base/10_preguntas_abiertas.md`) a resolver antes o durante la implementación: rotación del `manage_token` en reprogramación, CAPTCHA/anti-bot de la reserva pública, titularidad de plantillas WhatsApp y número (clínica vs. número compartido), resguardos Ley 27.706/26.529 (consentimiento, retención, portabilidad) desde v1.
