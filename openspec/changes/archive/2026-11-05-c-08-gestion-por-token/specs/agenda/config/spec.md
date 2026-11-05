# Spec Delta — agenda/config

## ADDED Requirements

### Requirement: Teléfono de contacto de la clínica

La clínica SHALL poder guardar un teléfono de contacto (`contact_phone`)
normalizado en E.164, editable solo por admin junto con el resto de sus
políticas, y SHALL exponerlo en las superficies públicas que derivan a la
clínica (RN-ON-04, RN-CX-01). Un teléfono inválido SHALL responderse `422` sin
guardarse.

#### Scenario: Guardar el teléfono de contacto

- **WHEN** un admin guarda un teléfono nacional válido en las políticas de la clínica
- **THEN** queda normalizado en E.164 y se devuelve en las políticas

#### Scenario: Teléfono inválido

- **WHEN** un admin guarda un teléfono inválido
- **THEN** responde `422` y la clínica conserva el valor anterior

#### Scenario: Solo admin

- **WHEN** un usuario con rol recepción intenta cambiar el teléfono de contacto
- **THEN** responde `403 forbidden_role` y el valor no cambia

#### Scenario: La clínica sin teléfono

- **WHEN** una clínica no tiene `contact_phone` y se consulta un token vencido
- **THEN** la vista de contacto muestra la clínica sin teléfono y no falla
