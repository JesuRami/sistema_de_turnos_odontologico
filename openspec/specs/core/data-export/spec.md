# core/data-export Specification

## Purpose

Define la exportación completa de datos de la agenda (turnos, pacientes y auditoría) para el administrador, sin vendor lock-in y con registro de cada exportación.

## Requirements

### Requirement: Exportación completa de datos de agenda

`GET /api/exports/full?format=csv|json` SHALL devolver un ZIP con seis
archivos de la clínica del admin: turnos, pacientes operativos, eventos de
auditoría de turnos, entradas de la lista de espera, ofertas y eventos de la
lista de espera. SHALL leerse por lotes. Solo admin; otros roles `403
forbidden_role`. `format` fuera de `csv|json` SHALL responder `422
invalid_format`.

#### Scenario: Export completo
- **WHEN** el admin exporta en CSV
- **THEN** el ZIP trae `appointments.csv`, `patients.csv`, `appointment_events.csv`, `waiting_list_entries.csv`, `waitlist_offers.csv` y `waitlist_events.csv` con todas las filas de su clínica

#### Scenario: Formato JSON
- **WHEN** el admin exporta en JSON
- **THEN** el ZIP trae los mismos seis conjuntos como `.json`

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

#### Scenario: Lista de espera vacía
- **WHEN** la clínica no tiene entradas en la lista de espera
- **THEN** los tres archivos de la lista vienen solo con encabezados (CSV) o vacíos (JSON)

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

### Requirement: Las exportaciones no incluyen datos clínicos
`GET /api/exports/full` y `GET /api/exports/patients/{patient_id}` SHALL no incluir en ningún archivo datos de las tablas clínicas (ficha, anamnesis, odontograma, evoluciones, adjuntos, planes, bitácora de accesos) ni sus conteos. La portabilidad de la historia clínica queda como follow-up. (TBD, Open Decision 11)

#### Scenario: Exportación completa con ficha cargada
- **WHEN** el admin exporta tras cargarse una ficha con anamnesis, evolución y adjunto sintéticos
- **THEN** el ZIP sigue teniendo los seis conjuntos de C-13 y ninguna cadena clínica sintética aparece en ellos

#### Scenario: Exportación de un paciente con ficha
- **WHEN** el admin exporta el JSON de un paciente con historia clínica
- **THEN** el documento no trae claves clínicas ni el texto sintético cargado

#### Scenario: Recorrido de tablas
- **WHEN** una prueba compara las tablas con `clinic_id` contra las que leen las exportaciones
- **THEN** cada tabla clínica nueva figura en la lista de excluidas y una tabla nueva sin clasificar hace fallar la prueba
