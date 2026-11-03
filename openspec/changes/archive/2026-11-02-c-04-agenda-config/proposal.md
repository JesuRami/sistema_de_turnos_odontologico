# Proposal

## Why

This change implements clinic-agenda configuration capabilities (US-001 to US-004), enabling per-clinic customization of professional schedules, chair assignments, time blocks, and business rules. It is needed to support the MVP agenda-first v1.0 functionality where each clinic can define its own working patterns, availability windows, and policies while preventing overlapping schedules and ensuring consistent behavior across the system.

## What Changes

- **New backend endpoints**: GET/POST/PUT for `/professionals`, `/chairs`, `/schedules`, and `/blocks` (admin CRUD; recepción read-only; odontólogo read-only own records)
- **ScheduleRule model**: per (professional, chair, weekday) with validity start/end dates; overlapping rules rejected via EXCLUDE USING gist constraint (RN-AG-05)
- **Block model**: catalog of blocking reasons; at least one objective required (RN-BL-01); writing a block that overlaps existing valid appointments requires explicit resolution in the same transaction (RN-BL-02); historical blocks remain immutable (RN-BL-03); holidays as manual multi-resource blocks (RN-BL-04)
- **Clinic policies**: editable cancellation window (default 24h), reminder steps (72/24/3 h), max double-bookings (default 2), offer expiration (default 4h); policy changes only affect future appointments (US-004 CA-2)
- **Professional/chair deactivation**: prevents new reservations while preserving historical appointment events (US-001 CA-1)
- **Migration 003**: adds `block` table with blocking-reason catalog, policy columns to `clinic` table; adds EXCLUDE constraint on `schedule_rule` (built in C-02)
- **Tests**: overlap detection, block-with-affected-appointments scenarios, policy changes do not touch scheduled jobs

## Capabilities

### New Capabilities

- `agenda/config`: per-clinic agenda configuration — professionals, chairs, schedules, blocks, rules, and policies. Owns related requirements as the system evolves. Includes: schedule-rule non-overlap, block catalog, policy mutation guards, deactivation behavior.

### Modified Capabilities

- (none at this time — all requirements are new to this change)

## Impact

- Backend: FastAPI routers for agenda config; Pydantic v2 schemas with `extra='forbid'` at edges; SQLAlchemy 2.x async models with Alembic migration 003
- Database: PostgreSQL 15 — `schedule_rule` table (built in C-02) with EXCLUDE USING gist on (professional, chair, weekday) tstzrange; new `block` table; policy columns on `clinic`
- No API changes for patient-facing flows; admin/recepción/odontólogo UI adjustments only
- Migration must follow rule #3 (Alembic-only, DDL in 3 steps: CONCURRENTLY NOT VALID → VALIDATE)
- Tests use real Postgres container; no DB mocks (rule #9)
- JWT access ≤15 min, refresh rotating with reuse-detection, HttpOnly cookie (rule #10)
- No hardcoded secrets — all via .env.example (rule #6)