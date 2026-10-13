# Skill Registry

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

See `_shared/skill-resolver.md` for the full resolution protocol.

> Rebuilt: skills moved from GLOBAL to PROJECT-LOCAL scope. The 12 coding skills below resolve to `.agents/skills/` in this repo; foundation/orchestrator skills remain global under `C:\Users\DWIOL-11-001816\.config\opencode\skills\`.

## Project Skills (local — `.agents/skills/`)

| Trigger | Skill | Path |
|---------|-------|------|
| Writing, reviewing, or refactoring React/Next.js code; React components, Next.js pages, data fetching, bundle optimization, performance improvements | vercel-react-best-practices | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\vercel-react-best-practices\SKILL.md |
| Creating or altering tables/columns, schema design, migrations, RLS policies, indexes, triggers, functions, queues/jobs, pgvector, restores; slow queries, CPU, timeouts, EXPLAIN, connections, locking, bloat, tenant leaks | supabase-postgres-best-practices | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\supabase-postgres-best-practices\SKILL.md |
| Building new UI or reshaping existing one; aesthetic direction, typography, distinctive visual design | frontend-design | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\frontend-design\SKILL.md |
| Review UI, check accessibility, audit design, review UX, check site against best practices | web-design-guidelines | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\web-design-guidelines\SKILL.md |
| Build features or fix bugs test-first; red-green-refactor; integration tests | tdd | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\tdd\SKILL.md |
| Review a branch, PR, work-in-progress changes, or review since a commit/branch/tag | code-review | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\code-review\SKILL.md |
| Implementing auth systems, securing APIs, OAuth2/social login, RBAC, session management, SSO/multi-tenancy, debugging auth | auth-implementation-patterns | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\auth-implementation-patterns\SKILL.md |
| Codebase or API uses JWTs for auth; audit tokens, auth review | jwt-security-review | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\jwt-security-review\SKILL.md |
| Writing, reviewing, or refactoring SQLAlchemy models, Alembic migrations, schema changes, query optimization | sqlalchemy-alembic-expert-best-practices-code-review | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\sqlalchemy-alembic-expert-best-practices-code-review\SKILL.md |
| Building REST APIs with FastAPI, async Python backends, SQLAlchemy/Pydantic integration, API auth, microservices | python-fastapi-development | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\python-fastapi-development\SKILL.md |
| Query tuning, indexing strategies, execution plan analysis, pagination, batch ops, performance monitoring (any SQL DB) | sql-optimization | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\sql-optimization\SKILL.md |
| Multi-container apps, dev environments with DB/cache, frontend+backend+DB orchestration, service dependencies, networking, volumes, production deployment | docker-compose-orchestration | C:\Users\DWIOL-11-001816\Downloads\bd\sistema_de_turnos_odontologico\.agents\skills\docker-compose-orchestration\SKILL.md |

## Foundation Skills (global — orchestrator/SDD flow, intentionally NOT local)

| Trigger | Skill | Path |
|---------|-------|------|
| Start a new project from scratch with SDD/OpenSpec flow; /active-orchestrator:* commands | active-orchestrator | C:\Users\DWIOL-11-001816\.config\opencode\skills\active-orchestrator\SKILL.md |
| Create/generate/update AGENTS.md or CLAUDE.md; project rules for agents | agents-md-generator | C:\Users\DWIOL-11-001816\.config\opencode\skills\agent-instruction\SKILL.md |
| Investigate market/competitors/think about what to build before KB exists; Discovery phase | discovery-research | C:\Users\DWIOL-11-001816\.config\opencode\skills\discovery-research\SKILL.md |
| How do I do X; find a skill for X; is there a skill that can...; extend capabilities | find-skills | C:\Users\DWIOL-11-001816\.config\opencode\skills\find-skill\SKILL.md |
| Create/build/generate a knowledge base; document a project from source docs; armar base de conocimiento | kb-creator | C:\Users\DWIOL-11-001816\.config\opencode\skills\kb-creator\SKILL.md |
| Create/build/regenerate CHANGES.md, roadmap, change map, implementation plan | roadmap-generator | C:\Users\DWIOL-11-001816\.config\opencode\skills\roadmap-generator\SKILL.md |
| Create a skill from scratch; edit/optimize an existing skill; benchmark skill performance | skill-creator | C:\Users\DWIOL-11-001816\.config\opencode\skills\skill-creator\SKILL.md |
| Investigate/scrape a competitor from a URL into fixed-schema markdown notes | web-scraper | C:\Users\DWIOL-11-001816\.config\opencode\skills\web-scraper\SKILL.md |

## Compact Rules

Pre-digested rules per skill. Delegators copy matching blocks into sub-agent prompts as `## Project Standards (auto-resolved)`.

