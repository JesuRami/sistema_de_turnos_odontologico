# Spec Delta — clinical/odontogram (C-15)

## Purpose
Define el odontograma FDI por pieza y cara con estados de catálogo, guardado como historial inmutable del que se deriva el estado vigente.

## ADDED Requirements

### Requirement: Catálogo de estados por clínica
El sistema SHALL ofrecer un catálogo `odontogram_condition` por clínica (código, nombre, categoría, si aplica a cara o a pieza completa, activo), sembrado con un set inicial para toda clínica nueva y existente. `GET /api/odontogram/conditions` SHALL listarlo. Los estados SHALL desactivarse, nunca borrarse. En C-15 el catálogo es de solo lectura por API. (TBD, Open Decision 8)

#### Scenario: Catálogo sembrado
- **WHEN** se crea una clínica nueva o se migra una existente
- **THEN** `GET /api/odontogram/conditions` devuelve el set inicial con códigos únicos por clínica

#### Scenario: Catálogo aislado
- **WHEN** la clínica A lista el catálogo
- **THEN** no aparece ningún estado de la clínica B

### Requirement: Numeración FDI y caras válidas
Cada entrada del odontograma SHALL identificar una pieza FDI válida y una cara. Permanentes: cuadrantes 1 a 4, piezas 1 a 8 (11–48). Temporales: cuadrantes 5 a 8, piezas 1 a 5 (51–85). Caras: `M`, `D`, `O` (oclusal en posteriores, incisal en anteriores), `V`, `L` y `W` (pieza completa). La dentición se SHALL derivar del código de la pieza. Un código o cara inválido SHALL responder `422`. Un estado que aplica solo a pieza completa SHALL exigir cara `W` y uno que aplica solo a cara SHALL rechazar `W`, con `422 condition_scope_mismatch`.

#### Scenario: Pieza permanente válida
- **WHEN** se registra caries en la pieza 36 cara `O`
- **THEN** responde `201` y la dentición derivada es `permanent`

#### Scenario: Pieza temporal válida
- **WHEN** se registra obturación en la pieza 55 cara `D`
- **THEN** responde `201` y la dentición derivada es `deciduous`

#### Scenario: Códigos fuera de rango
- **WHEN** se envían las piezas 19, 49, 56, 86 o 0
- **THEN** responde `422` y no se inserta ninguna fila (el lote entero se rechaza)

#### Scenario: Estado de pieza completa sobre una cara
- **WHEN** se registra "ausente" (solo pieza completa) con cara `O`
- **THEN** responde `422 condition_scope_mismatch`

#### Scenario: Estado de cara sobre pieza completa
- **WHEN** se registra "caries" (solo cara) con cara `W`
- **THEN** responde `422 condition_scope_mismatch`

### Requirement: Registro de hallazgos como eventos append-only
`POST /api/clinical-records/{record_id}/odontogram/events` SHALL aceptar un lote de 1 a 32 entradas `{tooth, surface, condition_id | null, note?}` y SHALL insertarlas en una sola transacción; `condition_id` nulo significa "limpiar" esa pieza y cara. Las filas SHALL ser inmutables, con `created_by_user_id`, `professional_id` e instante del servidor. El `condition_id` SHALL pertenecer a la misma clínica y estar activo, si no `422 condition_not_found` o `422 condition_inactive`.

#### Scenario: Lote de varias caras
- **WHEN** se envían 5 entradas válidas
- **THEN** responde `201`, se insertan 5 filas y un solo evento de acceso del lote

#### Scenario: Lote con una entrada inválida
- **WHEN** 4 entradas son válidas y la quinta usa la pieza 99
- **THEN** responde `422` y no se inserta ninguna

#### Scenario: Lote vacío o excedido
- **WHEN** el lote tiene 0 o 33 entradas
- **THEN** responde `422` sin insertar nada

#### Scenario: Estado de otra clínica o inactivo
- **WHEN** `condition_id` pertenece a otra clínica o está desactivado
- **THEN** responde `422 condition_not_found` o `422 condition_inactive` y no inserta

#### Scenario: Nota demasiado larga
- **WHEN** `note` supera 500 caracteres
- **THEN** responde `422`

#### Scenario: Historial inmutable
- **WHEN** se intenta `UPDATE` o `DELETE` sobre `odontogram_event`, como dueño o con `app_writer`
- **THEN** Postgres lo rechaza

### Requirement: Estado vigente derivado del historial
`GET /api/clinical-records/{record_id}/odontogram?dentition=permanent|deciduous` SHALL devolver, por (pieza, cara), el estado de la **última** entrada (desempate por instante y luego por id); una pieza y cara cuya última entrada es "limpiar" o sin entradas SHALL salir sin estado. La proyección SHALL calcularse desde `odontogram_event`, sin tabla de estado mutable. `GET .../odontogram/teeth/{tooth}/history` SHALL listar el historial de una pieza con paginación por cursor.

#### Scenario: La última entrada gana
- **WHEN** en 36/O se registra caries y luego obturación
- **THEN** el odontograma vigente muestra obturación y el historial de la pieza 36 lista ambas, la más reciente primero

#### Scenario: Limpiar una cara
- **WHEN** después se registra `condition_id=null` en 36/O
- **THEN** el vigente no trae estado en 36/O y el historial conserva las tres entradas

#### Scenario: Dos escrituras simultáneas en la misma cara
- **WHEN** dos odontólogos registran estados distintos en 36/O al mismo tiempo
- **THEN** ambas filas existen y el vigente es el de mayor instante/id, de forma determinista

#### Scenario: Filtro por dentición
- **WHEN** se pide `dentition=deciduous` con hallazgos en 36 y 55
- **THEN** solo aparece la pieza 55

#### Scenario: Paciente sin hallazgos
- **WHEN** la ficha no tiene entradas
- **THEN** responde `200` con todas las caras sin estado

#### Scenario: Pieza inválida en el historial
- **WHEN** se pide el historial de la pieza 99
- **THEN** responde `422`

### Requirement: Vínculo opcional con la evolución
Una entrada del odontograma SHALL poder referenciar una evolución de la misma ficha (`evolution_id`); una evolución de otra ficha o clínica SHALL rechazarse con `422 evolution_not_found`.

#### Scenario: Hallazgo ligado a evolución
- **WHEN** se registra una entrada con el `evolution_id` de una evolución de esa ficha
- **THEN** responde `201` y la entrada guarda el vínculo

#### Scenario: Evolución ajena
- **WHEN** se usa el `evolution_id` de otra ficha
- **THEN** responde `422 evolution_not_found`
