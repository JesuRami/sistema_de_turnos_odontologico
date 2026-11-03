# identity/staff-auth Specification

## Purpose
Define cómo el personal de la clínica inicia, renueva, cierra y revoca su
sesión: credenciales con hash argon2id, token de acceso corto, refresh
rotativo con detección de reuso, cookie endurecida y política de contraseñas.

## Requirements

### Requirement: Login emite una sesión con access corto y refresh en cookie

Con credenciales válidas de un usuario activo, el sistema SHALL crear una
sesión nueva y responder `200` con un token de acceso de vida corta en el
cuerpo y el refresh token únicamente en una cookie; SHALL registrar
`last_login_at` y SHALL informar si la contraseña es provisoria.

#### Scenario: Login correcto

- **WHEN** un usuario activo de la clínica envía su email y contraseña correctos
- **THEN** responde `200` con `access_token`, `token_type=bearer`, `expires_in`
  de 900 segundos o menos, la cookie de refresh y los datos del usuario
  (`id`, `email`, `role`, `clinic_id`, `professional_id`, `must_change_password`)
- **AND** el cuerpo de la respuesta no contiene el refresh token
- **AND** `last_login_at` del usuario queda actualizado

#### Scenario: Refresh nunca se expone a JavaScript

- **WHEN** se completa un login o un refresh
- **THEN** el refresh token solo viaja en la cookie `HttpOnly` y no aparece en
  el cuerpo, ni en encabezados accesibles al cliente, ni en respuestas de error

### Requirement: Credenciales inválidas responden igual sin revelar la causa

Ante email inexistente, contraseña incorrecta, usuario inactivo o email
ambiguo, el sistema SHALL responder `401` con el mismo cuerpo genérico y sin
distinguir el motivo, y SHALL consumir un tiempo de verificación comparable
para no habilitar enumeración de cuentas.

#### Scenario: Contraseña incorrecta y usuario inexistente son indistinguibles

- **WHEN** se intenta login con un email existente y contraseña incorrecta, y
  luego con un email inexistente
- **THEN** ambas respuestas son `401` con idéntico `detail` y ninguna indica
  cuál de los dos datos falló

#### Scenario: Usuario desactivado no obtiene sesión

- **WHEN** un usuario con `active=false` y contraseña correcta intenta login
- **THEN** responde `401` genérico y no se emite access ni refresh token

### Requirement: El login está limitado por IP y por email

El sistema SHALL rechazar `429` con `Retry-After` cuando se superan los
intentos permitidos en la ventana, aplicando un cupo por par IP+email de 5
intentos cada 60 segundos y un tope agregado por IP, contados en el
almacenamiento compartido entre procesos.

#### Scenario: Sexto intento en un minuto

- **WHEN** el mismo par IP+email acumula 5 intentos de login dentro de 60 segundos
- **THEN** el sexto intento responde `429` con `Retry-After`
- **AND** las credenciales no se evalúan en ese intento

#### Scenario: Ataque de pulverización desde una IP

- **WHEN** la misma IP intenta login contra muchos emails distintos hasta
  superar el tope agregado por IP
- **THEN** responde `429` aunque cada par IP+email siga por debajo de su cupo

### Requirement: El token de acceso tiene claims acotados y algoritmo pineado

Cada token de acceso SHALL incluir `sub`, `clinic_id`, `roles`, `email`,
`jti`, `sid`, `type`, `iat`, `exp`, `iss` y `aud`, con vigencia máxima de 15
minutos; el sistema SHALL validarlo con algoritmo fijado en servidor,
`iss`/`aud` esperados, `exp` obligatorio y `type=access`.

#### Scenario: Access token emitido con el contrato completo

- **WHEN** se emite un token de acceso
- **THEN** contiene los diez claims indicados, `exp - iat` no supera 900
  segundos y `roles` es una lista con el rol vigente del usuario

#### Scenario: Token expirado rechazado

- **WHEN** se presenta un token de acceso cuyo `exp` ya pasó
- **THEN** responde `401` con código `token_expired` y no se ejecuta el endpoint

#### Scenario: Firma o algoritmo no aceptados

- **WHEN** se presenta un token firmado con otro secreto, con algoritmo
  distinto al pineado o sin firma (`alg=none`)
- **THEN** responde `401` sin distinguir entre las tres causas

#### Scenario: `iss` o `aud` incorrectos

- **WHEN** se presenta un token válido en firma pero con `iss` o `aud`
  distintos a los configurados
- **THEN** responde `401`

### Requirement: El access token solo es válido mientras su sesión esté viva

Todo request autenticado SHALL verificar que la sesión referenciada por el
claim `sid` sigue vigente; si la sesión fue revocada, cerrada o nunca existió,
el token de acceso SHALL rechazarse aunque no haya expirado.

#### Scenario: Access de una sesión cerrada deja de servir

- **WHEN** un usuario hace logout y reutiliza el access token anterior
- **THEN** responde `401` de inmediato, sin esperar los 15 minutos de vigencia

### Requirement: El refresh rota en cada uso y detecta reuso

Cada refresh válido SHALL emitir un refresh nuevo y dejar inservible el
anterior dentro de la misma familia de sesión; si un refresh ya rotado se
presenta otra vez, el sistema SHALL revocar la familia completa, auditar el
evento y responder `401`.

#### Scenario: Rotación exitosa

- **WHEN** se presenta el refresh vigente de una sesión
- **THEN** responde `200` con un access nuevo y una cookie de refresh nueva
- **AND** el refresh anterior responde `401` en un intento posterior

#### Scenario: Reuso de refresh rotado revoca la familia

- **WHEN** se presenta un refresh que ya fue rotado mientras la familia sigue
  vigente