### vercel-react-best-practices
- Eliminate waterfalls: parallelize independent fetches with Promise.all, start promises early / await late, stream with Suspense boundaries
- Import directly from modules, never barrel files; use next/dynamic for heavy components; defer analytics/logging until after hydration; preload on hover/focus
- Never share mutable module-level request state in RSC/SSR; minimize data serialized to client components; use React.cache() for per-request dedup
- Prefer SWR for client fetch dedup; deduplicate global event listeners; use passive listeners for scroll; version and minimize localStorage payloads
- Derive state during render, not in effects; subscribe to derived booleans not raw values; use functional setState for stable callbacks; split hooks with independent deps
- Never define components inside components; extract expensive work into memoized components; use startTransition/useDeferredValue for non-urgent renders
- For agenda SPA: keep day/week views fast with hundreds of turnos — virtualize long lists (content-visibility), hoist static JSX, batch DOM/CSS writes

### supabase-postgres-best-practices
- Design schema first: choose correct column types, NOT NULL + CHECK constraints to help the optimizer, normalize OLTP to 3NF
- Index every frequent filter/join/sort path; prefer partial indexes (e.g. WHERE estado vigente) and composite indexes in filter-order
- Always EXPLAIN (ANALYZE, BUFFERS) slow queries; fix missing-index sequential scans before rewriting logic
- Enforce tenant isolation: mandatory clinic_id on operative tables + RLS policies, with tests proving cross-tenant invisibility
- Use SELECT column lists, never SELECT * in production; filter early in WHERE; prefer EXISTS over IN; never wrap indexed columns in functions in WHERE
- Concurrency: use FOR UPDATE SKIP LOCKED for worker ticks (reminders/waitlist); keep transactions short; handle exclusion-constraint violations (409 + alternatives) not pre-checks
- Connection pooling mandatory (PgBouncer/Supavisor); never open per-request connections without pooling; monitor pg_stat_statements, bloat, lock waits

### frontend-design
- Ground every screen in the dental brief: recepción agenda multi-profesional vs paciente mobile-first booking — never generic SaaS-card kit
- Plan first in two passes: compact tokens (4-6 named hex, type roles, layout concept + ASCII wireframe), then revise anything that reads as AI-default before coding
- One memorable element per screen; keep surroundings quiet; cut decoration that does not serve the brief
- Typography: one or two clearly distinct families, clear scale, line length < 80 chars; never accent a single headline word, all-caps labels, or gratuitous eyebrows
- Motion answers user action (open/expand/confirm) only; single orchestrated load moment max; respect prefers-reduced-motion; no scattered fade-slide entrances
- Copy from end-user perspective, active voice, sentence case; CTA names the exact outcome ("Confirmar turno"); errors explain what happened + how to fix, never vague apologies
- Quality floor without announcing: responsive to mobile, visible keyboard focus, accessible contrast, harmonious palette; screenshot-critique each build

### web-design-guidelines
- Always fetch fresh rules before a UI review: WebFetch https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
- Review the exact files/pattern given (ask if missing); check every fetched rule, no sampling
- Output findings only in the terse file:line format defined by the fetched guidelines
- Cover accessibility (focus, contrast, reduced motion, keyboard), UX consistency, and guideline compliance in every audit
- Never fix code during a review pass — report findings; fixes belong to a separate implementation step

### tdd
- Red before green: write the failing test first, then only enough code to pass; no speculative features
- Agree seams in writing before any test (public boundary under test + what it catches/misses); never test internals or unconfirmed seams
- One vertical slice per cycle: one seam → one test (tracer bullet) → one minimal implementation → repeat; never horizontal slicing (all tests then all code)
- Tests assert behavior through public interfaces (e.g. concurrent booking → 409, clashing reprogram leaves turno intact); survive refactors
- Expected values come from independent truth (literal, worked example, spec RN-AG/RN-ST/RN-CX) — never recompute the way the code does; no tautological assertions or hand-derived snapshots
- No mocks of internal collaborators, no private-method tests, no DB side-channel assertions; real Postgres for agenda invariants
- Refactoring belongs to review stage (code-review skill), not the red→green loop

