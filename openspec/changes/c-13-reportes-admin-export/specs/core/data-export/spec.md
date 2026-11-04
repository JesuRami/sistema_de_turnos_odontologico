# Spec Delta — core/data-export

## ADDED Requirements

### Requirement: Exportación completa de datos de agenda

`GET /api/exports/full?format=csv|json` SHALL devolver un ZIP con tres
archivos de la clínica del admin: turnos, pacientes operativos y eventos de
auditoría de turnos. SHALL leerse por lotes. Solo admin; otros roles `403
forbidden_role`. `format` fuera de `csv|json` SHALL responder `422
invalid_format`.

#### Scenario: Export completo
- **WHEN** el admin exporta en CSV
- **THEN** el ZIP trae `appointments.csv`, `patients.csv` y `appointment_events.csv` con todas las filas de su clínica

#### Scenario: Formato JSON
- **WHEN** el admin exporta en JSON
- **THEN** el ZIP trae los mismos tres conjuntos como `.json`

#### Scenario: Sin datos de otra clínica
- **WHEN** existen datos de otra clínica
- **THEN** ninguna fila del ZIP les pertenece

#### Scenario: Pacientes archivados y fusionados
- **WHEN** hay pacientes archivados o fusionados
- **THEN** se exportan con `archived_at` y `merged_into_patient_id`

#### Scenario: Fórmulas en CSV
- **WHEN** un nombre ficticio empieza con `=`
- **THEN** la celda se exporta prefijada con `'`

#### Scenario: Recepción exporta
- **WHEN** recepción llama el endpoint
- **THEN** responde `403 forbidden_role`

### Requirement: Traza de cada exportación

Cada exportación exitosa SHALL registrar un evento `data_exported` en
`auth_event` con actor, formato y conteos por archivo, sin datos de pacientes
en el payload.

#### Scenario: Evento registrado
- **WHEN** el admin completa una exportación
- **THEN** existe un `auth_event` `data_exported` con su `user_id` y los conteos

#### Scenario: Sin PII en logs ni payload
- **WHEN** se inspecciona el evento y los logs de la request
- **THEN** no aparecen nombres, teléfonos ni emails
