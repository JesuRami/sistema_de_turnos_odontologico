# booking/manage-token Specification

## Purpose
Permite que un paciente confirme, cancele o reprograme su turno desde el link
con token que recibió, sin cuenta ni sesión, con datos mínimos, ventana de
cancelación respetada e idempotencia frente a dobles clicks.

## Requirements

### Requirement: Resolución del link de gestión por hash

`GET /api/manage/{token}` SHALL resolver el turno, dentro de una sola clínica y
sin sesión ni `Principal`, por una de dos credenciales: el SHA-256 del token
aleatorio contra `appointment.manage_token_hash`, o un token firmado cuya firma
se verifica en tiempo constante. Un token malformado, desconocido o con firma
inválida SHALL responder `404 manage_link_not_found` con el mismo cuerpo, sin
revelar si el turno existe.

#### Scenario: Token válido resuelve su turno

- **WHEN** existe un turno online con el hash del token presentado
- **THEN** responde 200 con la vista de gestión de ese turno

#### Scenario: Token firmado resuelve su turno

- **WHEN** se presenta el token firmado emitido para un turno, incluso de recepción
  que no tiene token aleatorio
- **THEN** responde 200 con la vista de gestión de ese turno

#### Scenario: Token desconocido y token malformado son indistinguibles

- **WHEN** se pide un token aleatorio de 43 caracteres y uno de 10 caracteres
- **THEN** ambos responden `404 manage_link_not_found` con el mismo cuerpo

#### Scenario: Firma alterada

- **WHEN** se presenta un token firmado al que se le cambió un carácter
- **THEN** responde `404 manage_link_not_found` con el mismo cuerpo que un token
  desconocido

#### Scenario: Representación alternativa del mismo token

- **WHEN** se presenta un token firmado válido con el último carácter cambiado de modo que
  decodifica a los mismos bytes
- **THEN** responde `404 manage_link_not_found`, así cada credencial tiene una sola representación

#### Scenario: Token firmado de otro turno

- **WHEN** se usa el token firmado de un turno con la firma de otro
- **THEN** responde `404 manage_link_not_found` y ningún turno cambia

#### Scenario: El token no alcanza otro turno

- **WHEN** la clínica tiene dos turnos online y se usa el token de uno
- **THEN** solo se devuelve ese turno y ningún dato del otro

### Requirement: Vigencia del token y pantalla de contacto

El token SHALL ser válido desde la creación del turno hasta
`ends_at + MANAGE_TOKEN_TTL_H` (default 72 h) del turno, calculado en el
servidor. Pasado ese instante SHALL responder `410 manage_link_expired` y
ninguna acción SHALL mutar el turno; la vista de contacto SHALL indicar cómo
comunicarse con la clínica (RN-ON-04).

#### Scenario: Token vencido

- **WHEN** el turno terminó hace 73 h y se consulta su token
- **THEN** responde `410 manage_link_expired` y el turno no cambia

#### Scenario: Token vigente después del turno

- **WHEN** el turno terminó hace 2 h y se consulta su token
- **THEN** responde 200 con el turno en su estado final y sin acciones habilitadas

#### Scenario: Token vencido no permite mutar

- **WHEN** se envía `PATCH /api/manage/{token}` con `action=confirm` sobre un token vencido
- **THEN** responde `410 manage_link_expired` y el turno conserva su estado

### Requirement: Vista de gestión con datos mínimos

La vista SHALL incluir nombre de la clínica, teléfono de contacto, zona horaria,
nombre de pila del paciente, fecha y hora del turno, nombre visible del
profesional, estado, vencimiento del token, ventana de cancelación y qué
acciones están habilitadas. SHALL NOT incluir ids de turno, paciente, sillón o
profesional, ni teléfono o email del paciente.

#### Scenario: Vista de un turno pendiente

- **WHEN** se consulta el token de un turno `pending` que empieza en 5 días
- **THEN** la respuesta trae fecha, hora, profesional, estado y las tres acciones habilitadas

#### Scenario: La vista no filtra datos internos

- **WHEN** se inspecciona el JSON crudo de la vista
- **THEN** no aparecen ids de turno, paciente, sillón o profesional, ni el teléfono o el email del paciente

#### Scenario: Turno cancelado

- **WHEN** se consulta el token de un turno cancelado
- **THEN** la vista muestra el estado `cancelled` y ninguna acción habilitada

### Requirement: Catálogo cerrado de motivos del paciente

La vista SHALL exponer el catálogo cerrado de motivos de cancelación del
paciente, y la cancelación SHALL aceptar solo valores de ese catálogo o
`null`. Un valor fuera del catálogo SHALL responder `422 invalid_request` sin
cancelar.

