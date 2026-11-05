# core/patients Specification

## Purpose
Registra pacientes de forma liviana (sin historia clínica) con un contacto
utilizable para recordatorios, identificados por teléfono E.164 normalizado
(SU-03) y con resguardos mínimos de datos personales desde v1.

## Requirements

### Requirement: Paciente con al menos un contacto

Un paciente SHALL tener `full_name` no vacío y al menos uno de `phone_e164` o
`email`; la base SHALL rechazar un paciente sin ningún contacto.

#### Scenario: Paciente sin teléfono ni email rechazado

- **WHEN** se persiste un paciente con `phone_e164` y `email` nulos
- **THEN** la base rechaza la fila con violación de CHECK

#### Scenario: Paciente solo con email válido

- **WHEN** se persiste un paciente con email `paciente.ficticio@example.com` y
  sin teléfono
- **THEN** el paciente persiste con `whatsapp_opt_in=false`

### Requirement: DNI opcional y no único

El DNI SHALL ser opcional y NO único: dos pacientes de la misma clínica SHALL
poder compartir DNI sin error (el DNI no identifica pacientes en v1).

#### Scenario: Dos pacientes con el mismo DNI

- **WHEN** se persisten dos pacientes de la misma clínica con el mismo DNI
  ficticio
- **THEN** ambos persisten sin violación de unicidad

### Requirement: Teléfono normalizado a E.164

Todo teléfono de paciente SHALL guardarse en formato E.164; una entrada
nacional sin prefijo SHALL interpretarse con región default Argentina y un
número no válido SHALL rechazarse sin incluir el valor en el mensaje de error.

#### Scenario: Formatos equivalentes normalizan igual

- **WHEN** se normalizan un celular ficticio de Buenos Aires escrito en formato
  nacional con `15`, en formato internacional con espacios y guiones, y ya en
  E.164
- **THEN** los tres producen el mismo valor E.164 `+549...`

#### Scenario: Número inválido rechazado sin filtrar el dato

- **WHEN** se normaliza `12ab` o un número con dígitos insuficientes
- **THEN** se rechaza con un error de validación cuyo mensaje no contiene el
  valor ingresado

#### Scenario: La base no acepta teléfonos fuera de E.164

- **WHEN** se inserta directamente un `phone_e164` con espacios o sin `+`
- **THEN** la base rechaza la fila con violación de CHECK

### Requirement: Match de paciente por teléfono normalizado

La búsqueda de paciente por teléfono SHALL normalizar la entrada y devolver
todos los pacientes de la clínica con ese E.164 (un teléfono puede ser
compartido por una familia), ordenados del más reciente al más antiguo.

#### Scenario: Match con formato distinto al guardado

- **WHEN** un paciente se guardó con un E.164 y se busca el mismo número
  escrito en formato nacional
- **THEN** la búsqueda devuelve ese paciente

#### Scenario: Teléfono compartido devuelve todos

- **WHEN** dos pacientes de la clínica comparten teléfono y se busca ese
  número
- **THEN** se devuelven ambos, el más reciente primero

#### Scenario: Sin coincidencias

- **WHEN** se busca un teléfono válido que ningún paciente tiene
- **THEN** se devuelve una lista vacía

### Requirement: Resguardos mínimos de datos personales

El paciente SHALL registrar consentimiento de tratamiento de datos (momento y
versión del texto aceptado) y SHALL archivarse lógicamente en lugar de
borrarse físicamente; los pacientes archivados SHALL excluirse del match.

#### Scenario: Paciente archivado no aparece en el match

- **WHEN** un paciente se marca archivado y se busca su teléfono
- **THEN** no se devuelve y su fila sigue existiendo

#### Scenario: Consentimiento coherente

- **WHEN** se persiste un paciente con versión de consentimiento pero sin
  fecha de consentimiento
- **THEN** la base rechaza la fila con violación de CHECK

### Requirement: Búsqueda de pacientes por el personal

Admin y recepción SHALL buscar pacientes no archivados de su clínica con un
único término: si es un teléfono válido SHALL aplicarse el match por teléfono
normalizado; si no, SHALL buscarse por similitud de nombre. El resultado SHALL
tener como máximo 20 pacientes. El odontólogo SHALL NOT acceder a la búsqueda.

#### Scenario: Búsqueda por nombre aproximado

- **WHEN** existe la paciente ficticia `Ana Prueba Ejemplo` y recepción busca `ana prueba`
- **THEN** la respuesta la incluye

#### Scenario: Búsqueda por teléfono en formato nacional

- **WHEN** un paciente tiene un E.164 ficticio y se busca el mismo número en formato nacional
- **THEN** la respuesta lo incluye

#### Scenario: Término demasiado corto

- **WHEN** se busca con menos de 3 caracteres
- **THEN** responde `422 query_too_short`

#### Scenario: Odontólogo busca pacientes

- **WHEN** un odontólogo envía `GET /api/patients?q=...`
- **THEN** responde `403 forbidden_role`

### Requirement: Alta rápida de paciente por el personal

Admin y recepción SHALL dar de alta un paciente con nombre y al menos un
contacto; el teléfono SHALL normalizarse a E.164. Un paciente con el mismo
teléfono y el mismo nombre normalizado SHALL rechazarse con `409
patient_duplicate` y el id existente; mismo teléfono con otro nombre SHALL
aceptarse (familias).

#### Scenario: Alta con nombre y teléfono

- **WHEN** recepción crea un paciente ficticio con nombre y teléfono nacional
- **THEN** responde 201 con el teléfono en E.164 y `whatsapp_opt_in=false` salvo indicación

#### Scenario: Duplicado exacto

- **WHEN** ya existe un paciente con ese teléfono y el mismo nombre en otro uso de mayúsculas
- **THEN** responde `409 patient_duplicate` con el id del existente