### code-review
- Pin the fixed point first: git rev-parse <ref>, diff with git diff <fixed-point>...HEAD (three-dot) + git log <fixed-point>..HEAD --oneline; fail on bad ref or empty diff
- Run Standards and Spec axes as parallel sub-agents; never merge/rerank across axes — report under separate ## Standards / ## Spec headings
- Standards = repo docs (AGENTS.md/CLAUDE.md hard rules + KB) + Fowler smell baseline as judgement calls only; repo standard always overrides baseline; skip tooling-enforced items
- Flag smells by name with hunk quotes: Mysterious Name, Duplicated Code, Feature Envy, Data Clumps, Primitive Obsession, Repeated Switches, Shotgun Surgery, Divergent Change, Speculative Generality, Message Chains, Middle Man, Refused Bequest
- Spec = originating issue/spec (commit refs → user path → docs/specs/.scratch match → ask); report missing/partial requirements, scope creep, and plausible-but-wrong implementations with spec line quotes; if no spec, skip Spec axis explicitly
- Keep each axis report < 400 words; end with per-axis totals + worst issue per axis

### auth-implementation-patterns
- Separate AuthN (who) from AuthZ (what): verify identity, then enforce permissions server-side on every request — never client-only checks
- Passwords: argon2id (or bcrypt) hashing only, never plaintext; enforce strength; secure reset tokens with expiry
- JWT access tokens short-lived (≤15 min); refresh tokens rotating with reuse-detection, hashed server-side, HttpOnly Secure SameSite=Lax cookies
- RBAC via FastAPI dependencies (e.g. require_roles('admin','recepcion')); odontólogo sees only own turnos enforced in SQLAlchemy query, not frontend
- Rate-limit auth endpoints (login strict per IP+email; booking/webhooks strict); validate all input (email, E.164 phone, Pydantic v2 extra='forbid' at edges)
- Use HTTPS everywhere; rotate JWT/session secrets regularly; log security events (login attempts, failed auth) without PII
- Never put JWTs in localStorage when XSS surface exists; add CSRF protection for cookie flows; offer MFA where possible

### jwt-security-review
- Pin expected alg server-side; reject alg:none outright; never accept algorithms:['*']; verify RS256 with public key, never HMAC-with-public-key (RS256→HS256 confusion)
- Reject jku/x5u to attacker URLs and kid path-traversal/SQL/command injection in key lookup
- HS256 secrets ≥ 32 bytes entropy, not wordlist-derived; rotate keys and revoke old ones (not just unused)
- Enforce exp + nbf with bounded clock skew; validate iss + aud against expected values; allowlist claims — reject unexpected privileged claims (e.g. admin:true)
- Never trust client-controlled role/uid claims when server lookup exists; sub must be stable user ID, not mutable email
- Refresh rotation with reuse-detection invalidates the whole family on replay; revocation path for logout/password-change/force-logout; access ≤ 15 min, no long-lived bearers
- Test: unsigned alg:none, HS256-forged-with-pubkey, expired/wrong iss/aud, tampered role escalation, replayed rotated refresh → must fail/invalidate
- Smell: jwt.decode() without verify, jwt.verify() without algorithms pin

### sqlalchemy-alembic-expert-best-practices-code-review
- One Alembic migration per change, versioned; DDL for EXCLUDE constraints
- Create indexes CONCURRENTLY (postgresql_concurrently=True + autocommit block); never blocking CREATE INDEX on hot tables
- Add FKs and CHECKs as NOT VALID first, then VALIDATE separately; split unique constraints into concurrent index + constraint steps
- Column type changes via multi-step (add → backfill → swap) to avoid long table locks
- Cap non-unique indexes at 3 columns; drop redundant indexes covered by composite prefixes; verify every SQLAlchemy query pattern has a matching index
- Models: SQLAlchemy 2.x async, clinic_id mandatory on operative tables, tstzrange + EXCLUDE USING gist for appointments per professional/chair WHERE estado vigente; appointment_event append-only
- Review checklist: safe migration path, index coverage, constraint safety, query patterns (availability = schedule_rule − block − vigentes − buffers)