- **THEN** responde `401`, la familia completa queda revocada (el refresh
  vigente también deja de servir) y se registra `refresh_reuse_detected`

#### Scenario: Refresh ausente, expirado o de familia revocada

- **WHEN** el request de refresh no trae cookie, la cookie expiró o la familia
  fue revocada
- **THEN** responde `401` genérico y envía la cookie de borrado

### Requirement: Logout revoca la sesión de forma idempotente

El logout SHALL revocar la sesión del portador (refresh y access asociados al
`sid`) y borrar la cookie; repetirlo SHALL responder éxito sin efectos
adicionales.

#### Scenario: Logout invalida access y refresh

- **WHEN** un usuario autenticado hace logout
- **THEN** responde `204`, la cookie se borra y tanto el refresh como el access
  de esa sesión son rechazados en el siguiente request

#### Scenario: Logout repetido no falla

- **WHEN** se repite el logout con la cookie ya borrada o con un token ya revocado
- **THEN** responde `204` sin error y sin crear ni revivir sesiones

### Requirement: El perfil propio se consulta sin datos sensibles

`GET /api/auth/me` SHALL devolver la identidad efectiva del portador —
`id`, `email`, `role`, `clinic_id`, `professional_id`, `must_change_password`
y `last_login_at`— y NUNCA SHALL incluir el hash de contraseña ni secretos.

#### Scenario: Perfil del odontólogo incluye su profesional

- **WHEN** un usuario con rol `odontologo` consulta su perfil
- **THEN** la respuesta incluye el `professional_id` al que está atado y no
  incluye `password_hash` ni tokens

### Requirement: Cambio de contraseña revoca las demás sesiones

Un usuario autenticado SHALL poder cambiar su contraseña presentando la actual
y una nueva que cumpla la política; el sistema SHALL rehashear con argon2id,
marcar `password_changed_at`, limpiar `must_change_password` y revocar todas
las demás sesiones del usuario.

#### Scenario: Cambio exitoso cierra las otras sesiones

- **WHEN** un usuario con sesiones abiertas en dos dispositivos cambia su
  contraseña desde uno de ellos
- **THEN** responde `200`, la contraseña vieja deja de autenticar y la sesión
  del otro dispositivo recibe `401` en su siguiente request

#### Scenario: Contraseña actual incorrecta no cambia nada

- **WHEN** el cambio se pide con la contraseña actual equivocada
- **THEN** responde `401` y el hash, `password_changed_at` y las sesiones
  quedan intactos

### Requirement: La política de contraseñas se valida en el servidor

Toda contraseña fijada (alta, reseteo o cambio) SHALL tener entre 12 y 128
caracteres, SHALL ser distinta de la anterior y NUNCA SHALL registrarse en
logs ni devolverse en respuestas; no se exigen reglas de composición.

#### Scenario: Contraseña corta rechazada

- **WHEN** se intenta fijar una contraseña de 11 caracteres
- **THEN** responde `422` y el hash anterior no cambia

#### Scenario: Contraseña igual a la anterior rechazada

- **WHEN** un usuario cambia su contraseña por el mismo valor actual
- **THEN** responde `422` sin rehashear

### Requirement: El cambio obligatorio de contraseña bloquea el resto de la API

Un usuario con `must_change_password=true` SHALL poder autenticarse y usar solo
`/api/auth/me`, `/api/auth/change-password` y `/api/auth/logout`; cualquier
otro endpoint autenticado SHALL responder `403` con código
`password_change_required`.

#### Scenario: Admin del seed queda contenido hasta cambiar la clave

- **WHEN** el admin creado por el seed (`must_change_password=true`) llama un
  endpoint de gestión de usuarios
- **THEN** responde `403` con código `password_change_required`
- **AND** tras cambiar la contraseña el mismo endpoint responde según su rol

### Requirement: El login rehashea hashes con parámetros viejos

Si la contraseña verifica pero el hash fue generado con parámetros distintos a
los vigentes, el sistema SHALL rehashear en el mismo login sin cambiar la
contraseña ni pedir al usuario nada adicional.

#### Scenario: Hash legado se actualiza al entrar

- **WHEN** un usuario con hash argon2id de parámetros antiguos hace login correcto
- **THEN** el `password_hash` almacenado pasa a usar los parámetros vigentes y
  la contraseña sigue siendo la misma

### Requirement: El secreto JWT se valida al arrancar

La aplicación SHALL negarse a arrancar si `JWT_SECRET` falta o mide menos de 32
bytes, nombrando la variable sin imprimir su valor, y NUNCA SHALL contener un
secreto por defecto en el código.

#### Scenario: Secreto corto aborta el arranque

- **WHEN** se inicia la app con `JWT_SECRET` de 20 caracteres
- **THEN** el arranque falla indicando `JWT_SECRET` y el valor no aparece en el
  mensaje ni en los logs

### Requirement: Los flags de la cookie de refresh dependen del entorno

La cookie de refresh SHALL ser siempre `HttpOnly` y `SameSite=Lax`; en
producción SHALL ser `Secure`, con prefijo `__Host-`, `Path=/` y sin `Domain`,
mientras que en desarrollo SHALL permitir HTTP local sin prefijo `__Host-`.

#### Scenario: Cookie endurecida en producción

- **WHEN** la app corre con `ENV=prod` y responde un login
- **THEN** el `Set-Cookie` del refresh incluye `HttpOnly`, `Secure`,
  `SameSite=Lax`, `Path=/`, nombre con prefijo `__Host-` y ningún `Domain`

#### Scenario: Cookie utilizable en desarrollo local

- **WHEN** la app corre con `ENV=dev` sobre HTTP local
- **THEN** la cookie de refresh se emite con `HttpOnly` y `SameSite=Lax` y sin
  el flag `Secure`, para que el navegador la retenga en `localhost`
