# reminders/channel-consent Specification

## Purpose
Registra de forma auditable el consentimiento de cada paciente por canal
(WhatsApp, email) y lo hace efectivo de inmediato sobre los recordatorios: sin
opt-in vigente no se envía nada por WhatsApp (RN-WA-01).

## Requirements

### Requirement: Consentimiento append-only con fuente

Cada cambio de consentimiento SHALL agregar una fila en `consent` con paciente,
canal (`whatsapp` o `email`), estado (`opt_in` u `opt_out`), fuente (`booking`,
`whatsapp_reply`, `reception` o `legacy`), instante y, si lo hizo personal, el
usuario. La tabla SHALL ser append-only en la base y llevar `clinic_id`.

#### Scenario: Opt-in en la reserva

- **WHEN** un paciente reserva online con consentimiento de WhatsApp
- **THEN** existe una fila `whatsapp / opt_in / booking` para ese paciente

#### Scenario: Opt-in cargado por recepción

- **WHEN** recepción da de alta un paciente con WhatsApp autorizado
- **THEN** existe una fila `whatsapp / opt_in / reception` con el usuario que la cargó

#### Scenario: Inmutabilidad

- **WHEN** se intenta modificar o borrar una fila de `consent`
- **THEN** la base lo rechaza

### Requirement: Un único escritor mantiene el estado vigente

El estado vigente por paciente y canal SHALL ser el de la última fila de
`consent`, y `patient.whatsapp_opt_in` SHALL reflejarlo. Ambos SHALL cambiar
juntos en una misma transacción; ningún otro camino SHALL escribir
`whatsapp_opt_in`.

#### Scenario: Cambio consistente

- **WHEN** se registra un `opt_out` de WhatsApp
- **THEN** `patient.whatsapp_opt_in` pasa a `false` en la misma transacción

#### Scenario: Registro redundante

- **WHEN** se registra un `opt_in` de un paciente que ya tiene opt-in vigente
- **THEN** no se agrega fila y el estado no cambia

#### Scenario: Reversión conjunta

- **WHEN** falla la transacción que registra el consentimiento
- **THEN** ni `consent` ni `patient.whatsapp_opt_in` cambian

### Requirement: Sin opt-in no hay envío por WhatsApp

El motor SHALL NOT enviar ningún mensaje por WhatsApp a un paciente sin opt-in
vigente. La baja SHALL tener efecto inmediato sobre los jobs pendientes de ese
paciente.

#### Scenario: Paciente nunca autorizó

- **WHEN** existe un job de WhatsApp de un paciente sin ninguna fila de consentimiento
- **THEN** el job no se envía y queda `skipped`

#### Scenario: Baja con jobs pendientes

- **WHEN** se registra un `opt_out` de WhatsApp de un paciente con dos jobs
  `scheduled`
- **THEN** ambos quedan `skipped` con motivo `no_consent` en la misma transacción

#### Scenario: Reactivación

- **WHEN** un paciente con `opt_out` vuelve a dar `opt_in`
- **THEN** los jobs ya `skipped` no se reviven ni se envían

### Requirement: El email es respaldo con baja simple

El canal de email SHALL permitir el envío salvo que el paciente tenga un
`opt_out` vigente de email, y solo cuando el paciente tenga una dirección
cargada.

#### Scenario: Email sin registro de consentimiento

- **WHEN** un paciente con email y sin filas de consentimiento de email recibe un
  escalado
- **THEN** el email se envía

#### Scenario: Baja de email

- **WHEN** el paciente tiene `opt_out` de email vigente
- **THEN** el job de email queda `skipped` con motivo `no_consent`

### Requirement: Backfill del consentimiento previo

La migración SHALL registrar un `opt_in` de WhatsApp con fuente `legacy` para
cada paciente existente con `whatsapp_opt_in = true`, de modo que el estado
vigente sea derivable de `consent` desde el primer día.

#### Scenario: Paciente previo a C-09

- **WHEN** se aplica la migración sobre una base con un paciente con
  `whatsapp_opt_in = true`
- **THEN** existe una fila `whatsapp / opt_in / legacy` para él y el flag no cambia

### Requirement: Aislamiento por clínica del consentimiento

`consent` SHALL referenciar al paciente por clave compuesta con la clínica; el
consentimiento de un paciente de una clínica SHALL NOT afectar a otra.

#### Scenario: Paciente de otra clínica

- **WHEN** se intenta insertar un consentimiento con `clinic_id` B y el paciente
  de la clínica A
- **THEN** la base lo rechaza por la clave foránea compuesta

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
