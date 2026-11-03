# Spec Delta — core/patients

## ADDED Requirements

### Requirement: Consulta de un paciente por el personal

Admin y recepción SHALL consultar un paciente de su clínica por id, incluido
uno archivado, con la indicación de en qué paciente fue fusionado si
corresponde. Un paciente de otra clínica o inexistente SHALL responder `404
not_found`. El odontólogo SHALL NOT acceder.

#### Scenario: Paciente de la clínica

- **WHEN** recepción pide un paciente ficticio de su clínica
- **THEN** recibe nombre, contacto, opt-in y `merged_into_patient_id` nulo

#### Scenario: Paciente de otra clínica

- **WHEN** un admin de la clínica B pide un paciente de la clínica A
- **THEN** responde `404 not_found`

#### Scenario: Odontólogo

- **WHEN** un odontólogo pide un paciente por id
- **THEN** responde `403 forbidden_role`

### Requirement: Fusión de pacientes duplicados sin borrado

Admin y recepción SHALL fusionar un paciente duplicado en otro de la misma
clínica. El duplicado SHALL quedar archivado y apuntando al conservado; sus
turnos de cualquier estado SHALL pasar al conservado; los datos de contacto
vacíos del conservado SHALL completarse con los del duplicado. Todo SHALL
ocurrir en una transacción y ninguna ficha SHALL borrarse.

#### Scenario: Fusión con turnos

- **WHEN** recepción fusiona un duplicado con 2 turnos (uno cancelado) en el paciente conservado
- **THEN** responde 200 con 2 turnos movidos, ambos turnos quedan del conservado y el duplicado queda archivado

#### Scenario: Completar contacto faltante

- **WHEN** el conservado no tiene email y el duplicado sí
- **THEN** el conservado queda con el email del duplicado y conserva su teléfono

#### Scenario: Duplicado sin turnos

- **WHEN** se fusiona un duplicado sin turnos
- **THEN** responde 200 con 0 turnos movidos y el duplicado queda archivado

### Requirement: La fusión valida sus fichas

La fusión SHALL rechazar con `422 invalid_merge` fusionar un paciente consigo
mismo, con uno archivado o ya fusionado, o con uno de otra clínica (sin revelar
si existe). Una request con campos desconocidos SHALL responder 422.

#### Scenario: Mismo paciente

- **WHEN** se pide fusionar un paciente consigo mismo
- **THEN** responde `422 invalid_merge` y nada cambia

#### Scenario: Paciente ya fusionado

- **WHEN** el duplicado ya fue fusionado antes
- **THEN** responde `422 invalid_merge`

#### Scenario: Conservado de otra clínica

- **WHEN** el paciente a conservar es de otra clínica
- **THEN** responde `422 invalid_merge` igual que si no existiera

### Requirement: La fusión queda auditada

Cada fusión SHALL registrar en una auditoría append-only el actor, ambos
pacientes, los ids de turnos movidos y los campos de contacto completados, sin
nombre, teléfono ni email en el registro. Cada turno movido SHALL registrar su
propio evento con el paciente anterior y el nuevo. La base SHALL rechazar
UPDATE y DELETE sobre esa auditoría.

#### Scenario: Registro de la fusión

- **WHEN** se completa una fusión con 2 turnos movidos
- **THEN** existe un registro de fusión con ambos ids y los 2 turnos, y cada turno tiene un evento `updated` con `patient_id` anterior y nuevo

#### Scenario: Auditoría inmutable

- **WHEN** se ejecuta un UPDATE o DELETE sobre un registro de fusión
- **THEN** la base lo rechaza con error

### Requirement: Un paciente fusionado deja de usarse

Un paciente fusionado SHALL NOT aparecer en la búsqueda ni aceptarse en turnos
nuevos, igual que un archivado.

#### Scenario: Turno para un fusionado

- **WHEN** recepción crea un turno para el paciente fusionado
- **THEN** responde `422 invalid_patient`
