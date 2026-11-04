# Spec Delta — agenda/appointments

## ADDED Requirements

### Requirement: Turno online con token de gestión hasheado

Todo turno con origen `online` SHALL tener un hash de token de gestión de 32
bytes, único entre todos los turnos; la base SHALL rechazar un turno online sin
hash, un hash de otra longitud o un hash repetido. Los turnos de recepción SHALL
poder no tenerlo.

#### Scenario: Turno online sin hash

- **WHEN** se inserta directamente un turno `origin=online` sin hash de token
- **THEN** la base rechaza la fila con violación de CHECK

#### Scenario: Hash repetido

- **WHEN** se insertan dos turnos con el mismo hash de token
- **THEN** la base rechaza el segundo con violación de unicidad

#### Scenario: Turno de recepción sin token

- **WHEN** recepción crea un turno
- **THEN** persiste sin hash de token
