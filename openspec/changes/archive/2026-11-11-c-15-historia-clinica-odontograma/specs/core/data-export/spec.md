# Spec Delta — core/data-export (C-15)

## ADDED Requirements

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