#### Scenario: Motivo fuera del catálogo

- **WHEN** se cancela con `reason=motivo_inventado`
- **THEN** responde `422 invalid_request` y el turno sigue `pending`

#### Scenario: Catálogo en la vista

- **WHEN** se consulta la vista de un turno cancelable
- **THEN** incluye la lista de motivos con su valor y su etiqueta

### Requirement: Huecos ofrecibles para reprogramar

`GET /api/manage/{token}/availability` SHALL devolver los huecos realmente
ofrecibles del **mismo profesional** del turno, con la misma definición de hueco
que la reserva pública (plantilla menos bloqueos, turnos vigentes y buffers),
desde ahora y en la zona de la clínica. El rango SHALL ser de hasta 14 días y
estar dentro del horizonte de reserva; fuera de eso SHALL responder
`422 invalid_range`.

#### Scenario: Un turno ocupado no se ofrece

- **WHEN** el profesional tiene otro turno vigente a las 10:00
- **THEN** las 10:00 no aparecen entre los huecos ofrecidos

#### Scenario: El horario actual del turno sí se ofrece

- **WHEN** se piden huecos de un turno que hoy empieza a las 15:00
- **THEN** las 15:00 aparecen entre los huecos ofrecidos

#### Scenario: Rango inválido

- **WHEN** se piden huecos para 30 días
- **THEN** responde `422 invalid_range`

### Requirement: Confirmación en un toque

`PATCH /api/manage/{token}` con `action=confirm` SHALL pasar el turno de
`pending` a `confirmed` y SHALL registrar el evento `confirmed` con actor
`patient_token` en la misma transacción. Un turno ya `confirmed` SHALL responder
200 sin cambiar de estado.

#### Scenario: Confirmar un turno pendiente

- **WHEN** se confirma un turno `pending` con token vigente
- **THEN** responde 200 con estado `confirmed` y existe un evento `confirmed` con `from_status=pending`

#### Scenario: Confirmar un turno ya confirmado

- **WHEN** se confirma un turno que ya estaba `confirmed`
- **THEN** responde 200 con estado `confirmed` y no se duplica la transición

#### Scenario: Confirmar un turno cancelado

- **WHEN** se confirma un turno `cancelled`
- **THEN** responde `409 invalid_transition` y el turno sigue `cancelled`

#### Scenario: Confirmar un turno ya empezado

- **WHEN** se confirma un turno cuyo inicio ya pasó
- **THEN** responde `409 appointment_started` y el turno no cambia

### Requirement: Acción repetida es un no-op auditado

Repetir una acción ya aplicada SHALL ser idempotente: la respuesta SHALL ser
200 con el estado actual y SHALL registrarse un evento `updated` con
`idempotent_replay=true` y la acción pedida, sin repetir la transición ni
duplicar la cancelación.

#### Scenario: Doble click en confirmar

- **WHEN** dos `action=confirm` llegan con el mismo token y el turno ya está `confirmed`
- **THEN** el segundo responde 200 y deja un evento `updated` con `idempotent_replay=true`

#### Scenario: Doble click en cancelar

- **WHEN** se repite `action=cancel` sobre un turno ya cancelado por ese token
- **THEN** responde 200 con `cancelled` y no se escribe un segundo evento `cancelled`

#### Scenario: Reprogramar al mismo horario

- **WHEN** se reprograma un turno al horario que ya tiene
- **THEN** responde 200 con el mismo `starts_at` y un evento `updated` de replay

### Requirement: Cancelación dentro de la ventana con motivo opcional

`PATCH /api/manage/{token}` con `action=cancel` SHALL pasar el turno de
`pending` o `confirmed` a `cancelled` solo si faltan al menos
`clinic.cancellation_window_hours` horas para el inicio. El motivo SHALL ser
opcional, de la lista cerrada, y la nota libre SHALL tener como máximo 200
caracteres.

#### Scenario: Cancelación en plazo

- **WHEN** la ventana es 24 h y se cancela un turno que empieza en 5 días
- **THEN** responde 200 con `cancelled` y el evento `cancelled` lleva `late=false`

#### Scenario: Cancelación sin motivo

- **WHEN** se cancela dentro de la ventana sin enviar `reason`
- **THEN** responde 200 con `cancelled` y el evento registra la causa `paciente`

#### Scenario: Nota demasiado larga

- **WHEN** se cancela con una nota de 201 caracteres
- **THEN** responde `422 invalid_request` y el turno no cambia

#### Scenario: Cancelar dos veces el mismo turno

- **WHEN** se repite la cancelación con el mismo token
- **THEN** la segunda responde 200 y el turno sigue `cancelled` una sola vez

### Requirement: Cancelación fuera de la ventana se deriva a la clínica

