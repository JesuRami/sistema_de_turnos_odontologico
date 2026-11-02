# core/tenancy Specification

## Purpose
Garantiza la partición lógica por clínica (`clinic_id`) en todo dato operativo,
de modo que ninguna fila pueda verse ni referenciarse desde otra clínica y la
consolidación multi-tenant futura (DD-07) sea mecánica.

## Requirements

### Requirement: clinic_id obligatorio en toda tabla operativa

Toda tabla operativa SHALL tener `clinic_id` NOT NULL con FK a `clinic`. Una
inserción sin `clinic_id` SHALL ser rechazada por la base de datos, no solo por
la aplicación.

#### Scenario: Inserción sin clínica rechazada por la DB

- **WHEN** se inserta un `professional`, `chair`, `schedule_rule`, `patient` o
  `user` con `clinic_id` nulo directamente en Postgres
- **THEN** la base rechaza la fila con violación NOT NULL y no queda nada
  persistido

#### Scenario: Clínica inexistente rechazada

- **WHEN** se inserta una fila operativa con un `clinic_id` que no existe
- **THEN** la base rechaza la fila con violación de FK

### Requirement: Referencias intra-tenant no cruzan clínicas

Toda referencia entre tablas operativas SHALL resolverse dentro de la misma
clínica: la base SHALL rechazar una fila que referencie un profesional o
sillón perteneciente a otra clínica.

#### Scenario: Usuario odontólogo apuntando a profesional ajeno

- **WHEN** se crea un `user` de la clínica A con `professional_id` de un
  profesional de la clínica B
- **THEN** la base rechaza la fila con violación de FK y el usuario no existe

#### Scenario: Plantilla semanal con sillón de otra clínica

- **WHEN** se crea una `schedule_rule` de la clínica A con profesional de A y
  `chair_id` de un sillón de la clínica B
- **THEN** la base rechaza la fila con violación de FK

### Requirement: Consultas de dominio aisladas por clínica

Toda consulta de dominio expuesta por los servicios SHALL filtrar por la
clínica solicitante y NUNCA devolver filas de otra clínica.

#### Scenario: Aislamiento cross-tenant por tabla

- **WHEN** existen dos clínicas A y B con filas en `professional`, `chair`,
  `schedule_rule`, `patient` y `user`, y se consulta cada recurso para A
- **THEN** el resultado contiene solo filas de A y ninguna de B

#### Scenario: Match de paciente no cruza clínicas

- **WHEN** A y B tienen pacientes con el mismo teléfono E.164 y se busca ese
  teléfono en A
- **THEN** solo se devuelven los pacientes de A

### Requirement: Migración única y reversible del modelo core

El esquema core SHALL crearse con una única revisión Alembic posterior a la
base de C-01, aplicable sobre una DB vacía y reversible sin residuos de tablas
ni tipos del change.

#### Scenario: Ciclo upgrade-downgrade-upgrade limpio

- **WHEN** se ejecuta `upgrade head`, luego `downgrade` a la base de C-01 y
  otra vez `upgrade head` contra Postgres 15 real
- **THEN** los tres pasos terminan sin error y el esquema final es idéntico al
  del primer `upgrade`

#### Scenario: Downgrade no deja residuos

- **WHEN** se hace `downgrade` a la base de C-01
- **THEN** no quedan tablas ni tipos enum creados por el change
