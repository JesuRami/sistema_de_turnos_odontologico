# waitlist/offers Specification

## Purpose
Convierte un hueco liberado en una oferta con expiración para la primera persona
compatible de la lista de espera, la rota cuando vence o se rechaza y, al
aceptarse, crea el turno por el camino normal de la agenda.

## Requirements

### Requirement: Evaluación al cancelar

Cancelar un turno futuro por cualquier vía SHALL evaluar la lista en la misma
transacción que la cancelación (RN-CX-03) y, si hay una entrada compatible,
crear una oferta para el hueco exacto del turno cancelado: mismo profesional,
mismo sillón, mismo inicio y fin. Si la evaluación falla, la cancelación SHALL
revertir. Reprogramar, `absent` y `no_show` SHALL NOT disparar la evaluación.

#### Scenario: Cancelación con entrada compatible

- **WHEN** recepción cancela un turno del jueves 10:00 de la Dra. Ficticia y hay
  una entrada `waiting` para ella que cubre ese jueves
- **THEN** en la misma transacción se crea una oferta `pending` para ese hueco y
  la entrada queda `offered`

#### Scenario: Cancelación por link de gestión

- **WHEN** el paciente cancela con su token
- **THEN** la evaluación corre igual que en una cancelación de recepción

#### Scenario: Sin entradas compatibles

- **WHEN** se cancela un turno y ninguna entrada es compatible
- **THEN** la cancelación se completa y no se crea ninguna oferta

#### Scenario: Reprogramación no ofrece

- **WHEN** recepción mueve un turno a otro día
- **THEN** no se crea ninguna oferta por el horario anterior

### Requirement: Compatibilidad de una entrada con un hueco

Una entrada SHALL ser compatible si está `waiting`, su profesional es el del
hueco o "cualquiera", la fecha local del hueco cae en su período, el hueco
completo cae en su franja (si tiene) y en sus días (si tiene), su paciente no
está archivado, tiene un canal de contacto utilizable, no tiene otro turno
vigente que se superponga con el hueco y no recibió antes una oferta para ese
mismo hueco.

#### Scenario: Fuera de la franja

- **WHEN** el hueco es 13:30–14:30 y la entrada pide 14:00–18:00
- **THEN** la entrada no es compatible

#### Scenario: Día no elegido

- **WHEN** el hueco es un martes y la entrada pide solo lunes y jueves
- **THEN** la entrada no es compatible

#### Scenario: Sin canal utilizable

- **WHEN** el paciente tiene teléfono sin opt-in de WhatsApp y no tiene email
- **THEN** la entrada se saltea y se evalúa la siguiente

#### Scenario: Paciente ocupado a esa hora

- **WHEN** el paciente ya tiene un turno vigente que se superpone con el hueco
- **THEN** la entrada se saltea

#### Scenario: Ya rechazó ese hueco

- **WHEN** la entrada rechazó o dejó vencer una oferta del mismo hueco
- **THEN** no vuelve a recibir ese hueco

### Requirement: Orden de la evaluación

Entre las entradas compatibles, la evaluación SHALL elegir primero las
prioritarias, por instante de priorización, y después las demás por antigüedad
de alta (FIFO con filtro, RN-LE-02). Una entrada que otra transacción tiene
tomada SHALL saltearse sin esperar.

#### Scenario: FIFO con filtro

- **WHEN** la entrada más antigua no es compatible y la segunda sí
- **THEN** la oferta es para la segunda

#### Scenario: Prioritaria primero

- **WHEN** hay una entrada común antigua y una prioritaria reciente, ambas
  compatibles
- **THEN** la oferta es para la prioritaria

#### Scenario: Dos cancelaciones simultáneas

- **WHEN** se cancelan a la vez dos turnos compatibles con la misma única entrada
- **THEN** la entrada recibe una sola oferta y la otra cancelación termina sin
  oferta

### Requirement: Hueco todavía ofrecible

Antes de crear una oferta, el hueco SHALL estar libre de turnos vigentes y de
bloqueos del profesional y del sillón, y su inicio SHALL dejar una ventana de
oferta suficiente. El vencimiento SHALL ser el menor entre ahora más
`waitlist_offer_ttl_hours` y el inicio menos `WAITLIST_MIN_LEAD_MINUTES`
(default 60); si quedan menos de `WAITLIST_MIN_OFFER_WINDOW_MINUTES` (default 15)
hasta el vencimiento, SHALL NOT crearse una oferta automática.

#### Scenario: Oferta con TTL completo

- **WHEN** el TTL es 4 h y el hueco empieza en 2 días
- **THEN** la oferta vence en 4 h

#### Scenario: Oferta recortada por la cercanía

- **WHEN** el TTL es 4 h y el hueco empieza en 3 h
- **THEN** la oferta vence 60 min antes del inicio

#### Scenario: Hueco demasiado cerca

- **WHEN** el hueco empieza en 70 min
- **THEN** no se crea oferta automática

#### Scenario: Hueco bloqueado

- **WHEN** el turno se canceló con motivo `bloqueo` y un bloqueo cubre el horario
- **THEN** no se crea oferta