### python-fastapi-development
- Stack: Python 3.12+, FastAPI async, SQLAlchemy 2.x async + asyncpg, Alembic, Pydantic v2 + pydantic-settings, Redis 7, pytest + httpx/TestClient
- Structure per domain (auth, clinic, agenda, booking_public, waiting_list, reminders, notifications, users, reports): routers/ + services/ + schemas/ + models/; app/main.py with CORS + global rate-limit
- Routers thin → services hold logic; request/response validation with Pydantic schemas (extra='forbid') at every edge; custom exceptions + handlers with consistent error envelopes
- Auth via dependencies (require_roles); argon2id passwords; JWT (see auth/jwt skills); rate-limit sensitive routes via Redis
- DB sessions async with correct lifespan/dependency scoping; Alembic for all schema changes; never raw DDL outside migrations
- Quality gates per change: pytest green (coverage on critical paths: overlap, sobreturnos, lista de espera, RBAC), mypy + ruff clean, OpenAPI docs complete
- Config via .env (.env.example complete; never commit .env): DATABASE_URL, REDIS_URL, JWT_SECRET, WHATSAPP_TOKEN, EMAIL_*, CLINIC_TZ_DEFAULT, BOOKING_RATE_LIMIT, MANAGE_TOKEN_TTL_H, FRONTEND_PUBLIC_URL, CORS_ORIGINS

### sql-optimization
- Never SELECT * in production; list columns explicitly; filter early; prefer INNER over LEFT when semantics allow; push filters into JOIN ON where it reduces rows
- Keep WHERE index-friendly: no functions on indexed columns (use range predicates on tstzrange/created_at); prefer UNION ALL over complex OR branches
- Replace correlated subqueries with window functions or single conditional-aggregation pass (e.g. occupation/absenteeism counts in one query over appointment_event)
- Pagination: cursor/keyset (WHERE created_at < ? / id > ? ORDER BY … LIMIT n), never large OFFSET; batch inserts (multi-row VALUES), never row-by-row
- Index design: composite in filter-order, covering where beneficial, partial for hot subsets (vigentes, pending); avoid over-indexing (hurts INSERT/UPDATE); ≤3 cols for non-unique
- Availability/occupation/report queries read appointment_event (immutable log), never mutated state; compute over date ranges with sargable predicates
- Methodology: identify via pg_stat_statements/slow log → EXPLAIN → optimize → test with realistic volumes → monitor → iterate; set slow-query alerts

### docker-compose-orchestration
- Services: api (FastAPI), db (postgres 15 pinned), redis (redis 7 pinned), worker (async reminder/WhatsApp/waitlist jobs), frontend (React+TS+Vite static after build); single cloud deploy per tenant
- Pin specific image tags, never latest in production; one process per container; restart: unless-stopped (always in prod); healthcheck on every service
- Dependencies via depends_on with health conditions: pg_isready (db), redis-cli ping (redis); api/worker wait for healthy db + started redis
- Networking: services reach each other by name (DATABASE_URL, REDIS_URL); isolate with frontend/backend networks, internal:true for DB net
- Volumes: named volumes for pgdata/redis-data; bind-mount source only in dev for hot reload; :ro for configs; never commit .env (use env_file + secrets for JWT_SECRET/DB_PASSWORD)
- Config: base compose.yaml + compose.override.yaml (dev) + compose.prod.yaml (replicas, resource limits, log rotation, secrets); validate with docker compose config
- Lifecycle: up -d --build for deploy; logs -f <svc>, exec <svc> sh for debug; down -v also removes volumes (data loss)

### active-orchestrator
- Thin orchestrator only: owns `.active-orchestrator-state.json` and the `step` field; never change step/owner except through its own flow
- Order: openspec init → optional Discovery → kb-creator → roadmap-generator → find-skill → skill-registry → agent-instruction; checkpoint at every phase boundary, never back-to-back
- Never ask strategic discovery content questions (system_type, scale, stack, checklist) — those belong to kb-creator/discovery-research; only ask phase-selection (whether to run Discovery)

### agents-md-generator
- Generates canonical AGENTS.md/CLAUDE.md from KB + roadmap: stack, knowledge-base/ refs, skills per agent, CHANGES.md roadmap, hard rules; interactive ONLY to confirm hard rules
- Pre-checks: KB must exist (run kb-creator first); never repeat global CLAUDE.md content — project-specific only
- For single-rule edits, edit AGENTS.md directly instead of regenerating

