# Spec Delta — core/patients

## ADDED Requirements

### Requirement: El consentimiento de WhatsApp se registra al cambiar

Todo alta o cambio de `whatsapp_opt_in` de un paciente, por reserva pública o por
el personal, SHALL registrar un consentimiento con su fuente en la misma
transacción. Un paciente creado con `whatsapp_opt_in=false` SHALL NOT generar
consentimiento de WhatsApp.

#### Scenario: Alta con WhatsApp autorizado

- **WHEN** recepción crea un paciente ficticio con `whatsapp_opt_in=true`
- **THEN** persiste con el flag activo y con un consentimiento `opt_in` de fuente
  `reception`

#### Scenario: Alta sin autorización

- **WHEN** recepción crea un paciente sin indicar `whatsapp_opt_in`
- **THEN** persiste con el flag en `false` y sin filas de consentimiento

#### Scenario: Match que otorga opt-in

- **WHEN** una reserva pública reutiliza un paciente existente sin opt-in y el
  paciente acepta WhatsApp
- **THEN** el flag pasa a `true` y se registra un consentimiento `opt_in` de
  fuente `booking`

#### Scenario: Match que no cambia nada

- **WHEN** una reserva pública reutiliza un paciente que ya tiene opt-in
- **THEN** no se agrega ningún consentimiento

#### Scenario: La fusión no hereda el opt-in

- **WHEN** se fusiona un paciente con opt-in en uno sin opt-in
- **THEN** el conservado mantiene su estado de consentimiento y no se crea
  ninguno nuevo
