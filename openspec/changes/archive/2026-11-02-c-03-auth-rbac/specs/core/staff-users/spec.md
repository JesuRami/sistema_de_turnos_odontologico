# Spec Delta

## ADDED Requirements

### Requirement: Alta de usuario del personal por API

Un administrador SHALL poder crear usuarios del personal con rol `admin`,
`recepcion` u `odontologo`; el alta SHALL normalizar el email, hashear la
contraseña, marcar la credencial como provisoria y devolver el usuario creado
sin hash ni contraseña.

#### Scenario: Alta de recepción

- **WHEN** un admin crea un usuario `recepcion` con email, contraseña válida y
  sin `professional_id`
- **THEN** responde `201` con `id`, `email` en minúsculas y `role`, y
  `must_change_password=true`
- **AND** la respuesta no contiene `password_hash` ni la contraseña

#### Scenario: Odontólogo sin profesional rechazado en el borde

- **WHEN** un admin crea un usuario `odontologo` sin `professional_id`
- **THEN** responde `422` y no se crea el usuario

#### Scenario: Profesional de otra clínica rechazado

- **WHEN** un admin de A crea un odontólogo con `professional_id` de B
- **THEN** responde `422` sin revelar datos del profesional de B y sin crear
  el usuario

#### Scenario: Email duplicado en la clínica

- **WHEN** se crea un usuario con un email ya usado en su clínica
- **THEN** responde `422` con mensaje de dominio sin PII

### Requirement: La baja de usuario es lógica y revoca sus sesiones

Desactivar un usuario SHALL poner `active=false` conservando la fila y SHALL
revocar todas sus sesiones; no SHALL existir endpoint de borrado físico.

#### Scenario: Usuario desactivado no puede volver a entrar

- **WHEN** un admin desactiva un usuario que tenía sesión abierta
- **THEN** responde `200` con `active=false`, la fila sigue existiendo y el
  siguiente request del usuario desactivado responde `401`

#### Scenario: Borrado físico no ofrecido

- **WHEN** se llama `DELETE /api/users/{id}`
- **THEN** responde `405` y el usuario permanece en la base

### Requirement: El cambio de rol mantiene la coherencia del vínculo profesional

Cambiar el rol de un usuario SHALL validar el vínculo con `professional_id`
(el rol `odontologo` lo exige y los demás roles pueden prescindir de él) y
SHALL revocar las sesiones vigentes para que el nuevo rol rija de inmediato.

#### Scenario: Recepción promovida a odontóloga sin profesional

- **WHEN** un admin cambia a `odontologo` un usuario `recepcion` sin
  `professional_id`
- **THEN** responde `422` y el rol anterior se conserva

#### Scenario: Cambio de rol aplica en el siguiente request

- **WHEN** un admin cambia el rol de un usuario con sesión abierta
- **THEN** la sesión anterior deja de servir y el usuario debe autenticarse de
  nuevo con el rol actualizado

### Requirement: El reseteo de contraseña es provisorio y revoca sesiones

Un administrador SHALL poder fijar una contraseña provisoria a un usuario; el
sistema SHALL rehashear, marcar `must_change_password=true`, revocar las
sesiones del usuario y NUNCA SHALL devolver ni registrar la contraseña.

#### Scenario: Reseteo por administrador

- **WHEN** un admin resetea la contraseña de un usuario
- **THEN** responde `204`, la contraseña anterior deja de autenticar, la nueva
  funciona y `must_change_password` queda en `true`

#### Scenario: Contraseña provisoria no aparece en la respuesta ni en logs

- **WHEN** se ejecuta un reseteo
- **THEN** ni el cuerpo de la respuesta ni los logs contienen la contraseña
  nueva ni el hash

### Requirement: El listado de usuarios es por clínica y sin secretos

`GET /api/users` SHALL devolver solo usuarios de la clínica del principal,
paginados por cursor, con columnas explícitas y sin `password_hash`; el
odontólogo y la recepción NUNCA SHALL acceder al listado.

#### Scenario: Listado acotado y sin hash

- **WHEN** un admin de A lista sus usuarios
- **THEN** recibe solo usuarios de A, sin `password_hash`, y el cursor permite
  continuar el listado sin `OFFSET`

#### Scenario: Roles sin permiso

- **WHEN** un principal `recepcion` o `odontologo` llama `GET /api/users`
- **THEN** responde `403` con `forbidden_role`

### Requirement: El administrador no puede dejar la clínica sin administración

El sistema SHALL impedir que el último administrador activo se desactive a sí
mismo o se quite el rol `admin`, de modo que la clínica nunca quede sin acceso
administrativo.

#### Scenario: Último admin no se desactiva

- **WHEN** el único admin activo intenta desactivar su propia cuenta
- **THEN** responde `409` y la cuenta sigue activa

#### Scenario: Último admin no se cambia el rol

- **WHEN** el único admin activo intenta cambiar su rol a `recepcion`
- **THEN** responde `409` y su rol se conserva
