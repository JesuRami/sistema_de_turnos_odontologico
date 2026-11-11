# clinical/patient-record Specification

## Purpose
Define la ficha clínica por paciente y su anamnesis versionada, enganchadas al `patient_id` estable de la agenda sin modificar tablas existentes (DD-02).

## Requirements

### Requirement: Apertura idempotente de la ficha clínica
`POST /api/patients/{patient_id}/clinical-record` SHALL abrir la ficha del paciente si no existe (`201`) o devolver la existente (`200`), con a lo sumo una ficha por (`clinic_id`, `patient_id`). Un paciente archivado o fusionado SHALL responder `409 patient_archived`.

#### Scenario: Primera apertura
- **WHEN** un odontólogo con alcance abre la ficha de un paciente sin ficha
- **THEN** responde `201` con `record_id`, se crea una fila de `clinical_record` y un evento de acceso `record_open`

#### Scenario: Apertura repetida
- **WHEN** se llama dos veces seguidas
- **THEN** la segunda responde `200` con el mismo `record_id` y sigue existiendo una sola fila

#### Scenario: Apertura simultánea
- **WHEN** dos requests abren la ficha del mismo paciente a la vez
- **THEN** ambos responden `200` o `201` con el mismo `record_id` y la base conserva una sola fila (UNIQUE `(clinic_id, patient_id)`)

#### Scenario: Paciente archivado
- **WHEN** se abre la ficha de un paciente fusionado en otro
- **THEN** responde `409 patient_archived` y no se crea ninguna fila

### Requirement: Consulta de la ficha
`GET /api/patients/{patient_id}/clinical-record` SHALL devolver `record_id`, la anamnesis vigente (si hay) y los conteos de evoluciones, adjuntos activos y planes; sin ficha abierta SHALL responder `404 clinical_record_not_opened`.

#### Scenario: Ficha con contenido
- **WHEN** la ficha tiene 2 versiones de anamnesis, 3 evoluciones y 1 adjunto dado de baja
- **THEN** la respuesta trae la anamnesis `version=2`, `evolutions_count=3` y `attachments_count=0`

#### Scenario: Ficha no abierta
- **WHEN** el paciente existe pero no tiene ficha
- **THEN** responde `404 clinical_record_not_opened`

### Requirement: Anamnesis versionada e inmutable
`POST /api/clinical-records/{record_id}/anamnesis` SHALL crear la versión N+1 con `expected_version` (0 para la primera) y los campos estructurados (alergias, medicación, condiciones sistémicas, embarazo, tabaquismo, anticoagulantes, observaciones ≤ 1000 caracteres). Si `expected_version` no coincide con la última versión SHALL responder `409 version_conflict` sin crear nada. Las versiones SHALL ser inmutables y `GET /api/clinical-records/{record_id}/anamnesis/versions` SHALL listarlas.

#### Scenario: Primera versión
- **WHEN** se guarda la anamnesis con `expected_version=0`
- **THEN** responde `201` con `version=1` y `created_by_user_id`, y se inserta un evento de acceso

#### Scenario: Corrección crea nueva versión
- **WHEN** se guarda con `expected_version=1` cambiando una alergia
- **THEN** existe la versión 2, la versión 1 conserva su contenido original y `GET` devuelve la 2 como vigente

#### Scenario: Versión desactualizada
- **WHEN** dos odontólogos leen la versión 1 y ambos guardan con `expected_version=1`
- **THEN** uno obtiene `201` (versión 2), el otro `409 version_conflict`, y no existe versión 3

#### Scenario: Observaciones demasiado largas
- **WHEN** `observations` tiene 1001 caracteres
- **THEN** responde `422` y no se crea versión

#### Scenario: Campos desconocidos
- **WHEN** el cuerpo trae un campo no definido
- **THEN** responde `422` (extra='forbid')

#### Scenario: Anamnesis vacía
- **WHEN** se guarda con todas las condiciones en `false` y listas vacías
- **THEN** responde `201` con `version=1`

#### Scenario: Versiones inmutables
- **WHEN** se intenta `UPDATE` o `DELETE` sobre `anamnesis_version`, como dueño del schema o con `app_writer`
- **THEN** Postgres lo rechaza

### Requirement: Paciente archivado: lectura sí, escritura no
Toda escritura clínica (anamnesis, odontograma, evolución, corrección, adjunto, baja, plan, versión, decisión) sobre la ficha de un paciente archivado SHALL responder `409 patient_archived` sin insertar filas ni eventos; las lecturas SHALL seguir permitidas y auditadas. (TBD, Open Decision 13)

#### Scenario: Escritura sobre paciente archivado
- **WHEN** se archiva un paciente con ficha y un odontólogo intenta `POST` de evolución
- **THEN** responde `409 patient_archived` y el conteo de `clinical_evolution` no cambia

#### Scenario: Lectura sobre paciente archivado
- **WHEN** el mismo odontólogo lee la ficha
- **THEN** responde `200` y se inserta un evento `record_read`
