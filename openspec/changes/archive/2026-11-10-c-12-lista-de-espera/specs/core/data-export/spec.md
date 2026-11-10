# Spec Delta — core/data-export

## MODIFIED Requirements

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
