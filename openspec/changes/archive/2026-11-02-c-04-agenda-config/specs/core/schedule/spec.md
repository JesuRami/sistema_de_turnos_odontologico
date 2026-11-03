# Spec: Core - Schedule Rules and Blocks

## Purpose

Defines the schedule rule non-overlap constraints, block catalog, and clinic policy requirements for agenda configuration.

## ADDED Requirements

### Requirement: Schedule rule non-overlap constraint

The system SHALL reject overlapping ScheduleRule entries for the same (professional, chair, weekday) combination using a GIST exclusion constraint on tstzrange.

#### Scenario: Overlapping schedule rules rejected

- **WHEN** a new ScheduleRule is created with a validity period that overlaps an existing active rule for the same professional, chair, and weekday
- **THEN** the system rejects the insertion with a 409 Conflict error and suggests alternative time slots

### Requirement: Block requires at least one objective

The system SHALL require at least one objective (purpose) when creating a Block, and reject blocks with empty objectives.

#### Scenario: Block creation with objective

- **WHEN** a user creates a Block with at least one objective specified
- **THEN** the system accepts the Block and associates it with the specified resources

### Requirement: Policy window changes affect only future appointments

The system SHALL ensure that clinic policy changes (cancellation window, reminder steps, max double-bookings, offer expiration) only affect appointments scheduled after the policy change.

#### Scenario: Policy change does not affect past appointments

- **WHEN** a clinic policy is updated (e.g., cancellation window changed from 24h to 48h)
- **THEN** existing appointments retain their original policy, and only new appointments respect the updated policy

### Requirement: Block catalog with valid blocking reasons

The system SHALL provide a catalog of valid blocking reasons for the Block model, and reject blocks with invalid or missing reasons.

#### Scenario: Block created with valid reason

- **WHEN** a user creates a Block with a valid blocking reason from the catalog
- **THEN** the system accepts the Block and stores the reason code

