# booking/public-booking Specification

## Purpose

Define la reserva online pública de una clínica por su slug: qué ve un visitante
anónimo, cómo reserva un turno sin cuenta, qué protege al sistema del abuso y qué
datos nunca se exponen.

## Requirements

### Requirement: Catálogo público de la clínica por slug

`GET /api/booking/{slug}` SHALL devolver nombre y zona horaria de la clínica y
sus profesionales reservables (solo id y nombre visible). Reservable SHALL ser:
clínica con reserva habilitada; profesional activo, con reserva habilitada y con
al menos una regla semanal activa y vigente sobre un sillón activo.

#### Scenario: Clínica con reserva habilitada

- **WHEN** la clínica ficticia `clinica-demo` tiene reserva habilitada y dos profesionales reservables
- **THEN** responde 200 con su nombre, su zona horaria y esos dos profesionales con `id` y `display_name`, sin otros campos

#### Scenario: Profesional sin regla vigente no aparece

- **WHEN** un profesional activo con reserva habilitada no tiene ninguna regla semanal vigente
- **THEN** no figura en el catálogo

#### Scenario: Profesional con reserva deshabilitada no aparece

- **WHEN** un profesional tiene `booking_enabled=false` o está inactivo
- **THEN** no figura en el catálogo

### Requirement: Slug inexistente y reserva deshabilitada son indistinguibles

Para un slug inexistente o de una clínica con reserva deshabilitada, todos los
endpoints públicos SHALL responder `404 booking_not_found` con el mismo cuerpo,
sin revelar si la clínica existe.

#### Scenario: Slug inexistente

- **WHEN** se consulta `GET /api/booking/no-existe-xyz`
- **THEN** responde `404 booking_not_found`

#### Scenario: Clínica con reserva deshabilitada

- **WHEN** se consulta el slug de una clínica existente con `booking_enabled=false`
- **THEN** responde `404 booking_not_found` con cuerpo idéntico al del slug inexistente

### Requirement: Disponibilidad pública solo con huecos libres

`GET /api/booking/{slug}/availability` SHALL devolver los horarios libres de un
profesional reservable: plantilla semanal vigente menos bloqueos, turnos
vigentes (incluidos sobreturnos) y buffers, en la zona de la clínica y desde
ahora. Cada hueco SHALL tener solo inicio, fin y profesional.

#### Scenario: Huecos descuentan turnos, bloqueos y buffer

- **WHEN** el profesional tiene franja 09:00–12:00 de 30 min, buffer 10 min, un turno vigente a las 10:00 y un bloqueo 11:00–12:00
- **THEN** la respuesta incluye 09:00 y no incluye 09:30 (su rango ocupado pisa el turno de 10:00), 10:00, 10:30, 11:00 ni 11:30

#### Scenario: Turno cancelado libera el hueco

- **WHEN** el único turno de las 10:00 pasa a `cancelled`
- **THEN** el hueco de las 10:00 vuelve a aparecer

#### Scenario: La respuesta no expone datos de otros pacientes

- **WHEN** existen turnos de pacientes ficticios en el rango consultado
- **THEN** la respuesta no contiene ids de turnos, ids de pacientes, sillones, nombres, teléfonos, emails, estados ni conteos de ocupación

#### Scenario: Huecos pasados no se ofrecen

- **WHEN** se consulta el día de hoy a media jornada
- **THEN** solo aparecen horarios con inicio posterior al momento actual

### Requirement: Rango de disponibilidad acotado

La consulta SHALL exigir `from` y `to` con `to > from`, un rango de hasta 14 días
y `to` dentro del horizonte de reserva de la clínica (default 60 días desde
hoy); fuera de esos límites SHALL responder `422 invalid_range`.

#### Scenario: Rango demasiado largo

- **WHEN** se pide disponibilidad para 30 días
- **THEN** responde `422 invalid_range`

#### Scenario: Más allá del horizonte

