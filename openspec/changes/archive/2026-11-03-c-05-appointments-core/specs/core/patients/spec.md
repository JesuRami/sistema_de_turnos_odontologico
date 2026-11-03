# Spec Delta — core/patients

## ADDED Requirements

### Requirement: Búsqueda de pacientes por el personal

Admin y recepción SHALL buscar pacientes no archivados de su clínica con un
único término: si es un teléfono válido SHALL aplicarse el match por teléfono
normalizado; si no, SHALL buscarse por similitud de nombre. El resultado SHALL
tener como máximo 20 pacientes. El odontólogo SHALL NOT acceder a la búsqueda.

#### Scenario: Búsqueda por nombre aproximado

- **WHEN** existe la paciente ficticia `Ana Prueba Ejemplo` y recepción busca `ana prueba`
- **THEN** la respuesta la incluye

#### Scenario: Búsqueda por teléfono en formato nacional

- **WHEN** un paciente tiene un E.164 ficticio y se busca el mismo número en formato nacional
- **THEN** la respuesta lo incluye

#### Scenario: Término demasiado corto

- **WHEN** se busca con menos de 3 caracteres
- **THEN** responde `422 query_too_short`

#### Scenario: Odontólogo busca pacientes

- **WHEN** un odontólogo envía `GET /api/patients?q=...`
- **THEN** responde `403 forbidden_role`

### Requirement: Alta rápida de paciente por el personal

Admin y recepción SHALL dar de alta un paciente con nombre y al menos un
contacto; el teléfono SHALL normalizarse a E.164. Un paciente con el mismo
teléfono y el mismo nombre normalizado SHALL rechazarse con `409
patient_duplicate` y el id existente; mismo teléfono con otro nombre SHALL
aceptarse (familias).

#### Scenario: Alta con nombre y teléfono

- **WHEN** recepción crea un paciente ficticio con nombre y teléfono nacional
- **THEN** responde 201 con el teléfono en E.164 y `whatsapp_opt_in=false` salvo indicación

#### Scenario: Duplicado exacto

- **WHEN** ya existe un paciente con ese teléfono y el mismo nombre en otro uso de mayúsculas
- **THEN** responde `409 patient_duplicate` con el id del existente

#### Scenario: Familia que comparte teléfono

- **WHEN** se crea otro paciente con el mismo teléfono y distinto nombre
- **THEN** responde 201

#### Scenario: Errores sin datos personales

- **WHEN** el alta falla por teléfono inválido
- **THEN** responde 422 y ni la respuesta ni los logs contienen el teléfono enviado