Si faltan menos horas que la ventana de cancelación de la clínica, la
cancelación online SHALL rechazarse con `409 cancellation_window_closed` sin
cambiar el turno, y la vista SHALL mostrar el teléfono de la clínica
(RN-CX-01).

#### Scenario: Cancelación tardía

- **WHEN** la ventana es 24 h y se cancela un turno que empieza en 3 h
- **THEN** responde `409 cancellation_window_closed` y el turno sigue vigente

#### Scenario: La vista informa la derivación

- **WHEN** se consulta un turno que empieza en 3 h con ventana de 24 h
- **THEN** la vista deshabilita la cancelación online y muestra el teléfono de la clínica

### Requirement: Turno pasado o no operable no se cancela

Cancelar un turno cuyo inicio ya pasó SHALL responder `422
appointment_in_past`. Cancelar un turno `present`, `absent` o `no_show` SHALL
responder `409 invalid_transition`. En ambos casos el turno SHALL conservarse
sin cambios (RN-CX-05).

#### Scenario: Cancelar un turno pasado

- **WHEN** se cancela un turno que empezó ayer
- **THEN** responde `422 appointment_in_past` y el turno conserva su estado

#### Scenario: Cancelar un turno marcado presente

- **WHEN** se cancela un turno en estado `present`
- **THEN** responde `409 invalid_transition` y el turno sigue `present`

### Requirement: Reprogramación atómica conservando el turno

`PATCH /api/manage/{token}` con `action=reschedule` SHALL mover el turno a un
inicio ofrecible del mismo profesional conservando el `appointment_id`, en una
sola transacción, respetando la ventana de cancelación de la clínica. Si
cualquier validación falla, el turno SHALL conservar su horario original
(RN-AG-06, RN-CX-02).

#### Scenario: Reprogramación exitosa

- **WHEN** se reprograma un turno de las 10:00 a un hueco libre de las 11:00 del mismo profesional
- **THEN** responde 200 con el mismo id, `starts_at=11:00` y un evento `rescheduled` con horario anterior y nuevo

#### Scenario: Reprogramación fuera de la ventana

- **WHEN** la ventana es 24 h y se reprograma un turno que empieza en 3 h
- **THEN** responde `409 cancellation_window_closed` y el turno conserva su horario

#### Scenario: Inicio fuera de la grilla

- **WHEN** se reprograma a un inicio que no genera la plantilla del profesional
- **THEN** responde `422 slot_not_offered` y el turno conserva su horario

#### Scenario: Reprogramación a un horario ocupado

- **WHEN** se reprograma a un hueco que ya ocupa otro turno
- **THEN** responde `409 slot_taken` con alternativos y el turno conserva su horario

### Requirement: Colisión al reprogramar responde con alternativos públicos

Ante `409 slot_taken`, la respuesta SHALL incluir hasta 3 horarios alternativos
del mismo profesional dentro de los 14 días siguientes, con solo inicio y fin,
sin ids de turnos en conflicto ni sillones.

#### Scenario: Alternativos tras la colisión

- **WHEN** la reprogramación choca con otro turno y quedan huecos libres ese día
- **THEN** la respuesta lista hasta 3 alternativos en orden cronológico

#### Scenario: Sin datos ajenos en el 409

- **WHEN** se inspecciona el cuerpo del 409 de reprogramación
- **THEN** no incluye `conflicts`, ids de turnos ni sillones

### Requirement: La base impone el anti-solapamiento en la reprogramación

La reprogramación SHALL apoyarse en la restricción de exclusión de la base como
barrera final: dos reprogramaciones concurrentes al mismo hueco SHALL dejar
exactamente una ganadora y la otra SHALL recibir `409 slot_taken` con el turno
en su horario original. La validación previa en el backend SHALL NOT ser la
única defensa.

#### Scenario: Dos reprogramaciones concurrentes al mismo hueco

- **WHEN** dos turnos distintos se reprograman al mismo hueco al mismo tiempo
- **THEN** una responde 200 y la otra `409 slot_taken` sin quedar en horario intermedio

#### Scenario: Recepción gana la carrera

- **WHEN** recepción crea un turno en el hueco mientras el paciente lo reprograma
- **THEN** solo uno persiste y el perdedor responde `409 slot_taken`

### Requirement: Rate-limit por token y por IP con falla cerrada

Las lecturas y las escrituras de gestión SHALL limitarse por hash de token y por
IP. Al excederse SHALL responder `429 rate_limited` con `Retry-After`, sin mutar
el turno. Si el almacenamiento del rate-limit no está disponible SHALL responder
`503 manage_unavailable`.

#### Scenario: Ráfaga de escrituras con el mismo token