- **WHEN** se pide disponibilidad que termina 90 días después de hoy
- **THEN** responde `422 invalid_range`

### Requirement: Profesional no reservable responde como inexistente

Pedir disponibilidad o reservar con un profesional inexistente, de otra
clínica, inactivo, con reserva deshabilitada o sin regla vigente SHALL responder
`404 professional_not_found`, con el mismo cuerpo en todos los casos.

#### Scenario: Profesional de otra clínica

- **WHEN** se usa el slug de la clínica A con el id de un profesional de la clínica B
- **THEN** responde `404 professional_not_found`

#### Scenario: Profesional sin regla vigente

- **WHEN** se pide disponibilidad de un profesional activo sin regla semanal vigente
- **THEN** responde `404 professional_not_found`

### Requirement: Reserva con nombre, contacto y consentimientos explícitos

`POST /api/booking/{slug}/appointments` SHALL exigir nombre no vacío, al menos
un contacto válido (teléfono o email), la elección explícita de opt-in de
WhatsApp cuando hay teléfono y la aceptación de la política de privacidad
vigente. Ante cualquier falta SHALL responder `422` y no crear paciente ni turno.

#### Scenario: Sin contacto

- **WHEN** se reserva solo con nombre
- **THEN** responde `422 contact_required` y no existe paciente ni turno nuevo

#### Scenario: Sin aceptar privacidad

- **WHEN** se reserva con `privacy_accepted=false`
- **THEN** responde `422 privacy_consent_required`

#### Scenario: Teléfono sin opt-in y sin email

- **WHEN** se reserva con teléfono válido, `whatsapp_opt_in=false` y sin email
- **THEN** responde `422 whatsapp_opt_in_required`

#### Scenario: Reserva válida con teléfono y opt-in

- **WHEN** se reserva con nombre ficticio, teléfono nacional válido y `whatsapp_opt_in=true`
- **THEN** responde 201 con `channel=whatsapp` y el paciente queda con el teléfono en E.164 y opt-in activo

### Requirement: Email como canal cuando el teléfono no sirve para WhatsApp

Si el teléfono es inválido o el paciente rechaza WhatsApp y hay un email válido,
la reserva SHALL aceptarse con `channel=email` y un aviso explícito en la
respuesta. Un teléfono inválido SHALL descartarse sin guardarse.

#### Scenario: Teléfono inválido con email

- **WHEN** se reserva con un teléfono inválido y un email `@example.com`
- **THEN** responde 201 con `channel=email`, el aviso `phone_invalid_email_channel` y el paciente sin teléfono

#### Scenario: WhatsApp rechazado con email

- **WHEN** se reserva con teléfono válido, `whatsapp_opt_in=false` y email
- **THEN** responde 201 con `channel=email` y el aviso `whatsapp_declined_email_channel`

#### Scenario: Teléfono inválido sin email

- **WHEN** se reserva con un teléfono inválido y sin email
- **THEN** responde `422 contact_required` sin incluir el teléfono enviado

### Requirement: Solo horarios ofrecidos y duración de la plantilla

La reserva SHALL indicar profesional e inicio; el inicio SHALL coincidir con un
hueco de la grilla de la plantilla vigente y la duración SHALL ser la
`slot_duration_min` de la regla. Un inicio fuera de grilla o de horario SHALL
responder `422 slot_not_offered`; uno no futuro, `422 appointment_in_past`.

#### Scenario: Inicio fuera de grilla

- **WHEN** la franja es de 30 min desde 09:00 y se reserva a las 09:10
- **THEN** responde `422 slot_not_offered`

#### Scenario: Duración enviada por el paciente

- **WHEN** el cuerpo incluye `duration_min`, `chair_id`, `status` o `clinic_id`
- **THEN** responde 422 por campo no permitido

#### Scenario: Duración de la regla

- **WHEN** se reserva un hueco de una regla de 45 min
- **THEN** el turno creado dura 45 min

### Requirement: El turno online nace pendiente y ocupa la agenda

