# Spec Delta

## Purpose

Deja una traza de seguridad consultable e inmutable de los eventos de
autenticación y de gestión de usuarios, suficiente para investigar accesos sin
guardar datos personales.

## ADDED Requirements

### Requirement: Los eventos de seguridad se registran append-only

El sistema SHALL registrar en una tabla append-only, en cada clínica, los
eventos `login_success`, `login_failed`, `refresh_reuse_detected`, `logout`,
`password_changed`, `user_created`, `user_updated`, `user_deactivated` y
`role_changed`, con `clinic_id`, `user_id` cuando se conoce, `actor_user_id`
para las acciones administrativas, el tipo de evento, un `payload` jsonb y
`created_at`.

#### Scenario: Login exitoso queda auditado

- **WHEN** un usuario completa un login correcto
- **THEN** existe un `auth_event` con su `user_id`, su `clinic_id` y evento
  `login_success`

#### Scenario: Acción de admin registra actor y objetivo

- **WHEN** un admin crea o desactiva a otro usuario
- **THEN** el evento correspondiente guarda al admin como `actor_user_id` y al
  usuario afectado como `user_id`

### Requirement: La auditoría no muta ni se borra

La base de datos SHALL rechazar cualquier `UPDATE` o `DELETE` sobre la tabla de
eventos de seguridad; corregir o retirar un evento NUNCA SHALL ser posible por
sentencia SQL ni por código de aplicación.

#### Scenario: UPDATE rechazado por la base

- **WHEN** se ejecuta un `UPDATE` sobre una fila de eventos de seguridad
- **THEN** la base rechaza la sentencia y la fila queda idéntica

#### Scenario: DELETE rechazado por la base

- **WHEN** se ejecuta un `DELETE` sobre una fila de eventos de seguridad
- **THEN** la base rechaza la sentencia y la fila sigue existiendo

### Requirement: La auditoría de seguridad no guarda datos personales

Los eventos SHALL identificar al sujeto por `user_id` o, si no existe, por una
huella irreversible del email normalizado; NUNCA SHALL guardar email, teléfono,
nombre, contraseña, tokens ni IP en claro.

#### Scenario: Login fallido con email inexistente

- **WHEN** se registra `login_failed` de un email que no corresponde a ningún
  usuario
- **THEN** el evento guarda solo una huella derivada y el payload no contiene
  el email, la contraseña ni la IP en claro

#### Scenario: Sin tokens en la traza

- **WHEN** ocurre cualquier evento de autenticación
- **THEN** ningún campo del evento contiene el access token, el refresh token
  ni su valor en claro

### Requirement: Los cambios administrativos y su auditoría son atómicos

Cuando un evento acompaña una mutación de estado (alta, cambio, desactivación,
reseteo de contraseña o cambio de contraseña), el evento SHALL escribirse en la
misma transacción que la mutación: si una falla, ninguna persiste.

#### Scenario: Fallo del cambio no deja evento huérfano

- **WHEN** un alta de usuario falla por email duplicado después de intentar
  registrar el evento
- **THEN** no queda ni el usuario ni el evento, y la respuesta es el error de
  validación correspondiente

### Requirement: La auditoría de intentos no bloquea la autenticación

Si el registro del evento de un intento de login, refresh o logout falla, la
respuesta de autenticación SHALL mantener su resultado y el sistema SHALL dejar
un aviso operativo sin secretos, en lugar de devolver un error al usuario.

#### Scenario: Fallo de auditoría no rompe el login

- **WHEN** el login valida las credenciales pero la escritura del evento falla
- **THEN** el usuario recibe su sesión normalmente y queda un aviso operativo
  que no contiene credenciales
