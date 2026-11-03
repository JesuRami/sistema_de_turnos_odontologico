# Design

## Context

This change adds per-clinic agenda configuration to the FastAPI backend. It builds on the foundation from C-01 (scaffolding) and C-02 (core models), and adds the agenda-config capability after C-03 (auth-rbac). The design must honor all 12 hard rules from AGENTS.md, especially: Pydantic `extra='forbid'` at edges, Alembic-only migrations with CONCURRENTLY NOT VALID → VALIDATE pattern, `clinic_id` mandatory + cross-tenant tests, env-only secrets, real DB in tests, JWT ≤15 min rotating refresh with HttpOnly cookie, and index/FK constraints in 3-step validate pattern.

## Goals

- Enable per-clinic CRUD of professionals, chairs, schedules, and blocks
- Enforce ScheduleRule non-overlap via GIST exclusion on (professional, chair, weekday)
- Provide Block catalog with at least one objective; prevent blocks from overlapping valid appointments without explicit resolution
- Make clinic policies (cancellation window, reminder steps, max double-bookings, offer expiration) editable and scoped to future appointments only
- Deactivate professional/chair to block new reservations while preserving history

## Non-Goals

- Patient-facing frontend changes (handled in later changes)
- WhatsApp reminder engine (Fase 3, C-07 onward)
- Clinical history/cashiering/ARCA integrations (post-MVP phases)
- JWT implementation details (auth-rbac C-03 already established the pattern)

## Decisions

### Decision: ScheduleRule non-overlap via EXCLUDE USING gist
- **Choice**: Add `EXCLUDE USING gist (professional_id WITH =, chair_id WITH =, schedule_period WITH &&) ON schedule_rule`
- **Rationale**: PostgreSQL GIST exclusion is the most efficient way to enforce interval overlap constraints at the DB level; prevents race conditions that application-level checks alone cannot guarantee
- **Alternative**: Application-level check only — rejected because it is vulnerable to race conditions under concurrent booking

### Decision: Block catalog with RN-BL-01/02/03/04 enforcement
- **Choice**: Block model has `reason` column referencing a catalog of valid blocking reasons; `objective` column (non-null); overlap check with `appointment_event` uses same-transaction resolution flag
- **Rationale**: Explicit objective satisfies RN-BL-01; transaction-scoped resolution flag satisfies RN-BL-02; immutability is enforced by `created_at` lock and soft-delete flag satisfying RN-BL-03; multi-resource holiday blocks supported by separate reason code satisfying RN-BL-04
- **Alternative**: Boolean `is_holiday` flag only — rejected because it does not support multi-resource blocking or varied reason codes

### Decision: Clinic policies editable, future-scoped only
- **Choice**: `clinic` table columns: `cancellation_window_minutes` (integer, default 1440 i.e. 24h), `reminder_steps` (jsonb array default '[72,24,3]'), `max_double_bookings` (integer default 2), `offer_expiration_minutes` (integer default 240 i.e. 4h). All policy changes set a `policy_effective_at` timestamp; existing appointments retain original values via row-level copy.
- **Rationale**: JSONB for reminder steps allows flexible step intervals; effective_at timestamp makes the "future-only" semantics explicit and queryable
- **Alternative**: Simple column default changes without timestamp — rejected because it cannot distinguish which appointments were created under which policy version

### Decision: Professional/chair deactivation preserves history
- **Choice**: `professionals` and `chairs` tables get `is_active` boolean (default true). New reservation attempts check `is_active` and return 409 if false. Historical `appointment_event` rows remain untouched; no physical deletion.
- **Rationale**: Satisfies US-001 CA-1 and the hard rule #7 (no physical deletion → machine state + append-only event)
- **Alternative**: Soft-delete with `deleted_at` flag — rejected because it conflates "inactive" with "deleted", losing historical tracking clarity

### Decision: Migration 003 follows 3-step DDL pattern
- **Choice**: Step 1: `ADD COLUMN` with `NOT VALID`; Step 2: `VALIDATE` constraint; Step 3: Create EXCLUDE index with `CONCURRENTLY`. Data integrity checked between steps.
- **Rationale**: Satisfies hard rule #11 (CONCURRENTLY NOT VALID → VALIDATE in 3 steps); minimizes lock time
- **Alternative**: Single-step `ADD CONSTRAINT` — rejected because it requires a full table rewrite and blocks writes during migration

### Decision: Pydantic v2 schemas with extra='forbid' at edges
- **Choice**: All API edge schemas (booking public, webhooks, admin) use `ConfigDict(extra='forbid')`. Internal domain schemas may relax this but are audited.
- **Rationale**: Satisfies hard rule #2; prevents unexpected payload injection at public boundaries
- **Alternative**: Default Pydantic v2 behavior (allow extra) — rejected because it violates rule #2 and creates security risk

## Risks / Trade-offs

- [Risk] GIST exclusion on large tables may impact write throughput during peak booking — Mitigation: test with realistic concurrency; consider partitioning by clinic_id if needed
- [Risk] Policy changes could create inconsistencies if not rolled out atomically — Mitigation: `policy_effective_at` timestamp + query guard; all services read the effective policy at reservation time
- [Risk] JWT refresh rotation with reuse-detection may reject legitimate re-connections — Mitigation: short access token TTL (15 min) + silent refresh flow; log reuse events for audit
- [Risk] Concurrent block creation could violate exclusion constraint — Mitigation: application-level check before DB insert; 409 error with alternative slot suggestions

## Migration Plan

1. **Migration 003 (Alembic)**: 
   - Add `block` table with columns: `id`, `clinic_id`, `reason` (enum/catalog), `objective` (text, not-null), `start`, `end`, `created_at`
   - Add policy columns to `clinic` table: `cancellation_window_minutes`, `reminder_steps` (jsonb), `max_double_bookings`, `offer_expiration_minutes`
   - Add EXCLUDE GIST constraint on `schedule_rule` (professional, chair, weekday) — 3 steps: add column NOT VALID, validate, CONCURRENTLY create index
   - Seed blocking-reason catalog data

2. **Rollback**: 
   - Drop EXCLUDE constraint with `DROP INDEX CONCURRENTLY`
   - Remove policy columns from `clinic`
   - Drop `block` table (data loss accepted in rollback scenario)

3. **Verification**: 
   - Run pytest suite against real Postgres container
   - Test overlap rejection for ScheduleRule
   - Test block creation with/without objective
   - Test policy change does not affect existing appointments
   - Test professional deactivation blocks new reservations

## Open Questions

- [ ] Should the Block `reason` be an PostgreSQL ENUM or a separate `block_reasons` table with foreign key? (Can be decided before migration; ENUM is simpler for catalog size < 20 entries)
- [ ] What is the exact format of `reminder_steps` jsonb? (Default '[72,24,3]' agreed; can be changed via policy API)
- [ ] Should `offer_expiration_minutes` default be 240 (4h) or 120 (2h)? (Default 240 aligns with RN-BL-04 and US-004 CA-2; can be overridden per-clinic)