Una reserva válida SHALL crear un turno `pending` con origen `online`, sin
sobreturno, sobre un sillón de una regla vigente del profesional que contenga el
horario y esté libre, con la misma invariante anti-solapamiento que el resto de
los turnos, y SHALL ser visible en la agenda del personal.

#### Scenario: Turno creado

- **WHEN** se reserva un hueco libre
- **THEN** existe un turno `pending`, `origin=online`, `is_overbooking=false` y el listado de agenda de recepción lo incluye

#### Scenario: Sillón asignado por el sistema

- **WHEN** el profesional atiende el mismo horario en dos sillones y uno está ocupado
- **THEN** el turno se crea sobre el sillón libre

### Requirement: Carrera por el hueco responde 409 con alternativos públicos

Si el hueco se ocupó entre la consulta y la reserva, SHALL responder `409
slot_taken` con hasta 3 horarios alternativos del mismo profesional (solo inicio,
fin y profesional) y sin ids de turnos en conflicto; no SHALL crearse paciente
nuevo ni turno.

#### Scenario: Dos reservas concurrentes por el mismo hueco

- **WHEN** dos reservas online por el mismo horario y profesional llegan al mismo tiempo
- **THEN** exactamente una responde 201 y la otra `409 slot_taken` con `alternatives`

#### Scenario: Recepción gana la carrera

- **WHEN** recepción y una reserva online compiten por el mismo hueco
- **THEN** solo uno se crea y la reserva online perdedora responde `409 slot_taken`

#### Scenario: Cuerpo del 409 sin datos ajenos

- **WHEN** la reserva responde `409 slot_taken`
- **THEN** el cuerpo no incluye `conflicts`, ids de turnos, sillones ni datos de pacientes

### Requirement: Reutilización del paciente existente

Si el teléfono normalizado y el nombre normalizado coinciden con un paciente no
archivado de la clínica, la reserva SHALL usar ese paciente; si no, SHALL crear
uno. La reserva SHALL NOT modificar nombre ni contactos guardados y solo SHALL
poder activar el opt-in de WhatsApp, nunca desactivarlo.

#### Scenario: Paciente recurrente

- **WHEN** existe un paciente ficticio con ese teléfono y el mismo nombre con otras mayúsculas
- **THEN** el turno se asocia a ese paciente y no se crea otro

#### Scenario: Familia que comparte teléfono

- **WHEN** existe un paciente con ese teléfono pero otro nombre
- **THEN** se crea un paciente nuevo con el mismo teléfono

#### Scenario: Paciente de otra clínica con el mismo teléfono

- **WHEN** solo la clínica B tiene un paciente con ese teléfono y nombre y se reserva en la clínica A
- **THEN** se crea un paciente nuevo en la clínica A

#### Scenario: La reserva no pisa datos guardados

- **WHEN** un paciente recurrente reserva con un email distinto del guardado
- **THEN** el paciente conserva su email original

### Requirement: Emisión del token de gestión

Cada reserva SHALL emitir un token de gestión aleatorio de 256 bits, devuelto una
sola vez como link de gestión en la respuesta 201. La base SHALL guardar solo su
hash SHA-256, único. El token SHALL NOT aparecer en logs, eventos ni en ninguna
otra respuesta.

#### Scenario: Link de gestión en la respuesta

- **WHEN** una reserva responde 201
- **THEN** incluye `manage_url` con un token URL-safe de al menos 43 caracteres y la cabecera `Cache-Control: no-store`

#### Scenario: Solo el hash persiste

- **WHEN** se lee el turno creado en la base
- **THEN** guarda el SHA-256 del token (32 bytes) y ninguna columna ni evento contiene el token en claro

#### Scenario: Tokens distintos por reserva

- **WHEN** se hacen dos reservas válidas
- **THEN** reciben tokens distintos

### Requirement: Auditoría de la reserva sin datos personales