- **WHEN** se supera el cupo de escrituras del token en la ventana
- **THEN** responde `429 rate_limited` con `Retry-After` y el turno no cambia

#### Scenario: Barrido de tokens desde una IP

- **WHEN** una IP consulta muchos tokens distintos y supera su cupo
- **THEN** recibe `429 rate_limited` antes que `404`

#### Scenario: Redis caído

- **WHEN** Redis no responde y se envía una confirmación
- **THEN** responde `503 manage_unavailable` y el turno sigue `pending`

### Requirement: Auditoría de la gestión sin datos personales

Toda mutación originada por el token SHALL escribir su evento en la misma
transacción con `actor_type=patient_token`, `actor_user_id` nulo y el detalle de
la acción (motivo del paciente, horario anterior y nuevo, replay). El evento
SHALL NOT contener nombre, teléfono, email ni el token. Si el evento no se
escribe, la mutación SHALL fallar.

#### Scenario: Evento de cancelación con motivo

- **WHEN** el paciente cancela indicando el motivo `viaje`
- **THEN** el evento `cancelled` lleva `actor_type=patient_token`, causa `paciente` y motivo `viaje`

#### Scenario: El evento no guarda datos personales

- **WHEN** se inspecciona el payload del evento de una mutación por token
- **THEN** no aparecen nombre, teléfono, email ni el token del paciente

#### Scenario: Falla al escribir el evento

- **WHEN** la escritura del evento falla durante una cancelación por token
- **THEN** la cancelación no se persiste y el turno conserva su estado

### Requirement: El token no aparece en logs, caché ni respuestas

Las respuestas de gestión SHALL llevar `Cache-Control: no-store` y
`Referrer-Policy: no-referrer`. El token SHALL NOT aparecer en logs de la
aplicación, en cuerpos de error ni en eventos de auditoría.

#### Scenario: Cabeceras de la vista

- **WHEN** se consulta la vista de gestión
- **THEN** la respuesta trae `Cache-Control: no-store` y `Referrer-Policy: no-referrer`

#### Scenario: Error sin eco del token

- **WHEN** una acción falla con 409 o 422
- **THEN** ni el cuerpo del error ni los logs capturados contienen el token

### Requirement: Invalidación de recordatorios en la misma transacción

Confirmar, cancelar o reprogramar SHALL invocar el punto de invalidación de
recordatorios pendientes dentro de la misma transacción de la mutación, con el
turno y la acción. La implementación SHALL cancelar o recalcular los
`reminder_job` del turno según la acción; si falla, la mutación SHALL revertir.

#### Scenario: Confirmación invalida recordatorios

- **WHEN** se confirma un turno con token
- **THEN** el punto de invalidación recibe ese turno y la acción `confirm` una sola vez

#### Scenario: Confirmación cancela los pasos que piden confirmar

- **WHEN** se confirma con token un turno con jobs 72/24/3 h pendientes
- **THEN** los jobs de 72 h y 24 h quedan `cancelled` y el de 3 h sigue `scheduled`

#### Scenario: Reprogramación invalida y reprograma

- **WHEN** se reprograma un turno con token
- **THEN** el punto de invalidación recibe la acción `reschedule` con el horario nuevo
  y los jobs pendientes se recalculan sobre ese horario

#### Scenario: Cancelación cancela los jobs

- **WHEN** se cancela un turno con token
- **THEN** sus jobs pendientes quedan `cancelled` y la acción se registra una sola vez

#### Scenario: La mutación no depende del canal de recordatorios

- **WHEN** el punto de invalidación es no-op
- **THEN** la confirmación, la cancelación y la reprogramación funcionan igual

#### Scenario: Falla de la invalidación revierte la mutación

- **WHEN** el punto de invalidación falla durante una cancelación por token
- **THEN** el turno conserva su estado y sus jobs siguen `scheduled`

#### Scenario: Acción repetida no duplica efectos

- **WHEN** se repite la confirmación de un turno ya confirmado
- **THEN** los jobs no cambian por segunda vez

### Requirement: Aislamiento por clínica en la gestión por token

Todo lo resuelto con un token SHALL limitarse a la clínica del turno: vista,
disponibilidad, mutaciones y alternativos. Un token de otra clínica SHALL NOT
alcanzar recursos ajenos y SHALL comportarse como desconocido.

#### Scenario: Token de otra clínica

- **WHEN** se usa en la clínica A un token cuyo turno pertenece a la clínica B
- **THEN** responde `404 manage_link_not_found` y ninguna de las dos cambia

#### Scenario: La disponibilidad no cruza clínicas

- **WHEN** la clínica B tiene un turno en el horario consultado para un turno de la clínica A
- **THEN** ese horario sigue ofreciéndose en A