#### Scenario: Familia que comparte teléfono

- **WHEN** se crea otro paciente con el mismo teléfono y distinto nombre
- **THEN** responde 201

#### Scenario: Errores sin datos personales

- **WHEN** el alta falla por teléfono inválido
- **THEN** responde 422 y ni la respuesta ni los logs contienen el teléfono enviado

### Requirement: Consulta de un paciente por el personal

Admin y recepción SHALL consultar un paciente de su clínica por id, incluido
uno archivado, con la indicación de en qué paciente fue fusionado si
corresponde. Un paciente de otra clínica o inexistente SHALL responder `404
not_found`. El odontólogo SHALL NOT acceder.

#### Scenario: Paciente de la clínica

- **WHEN** recepción pide un paciente ficticio de su clínica
- **THEN** recibe nombre, contacto, opt-in y `merged_into_patient_id` nulo

#### Scenario: Paciente de otra clínica

- **WHEN** un admin de la clínica B pide un paciente de la clínica A
- **THEN** responde `404 not_found`

#### Scenario: Odontólogo

- **WHEN** un odontólogo pide un paciente por id
- **THEN** responde `403 forbidden_role`

### Requirement: Fusión de pacientes duplicados sin borrado

Admin y recepción SHALL fusionar un paciente duplicado en otro de la misma
clínica. El duplicado SHALL quedar archivado y apuntando al conservado; sus
turnos de cualquier estado SHALL pasar al conservado; los datos de contacto
vacíos del conservado SHALL completarse con los del duplicado. Todo SHALL
ocurrir en una transacción y ninguna ficha SHALL borrarse.

#### Scenario: Fusión con turnos

- **WHEN** recepción fusiona un duplicado con 2 turnos (uno cancelado) en el paciente conservado
- **THEN** responde 200 con 2 turnos movidos, ambos turnos quedan del conservado y el duplicado queda archivado

#### Scenario: Completar contacto faltante

- **WHEN** el conservado no tiene email y el duplicado sí
- **THEN** el conservado queda con el email del duplicado y conserva su teléfono

#### Scenario: Duplicado sin turnos

- **WHEN** se fusiona un duplicado sin turnos
- **THEN** responde 200 con 0 turnos movidos y el duplicado queda archivado

### Requirement: La fusión valida sus fichas

La fusión SHALL rechazar con `422 invalid_merge` fusionar un paciente consigo
mismo, con uno archivado o ya fusionado, o con uno de otra clínica (sin revelar
si existe). Una request con campos desconocidos SHALL responder 422.

#### Scenario: Mismo paciente

- **WHEN** se pide fusionar un paciente consigo mismo
- **THEN** responde `422 invalid_merge` y nada cambia

#### Scenario: Paciente ya fusionado

- **WHEN** el duplicado ya fue fusionado antes
- **THEN** responde `422 invalid_merge`

#### Scenario: Conservado de otra clínica

- **WHEN** el paciente a conservar es de otra clínica
- **THEN** responde `422 invalid_merge` igual que si no existiera

### Requirement: La fusión queda auditada

Cada fusión SHALL registrar en una auditoría append-only el actor, ambos
pacientes, los ids de turnos movidos y los campos de contacto completados, sin
nombre, teléfono ni email en el registro. Cada turno movido SHALL registrar su
propio evento con el paciente anterior y el nuevo. La base SHALL rechazar
UPDATE y DELETE sobre esa auditoría.

#### Scenario: Registro de la fusión

- **WHEN** se completa una fusión con 2 turnos movidos
- **THEN** existe un registro de fusión con ambos ids y los 2 turnos, y cada turno tiene un evento `updated` con `patient_id` anterior y nuevo

#### Scenario: Auditoría inmutable

- **WHEN** se ejecuta un UPDATE o DELETE sobre un registro de fusión
- **THEN** la base lo rechaza con error

### Requirement: Un paciente fusionado deja de usarse

Un paciente fusionado SHALL NOT aparecer en la búsqueda ni aceptarse en turnos
nuevos, igual que un archivado.

#### Scenario: Turno para un fusionado

- **WHEN** recepción crea un turno para el paciente fusionado
- **THEN** responde `422 invalid_patient`

### Requirement: El consentimiento de WhatsApp se registra al cambiar

Todo alta o cambio de `whatsapp_opt_in` de un paciente, por reserva pública o por
el personal, SHALL registrar un consentimiento con su fuente en la misma
transacción. Un paciente creado con `whatsapp_opt_in=false` SHALL NOT generar
consentimiento de WhatsApp.

#### Scenario: Alta con WhatsApp autorizado

- **WHEN** recepción crea un paciente ficticio con `whatsapp_opt_in=true`
- **THEN** persiste con el flag activo y con un consentimiento `opt_in` de fuente
  `reception`

#### Scenario: Alta sin autorización

- **WHEN** recepción crea un paciente sin indicar `whatsapp_opt_in`
- **THEN** persiste con el flag en `false` y sin filas de consentimiento

#### Scenario: Match que otorga opt-in

- **WHEN** una reserva pública reutiliza un paciente existente sin opt-in y el
  paciente acepta WhatsApp
- **THEN** el flag pasa a `true` y se registra un consentimiento `opt_in` de
  fuente `booking`

#### Scenario: Match que no cambia nada

- **WHEN** una reserva pública reutiliza un paciente que ya tiene opt-in
- **THEN** no se agrega ningún consentimiento

#### Scenario: La fusión no hereda el opt-in

- **WHEN** se fusiona un paciente con opt-in en uno sin opt-in
- **THEN** el conservado mantiene su estado de consentimiento y no se crea
  ninguno nuevo
