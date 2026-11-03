# Spec Delta — agenda/config

## ADDED Requirements

### Requirement: Un bloqueo no pisa turnos vigentes sin resolución explícita

Crear o editar un bloqueo cuyo rango intersecte turnos `pending` o `confirmed`
de su profesional o sillón SHALL responder `409 block_conflicts` con los ids de
los turnos afectados, salvo que la misma request cancele todos esos turnos con
motivo. La cancelación y el bloqueo SHALL persistir en una sola transacción. El
sistema SHALL NOT mover ni cancelar turnos por su cuenta.

#### Scenario: Bloqueo sobre un turno vigente

- **WHEN** recepción crea un bloqueo del profesional P que cubre un turno
  confirmado de P
- **THEN** responde `409 block_conflicts` con el id del turno y no persiste nada

#### Scenario: Bloqueo con resolución explícita

- **WHEN** un admin crea el mismo bloqueo indicando cancelar ese turno con motivo
  `bloqueo`
- **THEN** responde 201, el turno queda `cancelled` con evento `cancelled` y el
  bloqueo persiste, todo en la misma transacción

#### Scenario: Resolución incompleta

- **WHEN** el bloqueo afecta dos turnos y la request cancela solo uno
- **THEN** responde `409 block_conflicts` con el turno no resuelto y no persiste nada

#### Scenario: Turnos terminados no cuentan

- **WHEN** el rango del bloqueo solo intersecta turnos `cancelled` o `no_show`
- **THEN** el bloqueo persiste sin pedir resolución

#### Scenario: Odontólogo sobre sus propios turnos

- **WHEN** un odontólogo crea un bloqueo propio que pisa un turno suyo e indica
  cancelarlo
- **THEN** responde `403 forbidden_role` (cancelar turnos es de admin o recepción)