La reserva SHALL escribir en la misma transacción el evento `created` del turno
con actor de tipo paciente, origen `online` y el canal elegido. El evento SHALL
NOT contener nombre, teléfono, email ni el token.

#### Scenario: Evento de alta online

- **WHEN** una reserva responde 201
- **THEN** el turno tiene un evento `created` con `actor_type=patient_token`, `origin=online` y sin datos personales

### Requirement: Rate-limit de reservas por IP y por clínica

La creación de reservas SHALL limitarse por IP (default 10 por hora) y por slug
(default configurable). Al excederse SHALL responder `429 rate_limited` con
cabecera `Retry-After`, sin crear nada. Los intentos rechazados por validación
SHALL consumir cupo.

#### Scenario: Undécima reserva de la misma IP

- **WHEN** una IP hace 10 reservas en una hora y envía la undécima
- **THEN** responde `429 rate_limited` con `Retry-After` y no se crea turno

#### Scenario: Otra IP no se ve afectada

- **WHEN** una IP agotó su cupo y otra IP reserva en la misma clínica
- **THEN** la segunda responde 201

### Requirement: Rate-limit de lecturas públicas por IP

Las lecturas de catálogo y disponibilidad SHALL limitarse por IP (default
configurable, más holgado que el de reservas) y SHALL responder `429
rate_limited` con `Retry-After` al excederse, también para slugs inexistentes.

#### Scenario: Barrido de disponibilidad

- **WHEN** una IP supera el cupo de consultas de disponibilidad en la ventana
- **THEN** recibe `429 rate_limited`

#### Scenario: Barrido de slugs

- **WHEN** una IP consulta muchos slugs inexistentes y supera el cupo
- **THEN** recibe `429 rate_limited` en lugar de `404`

### Requirement: Falla cerrada sin almacenamiento de rate-limit

Si el almacenamiento del rate-limit no está disponible, los endpoints públicos
SHALL responder `503 booking_unavailable` y SHALL NOT crear turnos ni devolver
disponibilidad.

#### Scenario: Redis caído

- **WHEN** Redis no responde y se envía una reserva
- **THEN** responde `503 booking_unavailable` y no se crea turno

### Requirement: Reserva sin CAPTCHA en v1 con verificación anti-bot conectable

En v1 la reserva SHALL NOT exigir CAPTCHA ni desafío; la protección SHALL ser el
rate-limit y la anti-enumeración. Toda reserva SHALL pasar por un punto de
verificación anti-bot reemplazable, que si rechaza SHALL responder `403
bot_check_failed` sin crear nada.

#### Scenario: Reserva sin desafío

- **WHEN** se reserva sin ningún campo de CAPTCHA
- **THEN** responde 201

#### Scenario: Verificador que rechaza

- **WHEN** se configura un verificador anti-bot que rechaza la solicitud
- **THEN** responde `403 bot_check_failed` y no se crea paciente ni turno

### Requirement: Errores y logs públicos sin datos personales

Las respuestas de error y los logs de los endpoints públicos SHALL NOT incluir
nombre, teléfono, email ni token enviados, ni detalles internos de la base.

#### Scenario: Error de validación

- **WHEN** una reserva falla con 422 por teléfono inválido sin email
- **THEN** ni la respuesta ni los logs capturados contienen el teléfono ni el nombre enviados

### Requirement: Aislamiento por clínica de la reserva pública

Todo lo resuelto bajo un slug SHALL limitarse a esa clínica: profesionales,
sillones, reglas, bloqueos, turnos considerados ocupados y pacientes
reutilizados.

#### Scenario: Turnos de otra clínica no ocupan huecos

- **WHEN** la clínica B tiene un turno a las 10:00 y la clínica A tiene ese horario libre
- **THEN** la disponibilidad de A incluye las 10:00

#### Scenario: Reserva no alcanza recursos ajenos

- **WHEN** se reserva bajo el slug de A con un profesional de B
- **THEN** responde `404 professional_not_found` y B no registra cambios
