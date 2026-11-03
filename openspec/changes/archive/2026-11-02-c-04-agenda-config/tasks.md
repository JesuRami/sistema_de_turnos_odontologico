# Tasks

## 1. Database Migration — ScheduleRule EXCLUDE GIST and Block model

- [ ] 1.1 Create Alembic migration 003 that adds `block` table with columns: `id`, `clinic_id` (UUID, not-null), `reason` (varchar, not-null, catalog reference), `objective` (text, not-null), `start` (tstzrange, not-null), `end` (tstzrange, not-null), `created_at` (timestamptz, not-null)
- [ ] 1.2 Add policy columns to `clinic` table: `cancellation_window_minutes` (integer, default 1440), `reminder_steps` (jsonb, default '[72,24,3]'), `max_double_bookings` (integer, default 2), `offer_expiration_minutes` (integer, default 240)
- [ ] 1.3 Step 1 of 3: Add EXCLUDE GIST column definitions to `schedule_rule` as `NOT VALID`: `EXCLUDE USING gist (professional_id WITH =, chair_id WITH =, schedule_period WITH &&) ON schedule_rule`
- [ ] 1.4 Step 2 of 3: `VALIDATE` the EXCLUDE constraint (checks existing data conforms)
- [ ] 1.5 Step 3 of 3: Create the GIST index with `CONCURRENTLY` (no write lock)
- [ ] 1.6 Seed initial blocking-reason catalog data (hard-coded reasons for: maintenance, holiday, staff shortage, room unavailability)
- [ ] 1.7 Write verification script: `python -m pytest tests/ -k "migration_003" -x --tb=short` and confirm green

## 2. SQLAlchemy 2.x Async Models

- [ ] 2.1 Add `ScheduleRule` model with `professional_id`, `chair_id`, `weekday` (integer 0-6), `start`, `end` (both tz-aware DateTime), `__table_args__` with the EXCLUDE GIST constraint (via Raw SQL or SQLAlchemy DDL)
- [ ] 2.2 Add `Block` model with `clinic_id`, `reason`, `objective`, `start`, `end`, `created_at`; relationship to Clinic
- [ ] 2.3 Add policy columns to `Clinic` model: `cancellation_window_minutes`, `reminder_steps` (JSON), `max_double_bookings`, `offer_expiration_minutes`
- [ ] 2.5 Write verification script: `python -m pytest tests/ -k "models" -x --tb=short` and confirm green

## 3. FastAPI Routers — CRUD for agenda config

- [ ] 3.1 Router for `professionals` (admin full CRUD; recepción read-only; odontólogo read-only own)
- [ ] 3.2 Router for `chairs` (admin full CRUD; recepción read-only; odontólogo read-only own)
- [ ] 3.3 Router for `schedules` (create ScheduleRule with overlap check; admin full CRUD)
- [ ] 3.4 Router for `blocks` (create/read blocks with objective validation; reject if objective empty per RN-BL-01)
- [ ] 3.5 Implement deactivation endpoint for professionals/chairs that sets `is_active=False` and returns 409 for new reservation attempts (US-001 CA-1)
- [ ] 3.6 Write verification script: `python -m pytest tests/ -k "router" -x --tb=short` and confirm green

## 4. Pydantic v2 Schemas with extra='forbid'

- [ ] 4.1 Professional schema: `ConfigDict(extra='forbid')` at edge (booking public, webhooks, admin)
- [ ] 4.2 Chair schema: `ConfigDict(extra='forbid')` at edge
- [ ] 4.3 ScheduleRule schema: `ConfigDict(extra='forbid')` at edge
- [ ] 4.4 Block schema: `ConfigDict(extra='forbid')` at edge; validate `objective` is non-empty (RN-BL-01)
- [ ] 4.5 Clinic policy schema: `cancellation_window_minutes`, `reminder_steps`, `max_double_bookings`, `offer_expiration_minutes` all with `extra='forbid'`
- [ ] 4.6 Write verification script: `python -m pytest tests/ -k "schema" -x --tb=short` and confirm green

## 5. Tests — Overlap, Block, Policy Invariants

- [ ] 5.1 Test: overlapping ScheduleRule rejected with 409 (uses real Postgres container, no mocks)
- [ ] 5.2 Test: Block creation with empty objective rejected (RN-BL-01)
- [ ] 5.3 Test: Block creation with valid objective accepted (RN-BL-01)
- [ ] 5.4 Test: Policy change does not affect existing appointments (only future ones)
- [ ] 5.5 Test: Deactivated professional blocks new reservations, history preserved
- [ ] 5.6 Test: Cross-tenant isolation via clinic_id on all queries
- [ ] 5.7 Write verification script: `python -m pytest tests/ -k "invariant" -x --tb=short` and confirm green

## 6. JWT and Auth Integration (rule #10)

- [ ] 6.1 Verify access token TTL ≤15 minutes
- [ ] 6.2 Verify refresh token rotation with reuse-detection
- [ ] 6.3 Verify HttpOnly cookie, Secure flag, SameSite=Lax
- [ ] 6.4 Validate iss, aud, exp claims on each token decode
- [ ] 6.5 Write verification script: `python -m pytest tests/ -k "jwt" -x --tb=short` and confirm green

## 7. Integration & Final Verification

- [ ] 7.1 Run full test suite: `python -m pytest tests/ -x --tb=short`
- [ ] 7.2 Run `openspec validate --changes --strict` and report result
- [ ] 7.3 Manual E2E: create clinic, add professional, create schedule, attempt overlapping booking (should fail), create block, test policy change scope
- [ ] 7.4 Verify no hardcoded secrets in codebase: `grep -r "SECRET_KEY\|password" backend/ --include="*.py" | grep -v ".env" | grep -v "# "`
- [ ] 7.5 Verify `any` type not used in TypeScript: `npx tsc --noEmit` clean