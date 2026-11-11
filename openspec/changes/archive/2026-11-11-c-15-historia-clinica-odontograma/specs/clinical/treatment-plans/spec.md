# Spec Delta — clinical/treatment-plans (C-15)

## Purpose
Define el plan de tratamiento y presupuesto por fases como versiones inmutables con decisión registrada y exportación a PDF.

## ADDED Requirements

### Requirement: Plan con versiones inmutables y fases
`POST /api/clinical-records/{record_id}/treatment-plans` SHALL crear un plan (`title` 3 a 120 caracteres) con su versión 1, y `POST .../treatment-plans/{plan_id}/versions` SHALL crear la versión N+1 con `expected_version`. Cada versión SHALL tener de 1 a 10 fases numeradas consecutivamente desde 1 y de 1 a 50 ítems en total, cada ítem con descripción (3 a 200 caracteres), cantidad entera ≥ 1, precio unitario en centavos de ARS entero ≥ 0, y pieza FDI y cara opcionales (validadas como en el odontograma). Las versiones e ítems SHALL ser inmutables. (TBD, Open Decision 12)

#### Scenario: Plan con dos fases
- **WHEN** se crea un plan con la fase 1 (2 ítems) y la fase 2 (1 ítem)
- **THEN** responde `201` con versión 1 y los ítems agrupados por fase

#### Scenario: Nueva versión conserva la anterior
- **WHEN** se crea la versión 2 con un precio distinto
- **THEN** la versión 1 conserva sus importes y la 2 es la vigente

#### Scenario: Versión desactualizada
- **WHEN** dos requests crean versión con `expected_version=1` a la vez
- **THEN** uno responde `201` y el otro `409 version_conflict`

#### Scenario: Fases no consecutivas
- **WHEN** el plan trae las fases 1 y 3
- **THEN** responde `422 invalid_phases` y no se crea nada

#### Scenario: Límites
- **WHEN** se envían 0 ítems, 51 ítems o 11 fases
- **THEN** responde `422`

#### Scenario: Importes inválidos
- **WHEN** un precio es negativo, decimal o la cantidad es 0
- **THEN** responde `422`

#### Scenario: Pieza o cara inválida
- **WHEN** un ítem trae la pieza 99
- **THEN** responde `422`

#### Scenario: Inmutabilidad
- **WHEN** se intenta `UPDATE` o `DELETE` sobre `treatment_plan_version`, `treatment_plan_item` o `treatment_plan_decision`, como dueño o con `app_writer`
- **THEN** Postgres lo rechaza

### Requirement: Totales calculados por el servidor
El subtotal por fase y el total de la versión SHALL calcularse en el servidor como la suma de `cantidad × precio unitario` en centavos y devolverse en la respuesta y en el PDF; el cliente no SHALL poder enviarlos.

#### Scenario: Totales correctos
- **WHEN** fase 1 = 2 × 15000 y 1 × 5000, fase 2 = 1 × 80000 (centavos)
- **THEN** subtotal fase 1 = 35000, fase 2 = 80000 y total = 115000

#### Scenario: Total enviado por el cliente
- **WHEN** el cuerpo incluye `total_cents`
- **THEN** responde `422` (extra='forbid')

#### Scenario: Desbordamiento
- **WHEN** la suma superaría el máximo de un bigint
- **THEN** responde `422 amount_too_large` sin crear nada

### Requirement: Decisión sobre una versión
`POST .../treatment-plans/{plan_id}/versions/{version}/decision` SHALL registrar `accepted` o `rejected` (con `note` opcional ≤ 300) en `treatment_plan_decision`, append-only. Solo la última versión SHALL poder decidirse y una versión ya decidida SHALL responder `409 version_already_decided`. Crear una versión nueva SHALL dejar la anterior sin decisión vigente.

#### Scenario: Aceptación
- **WHEN** el odontólogo registra `accepted` sobre la última versión
- **THEN** responde `201` y el detalle del plan muestra esa versión como aceptada

#### Scenario: Versión vieja
- **WHEN** se intenta decidir la versión 1 habiendo una versión 2
- **THEN** responde `409 version_superseded`

#### Scenario: Doble decisión
- **WHEN** se decide dos veces la misma versión (también en paralelo)
- **THEN** una sola decisión existe y la otra recibe `409 version_already_decided`

#### Scenario: Valor inválido
- **WHEN** `decision` es `pending`
- **THEN** responde `422`

### Requirement: Exportación a PDF
`GET .../treatment-plans/{plan_id}/versions/{version}/pdf` SHALL generar al vuelo un PDF con el nombre de la clínica, el nombre del paciente, las fases, ítems, subtotales, total y la fecha de emisión (zona horaria de la clínica), con `Content-Type: application/pdf`, `Content-Disposition: attachment` y `Cache-Control: no-store`. El PDF no SHALL persistirse, no SHALL incluir DNI ni teléfono y no SHALL indicar vigencia ni descuentos. El documento no es una factura. (TBD, Open Decision 6)

#### Scenario: PDF válido
- **WHEN** se exporta la versión 1 del plan con totales de 115000 centavos
- **THEN** responde `200`, el cuerpo empieza con `%PDF-`, y su texto extraído contiene el total "1.150,00" y los títulos de las fases

#### Scenario: Sin datos sensibles extra
- **WHEN** el paciente tiene DNI y teléfono cargados
- **THEN** el texto extraído del PDF no los contiene

#### Scenario: Versión inexistente
- **WHEN** se pide la versión 9
- **THEN** responde `404`

#### Scenario: Fecha de emisión en la zona de la clínica
- **WHEN** se exporta a las 23:30 hora de Buenos Aires del 10/11 (02:30 UTC del 11/11)
- **THEN** el PDF muestra la fecha de emisión "10/11/2026" (RN-GL-03)

#### Scenario: Auditoría del export
- **WHEN** se exporta el PDF
- **THEN** existe un `clinical_access_event` `plan_pdf_export` con el plan y la versión

#### Scenario: Nombres con caracteres especiales
- **WHEN** el paciente sintético se llama "Ñandú Pérez Ficticio" y un ítem lleva "Cóndilo/Ø"
- **THEN** el PDF se genera sin error y el texto conserva los acentos

### Requirement: Listado y detalle
`GET .../treatment-plans` SHALL listar los planes de la ficha con su última versión, total y decisión vigente, por cursor; `GET .../treatment-plans/{plan_id}` SHALL devolver todas las versiones con sus decisiones.

#### Scenario: Listado
- **WHEN** la ficha tiene 3 planes
- **THEN** el listado trae 3 con `latest_version`, `total_cents` y `decision` (o `null`)

#### Scenario: Plan de otra ficha
- **WHEN** se pide un `plan_id` de otra ficha o clínica
- **THEN** responde `404`
