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
