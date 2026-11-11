# Spec Delta — clinical/evolutions (C-15)

## Purpose
Define las evoluciones clínicas como registros inmutables firmados por el odontólogo, con correcciones agregadas como entradas nuevas (integridad de la historia clínica, Ley 26.529).

## ADDED Requirements

### Requirement: Evolución firmada e inmutable
`POST /api/clinical-records/{record_id}/evolutions` SHALL crear una evolución con `body` (1 a 4000 caracteres tras recortar), `appointment_id` opcional, y SHALL fijar del lado del servidor `professional_id` y `created_by_user_id` (desde el principal), `signed_at` (reloj del servidor) y `content_sha256` (hash del contenido canónico). La firma es **simple** (identidad autenticada + sello + hash) y no es firma digital Ley 25.506. Las filas SHALL ser inmutables.

#### Scenario: Evolución creada
- **WHEN** un odontólogo envía un `body` válido
- **THEN** responde `201` con `signed_at`, `professional_id` del principal y un `content_sha256` de 64 hex que coincide con el recalculado sobre el contenido

#### Scenario: Cuerpo vacío o demasiado largo
- **WHEN** `body` es solo espacios o supera 4000 caracteres
- **THEN** responde `422` y no se crea la evolución

#### Scenario: Inmutabilidad
- **WHEN** se intenta `UPDATE` o `DELETE` sobre `clinical_evolution`, como dueño o con `app_writer`
- **THEN** Postgres lo rechaza

#### Scenario: Reloj del cliente ignorado
- **WHEN** el cuerpo trae `signed_at`
- **THEN** responde `422` (extra='forbid')

#### Scenario: Hash determinista
- **WHEN** se recalcula el hash de una evolución existente desde sus campos
- **THEN** coincide con `content_sha256` almacenado; dos evoluciones con texto distinto tienen hashes distintos

### Requirement: Vínculo con el turno
Si se informa `appointment_id`, SHALL pertenecer a la misma clínica, al mismo paciente de la ficha y, para un odontólogo, a su propio `professional_id`; si no, `422 appointment_mismatch`. Un turno de otra clínica SHALL responder `422 appointment_mismatch` sin revelar su existencia.

#### Scenario: Turno propio del paciente
- **WHEN** el odontólogo vincula un turno suyo de ese paciente
- **THEN** responde `201` y la evolución guarda el `appointment_id`

#### Scenario: Turno de otro paciente
- **WHEN** el turno pertenece a otro paciente de la clínica
- **THEN** responde `422 appointment_mismatch`

#### Scenario: Turno de otro profesional
- **WHEN** un odontólogo vincula un turno de otro profesional
- **THEN** responde `422 appointment_mismatch`

#### Scenario: Turno de otra clínica
- **WHEN** el `appointment_id` es de la clínica B
- **THEN** responde `422 appointment_mismatch`

#### Scenario: Sin turno
- **WHEN** no se informa `appointment_id`
- **THEN** responde `201` con `appointment_id=null`

#### Scenario: Turno cancelado o futuro (TBD, Open Decision 13)
- **WHEN** el odontólogo vincula un turno propio del paciente en estado `cancelled` o con `starts_at` futuro
- **THEN** responde `201` y la evolución guarda el `appointment_id`; el estado del turno no cambia ni se escribe `appointment_event`

### Requirement: Correcciones como entradas nuevas
`POST /api/clinical-records/{record_id}/evolutions/{evolution_id}/corrections` SHALL crear una evolución de tipo `correction` con `corrects_evolution_id`, `reason` (10 a 300 caracteres) y `body`. Solo el autor original SHALL poder corregir; otro principal SHALL recibir `403 not_evolution_author`. La original SHALL seguir visible y ninguna fila SHALL reescribirse. Una corrección de una corrección SHALL apuntar a la entrada corregida. (TBD, Open Decision 4)

#### Scenario: Autor corrige
- **WHEN** el autor corrige su evolución con motivo válido
- **THEN** responde `201`, se crea una fila nueva con `kind=correction` y la original no cambia

#### Scenario: Otro odontólogo intenta corregir
- **WHEN** un odontólogo distinto del autor llama el endpoint
- **THEN** responde `403 not_evolution_author` y no se crea fila

#### Scenario: Motivo faltante
- **WHEN** `reason` tiene 9 caracteres
- **THEN** responde `422`

#### Scenario: Evolución de otra ficha
- **WHEN** `evolution_id` pertenece a otra ficha o clínica
- **THEN** responde `404`

#### Scenario: Correcciones concurrentes
- **WHEN** el autor envía dos correcciones de la misma evolución a la vez
- **THEN** ambas se registran como entradas distintas y la lectura las ordena por `signed_at` y `id`

### Requirement: Listado con cursor
`GET /api/clinical-records/{record_id}/evolutions` SHALL devolver las evoluciones (originales y correcciones, con la marca de cuáles fueron corregidas) por cursor, más recientes primero, con `limit` entre 1 y 100.

#### Scenario: Paginación
- **WHEN** hay 130 evoluciones y se pide `limit=100`
- **THEN** devuelve 100 y `next_cursor`; la segunda página trae 30 sin cursor

#### Scenario: Original corregida
- **WHEN** una evolución tiene una corrección
- **THEN** su ítem trae `corrected_by` con el id de la corrección y sigue mostrando su `body` original

#### Scenario: Filtro por turno
- **WHEN** se pide `appointment_id=X`
- **THEN** solo vuelven las evoluciones ligadas a ese turno

#### Scenario: Límite inválido
- **WHEN** `limit=0` o `limit=101`
- **THEN** responde `422`
