# Spec: Identity - Agenda Configuration

## Purpose

Defines the identity and access control requirements for agenda configuration per clinic and professional, ensuring proper RBAC, token-based patient access, and cross-tenant isolation.

## ADDED Requirements

### Requirement: Patient token access is single-use only

The system SHALL issue a single-use token to patients for appointment reservation, and the token MUST be invalidated after successful use.

#### Scenario: Successful single-use token reservation

- **WHEN** a patient requests an appointment via token
- **THEN** the system reserves the slot, invalidates the token, and returns confirmation

### Requirement: Professional/chair deactivation preserves history

The system SHALL prevent new reservations for a deactivated professional or chair while retaining all historical appointment events.

#### Scenario: Deactivated professional blocks new reservations

- **WHEN** a professional is marked inactive
- **THEN** the system rejects new appointment attempts with a 409 conflict and returns the existing appointment history

### Requirement: Cross-tenant isolation via clinic_id

The system SHALL enforce clinic_id on all operative tables and isolate data by tenant in queries and tests.

#### Scenario: Query isolation across clinics

- **WHEN** a reception user queries appointments for clinic A
- **THEN** the system returns only appointments where clinic_id = 'clinic-a', excluding clinic B data



