# Spec Delta — clinical/attachments (C-15)

## Purpose
Define los adjuntos clínicos (fotos, radiografías, documentos): metadatos en la base, bytes tras una abstracción de almacenamiento, descarga solo autenticada y baja lógica sin borrado físico.

## ADDED Requirements

### Requirement: Subida validada de adjuntos
`POST /api/clinical-records/{record_id}/attachments` (multipart) SHALL aceptar un archivo de hasta 10 MiB, de tipo `image/jpeg`, `image/png` o `application/pdf`, con `kind` (`xray`, `photo`, `document`, `other`) y `evolution_id` opcional. El tipo SHALL verificarse por los primeros bytes del contenido, no por el `Content-Type` declarado ni la extensión. SHALL guardar `size_bytes`, `sha256`, el nombre original saneado (solo para mostrar) y un `storage_key` opaco generado por el servidor que no contiene nombre de archivo ni datos del paciente. Una ficha SHALL admitir hasta 200 adjuntos activos. (TBD, Open Decisions 5 y 12)

#### Scenario: Subida válida
- **WHEN** un odontólogo sube un PNG sintético de 200 KB
- **THEN** responde `201` con `id`, `size_bytes=204800`, `sha256` correcto y `kind`; la fila existe y el archivo es recuperable por el almacenamiento

#### Scenario: Tipo declarado falso
- **WHEN** se sube un ejecutable renombrado `rx.png` con `Content-Type: image/png`
- **THEN** responde `415 unsupported_media_type` y no se guarda fila ni archivo

#### Scenario: Archivo demasiado grande
- **WHEN** el archivo pesa 10 MiB + 1 byte
- **THEN** responde `413 attachment_too_large` y no se guarda nada

#### Scenario: Archivo vacío
- **WHEN** el archivo tiene 0 bytes
- **THEN** responde `422 attachment_empty`

#### Scenario: Nombre con ruta o caracteres de control
- **WHEN** el nombre original es `../../etc/passwd\n.png`
- **THEN** el nombre mostrado queda saneado (sin separadores ni control) y el `storage_key` no lo incluye

#### Scenario: Tope de adjuntos
- **WHEN** la ficha ya tiene 200 adjuntos activos
- **THEN** responde `409 attachment_limit_reached`

#### Scenario: Falla del almacenamiento
- **WHEN** el almacenamiento falla al escribir
- **THEN** responde 5xx uniforme y no queda fila de metadatos huérfana

#### Scenario: Evolución ajena
- **WHEN** `evolution_id` es de otra ficha
- **THEN** responde `422 evolution_not_found` y no se guarda archivo

### Requirement: Descarga solo autenticada y con headers seguros
`GET /api/clinical-records/{record_id}/attachments/{attachment_id}/content` SHALL transmitir el archivo solo a personal con acceso y SHALL responder con `Content-Disposition: attachment`, el `Content-Type` verificado, `X-Content-Type-Options: nosniff` y `Cache-Control: no-store`. No SHALL existir URL pública ni firmada al almacenamiento.

#### Scenario: Descarga del adjunto
- **WHEN** un odontólogo con alcance descarga un adjunto activo
- **THEN** responde `200` con los bytes idénticos (mismo `sha256`) y los headers indicados, y se audita `attachment_download`

#### Scenario: Sin sesión
- **WHEN** se pide sin token
- **THEN** responde `401`

#### Scenario: Adjunto de otra clínica
- **WHEN** se pide el UUID de un adjunto de la clínica B
- **THEN** responde `404`

#### Scenario: Archivo ausente en el almacenamiento
- **WHEN** existe la fila pero el almacenamiento no encuentra el objeto
- **THEN** responde `500 internal_error` sin exponer la ruta y se registra el incidente sin PII

### Requirement: Baja lógica sin borrado físico
`POST /api/clinical-records/{record_id}/attachments/{attachment_id}/removal` SHALL registrar una baja en `clinical_attachment_removal` (append-only, UNIQUE por adjunto) con `reason` de 10 a 300 caracteres; el adjunto y su archivo SHALL conservarse. Los adjuntos dados de baja SHALL salir de los listados activos y SHALL seguir siendo recuperables para el admin con `include_removed=true`. Ninguna operación SHALL borrar un objeto del almacenamiento.

#### Scenario: Baja con motivo
- **WHEN** el odontólogo da de baja un adjunto con motivo válido
- **THEN** responde `201`, el adjunto sale del listado activo, su fila y archivo siguen existiendo y se audita

#### Scenario: Baja repetida
- **WHEN** se da de baja dos veces el mismo adjunto
- **THEN** la segunda responde `409 attachment_already_removed` y existe una sola baja

#### Scenario: Bajas simultáneas
- **WHEN** dos requests dan de baja el mismo adjunto a la vez
- **THEN** uno responde `201` y el otro `409`; hay una sola fila de baja

#### Scenario: Descarga de un adjunto dado de baja
- **WHEN** un odontólogo pide el contenido de un adjunto dado de baja
- **THEN** responde `404`; un admin descarga el contenido del mismo adjunto con `200` y se audita `attachment_download`

#### Scenario: Sin DELETE
- **WHEN** se intenta `DELETE` sobre `clinical_attachment` o `clinical_attachment_removal`, como dueño o con `app_writer`
- **THEN** Postgres lo rechaza

### Requirement: Almacenamiento intercambiable
El acceso a los bytes SHALL pasar por una interfaz de almacenamiento (guardar, abrir, existe) con una implementación de disco configurable por entorno; cambiar de implementación no SHALL alterar las tablas ni la API.

#### Scenario: Doble de prueba contra el contrato
- **WHEN** se ejecuta la misma batería de contrato contra la implementación de disco y contra una en memoria de pruebas
- **THEN** ambas cumplen guardar, abrir, ausencia y no sobrescritura de un `storage_key` existente

#### Scenario: Directorio fuera de la raíz
- **WHEN** un `storage_key` intenta escapar de la raíz (`../x`)
- **THEN** la implementación de disco lo rechaza sin leer ni escribir fuera de la raíz

### Requirement: Listado de adjuntos
`GET /api/clinical-records/{record_id}/attachments` SHALL listar los adjuntos activos (metadatos, nunca bytes) por cursor, más recientes primero, con `limit` de 1 a 100; solo el admin SHALL poder pedir `include_removed=true`, y un odontólogo que lo pida SHALL recibir `403 forbidden_role`.

#### Scenario: Listado activo
- **WHEN** la ficha tiene 3 adjuntos y 1 dado de baja
- **THEN** el listado trae 3 con `id`, `kind`, `display_name`, `size_bytes` y sin `storage_key`

#### Scenario: Admin con bajas
- **WHEN** el admin pide `include_removed=true`
- **THEN** trae los 4, con `removed=true` en el dado de baja y su motivo

#### Scenario: Odontólogo pide bajas
- **WHEN** un odontólogo pide `include_removed=true`
- **THEN** responde `403 forbidden_role`