### Requirement: Una oferta pendiente por entrada

Una entrada SHALL tener a lo sumo una oferta `pending`, impuesto por la base.
Mientras la tiene, la entrada SHALL estar `offered`.

#### Scenario: Segunda oferta a la misma entrada

- **WHEN** se intenta crear una oferta para una entrada que ya tiene una pendiente
- **THEN** la base la rechaza y la API responde `409 entry_offered`

### Requirement: Oferta manual de recepción

Admin y recepción SHALL ofrecer a una entrada `waiting` un hueco libre que caiga
en una regla vigente, con profesional, sillón e inicio; la duración SHALL ser la
de la regla. Si otra entrada compatible va antes en la cola, SHALL exigir un
motivo de excepción a FIFO, auditado.

#### Scenario: Oferta manual a la primera

- **WHEN** recepción ofrece un hueco libre a la primera entrada compatible
- **THEN** responde `201` sin pedir motivo y la oferta queda `pending`

#### Scenario: Saltear la cola sin motivo

- **WHEN** recepción ofrece un hueco a la tercera entrada compatible sin motivo
- **THEN** responde `422 fifo_skip_reason_required`

#### Scenario: Saltear la cola con motivo

- **WHEN** lo ofrece a la tercera con motivo
- **THEN** responde `201` y el evento registra `fifo_skip=true`, actor y motivo

#### Scenario: Hueco ocupado

- **WHEN** el hueco ofrecido se superpone con un turno vigente
- **THEN** responde `409 slot_taken` y no se crea la oferta

#### Scenario: Fuera de horario

- **WHEN** el inicio no cae en una regla vigente del par profesional-sillón
- **THEN** responde `422 outside_schedule`

### Requirement: Huecos ofrecibles para una entrada

`GET /api/waiting-list/{id}/slots?from=&to=` SHALL devolver a admin y recepción
los huecos libres de un rango de hasta 14 días que respetan el profesional, el
período, la franja y los días de la entrada, con profesional, sillón, inicio y
fin, usando la misma definición de hueco libre que la reserva online.

#### Scenario: Huecos dentro de la preferencia

- **WHEN** la entrada pide martes de 14:00 a 18:00 y se piden los huecos de la
  semana
- **THEN** solo aparecen huecos libres de martes que caen completos en esa franja

#### Scenario: Entrada para cualquiera

- **WHEN** la entrada es para "cualquiera"
- **THEN** aparecen huecos de todos los profesionales activos con regla vigente

#### Scenario: Rango excesivo

- **WHEN** el rango pedido supera 14 días
- **THEN** responde `422 range_too_large`

### Requirement: Aceptar crea el turno

Aceptar una oferta `pending` antes de su vencimiento SHALL crear un turno
`confirmed` con origen `waitlist` para el paciente de la entrada, con el
profesional, sillón, inicio y fin de la oferta, por el mismo camino de escritura
y con las mismas validaciones que un alta de recepción (RN-LE-05).

#### Scenario: Aceptación exitosa

- **WHEN** el paciente acepta una oferta vigente
- **THEN** existe un turno `confirmed` con origen `waitlist`, la oferta queda
  `accepted` con el id del turno y la entrada queda `converted`

#### Scenario: Aceptar no es sobreturno

- **WHEN** se acepta una oferta cuyo hueco tiene un sobreturno vigente encima
- **THEN** responde `409 slot_taken` y no se crea un sobreturno

#### Scenario: Recordatorios del turno nuevo

- **WHEN** se crea el turno por una aceptación
- **THEN** se programan sus recordatorios como en un alta de recepción

### Requirement: Efectos de la aceptación

En la misma transacción de la aceptación SHALL cerrarse como `cancelled` toda
otra oferta `pending` de la misma entrada y toda oferta `pending` de otra entrada
para el mismo hueco; esas otras entradas SHALL volver a `waiting` sin perder su
lugar. Aceptar una oferta ya `accepted` por el mismo paciente SHALL ser
idempotente.

#### Scenario: Oferta paralela del mismo hueco

- **WHEN** recepción ofreció a mano el mismo hueco a otra entrada y la primera
  acepta
- **THEN** la otra oferta queda `cancelled` con motivo `slot_taken` y su entrada
  vuelve a `waiting`

#### Scenario: Doble clic en aceptar

- **WHEN** el paciente acepta dos veces seguidas
- **THEN** la segunda responde `200` con el mismo turno y no crea otro

### Requirement: Carrera de aceptaciones

Si al aceptar el hueco ya está ocupado, SHALL responder `409 slot_taken` con
hasta 3 horarios alternativos del mismo profesional (solo inicio y fin), la
oferta SHALL quedar `cancelled` con motivo `slot_taken` y la entrada SHALL
volver a `waiting` marcada prioritaria con motivo `slot_lost`.

#### Scenario: Dos aceptaciones simultáneas

- **WHEN** dos pacientes con ofertas del mismo hueco aceptan a la vez
- **THEN** hay un solo turno; el segundo recibe `409 slot_taken` y su entrada
  queda `waiting` y prioritaria

