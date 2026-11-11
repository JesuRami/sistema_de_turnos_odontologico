# Spec Delta — core/patients (C-15)

## ADDED Requirements

### Requirement: La fusión se rechaza si el paciente absorbido tiene ficha clínica
Fusionar un paciente en otro SHALL responder `409 patient_has_clinical_record` si el paciente absorbido tiene ficha clínica, sin modificar ninguna fila; fusionar un paciente sin ficha SHALL seguir como en C-06. La unificación de historias clínicas queda diferida. (TBD, Open Decision 10)

#### Scenario: Absorbido con ficha
- **WHEN** se intenta fusionar un paciente con ficha clínica en otro
- **THEN** responde `409 patient_has_clinical_record` y ni `patient`, `patient_merge` ni las tablas clínicas cambian

#### Scenario: Destino con ficha, origen sin ficha
- **WHEN** el paciente absorbido no tiene ficha y el destino sí
- **THEN** la fusión procede y la ficha del destino no cambia

#### Scenario: Sin fichas
- **WHEN** ninguno tiene ficha
- **THEN** la fusión se comporta exactamente como en C-06

#### Scenario: Ficha abierta durante la fusión
- **WHEN** se abre la ficha del absorbido en paralelo con su fusión
- **THEN** o la fusión responde `409 patient_has_clinical_record`, o la apertura responde `409 patient_archived`; nunca quedan ambas
