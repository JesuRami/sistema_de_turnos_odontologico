# Spec Delta

## Purpose

Fija cómo la API decide qué puede hacer cada actor del personal: un principal
derivado del servidor, una dependency de roles reutilizable y el alcance
"odontólogo solo lo suyo" resuelto en la consulta, nunca en el frontend.

## ADDED Requirements

### Requirement: El principal se construye con datos del servidor

En cada request autenticado el sistema SHALL validar el token y luego cargar el
usuario por `id` y `clinic_id` desde la base; el principal resultante SHALL
tomar rol, `professional_id`, `clinic_id` y estado activo de esa fila, no de
los claims del token.

#### Scenario: Rol elevado en el token no otorga permisos

- **WHEN** un token válido de un usuario `recepcion` se presenta manipulado con
  `roles: ["admin"]` (re-firmado con otro secreto o claims alterados)
- **THEN** la firma se rechaza con `401` y, si el token fuera válido por otra
  vía, el principal se construye con el rol real de la base

#### Scenario: Usuario desactivado pierde acceso

- **WHEN** un usuario con token de acceso vigente es desactivado y su sesión
  fue revocada
- **THEN** su siguiente request responde `401`

#### Scenario: Usuario inexistente en la base

- **WHEN** el token referencia un `sub` que ya no existe en la clínica
- **THEN** responde `401` sin crear un principal

### Requirement: La dependency de roles responde 403 sin ejecutar el handler

Los endpoints protegidos SHALL declarar los roles admitidos; si el principal
autenticado no tiene ninguno, la respuesta SHALL ser `403` con código
`forbidden_role` y el handler no SHALL ejecutarse.

#### Scenario: Recepción no gestiona usuarios

- **WHEN** un principal `recepcion` llama `POST /api/users`
- **THEN** responde `403` con `forbidden_role` y no se crea ningún usuario

#### Scenario: Admin autorizado ejecuta el handler

- **WHEN** un principal `admin` llama el mismo endpoint con datos válidos
- **THEN** el handler se ejecuta y responde `201`

#### Scenario: Sin identidad es 401, no 403

- **WHEN** un endpoint protegido se llama sin cookie ni access token
- **THEN** responde `401`, nunca `403`

### Requirement: La matriz de permisos se aplica en el servidor

Cada endpoint SHALL mapear a la matriz rol→recurso de la KB y aplicar el control
del lado servidor: `admin` gestiona usuarios y configuración, `recepcion` opera
agenda sin gestionar usuarios, `odontologo` solo consulta y opera lo propio, y
el paciente no es un principal autenticado.

#### Scenario: Odontólogo no crea turnos ni gestiona personal

- **WHEN** un principal `odontologo` llama un endpoint de alta de turnos o de
  usuarios
- **THEN** responde `403` con `forbidden_role`

#### Scenario: Reglas idénticas fuera de la SPA

- **WHEN** las mismas operaciones se ejecutan por HTTP directo (httpx/curl), sin
  la interfaz de la SPA
- **THEN** las respuestas de autorización son las mismas que con la SPA, porque
  no existe ningún control de permisos solo en el cliente

### Requirement: El tenant siempre proviene del principal

Toda consulta y escritura SHALL usar el `clinic_id` del principal; ningún
endpoint SHALL aceptar `clinic_id` del cuerpo, query o encabezado como fuente
de tenant, y un intento de imponerlo SHALL rechazarse o ignorarse.

#### Scenario: Body con clínica ajena rechazado

- **WHEN** un admin de la clínica A envía `POST /api/users` incluyendo
  `clinic_id` de la clínica B
- **THEN** responde `422` por campo no permitido y no se crea nada en A ni en B

#### Scenario: Listado acotado a la clínica del principal

- **WHEN** un admin de A lista usuarios
- **THEN** el resultado contiene solo usuarios de A aunque existan usuarios con
  el mismo email en B

### Requirement: El odontólogo solo ve filas de su propio profesional

Toda consulta sobre datos con dueño profesional SHALL filtrar por
`professional_id` del principal cuando el rol es `odontologo`, además de
filtrar por `clinic_id`; `admin` y `recepcion` SHALL ver todas las filas de su
clínica. El filtro SHALL aplicarse en la sentencia SQL, no después de traer
los datos.

#### Scenario: Odontólogo consulta recursos con dueño profesional

- **WHEN** dos odontólogos de la misma clínica tienen agregados propios y uno
  consulta el recurso
- **THEN** recibe solo las filas de su `professional_id` y ninguna del otro
  odontólogo ni de otra clínica

#### Scenario: Recepción ve toda la clínica

- **WHEN** un principal `recepcion` ejecuta la misma consulta
- **THEN** recibe las filas de todos los profesionales de su clínica y ninguna
  de otra clínica

#### Scenario: Acceso directo a una fila ajena

- **WHEN** un odontólogo pide por identificador una fila de otro profesional
- **THEN** responde `404` sin revelar que la fila existe

### Requirement: El odontólogo sin profesional no accede a datos profesionales

Un principal con rol `odontologo` y `professional_id` nulo SHALL ser rechazado
con `403` en toda consulta o mutación con dueño profesional, sin caer en un
filtro vacío que devuelva filas de terceros.

#### Scenario: Principal incompleto no filtra por nulo

- **WHEN** un odontólogo sin `professional_id` consulta datos con dueño profesional
- **THEN** responde `403` y la consulta no se ejecuta
