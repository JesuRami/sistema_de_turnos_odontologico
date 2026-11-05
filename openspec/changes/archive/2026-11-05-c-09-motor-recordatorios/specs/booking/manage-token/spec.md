# Spec Delta — booking/manage-token

## MODIFIED Requirements

### Requirement: Resolución del link de gestión por hash

`GET /api/manage/{token}` SHALL resolver el turno, dentro de una sola clínica y
sin sesión ni `Principal`, por una de dos credenciales: el SHA-256 del token
aleatorio contra `appointment.manage_token_hash`, o un token firmado cuya firma
se verifica en tiempo constante. Un token malformado, desconocido o con firma
inválida SHALL responder `404 manage_link_not_found` con el mismo cuerpo, sin
revelar si el turno existe.

#### Scenario: Token válido resuelve su turno

- **WHEN** existe un turno online con el hash del token presentado
- **THEN** responde 200 con la vista de gestión de ese turno

#### Scenario: Token firmado resuelve su turno

- **WHEN** se presenta el token firmado emitido para un turno, incluso de recepción
  que no tiene token aleatorio
- **THEN** responde 200 con la vista de gestión de ese turno

#### Scenario: Token desconocido y token malformado son indistinguibles

- **WHEN** se pide un token aleatorio de 43 caracteres y uno de 10 caracteres
- **THEN** ambos responden `404 manage_link_not_found` con el mismo cuerpo

#### Scenario: Firma alterada

- **WHEN** se presenta un token firmado al que se le cambió un carácter
- **THEN** responde `404 manage_link_not_found` con el mismo cuerpo que un token
  desconocido

#### Scenario: Representación alternativa del mismo token

- **WHEN** se presenta un token firmado válido con el último carácter cambiado de modo que
  decodifica a los mismos bytes
- **THEN** responde `404 manage_link_not_found`, así cada credencial tiene una sola representación

#### Scenario: Token firmado de otro turno

- **WHEN** se usa el token firmado de un turno con la firma de otro
- **THEN** responde `404 manage_link_not_found` y ningún turno cambia

#### Scenario: El token no alcanza otro turno

- **WHEN** la clínica tiene dos turnos online y se usa el token de uno
- **THEN** solo se devuelve ese turno y ningún dato del otro

### Requirement: Invalidación de recordatorios en la misma transacción

Confirmar, cancelar o reprogramar SHALL invocar el punto de invalidación de
recordatorios pendientes dentro de la misma transacción de la mutación, con el
turno y la acción. La implementación SHALL cancelar o recalcular los
`reminder_job` del turno según la acción; si falla, la mutación SHALL revertir.

#### Scenario: Confirmación invalida recordatorios

- **WHEN** se confirma un turno con token
- **THEN** el punto de invalidación recibe ese turno y la acción `confirm` una sola vez

#### Scenario: Confirmación cancela los pasos que piden confirmar

- **WHEN** se confirma con token un turno con jobs 72/24/3 h pendientes
- **THEN** los jobs de 72 h y 24 h quedan `cancelled` y el de 3 h sigue `scheduled`

#### Scenario: Reprogramación invalida y reprograma

- **WHEN** se reprograma un turno con token
- **THEN** el punto de invalidación recibe la acción `reschedule` con el horario nuevo
  y los jobs pendientes se recalculan sobre ese horario

#### Scenario: Cancelación cancela los jobs

- **WHEN** se cancela un turno con token
- **THEN** sus jobs pendientes quedan `cancelled` y la acción se registra una sola vez

#### Scenario: La mutación no depende del canal de recordatorios

- **WHEN** el punto de invalidación es no-op
- **THEN** la confirmación, la cancelación y la reprogramación funcionan igual

#### Scenario: Falla de la invalidación revierte la mutación

- **WHEN** el punto de invalidación falla durante una cancelación por token
- **THEN** el turno conserva su estado y sus jobs siguen `scheduled`

#### Scenario: Acción repetida no duplica efectos

- **WHEN** se repite la confirmación de un turno ya confirmado
- **THEN** los jobs no cambian por segunda vez