#### Scenario: Recepción ocupó el hueco antes

- **WHEN** recepción dio el hueco a otro paciente mientras la oferta estaba
  pendiente y después el paciente acepta
- **THEN** responde `409 slot_taken` y la entrada queda prioritaria

### Requirement: Aceptación rechazada sin cambios

Aceptar SHALL responder `409 offer_expired` si la oferta venció, `409
offer_closed` si está `declined` o `cancelled`, y `409 patient_busy` si el
paciente tiene otro turno vigente superpuesto; en ese último caso la oferta
SHALL seguir `pending`. Ninguno SHALL crear un turno.

#### Scenario: Aceptar vencida

- **WHEN** el paciente acepta un minuto después de `expires_at`
- **THEN** responde `409 offer_expired` y no se crea turno

#### Scenario: Paciente ocupado al aceptar

- **WHEN** el paciente reservó por otro lado un turno a la misma hora y después
  acepta
- **THEN** responde `409 patient_busy` y la oferta sigue pendiente

### Requirement: Rechazo sin penalización

Rechazar una oferta `pending` SHALL dejarla `declined`, devolver la entrada a
`waiting` con su antigüedad y prioridad intactas y reiniciar su contador de
vencimientos. El paciente SHALL poder rechazar y salir de la lista en el mismo
acto, dejando la entrada `withdrawn`. El hueco SHALL rotar a la siguiente.

#### Scenario: Rechazar conserva la posición

- **WHEN** la primera de la cola rechaza
- **THEN** su entrada vuelve a `waiting` y sigue primera para el próximo hueco

#### Scenario: Rechazar y salir

- **WHEN** el paciente elige "rechazar y salir de la lista"
- **THEN** la oferta queda `declined` y la entrada `withdrawn`

### Requirement: Vencimiento y rotación

Una oferta `pending` cuyo `expires_at` pasó SHALL quedar `expired` en el
siguiente tick (RN-LE-03), su entrada SHALL volver a `waiting` y sumar un
vencimiento consecutivo. Tras un vencimiento o un rechazo, si el hueco sigue
ofrecible, SHALL evaluarse la siguiente entrada compatible.

#### Scenario: Vence y rota

- **WHEN** vence una oferta y hay otra entrada compatible
- **THEN** la oferta queda `expired`, su entrada vuelve a `waiting` y se crea una
  oferta para la siguiente

#### Scenario: Rotación con el hueco ya ocupado

- **WHEN** vence una oferta pero recepción ya ocupó ese hueco
- **THEN** no se crea otra oferta

#### Scenario: Tick repetido

- **WHEN** dos ticks procesan el mismo vencimiento a la vez
- **THEN** la oferta vence una sola vez y se crea a lo sumo una oferta siguiente

### Requirement: Tres vencimientos consecutivos

Una entrada que acumula `WAITLIST_MAX_CONSECUTIVE_EXPIRED` (default 3)
vencimientos consecutivos sin responder SHALL quedar `expired` con motivo
`no_response`. Un rechazo o una aceptación SHALL reiniciar el contador.

#### Scenario: Tercer vencimiento

- **WHEN** una entrada deja vencer su tercera oferta seguida
- **THEN** la entrada queda `expired` con motivo `no_response`

#### Scenario: Rechazo entre vencimientos

- **WHEN** deja vencer dos, rechaza una y deja vencer otra
- **THEN** la entrada sigue `waiting`

### Requirement: Ninguna automatización mueve turnos

La evaluación, la rotación y los vencimientos SHALL NOT cambiar el horario, el
estado ni los recursos de ningún turno existente (RN-GL-02). Solo la aceptación
SHALL crear un turno nuevo.

#### Scenario: Turnos intactos tras un tick

- **WHEN** el tick vence y rota ofertas
- **THEN** ningún `appointment` existente cambia y no hay `appointment_event` nuevo

### Requirement: Acciones de recepción sobre una oferta

Admin y recepción SHALL aceptar o rechazar una oferta en nombre del paciente que
llamó y SHALL retirar una oferta `pending` (queda `cancelled`, la entrada vuelve
a `waiting`). Cada acción SHALL auditarse con el usuario como actor.
`GET /api/waiting-list/offers` SHALL listar ofertas por estado y rango.

#### Scenario: Aceptar por teléfono

- **WHEN** recepción acepta una oferta en nombre del paciente
- **THEN** se crea el turno `waitlist` y el evento registra al usuario como actor

#### Scenario: Ofertas vencidas del día

- **WHEN** recepción lista las ofertas `expired` de hoy
- **THEN** ve cada una con entrada, hueco y vencimiento

### Requirement: Auditoría de ofertas

Crear, aceptar, rechazar, vencer o cerrar una oferta SHALL escribir un evento
append-only en la misma transacción, con tipo, actor, ids de entrada, oferta,
hueco y turno resultante, y modo `auto` o `manual`, sin PII.

#### Scenario: Traza completa de una conversión

- **WHEN** una cancelación genera una oferta, vence, rota y la segunda se acepta
- **THEN** los eventos registran `offered`, `expired`, `offered` y `accepted`
  con sus actores, en orden