### discovery-research
- Runs Discovery BEFORE the KB: competitor research via web-scraper + guided Q&A over the full checklist (problem, users, use cases, competitors, features, business rules, integrations, constraints, risks, open questions)
- Never complete a checklist point with an assumption when it can be asked or researched
- Output (docs/discovery/discovery.md + state.discovery) is INPUT to kb-creator, not a replacement

### find-skills
- Use when user asks how to do X or whether a skill exists for X; search via `npx skills find [query] [--owner <owner>]`
- Install with `npx skills add <package>` (local) or `-g` (global); update with `npx skills update`

### kb-creator
- Builds 10 canonical .md files at knowledge-base/; auto-detects mode: silent from existing docs/ sources vs interactive from scratch
- Don't use when KB already complete (update single files instead) or when user wants one specific document

### roadmap-generator
- Generates CHANGES.md: full change index with dependency tree, parallelism gates, critical path, multi-agent plan, governance levels, per-change scope/dependencies/KB pointers; fire-and-forget
- Pre-checks: knowledge-base/ and openspec/ must exist; don't regenerate wholesale for single-change updates

### skill-creator
- Draft → test prompts → evaluate (qualitative + quantitative) → rewrite → repeat; expand test set at larger scale
- Optimize the skill description for triggering accuracy after the skill works

### web-scraper
- Converts one competitor/solution URL into fixed-schema markdown notes (problem, users, features, pricing, positioning) via WebFetch/WebSearch — no API keys
- Output schema is fixed, always; writes to discovery/sources/<slug>.md for discovery-research to consume
- Never for mass crawling, JS-heavy/anti-bot sites, or a loose URL scrape outside the checklist (that's discovery-research's job)

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| Agent instructions | AGENTS.md | Canonical agent entrypoint: stack, KB index, skills per role, CHANGES roadmap, 12 hard rules; read FIRST on entering repo |
| Agent instructions (mirror) | CLAUDE.md | Mirror of AGENTS.md — keep in sync (`diff AGENTS.md CLAUDE.md`) |
| Change index | CHANGES.md | Canonical change index + dependency tree + parallelism gates + critical path; read before any /opsx:propose |
| KB README | knowledge-base/README.md | KB index — references files below |
| KB Visión | knowledge-base/01_vision_y_objetivos.md | Alcance v1.0 agenda-first, métricas de éxito |
| KB Descripción | knowledge-base/02_descripcion_general.md | Stack tecnológico |
| KB Actores | knowledge-base/03_actores_y_roles.md | RBAC matrix, reglas transversales |
| KB Datos | knowledge-base/04_modelo_de_datos.md | Entidades, appointment EXCLUDE, appointment_event, seed |
| KB Reglas | knowledge-base/05_reglas_de_negocio.md | RN-AG/RN-SB/RN-ST/RN-CX/RN-ON/RN-WA/RN-LE/RN-GL |
| KB Funcionalidades | knowledge-base/06_funcionalidades.md | Épicas US-001..US-051 |
| KB Flujos | knowledge-base/07_flujos_principales.md | Flujos 1-5 (booking, token, recordatorios, recepción, espera) |
| KB Arquitectura | knowledge-base/08_arquitectura_propuesta.md | Directorios, invariante DB, auditoría, seguridad, env vars |
| KB Decisiones | knowledge-base/09_decisiones_y_supuestos.md | DD-01..DD-07, SU-03/SU-04/SU-06/SU-07 |
| KB Abiertas | knowledge-base/10_preguntas_abiertas.md | ⚠️ Prioridad Alta a resolver antes/durante implementación |
| KB WhatsApp | knowledge-base/11_whatsapp_y_recordatorios.md | Canal, plantillas, motor, costos |
| Discovery | docs/discovery/discovery.md | Competitor research (22 fuentes, fetched 2026-10-08) |
| Orchestrator state | .active-orchestrator-state.json | step is "done" — do NOT change step/owner; MAY update state.registry only |

> Stack: Python/FastAPI + SQLAlchemy + PostgreSQL + Redis + React+TS+Vite (Docker Compose), JWT + RBAC (admin/recepcion/odontologo), Alembic versioned migrations, pytest + httpx/TestClient + Playwright.

Read the convention files listed above for project-specific patterns and rules. All referenced paths have been extracted — no need to read index files to discover more.
