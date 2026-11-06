# Spec Delta — reminders/channel-consent

## ADDED Requirements

### Requirement: Baja por respuesta de WhatsApp

Una baja pedida por WhatsApp SHALL registrarse como `opt_out` de WhatsApp con
fuente `whatsapp_reply`, sin usuario, con el mismo efecto inmediato sobre los
jobs pendientes que cualquier otra baja.

#### Scenario: Baja desde el chat

- **WHEN** el webhook procesa un "STOP" de un paciente con opt-in y dos jobs de
  WhatsApp `scheduled`
- **THEN** existe una fila `whatsapp / opt_out / whatsapp_reply`, el flag pasa a
  `false` y ambos jobs quedan `skipped` con motivo `no_consent`

### Requirement: El personal cambia el consentimiento de un paciente

`PUT /api/patients/{id}/consent/{channel}` SHALL permitir a admin y recepción
registrar `opt_in` u `opt_out` de un paciente de su clínica, con fuente
`reception` y el usuario que lo hizo. El odontólogo SHALL recibir `403
forbidden_role`; un paciente de otra clínica o fusionado, `404`.

#### Scenario: Recepción registra una baja

- **WHEN** recepción registra `opt_out` de WhatsApp de un paciente con opt-in
- **THEN** existe una fila `whatsapp / opt_out / reception` con su usuario y el
  flag pasa a `false`

#### Scenario: Cambio redundante

- **WHEN** recepción registra `opt_in` de un paciente que ya lo tiene
- **THEN** responde 200 con el estado vigente y no agrega fila

#### Scenario: Opt-in sin teléfono

- **WHEN** recepción registra `opt_in` de WhatsApp de un paciente sin teléfono
- **THEN** responde `422 phone_required` y no agrega fila

#### Scenario: Paciente de otra clínica

- **WHEN** recepción de la clínica A usa el id de un paciente de la clínica B
- **THEN** responde `404` sin revelar que existe

#### Scenario: Odontólogo

- **WHEN** un odontólogo llama al endpoint
- **THEN** responde `403 forbidden_role`
