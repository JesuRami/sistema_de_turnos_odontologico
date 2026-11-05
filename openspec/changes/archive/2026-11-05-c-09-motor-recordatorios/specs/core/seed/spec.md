# Spec Delta — core/seed

## ADDED Requirements

### Requirement: Plantillas de notificación por defecto en cada clínica

El seed SHALL crear, al dar de alta una clínica, las plantillas de alta de turno,
72 h, 24 h y 3 h para WhatsApp y su par de email, en `es_AR`, con nombres de
plantilla Meta placeholder y marcadas activas, sin pisar las que el admin haya
editado al re-ejecutarlo.

#### Scenario: Clínica nueva

- **WHEN** se ejecuta el seed sobre una base migrada vacía
- **THEN** la clínica tiene ocho plantillas activas, cuatro por canal, una por paso

#### Scenario: Re-ejecución respeta ediciones

- **WHEN** el admin cambió el texto de una plantilla y se re-ejecuta el seed
- **THEN** la plantilla conserva el texto editado y no se duplica ninguna

#### Scenario: Sin datos reales en las plantillas

- **WHEN** se inspeccionan las plantillas sembradas
- **THEN** solo contienen placeholders de variables y ningún dato personal ni
  teléfono o dirección reales
